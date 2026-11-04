"""
文字資料集 v5 的自動洩漏檢查（和 v4 並列）。用 .venv 執行。

    .venv\\Scripts\\python -m civil.dataset.leak_check

如果法院的判斷混進兩造段落，AUC 反而會上升，所以 v5 比 v4 好不能證明沒有洩漏。這裡做兩種檢查：
  1. 最能區分勝敗的字詞（同 tfidf.py：抽 8,000 筆 fit 有名稱的 TF-IDF＋logistic，取係數最大／最小各 100 個），
     標出看起來像法院用語的字詞，附例句。v2 的聲明洩漏（「如主文」）就是這樣發現的。
  2. 法院用語單獨的區分力：每個字詞出現在原告段／答辯段的案件比例、勝訴率，以及「有沒有這個字詞」單獨分辨
     勝敗的 AUC（0.5＝沒有資訊）。同進度報告第 2.4 節。
輸出：output/v5_leak_check.md、output/v5_leak_top_terms.csv、output/v5_leak_terms.csv
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

import config  # noqa: E402
from civil.models.tfidf import vec_named  # noqa: E402

DATA = config.DATASET_DIR
OUT = config.OUTPUT_DIR
# 看起來像法院在說話的字詞。當事人也會寫其中一些（「原告請求無理由」「足認」），所以要看例句判斷
COURT = ["本院", "鈞院", "堪認", "堪信", "足認", "經查", "得心證", "不爭執事項", "兩造不爭執", "為有理由", "為無理由",
         "應予准許", "應予駁回", "洵屬", "自屬有據", "不足採", "可採", "如主文", "主文", "判決如", "認定", "爰判決"]
COURT_RE = re.compile("|".join(map(re.escape, COURT)))


def load(ver):
    d = pd.read_csv(DATA / f"text_dataset_{ver}.csv", usecols=["id", "y", "plaintiff_claim_text", "defendant_defense_text"])
    d["p"] = d.plaintiff_claim_text.fillna("")
    d["d"] = d.defendant_defense_text.fillna("")
    return d


def top_terms(d):
    s = d.sample(8000, random_state=42)
    vp, vd = vec_named(), vec_named()
    X = hstack([vp.fit_transform(s.p), vd.fit_transform(s.d)]).tocsr()
    m = LogisticRegression(C=1.0, solver="liblinear", max_iter=2000).fit(X, s.y)
    names = np.array(["原告｜" + t for t in vp.get_feature_names_out()] + ["被告｜" + t for t in vd.get_feature_names_out()])
    coef = m.coef_[0]
    o = np.argsort(coef)
    return pd.concat([pd.DataFrame({"方向": "傾向原告勝", "排名": range(1, 101), "特徵": names[o[::-1][:100]],
                                    "係數": coef[o[::-1][:100]].round(3)}),
                      pd.DataFrame({"方向": "傾向原告敗", "排名": range(1, 101), "特徵": names[o[:100]],
                                    "係數": coef[o[:100]].round(3)})])


def term_table(d, ver):
    rows = []
    for w in COURT:
        for col, nm in (("p", "原告段"), ("d", "答辯段")):
            has = d[col].str.contains(w, regex=False)
            if has.sum() < 20:
                continue
            rows.append({"版本": ver, "字詞": w, "段落": nm, "件數": int(has.sum()), "占比": round(has.mean(), 4),
                         "有：勝訴率": round(d.y[has].mean(), 3), "沒有：勝訴率": round(d.y[~has].mean(), 3),
                         "單獨 AUC": round(roc_auc_score(d.y, has.astype(int)), 3)})
    return pd.DataFrame(rows)


def example(d, feat, n=2):
    side, term = feat.split("｜", 1)
    col = "p" if side == "原告" else "d"
    hit = d[d[col].str.contains(term, regex=False)].sample(frac=1, random_state=1).head(n)
    out = []
    for t in hit[col]:
        k = t.find(term)
        out.append(t[max(0, k - 30):k + len(term) + 20])
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    d4, d5 = load("v4"), load("v5")
    top = top_terms(d5)
    top.to_csv(OUT / "v5_leak_top_terms.csv", index=False, encoding="utf-8-sig")
    t4 = pd.read_csv(OUT / "tfidf_top_terms_v4.csv")
    terms = pd.concat([term_table(d4, "v4"), term_table(d5, "v5")])
    terms.to_csv(OUT / "v5_leak_terms.csv", index=False, encoding="utf-8-sig")

    L = ["# v5 自動洩漏檢查\n", f"v4 {len(d4):,} 件、v5 {len(d5):,} 件。\n",
         "## 1. 最能區分勝敗的字詞（v5，各方向前 30）\n"]
    for dirn in ("傾向原告勝", "傾向原告敗"):
        t = top[top.方向 == dirn].head(30)
        L.append(f"**{dirn}**：" + "、".join(t.特徵) + "\n")
    flagged = top[top.特徵.str.split("｜").str[1].str.contains(COURT_RE)]
    L.append(f"前 100 名裡像法院用語的特徵：{len(flagged)} 個（v4 同樣的方法："
             f"{int(t4.特徵.str.split('｜').str[1].str.contains(COURT_RE).sum())} 個）\n")
    if len(flagged):
        L += ["| 方向 | 排名 | 特徵 | 例句 |", "|---|---:|---|---|"]
        for _, r in flagged.iterrows():
            L.append(f"| {r.方向} | {r.排名} | {r.特徵} | {' ／ '.join(example(d5, r.特徵))} |")
    L += ["\n## 2. 法院用語單獨的區分力（單獨 AUC 0.5＝沒有資訊）\n",
          "| 字詞 | 段落 | v4 件數 | v4 單獨 AUC | v5 件數 | v5 有：勝訴率 | v5 沒有：勝訴率 | v5 單獨 AUC |",
          "|---|---|---:|---:|---:|---:|---:|---:|"]
    p4 = terms[terms.版本 == "v4"].set_index(["字詞", "段落"])
    for _, r in terms[terms.版本 == "v5"].iterrows():
        k = (r.字詞, r.段落)
        a4 = p4.loc[k] if k in p4.index else None
        L.append(f"| {r.字詞} | {r.段落} | {'' if a4 is None else f'{int(a4.件數):,}'} | "
                 f"{'' if a4 is None else a4['單獨 AUC']} | {r.件數:,} | {r['有：勝訴率']} | {r['沒有：勝訴率']} | {r['單獨 AUC']} |")
    worst = terms[terms.版本 == "v5"].assign(偏離=lambda x: (x["單獨 AUC"] - 0.5).abs()).sort_values("偏離", ascending=False)
    L.append(f"\nv5 中單獨 AUC 離 0.5 最遠的：" + "、".join(
        f"{r.字詞}（{r.段落}，{r['單獨 AUC']}，{r.件數:,} 件）" for _, r in worst.head(5).iterrows()))
    txt = "\n".join(L) + "\n"
    print(txt)
    (OUT / "v5_leak_check.md").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
