"""
相似判決檢索的評估（服務化評估 S1）：只用原告主張，找最像的已判決案件。

    python -m retrieval.evaluate               # 民事，文字資料集 v5

情境：使用者只提供自己（原告）這一方的說法，前端（問卷或 LLM）已經判斷出案由中類。
方法（字元 1–3 gram TF-IDF、餘弦相似度）：
  A. 全部案件中找
  B. 只在同一案由中類裡找（假設前端判斷的案由是對的）
評估（隨機 3,000 件當查詢，排除本身；種子 0）：
  - 前 10 件的勝訴比例當預測的 AUC；前 1／前 10 件同一案由中類的比例；第 1 件的相似度中位數
  - 一部勝訴的查詢：前 10 件中一部勝訴案件的獲償比例中位數 vs 實際（Spearman、絕對誤差中位數；至少 3 件才算）
人工核對表：20 個查詢 × 方法 B 的前 3 件，附原告主張開頭 300 字，欄位「像不像（1–3）」留給人填。
輸出：retrieval_{版本}.md、retrieval_{版本}_核對表.xlsx
"""
import argparse
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

import config
from retrieval.civil import load_corpus, partial_with_ratio
from retrieval.engine import TfidfIndex

K = 10


def main():
    ap = argparse.ArgumentParser(description="民事相似判決檢索的評估")
    ap.add_argument("--version", default="v5")
    ap.add_argument("--queries", type=int, default=3000)
    a = ap.parse_args()
    out = config.OUTPUT_DIR
    lines = []

    def say(s=""):
        print(s, flush=True)
        lines.append(s)

    t0 = time.time()
    v = load_corpus(a.version)
    index = TfidfIndex().fit(v.plaintiff_claim_text)
    q = np.random.default_rng(0).choice(len(v), a.queries, replace=False)
    y, mid = v.y.values, v.case_type_mid.fillna("").values
    part = partial_with_ratio(v).values
    gr = v.grant_ratio.values

    say(f"# 相似判決檢索（只用原告主張，{a.version} {len(v):,} 件，查詢 {a.queries:,} 件，前 {K} 件）\n")
    say("| 方法 | 鄰居勝訴比例的 AUC | 第 1 件同案由中類 | 前 10 件同案由中類 | 第 1 件相似度中位數 | 一部勝訴：鄰居比例 vs 實際 Spearman | 絕對誤差中位數 | 件數 |")
    say("|---|---:|---:|---:|---:|---:|---:|---:|")
    res = {}
    for name, same in (("A. 全部案件", False), ("B. 同案由中類", True)):
        nn, sim = index.neighbors(q, K, mid if same else None)
        res[name] = (nn, sim)
        auc = roc_auc_score(y[q], y[nn].mean(1))
        pred, act = [], []
        for i, qi in enumerate(q):
            if part[qi]:
                gg = [gr[j] for j in nn[i] if part[j]]
                if len(gg) >= 3:
                    pred.append(np.median(gg)); act.append(gr[qi])
        pred, act = np.array(pred), np.array(act)
        base = np.median(np.abs(np.median(gr[part]) - act))
        say(f"| {name} | {auc:.3f} | {(mid[nn[:, 0]] == mid[q]).mean():.1%} | {(mid[nn] == mid[q][:, None]).mean():.1%} | "
            f"{np.median(sim[:, 0]):.2f} | {spearmanr(pred, act).statistic:.3f} | {np.median(np.abs(pred - act)):.3f}"
            f"（一律猜全體中位數：{base:.3f}） | {len(pred)} |")
    say("\nB 假設前端判斷的案由正確，所以「同案由中類」一定是 100%。AUC 的對照：只用原告的 TF-IDF 分類模型約 0.77。")

    nn, sim = res["B. 同案由中類"]
    rows = []
    for i in range(min(20, len(q))):
        qi = q[i]
        rows.append({"查詢": i + 1, "角色": "查詢", "名次": "", "案號": v.case_number[qi], "案由中類": mid[qi],
                     "判決結果": v.outcome[qi], "獲償比例": gr[qi], "相似度": "",
                     "原告主張（前 300 字）": v.plaintiff_claim_text[qi][:300], "像不像（1–3）": "", "備註": ""})
        for r_, j in enumerate(nn[i, :3], 1):
            rows.append({"查詢": i + 1, "角色": "找到的", "名次": r_, "案號": v.case_number[j], "案由中類": mid[j],
                         "判決結果": v.outcome[j], "獲償比例": gr[j], "相似度": round(float(sim[i, r_ - 1]), 3),
                         "原告主張（前 300 字）": v.plaintiff_claim_text[j][:300], "像不像（1–3）": "", "備註": ""})
    with pd.ExcelWriter(out / f"retrieval_{a.version}_核對表.xlsx") as w:
        pd.DataFrame(rows).to_excel(w, index=False, sheet_name="核對")
        pd.DataFrame({"說明": ["每個查詢 1 列＋找到的前 3 件（方法 B：同案由中類）。",
                               "像不像：3＝爭點和事實都像、2＝案件類型像但事實不同、1＝不像。",
                               "只用原告主張比對；判決結果與獲償比例是參考，不要用來判斷像不像。"]}).to_excel(
            w, index=False, sheet_name="說明")
    (out / f"retrieval_{a.version}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"完成，{(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()
