# -*- coding: utf-8 -*-
"""
SVM 刑期加入罪名：TF-IDF 後面接罪名 one-hot，看知道罪名對刑期有多少幫助（共用實驗包 5 折）。

三種輸入都用同一個 TF-IDF 與模型（區間 LinearSVC ＋ log 月數 Ridge）：
  只看事實；事實 ＋ 正確罪名（上限，實際使用時拿不到）；事實 ＋ 預測罪名（實際可用）。
訓練一律用正確罪名；預測罪名來自只用該輪 train 訓練的 LinearSVC。罪名任務不可用的案件 one-hot 全 0。

用法：python criminal/models/svm_term_charge.py --shared <共用包> --out svm_term_charge.md
"""

import argparse
import collections
import os
import sys
import time

import numpy as np
import scipy.sparse as sp_
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.svm import LinearSVC

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluate as E  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--shared", required=True)
ap.add_argument("--folds", default="all")
ap.add_argument("--jobs", type=int, default=3)
ap.add_argument("--charge-weight", type=float, default=1.0, help="罪名 one-hot 的權重（TF-IDF 向量長度為 1）")
ap.add_argument("--out", default="svm_term_charge.md")
args = ap.parse_args()

rows, assignments, classes = E.load_shared(args.shared)
folds = E.shared_folds(assignments) if args.folds == "all" else args.folds.split(",")
mlb = MultiLabelBinarizer(classes=classes["accusation"]).fit([[]])
res = collections.defaultdict(list)
t0 = time.time()


def gold(rs):
    return sp_.csr_matrix(mlb.transform([r["accusation"] if r["valid"]["accusation"] else [] for r in rs]).astype(np.float32))


for fold in folds:
    sp = E.shared_split(rows, assignments, fold)
    tr = sp["train"]
    vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 2), min_df=3, max_features=300_000,
                          sublinear_tf=True, dtype=np.float32).fit([r["fact"] for r in tr])
    a = E.task_rows(tr, "accusation")
    Ya = mlb.transform([r["accusation"] for r in a]); keep = Ya.sum(0) > 0
    charge = OneVsRestClassifier(LinearSVC(C=0.5, class_weight="balanced"), n_jobs=args.jobs).fit(
        vec.transform([r["fact"] for r in a]), Ya[:, keep])

    t = E.task_rows(tr, "imprisonment")
    Xt = vec.transform([r["fact"] for r in t]); ma = np.array([r["months"] for r in t]); fin = ma >= 0
    for name, X in (("只看事實", Xt), ("事實＋罪名", sp_.hstack([Xt, gold(t) * args.charge_weight]).tocsr())):
        bins = LinearSVC(C=0.5).fit(X, [E.bin_of(m) for m in ma])
        reg = Ridge(alpha=1.0).fit(X[fin], np.log1p(ma[fin]))
        for split in ("test", "holdout"):
            b = E.task_rows(sp[split], "imprisonment")
            Xb = vec.transform([r["fact"] for r in b]); mb = [r["months"] for r in b]
            if name == "只看事實":
                inputs = {"只看事實": Xb}
            else:
                P = np.zeros((len(b), len(mlb.classes_)), dtype=np.float32)
                P[:, keep] = E.at_least_one(charge.decision_function(Xb))
                inputs = {"事實＋正確罪名": sp_.hstack([Xb, gold(b) * args.charge_weight]).tocsr(),
                          "事實＋預測罪名": sp_.hstack([Xb, sp_.csr_matrix(P) * args.charge_weight]).tocsr()}
            for label, Xi in inputs.items():
                pred = np.clip(np.expm1(reg.predict(Xi)), 0, None).round()
                for k, v in E.term_scores(mb, bins.predict(Xi), pred).items():
                    res[(label, split, k)].append(v)
    print(f"{fold} 完成（{time.time() - t0:.0f}s）", flush=True)

    L = [f"# SVM 刑期加入罪名（{os.path.basename(os.path.normpath(args.shared))}）", "", E.config_header(__file__, args), "",
         f"已完成 {len(res[('只看事實', 'test', '區間 accuracy')])} 輪。訓練用正確罪名；「預測罪名」來自只用該輪 train 訓練的 LinearSVC。", "",
         "| 輸入 | 指標 | test 平均 | test 標準差 | 2025 平均 | 2025 標準差 |", "|---|---|---|---|---|---|"]
    for label in ("只看事實", "事實＋預測罪名", "事實＋正確罪名"):
        for k in ("區間 accuracy", "CAIL 分數"):
            tm, ts = E.mean_std(res[(label, "test", k)]); hm, hs = E.mean_std(res[(label, "holdout", k)])
            L.append(f"| {label} | {k} | {tm:.3f} | {ts:.3f} | {hm:.3f} | {hs:.3f} |")
    open(args.out, "w", encoding="utf-8").write("\n".join(L) + "\n")
print(open(args.out, encoding="utf-8").read())
