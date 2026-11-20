"""
平台用的被告端勝敗模型（第一版）：使用者是被告時，用「對方（原告）的主張」＋「自己的答辯」估計原告勝訴的機率。

    python -m civil.models.defense_service evaluate     # 5 折評估（預設 v5 資料集），輸出 defense_model_v5.md
    python -m civil.models.defense_service train        # 用全部資料訓練，存到 artifacts/civil_defense_v1/

和原告端（service.py）的差別：
  - 文字有兩段，各自一個 TF-IDF（字元 1–3 gram）：原告主張、被告答辯。被告手上通常有起訴狀，寫得出對方主張什麼；
    答辯是選填的，訓練時隨機把 30% 的答辯換成空白，模型才學得到使用者沒寫答辯的情況。
  - 特徵改成被告填得出來的：
      mid                     案由中類
      court                   法院（被告收到起訴狀就知道，但仍可不填；訓練時 30% 換成「不知道」）
      defendant_has_lawyer    自己（被告）有沒有請律師
      defendant_is_corp       自己是不是公司、機關
    不用「原告有沒有律師」：被告不一定知道，上線時幾乎都會是「不知道」。
預測的仍是「原告勝訴（含一部勝訴）」的機率；前端換成被告的角度呈現。
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import OneHotEncoder

import config
from civil.dataset.fields import load_fields
from civil.dataset.text import prepare_input
from civil.models.service import (COURT_UNKNOWN_SHARE, SEED, SUMMARY_METRICS, THRESHOLD, UNKNOWN, calibration,
                                  classification, options)
from civil.models.tfidf import logreg, vec

MODEL_NAME = "civil_defense_v1"
FEATURES = ["mid", "court", "defendant_has_lawyer", "defendant_is_corp"]
DEFENSE_BLANK_SHARE = 0.3
MAIN = "主張＋答辯＋特徵"


def load_training(version: str = "v5") -> pd.DataFrame:
    t = pd.read_csv(config.dataset_path(version), usecols=["id", "case_type_category", "case_type_mid", "y", "fold",
                                                           "plaintiff_claim_text", "defendant_defense_text"])
    f = load_fields(version)[["id", "court_s", "defendant_has_lawyer", "defendant_is_corp"]]
    d = t.merge(f, on="id", how="left", validate="1:1")
    d["claim"] = d.plaintiff_claim_text.fillna("")
    d["defense"] = d.defendant_defense_text.fillna("")
    d["mid"] = d.case_type_mid.fillna("其他")
    d["court"] = d.court_s.fillna(UNKNOWN)
    for c in ("defendant_has_lawyer", "defendant_is_corp"):
        d[c] = d[c].astype(int).astype(str)
    return d


def features_frame(rows: List[Dict]) -> pd.DataFrame:
    """使用者的問卷答案 → 模型的特徵欄位。沒填的一律是「不知道」；是非題接受 True／False／"1"／"0"。"""
    def flag(v):
        if v is None or v == "" or v == UNKNOWN:
            return UNKNOWN
        return "1" if v in (True, 1, "1", "true", "True") else "0"
    return pd.DataFrame([{"mid": r.get("mid") or UNKNOWN, "court": r.get("court") or UNKNOWN,
                          "defendant_has_lawyer": flag(r.get("defendant_has_lawyer")),
                          "defendant_is_corp": flag(r.get("defendant_is_corp"))} for r in rows], columns=FEATURES)


class DefenseModel:
    """原告主張、被告答辯各一個 TF-IDF，加上特徵 one-hot，接一個 logistic regression。"""

    def __init__(self, use_defense: bool = True, use_features: bool = True):
        self.use_defense, self.use_features = use_defense, use_features
        self.vec_claim = self.vec_defense = self.enc = self.clf = None

    def _X(self, claims, defenses, feats, fit):
        parts = [self.vec_claim.fit_transform(claims) if fit else self.vec_claim.transform(claims)]
        if self.use_defense:
            parts.append(self.vec_defense.fit_transform(defenses) if fit else self.vec_defense.transform(defenses))
        if self.use_features:
            parts.append(self.enc.fit_transform(feats[FEATURES]) if fit else self.enc.transform(feats[FEATURES]))
        return hstack(parts).tocsr()

    def fit(self, claims, defenses, feats: pd.DataFrame, y) -> "DefenseModel":
        self.vec_claim, self.vec_defense, self.enc = vec(), vec(), OneHotEncoder(handle_unknown="ignore")
        self.clf = logreg().fit(self._X(list(claims), list(defenses), feats, True), np.asarray(y))
        return self

    def predict_proba(self, claims, defenses, feats: pd.DataFrame) -> np.ndarray:
        return self.clf.predict_proba(self._X(list(claims), list(defenses), feats, False))[:, 1]

    def predict_one(self, claim: str, defense: str, answers: Dict) -> float:
        """回傳原告勝訴（含一部勝訴）的機率。"""
        return float(self.predict_proba([prepare_input(claim)], [prepare_input(defense)], features_frame([answers]))[0])


def augment(d: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    """訓練資料：30% 的法院換成「不知道」、另外隨機 30% 的答辯換成空白（使用者常不寫答辯）。"""
    d = d.copy()
    rng = np.random.default_rng(seed)
    d.loc[rng.random(len(d)) < COURT_UNKNOWN_SHARE, "court"] = UNKNOWN
    d.loc[rng.random(len(d)) < DEFENSE_BLANK_SHARE, "defense"] = ""
    return d


def evaluate(d: pd.DataFrame) -> Dict:
    """5 折（資料集的 fold 欄）。測試時另外量「沒寫答辯」「法院不知道」「什麼特徵都沒填」。"""
    y = d.y.values
    specs = {"只用主張＋特徵": (False, True), MAIN: (True, True)}
    oof = {name: np.zeros(len(d)) for name in specs}
    extra = {f"{MAIN}（沒寫答辯）": lambda t: t.assign(defense=""),
             f"{MAIN}（法院不知道）": lambda t: t.assign(court=UNKNOWN),
             f"{MAIN}（沒寫答辯、特徵都不知道）": lambda t: t.assign(defense="", **{c: UNKNOWN for c in FEATURES})}
    oof.update({name: np.zeros(len(d)) for name in extra})
    for k in range(5):
        tr, te = (d.fold != k).values, (d.fold == k).values
        train, test = augment(d[tr]), d[te]
        for name, (use_d, use_f) in specs.items():
            m = DefenseModel(use_d, use_f).fit(train.claim, train.defense, train, train.y)
            oof[name][te] = m.predict_proba(test.claim, test.defense, test)
            if name == MAIN:
                for variant, change in extra.items():
                    t = change(test)
                    oof[variant][te] = m.predict_proba(t.claim, t.defense, t)
        print(f"  fold {k} 完成", flush=True)
    return {name: {**classification(y, p), "auc": float(roc_auc_score(y, p)), **calibration(y, p)} for name, p in oof.items()}


def artifact_dir(base: Optional[Path] = None) -> Path:
    return Path(base or config.ARTIFACTS_DIR) / MODEL_NAME


def train(d: pd.DataFrame, version: str, out: Path, metrics: Optional[Dict] = None) -> Path:
    rows = augment(d)
    model = DefenseModel().fit(rows.claim, rows.defense, rows, rows.y)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "model.joblib", compress=3)
    meta = {"name": MODEL_NAME, "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **config.build_info(),
            "dataset": f"text_dataset_{version}.csv", "n_cases": int(len(d)), "base_rate": float(d.y.mean()),
            "features": FEATURES, "unknown": UNKNOWN, "court_unknown_share": COURT_UNKNOWN_SHARE,
            "defense_blank_share": DEFENSE_BLANK_SHARE,
            "description": "TF-IDF（原告主張、被告答辯各一）＋案由中類、法院、被告有沒有律師、被告是否為法人",
            "metrics": metrics or {}, "options": options(d)}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load(path: Optional[Path] = None):
    """回傳（模型, meta）。"""
    path = Path(path or artifact_dir())
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    config.warn_if_other_sklearn(meta, MODEL_NAME)
    return joblib.load(path / "model.joblib"), meta


def report(results: Dict, version: str, n: int) -> str:
    lines = [f"# 平台用被告端勝敗模型（第一版）：原告主張＋被告答辯＋被告填得出來的特徵（{version}，{n:,} 件，5 折）\n",
             f"預測的是原告勝訴（含一部勝訴）；機率 {THRESHOLD} 以上算判原告勝訴。\n",
             "| 模型 | 勝訴 precision | 勝訴 recall | 勝訴 F1 | 敗訴 precision | 敗訴 recall | 敗訴 F1 | 正確率 | AUC | ECE |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, r in results.items():
        lines.append(f"| {name} | {r['win_precision']:.3f} | {r['win_recall']:.3f} | {r['win_f1']:.3f} | "
                     f"{r['lose_precision']:.3f} | {r['lose_recall']:.3f} | {r['lose_f1']:.3f} | "
                     f"{r['accuracy']:.3f} | {r['auc']:.3f} | {r['ece']:.3f} |")
    lines.append("\n特徵：案由中類、法院、被告有沒有請律師、被告是否為法人。訓練時 30% 的法院換成「不知道」、30% 的答辯換成空白。")
    lines.append("括號裡的列：同一個模型，測試時改成使用者沒填的情況。\n")
    lines.append(f"## 校準（{MAIN}）\n\n| 預測機率 | 件數 | 平均預測 | 實際原告勝訴比例 |\n|---|---:|---:|---:|")
    for row in results[MAIN]["table"]:
        lines.append(f"| {row['range']} | {row['n']:,} | {row['predicted']:.3f} | {row['actual']:.3f} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="平台用的被告端勝敗模型（第一版）")
    ap.add_argument("action", choices=("evaluate", "train"))
    ap.add_argument("--version", default="v5")
    ap.add_argument("--out", default=None, help="模型輸出資料夾；預設 artifacts/civil_defense_v1")
    a = ap.parse_args()
    t0 = time.time()
    d = load_training(a.version)
    print(f"{len(d):,} 件，原告勝訴比例 {d.y.mean():.3f}", flush=True)
    if a.action == "evaluate":
        results = evaluate(d)
        text = report(results, a.version, len(d))
        (config.OUTPUT_DIR / f"defense_model_{a.version}.md").write_text(text, encoding="utf-8")
        (config.OUTPUT_DIR / f"defense_model_{a.version}.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(text)
    else:
        metrics_file = config.OUTPUT_DIR / f"defense_model_{a.version}.json"
        metrics = json.loads(metrics_file.read_text(encoding="utf-8")) if metrics_file.exists() else {}
        summary = {k: {m: v[m] for m in SUMMARY_METRICS} for k, v in metrics.items()}
        out = train(d, a.version, Path(a.out) if a.out else artifact_dir(), summary)
        print(f"已存到 {out}")
    print(f"完成，{(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    # 同 service.py：用正式的模組名稱執行，模型檔裡的類別才不會記成 __main__.DefenseModel
    from civil.models import defense_service
    defense_service.main()
