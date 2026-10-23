# -*- coding: utf-8 -*-
"""
TF-IDF（字 1–2 gram）＋ LinearSVC，在共用實驗包（share_national150_100k_5fold）上跑 5 折。

每一輪用該輪 train 訓練（SVM 不需挑 epoch，valid 不用），評該輪 test 與 2025 holdout；
類別用 fixed_classes.json 的固定清單與順序。罪名、法條加 class_weight="balanced"；
刑期只用刑期任務可用的案件（拘役、只判罰金不算）。結果為各輪平均 ± 樣本標準差。
CPU 即可，不需要 GPU。

用法：
  python models/svm_shared.py --shared share_national150_100k_5fold_20261022
  python models/svm_shared.py --shared ... --folds fold_01 --out svm_fold01.md
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
ap.add_argument("--shared", required=True, help="共用實驗包資料夾（含 shared_100k.jsonl 等）")
ap.add_argument("--folds", default="all", help="要跑的輪，例如 fold_01,fold_02；all = 全部")
ap.add_argument("--jobs", type=int, default=-1, help="one-vs-rest 平行數；記憶體不夠就調小")
ap.add_argument("--out", default="svm_shared.md")
args = ap.parse_args()

rows, assignments, classes = E.load_shared(args.shared)
folds = E.shared_folds(assignments) if args.folds == "all" else args.folds.split(",")
mlb = {t: MultiLabelBinarizer(classes=classes[t]).fit([[]]) for t in ("accusation", "article")}
res = collections.defaultdict(list)          # (split, 指標) → 各輪的值
t0 = time.time()
for fold in folds:
    sp = E.shared_split(rows, assignments, fold)
    tr = sp["train"]
    vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 2), min_df=3, max_features=300_000,
                          sublinear_tf=True, dtype=np.float32).fit([r["fact"] for r in tr])
    for t in ("accusation", "article"):
        a = E.task_rows(tr, t)
        Xa = vec.transform([r["fact"] for r in a]); Ya = mlb[t].transform([r[t] for r in a])
        keep = Ya.sum(0) > 0
        clf = OneVsRestClassifier(LinearSVC(C=0.5, class_weight="balanced"), n_jobs=args.jobs).fit(Xa, Ya[:, keep])
        top = E.top_classes(Ya)
        for split in ("test", "holdout"):
            b = E.task_rows(sp[split], t)
            Xb = vec.transform([r["fact"] for r in b]); Yb = mlb[t].transform([r[t] for r in b])
            P = np.zeros_like(Yb); P[:, keep] = E.at_least_one(clf.decision_function(Xb))
            for name, v in E.multilabel_scores(Yb, P, top).items():
                res[(split, f"{E.TASK_NAMES[t]} {name}")].append(v)
    a = E.task_rows(tr, "imprisonment")
    Xa = vec.transform([r["fact"] for r in a]); ma = np.array([r["months"] for r in a])
    bins = LinearSVC(C=0.5).fit(Xa, [E.bin_of(m) for m in ma])
    fin = ma >= 0
    reg = Ridge(alpha=1.0).fit(Xa[fin], np.log1p(ma[fin]))
    for split in ("test", "holdout"):
        b = E.task_rows(sp[split], "imprisonment")
        Xb = vec.transform([r["fact"] for r in b]); mb = [r["months"] for r in b]
        pred = np.clip(np.expm1(reg.predict(Xb)), 0, None).round()
        for name, v in E.term_scores(mb, bins.predict(Xb), pred).items():
            res[(split, f"刑期 {name}")].append(v)
    print(f"{fold} 完成（{time.time() - t0:.0f}s）：train {len(tr):,}、test {len(sp['test']):,}、holdout {len(sp['holdout']):,}；"
          + "、".join(f"{k[1]} {v[-1]:.3f}" for k, v in res.items() if k[0] == "test"), flush=True)

    keys = [k for k in dict.fromkeys(k[1] for k in res)]
    L = [f"# TF-IDF ＋ LinearSVC（共用實驗包 {os.path.basename(os.path.normpath(args.shared))}）", "",
         E.config_header(__file__, args), "",
         f"已完成 {len(res[('test', keys[0])])} 輪：{'、'.join(folds[:len(res[('test', keys[0])])])}。各輪用 train 訓練，"
         "評該輪 test 與 2025 holdout；數字為各輪平均 ± 樣本標準差。", "",
         "| 指標 | test 平均 | test 標準差 | holdout（2025）平均 | holdout 標準差 |", "|---|---|---|---|---|"]
    for k in keys:
        tm, ts = E.mean_std(res[("test", k)]); hm, hs = E.mean_std(res[("holdout", k)])
        L.append(f"| {k} | {tm:.3f} | {ts:.3f} | {hm:.3f} | {hs:.3f} |")
    open(args.out, "w", encoding="utf-8").write("\n".join(L) + "\n")   # 每輪寫一次，中途停掉也留得下
print(open(args.out, encoding="utf-8").read())
