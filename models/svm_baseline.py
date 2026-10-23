# -*- coding: utf-8 -*-
"""
TF-IDF（字 1–2 gram）＋ LinearSVC 的 10-fold 基準線。

  罪名、法條：one-vs-rest 多標籤，比較有無 class_weight="balanced"
  刑期：只用刑期任務可用的案件；區間分類（LinearSVC）＋ log(月數 + 1) 迴歸（Ridge，算 CAIL 分數）
每個 fold 重新建 TF-IDF；各任務只用該任務標籤可用的案件（meta.task_validity）。
參數固定（C = 0.5），沒有調；結果為各 fold 平均 ± 標準差。

適合台北 v1.x（約 5 萬筆）。全國資料（約 100 萬筆）用 SVM 會跑不完，請改用 svm_learning_curve.py 或 fasttext_gpu.py。

用法：
  python models/svm_baseline.py --data CAIL格式_刑事判決_2018-2025_v1.1.jsonl
  python models/svm_baseline.py --data ... --folds 0,1,2 --out svm_3fold.md
"""

import argparse
import collections
import os
import sys
import time

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.svm import LinearSVC

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluate as E  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--data", required=True, help="CAIL 格式 .jsonl 或 .zip")
ap.add_argument("--folds", default="0,1,2,3,4,5,6,7,8,9", help="要當測試集的 fold，逗號分隔")
ap.add_argument("--out", default="svm_baseline.md")
args = ap.parse_args()

rows = E.load(args.data)
mlb = {t: MultiLabelBinarizer().fit([r[t] for r in rows if r["valid"][t]]) for t in ("accusation", "article")}
res = collections.defaultdict(list)
t0 = time.time()
for k in [int(x) for x in args.folds.split(",")]:
    tr = [r for r in rows if r["fold"] != k]; te = [r for r in rows if r["fold"] == k]
    vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 2), min_df=3, max_features=300_000, sublinear_tf=True)
    vec.fit([r["fact"] for r in tr])
    for t in ("accusation", "article"):
        a, b = E.task_rows(tr, t), E.task_rows(te, t)
        Xa, Xb = vec.transform([r["fact"] for r in a]), vec.transform([r["fact"] for r in b])
        Ya, Yb = mlb[t].transform([r[t] for r in a]), mlb[t].transform([r[t] for r in b])
        keep = Ya.sum(0) > 0
        top = E.top_classes(Ya)
        for cw in (None, "balanced"):
            clf = OneVsRestClassifier(LinearSVC(C=0.5, class_weight=cw), n_jobs=-1).fit(Xa, Ya[:, keep])
            P = np.zeros_like(Yb); P[:, keep] = E.at_least_one(clf.decision_function(Xb))
            for name, v in E.multilabel_scores(Yb, P, top).items():
                res[f"{E.TASK_NAMES[t]}｜{'加權重' if cw else '無權重'}｜{name}"].append(v)
        M = np.zeros_like(Yb); M[:, top[0]] = 1
        res[f"{E.TASK_NAMES[t]}｜全猜最常見｜micro"].append(E.multilabel_scores(Yb, M)["micro"])
    a, b = E.task_rows(tr, "imprisonment"), E.task_rows(te, "imprisonment")
    Xa, Xb = vec.transform([r["fact"] for r in a]), vec.transform([r["fact"] for r in b])
    ma, mb = np.array([r["months"] for r in a]), np.array([r["months"] for r in b])
    bins = LinearSVC(C=0.5).fit(Xa, [E.bin_of(m) for m in ma]).predict(Xb)
    fin = ma >= 0
    pred = np.clip(np.expm1(Ridge(alpha=1.0).fit(Xa[fin], np.log1p(ma[fin])).predict(Xb)), 0, None).round()
    for name, v in E.term_scores(mb, bins, pred).items():
        res[f"刑期｜{name}"].append(v)
    mode = collections.Counter(E.bin_of(m) for m in ma).most_common(1)[0][0]
    med = float(np.median(ma[fin]))
    res["刑期｜全猜最常見區間 accuracy"].append(E.term_scores(mb, [mode] * len(mb), [med] * len(mb))["區間 accuracy"])
    res["刑期｜全猜中位數 CAIL 分數"].append(E.cail_score(mb, [med] * len(mb)))
    print(f"fold {k} 完成（{time.time() - t0:.0f}s）", flush=True)

L = [f"# TF-IDF ＋ LinearSVC 基準線（{len(rows):,} 筆）", "", E.config_header(__file__, args), "",
     "| 項目 | 平均 | 標準差 |", "|---|---|---|"]
L += [f"| {k} | {np.mean(v):.3f} | {np.std(v):.3f} |" for k, v in res.items()]
open(args.out, "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L))
