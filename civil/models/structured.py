"""
文字 vs 結構化變數：在文字資料集的同一批案件、同一組 5 折上比較（待辦二的第 3 項）。

    python -m civil.models.structured v5
    python -m civil.models.structured v5 --crim     # 結構化變數再加「刑事移送」旗標

模型（全部用資料集的 fold 欄，logistic regression）：
  1. 結構化（base）：敏感度分析 A2 的變數（FEATS），不加懲罰
  2. 只用案由中間分類（同 tfidf.py）
  3. 文字：TF-IDF 原告＋被告（同 tfidf.py）
  4. 文字＋結構化：TF-IDF 稀疏矩陣直接接上結構化變數的 one-hot，一起 fit（C=1）。
     不用「把文字分數當變數」的堆疊法，因為訓練列的折外分數來自看過測試折的模型，會洩漏。
結構化欄位取自 analysis_fields.pkl（律師、法人、反訴、案由、請求權）；y 用文字資料集的結果。
輸出：text_vs_structured_{版本}.csv、text_vs_structured_oof_{版本}.csv
"""
import argparse
import time

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

import config
from civil.models.tfidf import logreg, vec

CATS = ["mid", "basis", "proc", "court_m", "year"]


def feats(crim: bool = False) -> list:
    return (["mid", "basis", "plaintiff_has_lawyer", "defendant_has_lawyer", "defendant_is_corp",
             "has_counterclaim", "proc", "remand", "court_m", "year"] + (["crim"] if crim else []))


FEATS = feats()


def load(version: str, crim: bool = False) -> pd.DataFrame:
    t = pd.read_csv(config.dataset_path(version), encoding="utf-8")
    f = pd.read_pickle(config.FIELDS_PKL)
    d = t.merge(f[["id", "claim_basis_group", "plaintiff_has_lawyer", "defendant_has_lawyer",
                   "defendant_is_corp", "has_counterclaim", "proc", "judgment_date", "court_s"]],
                on="id", how="left", validate="1:1")
    assert d.proc.notna().all(), "有案件對不到結構化欄位"
    if crim:
        # 「刑事移送」旗標（刑事移送_{版本}.csv）：這件民事判決是不是刑事庭移送過來的附帶民事訴訟
        c = pd.read_csv(config.OUTPUT_DIR / f"刑事移送_{version}.csv")
        d = d.merge(c, on="id", how="left", validate="1:1")
        assert d.crim.notna().all(), "有案件沒有刑事移送旗標"
    # 以下同 sensitivity.py 的 load() 與 add_categories()，在這個樣本內合併少數類別
    d["year"] = d.judgment_date.str[:4]
    d["remand"] = d.case_kind.str.contains(r"更[一二三]$").astype(int)
    for c in ["plaintiff_has_lawyer", "defendant_has_lawyer", "defendant_is_corp", "has_counterclaim"]:
        d[c] = d[c].astype(int)
    mid = d.case_type_mid.fillna("")
    d["mid"] = mid.where(mid.map(mid.value_counts()) >= 100, "其他小類")
    b = d.claim_basis_group.fillna("").replace("", "（未抽到）")
    d["basis"] = b.where(b.map(b.value_counts()) >= 100, "其他小類")
    d["court_m"] = d.court_s.where(d.court_s.map(d.court_s.value_counts()) >= 300, "小法院合併")
    d["p"] = d.plaintiff_claim_text.fillna("")
    d["d"] = d.defendant_defense_text.fillna("")
    return d


def design(d: pd.DataFrame, crim: bool = False) -> np.ndarray:
    """結構化變數的 one-hot 矩陣（drop_first），和合併模型用的是同一份。"""
    return pd.get_dummies(d[feats(crim)].astype({c: str for c in CATS}), drop_first=True).astype(float).values


def main():
    ap = argparse.ArgumentParser(description="文字 vs 結構化變數（5 折）")
    ap.add_argument("version", nargs="?", default="v5")
    ap.add_argument("--crim", action="store_true", help="結構化變數再加刑事移送旗標")
    a = ap.parse_args()
    tag = a.version + ("_crim" if a.crim else "")
    t0 = time.time()
    d = load(a.version, a.crim)
    print(f"{len(d):,} 筆，y＝1 比例 {d.y.mean():.3f}", flush=True)
    S = design(d, a.crim)
    M = pd.get_dummies(d[["mid"]], drop_first=True).astype(float).values
    y = d.y.values

    specs = {"結構化（base）": "S", "只用案由中間分類": "M", "文字（TF-IDF 原告＋被告）": "T",
             "文字＋結構化": "TS"}
    oof = {k: np.zeros(len(d)) for k in specs}
    aucs = {k: [] for k in specs}
    for k in range(5):
        tr, te = (d.fold != k).values, (d.fold == k).values
        vp, vd = vec(), vec()
        Ttr = hstack([vp.fit_transform(d.p[tr]), vd.fit_transform(d.d[tr])]).tocsr()
        Tte = hstack([vp.transform(d.p[te]), vd.transform(d.d[te])]).tocsr()
        for name, how in specs.items():
            if how == "S":
                m = LogisticRegression(penalty=None, max_iter=3000).fit(S[tr], y[tr]); Xte = S[te]
            elif how == "M":
                m = LogisticRegression(penalty=None, max_iter=3000).fit(M[tr], y[tr]); Xte = M[te]
            elif how == "T":
                m = logreg().fit(Ttr, y[tr]); Xte = Tte
            else:
                Xtr = hstack([Ttr, csr_matrix(S[tr])]).tocsr(); Xte = hstack([Tte, csr_matrix(S[te])]).tocsr()
                m = logreg().fit(Xtr, y[tr])
            oof[name][te] = m.predict_proba(Xte)[:, 1]
            aucs[name].append(roc_auc_score(y[te], oof[name][te]))
        print(f"  fold {k} 完成（{(time.time() - t0) / 60:.1f} 分）", flush=True)

    # 和結構化 base 的差：成對 bootstrap（全部折外預測，重抽 1,000 次）
    rng = np.random.default_rng(42)
    idx = [rng.integers(0, len(d), len(d)) for _ in range(1000)]
    base = oof["結構化（base）"]
    rows = []
    for name in specs:
        diff = [roc_auc_score(y[i], oof[name][i]) - roc_auc_score(y[i], base[i]) for i in idx]
        rows.append({"模型": name, "AUC平均": round(np.mean(aucs[name]), 4), "AUC標準差": round(np.std(aucs[name]), 4),
                     **{f"fold{k}": round(a, 4) for k, a in enumerate(aucs[name])},
                     "和base的差": round(np.mean(diff), 4),
                     "差_95CI": f"{np.percentile(diff, 2.5):+.4f}～{np.percentile(diff, 97.5):+.4f}"})
    r = pd.DataFrame(rows)
    r.to_csv(config.OUTPUT_DIR / f"text_vs_structured_{tag}.csv", index=False, encoding="utf-8-sig")
    o = d[["id", "fold", "y", "mid"]].copy()
    for name in specs:
        o[name] = oof[name]
    o.to_csv(config.OUTPUT_DIR / f"text_vs_structured_oof_{tag}.csv", index=False, encoding="utf-8-sig")
    print(r.to_string(index=False))
    print(f"完成，{(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()
