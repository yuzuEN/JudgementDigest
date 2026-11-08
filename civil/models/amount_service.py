"""
平台用的獲償比例模型（第一版，兩階段的第二階段）：「如果是一部勝訴，原告大約贏幾成」。

    python -m civil.models.amount_service evaluate     # 5 折評估，輸出 amount_service_v5.md
    python -m civil.models.amount_service train        # 用全部資料訓練，存到 artifacts/civil_amount_v1/

兩階段：第一階段是勝敗模型（civil.models.service，勝訴機率）；這個模型是第二階段，只回答
「一部勝訴時，判准金額占請求金額的比例」。訓練樣本是一部勝訴一部敗訴、獲償比例是算出來的案件（見 select_sample）；
全部勝訴的案件獲償比例大多不是算出來的，不在樣本裡，所以結果要標明「若為一部勝訴」。

輸入只用使用者填得出來的（同 service.py）：原告主張的 TF-IDF、案由中類、法院、自己有沒有請律師、對方是不是法人，
再加請求金額（log10，使用者可以不填）與從原告主張抽出的 13 個損害子項目旗標（醫療費、慰撫金…，同 amount.py）。
訓練時隨機把 30% 的法院換成「不知道」、30% 的請求金額換成沒填，模型才學得到使用者沒填的情況。

範圍：Ridge 迴歸給一個預測值，再用 5 折折外預測的殘差，依預測值分成 5 組，每組取殘差的 10%、50%、90% 分位數，
加回預測值，得到 10%–90% 的範圍（涵蓋率目標 80%）。評估時用其他折的殘差校準，不用自己那一折。
"""
import argparse
import json
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import joblib
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.preprocessing import OneHotEncoder

import config
from civil.dataset.text import prepare_input
from civil.models.amount import ITEMS
from civil.models.service import FEATURES, UNKNOWN, features_frame
from civil.models.tfidf import vec

MODEL_NAME = "civil_amount_v1"
LOW, HIGH = 0.1, 0.9
N_BINS = 5
UNKNOWN_SHARE = 0.3        # 訓練與校準時，法院、請求金額各有這個比例當作使用者沒填
ALPHA = 1.0                # 事先固定（同 amount.py），不看測試結果調整
SEED = 42
MIN_RATIO = 0.001
ITEM_PATTERNS = [re.compile(p) for p in ITEMS.values()]


# ── 資料 ──
def select_sample(d: pd.DataFrame) -> pd.DataFrame:
    """樣本條件同 amount.py 的主分析（一部勝訴）；回傳篩選後的資料與每一步的件數。"""
    flow = [("v5 全部", len(d))]
    d = d[d.outcome == "一部勝訴一部敗訴"]
    flow.append(("一部勝訴一部敗訴", len(d)))
    d = d[d.grant_ratio_source == "計算"]
    flow.append(("獲償比例是算出來的", len(d)))
    d = d[~d.quality_flags.fillna("").str.contains("判准大於請求")]
    flow.append(("排除「判准大於請求」旗標", len(d)))
    d = d[(d.grant_ratio > 0) & (d.grant_ratio <= 1) & (d.claimed_amount > 0)]
    flow.append(("比例在 (0, 1]、請求金額 > 0", len(d)))
    d = d[d.claimed_source.fillna("").str.startswith("直接抽取")]
    flow.append(("請求金額從聲明直接抽取", len(d)))
    d = d.copy()
    d.attrs["flow"] = flow
    return d.reset_index(drop=True)


AMOUNT_COLUMNS = ["grant_ratio", "grant_ratio_source", "claimed_amount", "claimed_source", "quality_flags"]


def rederive_amounts(ids, con) -> tuple:
    """
    用目前的 structuring.py 在記憶體裡重新推導金額欄位（資料庫不寫入）。
    資料庫是規則 2.4.0；金額規則在 2.5.1 修正（見 docs/資料版本.md），換庫之前先用這個方式取得新規則的欄位。
    回傳（id 與 AMOUNT_COLUMNS 的表, 規則版本）。
    """
    config.use_data_pipeline()
    import structuring as S
    con.execute("CREATE TEMP TABLE ids(id INTEGER PRIMARY KEY)")
    con.executemany("INSERT INTO ids VALUES (?)", [(int(i),) for i in ids])
    src = ", ".join(f"j.{c}" for c in S.SOURCE_COLUMNS)
    rows = pd.read_sql(f"SELECT j.id, {src} FROM judgments j JOIN ids USING (id)", con)
    derived = pd.DataFrame([S.derive_structured_fields(r) for r in rows[S.SOURCE_COLUMNS].to_dict("records")])
    out = derived[AMOUNT_COLUMNS].copy()
    out.insert(0, "id", rows.id.values)
    return out, S.STRUCTURING_VERSION


def load_training(version: str = "v5", rules: str = "current") -> pd.DataFrame:
    """
    rules="current"：金額欄位用目前的 structuring.py 重新推導（2.5.1）；rules="db"：直接讀資料庫的欄位（2.4.0）。
    """
    assert rules in ("current", "db")
    t = pd.read_csv(config.dataset_path(version), usecols=["id", "case_type_category", "case_type_mid", "outcome",
                                                           "fold", "plaintiff_claim_text"])
    f = pd.read_pickle(config.FIELDS_PKL)[["id", "court_s", "plaintiff_has_lawyer", "defendant_is_corp"]]
    d = t.merge(f, on="id", how="left", validate="1:1")
    with closing(sqlite3.connect(f"file:{config.WORK_DB}?mode=ro", uri=True)) as con:
        if rules == "db":
            con.execute("CREATE TEMP TABLE ids(id INTEGER PRIMARY KEY)")
            con.executemany("INSERT INTO ids VALUES (?)", [(int(i),) for i in d.id])
            a = pd.read_sql("""SELECT j.id, j.grant_ratio, j.grant_ratio_source, j.claimed_amount, j.claimed_source,
                                      j.quality_flags FROM judgments j JOIN ids USING (id)""", con)
            rule_version = "2.4.0"
        else:
            a, rule_version = rederive_amounts(d.id, con)
    d = select_sample(d.merge(a, on="id", how="left", validate="1:1"))
    flow = d.attrs["flow"]
    d["text"] = d.plaintiff_claim_text.fillna("")
    d["mid"] = d.case_type_mid.fillna("其他")
    d["court"] = d.court_s.fillna(UNKNOWN)
    for c in ("plaintiff_has_lawyer", "defendant_is_corp"):
        d[c] = d[c].astype(int).astype(str)
    d["claimed_amount"] = d.claimed_amount.astype(float)
    d["ratio"] = d.grant_ratio.astype(float)
    d.attrs["flow"], d.attrs["rule_version"] = flow, rule_version
    return d


def with_unknowns(d: pd.DataFrame, share: float = UNKNOWN_SHARE, seed: int = SEED) -> pd.DataFrame:
    """隨機把一部分法院換成「不知道」、一部分請求金額換成沒填（兩者各自獨立）。"""
    d = d.copy()
    rng = np.random.default_rng(seed)
    d.loc[rng.random(len(d)) < share, "court"] = UNKNOWN
    d.loc[rng.random(len(d)) < share, "claimed_amount"] = np.nan
    return d


# ── 範圍校準 ──
def calibrate(pred: np.ndarray, truth: np.ndarray, bins: int = N_BINS):
    """依預測值分組，每組殘差（實際 − 預測）的 10%、50%、90% 分位數。回傳（組界, 每組的三個分位數）。"""
    edges = np.quantile(pred, np.linspace(0, 1, bins + 1)[1:-1])
    idx = np.digitize(pred, edges)
    res = truth - pred
    q = np.array([np.quantile(res[idx == b], [LOW, 0.5, HIGH]) for b in range(bins)])
    return edges, q


def interval(pred: np.ndarray, edges: np.ndarray, q: np.ndarray) -> np.ndarray:
    """預測值 → (n, 3) 的（10%, 50%, 90%）獲償比例，裁到 [MIN_RATIO, 1]。"""
    idx = np.digitize(pred, edges)
    return np.clip(pred[:, None] + q[idx], MIN_RATIO, 1.0)


# ── 模型 ──
class AmountModel:
    """TF-IDF（原告主張）＋特徵 one-hot ＋請求金額與子項目，接一個 Ridge；範圍由校準得到。"""

    def __init__(self):
        self.vec = self.enc = self.ridge = None
        self.mu = self.sd = None
        self.edges = self.q = None

    def _dense(self, texts, claim, fit: bool) -> csr_matrix:
        claim = np.asarray(claim, dtype=float)
        known = np.isfinite(claim) & (claim > 0)
        lc = np.full(len(claim), np.nan)
        lc[known] = np.log10(claim[known])
        if fit:
            self.mu, self.sd = float(np.nanmean(lc)), float(np.nanstd(lc)) + 1e-9
        z = np.where(known, (lc - self.mu) / self.sd, 0.0)       # 沒填的請求金額放平均，另用旗標告訴模型
        items = np.array([[1.0 if p.search(t) else 0.0 for p in ITEM_PATTERNS] for t in texts]).reshape(len(texts), -1)
        return csr_matrix(np.column_stack([z, z ** 2, (~known).astype(float), items, items.sum(1) / 5]))

    def _X(self, texts, feats: pd.DataFrame, claim, fit: bool):
        texts = list(texts)
        text = self.vec.fit_transform(texts) if fit else self.vec.transform(texts)
        cat = self.enc.fit_transform(feats[FEATURES]) if fit else self.enc.transform(feats[FEATURES])
        return hstack([text, cat, self._dense(texts, claim, fit)]).tocsr()

    def fit(self, texts, feats: pd.DataFrame, claim, y) -> "AmountModel":
        self.vec, self.enc = vec(), OneHotEncoder(handle_unknown="ignore")
        self.ridge = Ridge(alpha=ALPHA).fit(self._X(texts, feats, claim, True), np.asarray(y, dtype=float))
        return self

    def predict(self, texts, feats: pd.DataFrame, claim) -> np.ndarray:
        return np.clip(self.ridge.predict(self._X(texts, feats, claim, False)), MIN_RATIO, 1.0)

    def predict_one(self, text: str, answers: Dict, claimed: Optional[float] = None) -> Dict:
        """使用者的描述與問卷答案 → 若為一部勝訴，獲償比例的（10%, 50%, 90%）。"""
        p = self.predict([prepare_input(text)], features_frame([answers]), [np.nan if not claimed else claimed])
        lo, mid, hi = interval(p, self.edges, self.q)[0]
        return {"ratio_low": float(lo), "ratio_median": float(mid), "ratio_high": float(hi), "coverage": HIGH - LOW}


# ── 評估 ──
def knn_quantiles(sim: np.ndarray, mids_tr: np.ndarray, ratio_tr: np.ndarray, mids_te: np.ndarray,
                  k: int = 30, min_same: int = 10) -> np.ndarray:
    """現行做法的近似：最相似的 k 件（同案由，同案由少於 min_same 件時不限案由）的獲償比例分位數。"""
    out = np.zeros((len(mids_te), 3))
    for i in range(len(mids_te)):
        same = np.where(mids_tr == mids_te[i])[0]
        idx = same if len(same) >= min_same else np.arange(len(mids_tr))
        top = idx[np.argsort(-sim[i, idx], kind="stable")[:k]]
        out[i] = np.quantile(ratio_tr[top], [LOW, 0.5, HIGH])
    return out


def group_quantiles(mids_tr, ratio_tr, mids_te, min_cases: int = 30) -> np.ndarray:
    allq = np.quantile(ratio_tr, [LOW, 0.5, HIGH])
    by = {m: np.quantile(ratio_tr[mids_tr == m], [LOW, 0.5, HIGH]) for m in np.unique(mids_tr)
          if (mids_tr == m).sum() >= min_cases}
    return np.array([by.get(m, allq) for m in mids_te])


def metrics(truth: np.ndarray, band: np.ndarray) -> Dict:
    """band 是 (n, 3)：10%、50%、90%。MAE 看中位數；涵蓋率是實際比例落在範圍內的比例（目標 80%）。"""
    lo, mid, hi = band[:, 0], band[:, 1], band[:, 2]
    return {"n": int(len(truth)), "mae": float(np.abs(mid - truth).mean()),
            "spearman": float(spearmanr(truth, mid).statistic),
            "coverage": float(((truth >= lo) & (truth <= hi)).mean()),
            "below": float((truth < lo).mean()), "above": float((truth > hi).mean()),
            "width": float((hi - lo).mean())}


def evaluate(d: pd.DataFrame, chunk: int = 500) -> Dict:
    """5 折（資料集的 fold 欄）。模型另外測「法院不知道」「請求金額沒填」「都沒填」三種使用者沒填的情況。"""
    truth = d.ratio.values
    scenarios = {"全部填": lambda x: x,
                 "法院不知道": lambda x: x.assign(court=UNKNOWN),
                 "請求金額沒填": lambda x: x.assign(claimed_amount=np.nan),
                 "都沒填": lambda x: x.assign(**{c: UNKNOWN for c in FEATURES}, claimed_amount=np.nan),
                 "混合（校準用）": lambda x: with_unknowns(x, seed=SEED + 1)}
    pred = {s: np.zeros(len(d)) for s in scenarios}
    base = {name: np.zeros((len(d), 3)) for name in ("全體分位數", "案由分位數", "相似判決分位數（現行做法的近似）")}
    for k in range(5):
        tr, te = (d.fold != k).values, (d.fold == k).values
        train, test = with_unknowns(d[tr]), d[te]
        model = AmountModel().fit(train.text, train, train.claimed_amount, train.ratio)
        for s, make in scenarios.items():
            x = make(test)
            pred[s][te] = model.predict(x.text, x, x.claimed_amount)
        ratio_tr, mids_tr, mids_te = d.ratio.values[tr], d.mid.values[tr], d.mid.values[te]
        base["全體分位數"][te] = np.quantile(ratio_tr, [LOW, 0.5, HIGH])
        base["案由分位數"][te] = group_quantiles(mids_tr, ratio_tr, mids_te)
        Ttr, Tte = model.vec.transform(list(train.text)), model.vec.transform(list(test.text))
        parts = [knn_quantiles((Tte[i:i + chunk] @ Ttr.T).toarray(), mids_tr, ratio_tr, mids_te[i:i + chunk])
                 for i in range(0, Tte.shape[0], chunk)]
        base["相似判決分位數（現行做法的近似）"][te] = np.vstack(parts)
        print(f"  fold {k} 完成", flush=True)

    # 範圍：用其他折的混合情境折外預測校準，再套到這一折（每個情境都用同一組校準）
    bands = {s: np.zeros((len(d), 3)) for s in scenarios}
    for k in range(5):
        te, rest = (d.fold == k).values, (d.fold != k).values
        edges, q = calibrate(pred["混合（校準用）"][rest], truth[rest])
        for s in scenarios:
            bands[s][te] = interval(pred[s][te], edges, q)
    results = {name: metrics(truth, band) for name, band in base.items()}
    results.update({f"模型：{s}": metrics(truth, bands[s]) for s in scenarios})
    results["_baseline_mae_global_median"] = float(np.abs(truth - np.median(truth)).mean())
    return results


def report(results: Dict, version: str, flow, rule_version: str = "") -> str:
    n = next(iter(results.values()))["n"]
    lines = [f"# 平台用獲償比例模型（第一版）：若為一部勝訴，原告贏幾成（{version}，{n:,} 件，5 折，金額欄位規則 {rule_version}）\n",
             "樣本流程：" + " → ".join(f"{s} {c:,}" for s, c in flow) + "\n",
             f"範圍是 {LOW:.0%}–{HIGH:.0%}（涵蓋率目標 {HIGH - LOW:.0%}）。MAE 是中位數和實際比例的平均差。"
             "「相似判決分位數」用 TF-IDF 找同案由最相似的 30 件，取獲償比例的分位數，近似平台現行做法"
             "（現行做法的相似判決還包含全部勝訴的案件，這裡只比一部勝訴）。\n",
             "| 方法 | MAE | Spearman | 涵蓋率 | 低於範圍 | 高於範圍 | 平均寬度 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name, r in results.items():
        if name.startswith("_"):
            continue
        lines.append(f"| {name} | {r['mae']:.3f} | {r['spearman']:.3f} | {r['coverage']:.1%} | {r['below']:.1%} | "
                     f"{r['above']:.1%} | {r['width']:.3f} |")
    lines.append(f"\n全部猜整體中位數的 MAE：{results['_baseline_mae_global_median']:.3f}。")
    lines.append("模型的範圍用「混合」情境（30% 法院不知道、30% 請求金額沒填）的折外殘差校準，其他情境套用同一組校準，"
                 "所以「全部填」會略高於 80%、「都沒填」會略低。")
    return "\n".join(lines) + "\n"


# ── 訓練與讀取 ──
def artifact_dir(base: Optional[Path] = None) -> Path:
    return Path(base or config.ARTIFACTS_DIR) / MODEL_NAME


def train(d: pd.DataFrame, version: str, out: Path, metrics_summary: Optional[Dict] = None,
          rule_version: str = "") -> Path:
    oof = np.zeros(len(d))
    for k in range(5):                         # 折外預測（測試折用混合情境）只用來校準範圍
        tr, te = (d.fold != k).values, (d.fold == k).values
        train_rows, test = with_unknowns(d[tr]), with_unknowns(d[te], seed=SEED + 1)
        m = AmountModel().fit(train_rows.text, train_rows, train_rows.claimed_amount, train_rows.ratio)
        oof[te] = m.predict(test.text, test, test.claimed_amount)
    rows = with_unknowns(d)
    model = AmountModel().fit(rows.text, rows, rows.claimed_amount, rows.ratio)
    model.edges, model.q = calibrate(oof, d.ratio.values)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "model.joblib", compress=3)
    meta = {"name": MODEL_NAME, "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dataset": f"text_dataset_{version}.csv", "n_cases": int(len(d)), "median_ratio": float(d.ratio.median()),
            "sample": f"一部勝訴一部敗訴、獲償比例是算出來的（金額欄位規則 {rule_version}）", "amount_rules": rule_version, "features": FEATURES + ["claimed_amount"],
            "unknown_share": UNKNOWN_SHARE, "interval": [LOW, HIGH],
            "description": "TF-IDF（原告主張）＋案由、法院、律師、對方是否為法人、請求金額、損害子項目；若為一部勝訴的獲償比例範圍",
            "metrics": metrics_summary or {}}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load(path: Optional[Path] = None):
    """回傳（模型, meta）。"""
    path = Path(path or artifact_dir())
    return joblib.load(path / "model.joblib"), json.loads((path / "meta.json").read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description="平台用的獲償比例模型（第一版）")
    ap.add_argument("action", choices=("evaluate", "train"))
    ap.add_argument("--version", default="v5")
    ap.add_argument("--out", default=None, help="模型輸出資料夾；預設 artifacts/civil_amount_v1")
    ap.add_argument("--rules", choices=("current", "db"), default="current",
                    help="金額欄位：current＝用目前的 structuring.py 重新推導（2.5.1，預設）；db＝資料庫的欄位（2.4.0）")
    a = ap.parse_args()
    t0 = time.time()
    d = load_training(a.version, a.rules)
    rule = d.attrs["rule_version"]
    print(f"{len(d):,} 件，獲償比例中位數 {d.ratio.median():.3f}，金額欄位規則 {rule}", flush=True)
    if a.action == "evaluate":
        results = evaluate(d)
        text = report(results, a.version, d.attrs["flow"], rule)
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (config.OUTPUT_DIR / f"amount_service_{a.version}_r{rule}.md").write_text(text, encoding="utf-8")
        (config.OUTPUT_DIR / f"amount_service_{a.version}_r{rule}.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(text)
    else:
        mf = config.OUTPUT_DIR / f"amount_service_{a.version}_r{rule}.json"
        summary = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
        out = train(d, a.version, Path(a.out) if a.out else artifact_dir(), summary, rule)
        print(f"已存到 {out}")
    print(f"完成，{(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    # 同 service.py：用 python -m 執行時模型檔裡的類別會記成 __main__.AmountModel，後端載入時找不到，
    # 改由正式的模組名稱執行。
    from civil.models import amount_service
    amount_service.main()
