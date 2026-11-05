"""
平台用的勝敗模型（第一版）：只用原告主張的 TF-IDF ＋ 使用者填得出來的案件特徵。

    python -m civil.models.service evaluate     # 5 折評估，輸出 service_model_v5.md
    python -m civil.models.service train        # 用全部資料訓練，存到 artifacts/civil_winloss_v1/

為什麼不用兩造的模型（AUC 0.827）：平台上的使用者只能提供自己這一方的說法，沒有被告答辯；
「對方會不會請律師」「會不會反訴」也要打了官司才知道。所以特徵只用使用者填得出來的：
  mid                     案由中類（問卷的「糾紛類型」）
  court                   法院（使用者常不知道，可填「不知道」）
  plaintiff_has_lawyer    自己有沒有請律師
  defendant_is_corp       對方是不是公司、機關
訓練時隨機把 30% 的法院換成「不知道」，模型才學得到使用者不填法院的情況。
文字的處理和資料集相同（civil.dataset.text.prepare_input），使用者輸入在預測前也經過同一道處理。
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
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.preprocessing import OneHotEncoder

import config
from civil.dataset.text import prepare_input
from civil.models.tfidf import logreg, vec

MODEL_NAME = "civil_winloss_v1"
FEATURES = ["mid", "court", "plaintiff_has_lawyer", "defendant_is_corp"]
UNKNOWN = "不知道"
COURT_UNKNOWN_SHARE = 0.3
SEED = 42


def load_training(version: str = "v5") -> pd.DataFrame:
    t = pd.read_csv(config.dataset_path(version), usecols=["id", "case_type_category", "case_type_mid", "y", "fold",
                                                           "plaintiff_claim_text"])
    f = pd.read_pickle(config.FIELDS_PKL)[["id", "court_s", "plaintiff_has_lawyer", "defendant_is_corp"]]
    d = t.merge(f, on="id", how="left", validate="1:1")
    d["text"] = d.plaintiff_claim_text.fillna("")
    d["mid"] = d.case_type_mid.fillna("其他")
    d["court"] = d.court_s.fillna(UNKNOWN)
    for c in ("plaintiff_has_lawyer", "defendant_is_corp"):
        d[c] = d[c].astype(int).astype(str)
    return d


def features_frame(rows: List[Dict]) -> pd.DataFrame:
    """使用者的問卷答案 → 模型的特徵欄位。沒填的一律是「不知道」；是非題接受 True／False／"1"／"0"。"""
    def flag(v):
        if v is None or v == "" or v == UNKNOWN:
            return UNKNOWN
        return "1" if v in (True, 1, "1", "true", "True") else "0"
    return pd.DataFrame([{"mid": r.get("mid") or UNKNOWN, "court": r.get("court") or UNKNOWN,
                          "plaintiff_has_lawyer": flag(r.get("plaintiff_has_lawyer")),
                          "defendant_is_corp": flag(r.get("defendant_is_corp"))} for r in rows], columns=FEATURES)


class ServiceModel:
    """TF-IDF（原告主張）＋特徵 one-hot，接一個 logistic regression。"""

    def __init__(self, use_text: bool = True, use_features: bool = True):
        self.use_text, self.use_features = use_text, use_features
        self.vec = self.enc = self.clf = None

    def _X(self, texts, feats, fit):
        parts = []
        if self.use_text:
            parts.append(self.vec.fit_transform(texts) if fit else self.vec.transform(texts))
        if self.use_features:
            parts.append(self.enc.fit_transform(feats[FEATURES]) if fit else self.enc.transform(feats[FEATURES]))
        return hstack(parts).tocsr()

    def fit(self, texts, feats: pd.DataFrame, y) -> "ServiceModel":
        self.vec, self.enc = vec(), OneHotEncoder(handle_unknown="ignore")
        self.clf = logreg().fit(self._X(list(texts), feats, True), np.asarray(y))
        return self

    def predict_proba(self, texts, feats: pd.DataFrame) -> np.ndarray:
        return self.clf.predict_proba(self._X(list(texts), feats, False))[:, 1]

    def predict_one(self, text: str, answers: Dict) -> float:
        return float(self.predict_proba([prepare_input(text)], features_frame([answers]))[0])


def with_unknown_courts(d: pd.DataFrame, share: float = COURT_UNKNOWN_SHARE, seed: int = SEED) -> pd.DataFrame:
    d = d.copy()
    hide = np.random.default_rng(seed).random(len(d)) < share
    d.loc[hide, "court"] = UNKNOWN
    return d


def calibration(y, p, bins: int = 10) -> Dict:
    """ECE（預測機率與實際勝訴比例的加權平均差）與分組表。"""
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    table, ece = [], 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
            table.append({"range": f"{edges[b]:.1f}–{edges[b + 1]:.1f}", "n": int(m.sum()),
                          "predicted": float(p[m].mean()), "actual": float(y[m].mean())})
    return {"ece": float(ece), "brier": float(brier_score_loss(y, p)), "table": table}


def evaluate(d: pd.DataFrame) -> Dict:
    """5 折（資料集的 fold 欄）。測試時另外量「法院不知道」「什麼特徵都沒填」兩種情況。"""
    y = d.y.values
    specs = {"只用原告主張": (True, False), "原告主張＋特徵": (True, True), "只用特徵": (False, True)}
    oof = {name: np.zeros(len(d)) for name in specs}
    oof["原告主張＋特徵（法院不知道）"] = np.zeros(len(d))
    oof["原告主張＋特徵（都不知道）"] = np.zeros(len(d))
    for k in range(5):
        tr, te = (d.fold != k).values, (d.fold == k).values
        train = with_unknown_courts(d[tr])
        test = d[te]
        for name, (t, f) in specs.items():
            m = ServiceModel(t, f).fit(train.text, train, train.y)
            oof[name][te] = m.predict_proba(test.text, test)
            if name == "原告主張＋特徵":
                no_court = test.assign(court=UNKNOWN)
                oof["原告主張＋特徵（法院不知道）"][te] = m.predict_proba(test.text, no_court)
                blank = test.assign(**{c: UNKNOWN for c in FEATURES})
                oof["原告主張＋特徵（都不知道）"][te] = m.predict_proba(test.text, blank)
        print(f"  fold {k} 完成", flush=True)
    return {name: {"auc": float(roc_auc_score(y, p)), **calibration(y, p)} for name, p in oof.items()}


def options(d: pd.DataFrame, min_cases: int = 30) -> Dict:
    """問卷的選項：依案由大類分組的中類（至少 min_cases 件），以及法院。"""
    mids = (d.groupby(["case_type_category", "mid"]).size().reset_index(name="n")
            .query("n >= @min_cases").sort_values(["case_type_category", "n"], ascending=[True, False]))
    groups = [{"category": cat, "mids": [{"value": m, "n": int(n)} for m, n in zip(g.mid, g.n)]}
              for cat, g in mids.groupby("case_type_category", sort=False)]
    groups.sort(key=lambda g: -sum(m["n"] for m in g["mids"]))
    courts = d.court_s.value_counts()
    return {"mid_groups": groups, "courts": [c for c in courts.index if c != UNKNOWN]}


def artifact_dir(base: Optional[Path] = None) -> Path:
    return Path(base or config.ARTIFACTS_DIR) / MODEL_NAME


def train(d: pd.DataFrame, version: str, out: Path, metrics: Optional[Dict] = None) -> Path:
    train_rows = with_unknown_courts(d)
    model = ServiceModel().fit(train_rows.text, train_rows, train_rows.y)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "model.joblib", compress=3)
    meta = {"name": MODEL_NAME, "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dataset": f"text_dataset_{version}.csv", "n_cases": int(len(d)), "base_rate": float(d.y.mean()),
            "features": FEATURES, "unknown": UNKNOWN, "court_unknown_share": COURT_UNKNOWN_SHARE,
            "description": "TF-IDF（只用原告主張）＋案由中類、法院、律師、對方是否為法人", "metrics": metrics or {},
            "options": options(d)}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load(path: Optional[Path] = None):
    """回傳（模型, meta）。"""
    path = Path(path or artifact_dir())
    return joblib.load(path / "model.joblib"), json.loads((path / "meta.json").read_text(encoding="utf-8"))


def report(results: Dict, version: str, n: int) -> str:
    lines = [f"# 平台用勝敗模型（第一版）：只用原告主張＋使用者填得出來的特徵（{version}，{n:,} 件，5 折）\n",
             "| 模型 | AUC | ECE（校準誤差） | Brier |", "|---|---:|---:|---:|"]
    for name, r in results.items():
        lines.append(f"| {name} | {r['auc']:.3f} | {r['ece']:.3f} | {r['brier']:.3f} |")
    lines.append("\n特徵：案由中類、法院、自己有沒有請律師、對方是否為法人。訓練時 30% 的法院換成「不知道」。")
    lines.append("「法院不知道」「都不知道」：同一個模型，測試時把特徵改成使用者沒填的情況。\n")
    lines.append("## 校準（原告主張＋特徵）\n\n| 預測機率 | 件數 | 平均預測 | 實際勝訴比例 |\n|---|---:|---:|---:|")
    for row in results["原告主張＋特徵"]["table"]:
        lines.append(f"| {row['range']} | {row['n']:,} | {row['predicted']:.3f} | {row['actual']:.3f} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="平台用的勝敗模型（第一版）")
    ap.add_argument("action", choices=("evaluate", "train"))
    ap.add_argument("--version", default="v5")
    ap.add_argument("--out", default=None, help="模型輸出資料夾；預設 artifacts/civil_winloss_v1")
    a = ap.parse_args()
    t0 = time.time()
    d = load_training(a.version)
    print(f"{len(d):,} 件，勝訴比例 {d.y.mean():.3f}", flush=True)
    if a.action == "evaluate":
        results = evaluate(d)
        text = report(results, a.version, len(d))
        out = config.OUTPUT_DIR / f"service_model_{a.version}.md"
        out.write_text(text, encoding="utf-8")
        (config.OUTPUT_DIR / f"service_model_{a.version}.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(text)
    else:
        metrics_file = config.OUTPUT_DIR / f"service_model_{a.version}.json"
        metrics = json.loads(metrics_file.read_text(encoding="utf-8")) if metrics_file.exists() else {}
        summary = {k: {m: v[m] for m in ("auc", "ece", "brier")} for k, v in metrics.items()}
        out = train(d, a.version, Path(a.out) if a.out else artifact_dir(), summary)
        print(f"已存到 {out}")
    print(f"完成，{(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    # 用 python -m 執行時這個檔案是 __main__，直接呼叫 main() 的話，模型檔裡的類別會記成
    # __main__.ServiceModel，後端載入時找不到。改由正式的模組名稱執行。
    from civil.models import service
    service.main()
