# -*- coding: utf-8 -*-
"""
TF-IDF ＋ LinearSVC 的學習曲線：固定測試集，訓練資料逐步增加，看資料量對各任務的影響。

切分見 evaluate.holdout_split（test：指定 fold 隨機 5 萬筆；train：其他 fold 打亂後的前 n 筆，巢狀子集）。
罪名、法條加 class_weight="balanced"；刑期只用刑期任務可用的案件。每跑完一個訓練量就寫一次結果檔。

注意：LinearSVC 加類別權重在 40 萬筆以上收斂很慢（Kaggle 12 小時跑不完），建議最多到 20 萬筆；
更大的訓練量請用 fasttext_gpu.py。本機記憶體不足時可在 Kaggle（CPU 即可）執行。

用法：
  python models/svm_learning_curve.py --data cail_v2.jsonl --sizes 50000,100000,200000
"""

import argparse
import gc
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
ap.add_argument("--sizes", default="50000,100000,200000", help="訓練筆數，逗號分隔")
ap.add_argument("--test-fold", type=int, default=0)
ap.add_argument("--jobs", type=int, default=-1, help="one-vs-rest 平行數；記憶體不夠就調小")
ap.add_argument("--dual", choices=["true", "false"], default="true",
                help="LinearSVC 解法；兩者分數相同，台北 2 萬／4 萬筆實測 true 較快")
ap.add_argument("--out", default="svm_learning_curve.md")
args = ap.parse_args()

rows = E.load(args.data)
sizes = [int(s) for s in args.sizes.split(",")]
pool, _, test = E.holdout_split(rows, test_fold=args.test_fold)
pool = pool[:max(sizes)]
del rows; gc.collect()
print(f"test {len(test):,}、train 候選 {len(pool):,}", flush=True)
mlb = {t: MultiLabelBinarizer().fit([r[t] for r in pool + test if r["valid"][t]]) for t in ("accusation", "article")}
svm = lambda **kw: LinearSVC(C=0.5, dual=args.dual == "true", **kw)
out_rows = []; t0 = time.time()
for n in sizes:
    tr = pool[:n]
    vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 2), min_df=3, max_features=300_000,
                          sublinear_tf=True, dtype=np.float32).fit([r["fact"] for r in tr])
    res = {"訓練筆數": n}
    for t in ("accusation", "article"):
        a, b = E.task_rows(tr, t), E.task_rows(test, t)
        Xa, Xb = vec.transform([r["fact"] for r in a]), vec.transform([r["fact"] for r in b])
        Ya, Yb = mlb[t].transform([r[t] for r in a]), mlb[t].transform([r[t] for r in b])
        keep = Ya.sum(0) > 0
        clf = OneVsRestClassifier(svm(class_weight="balanced"), n_jobs=args.jobs).fit(Xa, Ya[:, keep])
        P = np.zeros_like(Yb); P[:, keep] = E.at_least_one(clf.decision_function(Xb))
        for name, v in E.multilabel_scores(Yb, P, E.top_classes(Ya)).items():
            res[f"{E.TASK_NAMES[t]} {name}"] = v
        del clf; gc.collect()
    a, b = E.task_rows(tr, "imprisonment"), E.task_rows(test, "imprisonment")
    Xa, Xb = vec.transform([r["fact"] for r in a]), vec.transform([r["fact"] for r in b])
    ma, mb = np.array([r["months"] for r in a]), np.array([r["months"] for r in b])
    bins = svm().fit(Xa, [E.bin_of(m) for m in ma]).predict(Xb)
    fin = ma >= 0
    pred = np.clip(np.expm1(Ridge(alpha=1.0).fit(Xa[fin], np.log1p(ma[fin])).predict(Xb)), 0, None).round()
    for name, v in E.term_scores(mb, bins, pred).items():
        res[f"刑期 {name}"] = v
    out_rows.append(res)
    print(f"{n:,} 完成（{time.time() - t0:.0f}s）：" + "、".join(f"{k} {v:.3f}" for k, v in res.items() if k != "訓練筆數"), flush=True)
    keys = [k for k in out_rows[0] if k != "訓練筆數"]
    L = [f"# TF-IDF ＋ LinearSVC 學習曲線（test：fold {args.test_fold} 隨機 {len(test):,} 筆）", "",
         E.config_header(__file__, args), "",
         "| 訓練筆數 | " + " | ".join(keys) + " |", "|---" * (len(keys) + 1) + "|"]
    L += [f"| {r['訓練筆數']:,} | " + " | ".join(f"{r[k]:.3f}" for k in keys) + " |" for r in out_rows]
    open(args.out, "w", encoding="utf-8").write("\n".join(L) + "\n")   # 每組寫一次，中途停掉也留得下
    del vec; gc.collect()
print(open(args.out, encoding="utf-8").read())
