# -*- coding: utf-8 -*-
"""
fastText 架構（PyTorch 實作，Kaggle GPU 用），每個任務各訓練一個模型。

輸入：字 1–2 gram 雜湊到 --buckets 個桶（HashingVectorizer，L2 正規化），EmbeddingBag 加權相加成一個判決向量
  罪名、法條：多標籤（BCE，pos_weight = sqrt(負例／正例)，上限 30）；驗證分數 = micro 與 macro 的平均
  刑期：區間分類（7 類）＋ log(月數 + 1) 迴歸兩個頭；驗證分數 = CAIL 分數
各任務只用該任務標籤可用的案件（meta.task_validity）。驗證分數連續 --patience 個 epoch 沒進步就停，
取驗證最好的 epoch，在 test（與 holdout）上只算一次；每個 epoch 寫一次結果檔。

兩種切分：
  全國資料（--data）：見 evaluate.holdout_split
    開發／調參數：--test-fold 0（test 隨機 5 萬筆；驗證 5 萬筆；train 取前 n 筆，學習曲線用 --sizes）
    正式 10-fold：--test-fold 依序 0–9、--test-n 0（整個 fold 當 test），各跑一次後彙整
  共用實驗包（--shared，芸菲 share_national150_100k_5fold）：每一輪用 CSV 的 train／valid／test／holdout，
    類別用 fixed_classes.json；--folds all 依序跑 5 輪，最後彙整平均 ± 樣本標準差

20 萬筆實測（2026-10-20）：學習率 0.005／0.01／0.03 中 0.01 驗證最好；三任務一起訓練時刑期在第 1 個 epoch
後就下降，所以改成分開訓練。

用法（Kaggle notebook，Accelerator 選 GPU；evaluate.py 要放在同一個資料夾）：
  小量測試：!python -W ignore fasttext_gpu.py --data cail_v2.jsonl --sizes 50000 --epochs 1
  學習曲線：!python -W ignore fasttext_gpu.py --data cail_v2.jsonl --out /kaggle/working/fasttext.md
  10-fold： !python -W ignore fasttext_gpu.py --data cail_v2.jsonl --sizes all --test-fold 3 --test-n 0 --out fold3.md
  共用包：  !python -W ignore fasttext_gpu.py --shared share_national150_100k_5fold_20261022 --out fasttext_shared.md
"""

import argparse
import copy
import gc
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as Fn
from scipy.sparse import vstack
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.preprocessing import MultiLabelBinarizer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluate as E  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--data", help="全國 CAIL 格式 .jsonl 或 .zip（與 --shared 擇一）")
ap.add_argument("--shared", help="共用實驗包資料夾（含 shared_100k.jsonl、shared_fold_assignments.csv、fixed_classes.json）")
ap.add_argument("--folds", default="all", help="--shared 時要跑的輪，例如 fold_01,fold_02；all = 全部")
ap.add_argument("--sizes", default="50000,200000,all", help="--data 時的訓練筆數，逗號分隔；all = 扣掉驗證集的全部")
ap.add_argument("--tasks", default="accusation,article,imprisonment", help="要跑的任務，逗號分隔")
ap.add_argument("--test-fold", type=int, default=0, help="--data 時當測試集的 fold")
ap.add_argument("--test-n", type=int, default=50_000, help="--data 時測試集筆數；0 = 整個 fold")
ap.add_argument("--val-n", type=int, default=50_000, help="--data 時驗證集筆數（從其他 fold 抽）")
ap.add_argument("--article-field", default="relevant_articles",
                help="法條欄位；relevant_articles_merged = 修法換條號合併後的版本")
ap.add_argument("--epochs", type=int, default=15, help="最多幾個 epoch")
ap.add_argument("--patience", type=int, default=4, help="驗證分數連續幾個 epoch 沒進步就停")
ap.add_argument("--dim", type=int, default=128)
ap.add_argument("--buckets", type=int, default=2 ** 20)
ap.add_argument("--batch", type=int, default=512)
ap.add_argument("--lr", type=float, default=0.01)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--out", default="fasttext.md")
args = ap.parse_args()
if bool(args.data) == bool(args.shared):
    ap.error("--data 與 --shared 要擇一")
dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("裝置：", dev, torch.cuda.get_device_name(0) if dev.type == "cuda" else "", flush=True)
torch.manual_seed(args.seed); np.random.seed(args.seed)
TASKS = [t for t in args.tasks.split(",") if t]
HEADER = E.config_header(__file__, args)
METRICS = {"accusation": ["micro", "macro", "其餘 macro"], "article": ["micro", "macro", "其餘 macro"],
           "imprisonment": ["區間 accuracy", "CAIL 分數"]}
hv = HashingVectorizer(analyzer="char", ngram_range=(1, 2), n_features=args.buckets, alternate_sign=False,
                       norm="l2", dtype=np.float32)


def featurize(rs):
    X = vstack([hv.transform([r["fact"] for r in rs[i:i + 100_000]]) for i in range(0, len(rs), 100_000)]).tocsr()
    X.sort_indices()
    return X


def index_of(rs, task):
    return np.array([i for i, r in enumerate(rs) if r["valid"][task]], dtype=np.int64)


# ── 模型 ──
class FastText(nn.Module):
    def __init__(self, heads):
        super().__init__()
        self.emb = nn.EmbeddingBag(args.buckets, args.dim, mode="sum", sparse=True)
        nn.init.normal_(self.emb.weight, std=0.05)
        self.drop = nn.Dropout(0.2)
        self.heads = nn.ModuleDict({k: nn.Linear(args.dim, d) for k, d in heads.items()})

    def forward(self, idx, off, w):
        h = self.drop(self.emb(idx, off, per_sample_weights=w))
        return {k: head(h) for k, head in self.heads.items()}


def batch_tensors(X, ids):
    sub = X[ids]
    return (torch.from_numpy(sub.indices.astype(np.int64)).to(dev, non_blocking=True),
            torch.from_numpy(sub.indptr[:-1].astype(np.int64)).to(dev, non_blocking=True),
            torch.from_numpy(sub.data).to(dev, non_blocking=True))


def predict(model, X, ids):
    model.eval(); outs = {}
    with torch.no_grad():
        for i in range(0, len(ids), 4096):
            for k, t in model(*batch_tensors(X, ids[i:i + 4096])).items():
                outs.setdefault(k, []).append(t.float().cpu())
    return {k: torch.cat(v).numpy() for k, v in outs.items()}


def evaluate(task, model, X, rs, top, mlb):
    ids = index_of(rs, task)
    out = predict(model, X, ids)
    if task == "imprisonment":
        mon = [rs[i]["months"] for i in ids]
        res = E.term_scores(mon, out["bin"].argmax(1), np.clip(np.expm1(out["reg"][:, 0]), 0, None).round())
        res["驗證分數"] = res["CAIL 分數"]
    else:
        Y = mlb[task].transform([rs[i][task] for i in ids])
        res = E.multilabel_scores(Y, E.at_least_one(out["out"]), top)
        res["驗證分數"] = (res["micro"] + res["macro"]) / 2
    return res


def pos_weight(Y):
    pos = Y.sum(0); neg = len(Y) - pos
    return torch.tensor(np.clip(np.sqrt(neg / np.maximum(pos, 1)), 1, 30), dtype=torch.float32, device=dev)


val_rows, test_rows = [], []
SPLIT_NOTE = []


def write_table():
    L = ["# fastText 架構（GPU；每個任務各一個模型）", "", HEADER, ""] + SPLIT_NOTE + ["", "## test 結果", ""]
    for task in TASKS:
        rs = [r for r in test_rows if r["任務"] == task]
        if rs:
            L += [f"### {E.TASK_NAMES[task]}", "", "| 切分 | 評分資料 | 訓練筆數 | 選用 epoch | " + " | ".join(METRICS[task]) + " | 訓練秒數 |",
                  "|---" * (len(METRICS[task]) + 5) + "|"]
            L += [f"| {r['切分']} | {r['評分']} | {r['n']:,} | {r['epoch']} | " + " | ".join(f"{r[k]:.3f}" for k in METRICS[task])
                  + f" | {r['秒數']:.0f} |" for r in rs]
            L.append("")
    if args.shared and len({r["切分"] for r in test_rows}) > 1:   # 多輪：平均 ± 樣本標準差
        L += ["## 各輪平均 ± 樣本標準差", "", "| 任務 | 評分資料 | 指標 | 平均 | 標準差 | 輪數 |", "|---|---|---|---|---|---|"]
        for task in TASKS:
            for split in ("test", "holdout"):
                rs = [r for r in test_rows if r["任務"] == task and r["評分"] == split]
                for k in METRICS[task] if rs else []:
                    m, s = E.mean_std([r[k] for r in rs])
                    L.append(f"| {E.TASK_NAMES[task]} | {split} | {k} | {m:.3f} | {s:.3f} | {len(rs)} |")
        L.append("")
    L += ["## 驗證集（每個 epoch）", "", "| 切分 | 訓練筆數 | 任務 | epoch | loss | 驗證分數 | 指標 | 累計秒數 |", "|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['切分']} | {r['n']:,} | {E.TASK_NAMES[r['任務']]} | {r['epoch']} | {r['loss']:.4f} | {r['驗證分數']:.4f} | "
          + "、".join(f"{k} {r[k]:.3f}" for k in METRICS[r["任務"]]) + f" | {r['秒數']:.0f} |" for r in val_rows]
    open(args.out, "w", encoding="utf-8").write("\n".join(L) + "\n")


def run(pool, val, evals, sizes, mlb, tag):
    """pool 已打亂；sizes 為訓練筆數（取 pool 前 n 筆）；evals = {名稱: 評分資料}。"""
    t0 = time.time()
    Xpool, Xval = featurize(pool), featurize(val)
    Xev = {k: featurize(v) for k, v in evals.items()}
    print(f"[{tag}] 特徵完成（{time.time() - t0:.0f}s）：train {Xpool.shape}、nnz {Xpool.nnz:,}", flush=True)
    for n in sizes:
        tr = pool[:n]; Xtr = Xpool[:n]
        for task in TASKS:
            ids = index_of(tr, task)
            if task == "imprisonment":
                top = []
                model = FastText({"bin": len(E.BINS) + 1, "reg": 1}).to(dev)
                mon = np.zeros(n); mon[ids] = [tr[i]["months"] for i in ids]
                yb = torch.from_numpy(np.array([E.bin_of(m) for m in mon], dtype=np.int64))
                ylog = torch.from_numpy(np.log1p(np.clip(mon, 0, None)).astype(np.float32))
                fin = torch.from_numpy(mon >= 0)                     # 迴歸不含死刑／無期
            else:
                Yfull = np.zeros((n, len(mlb[task].classes_)), dtype=np.float32)
                Yfull[ids] = mlb[task].transform([tr[i][task] for i in ids])
                top = E.top_classes(Yfull[ids])
                model = FastText({"out": Yfull.shape[1]}).to(dev)
                pw = pos_weight(Yfull[ids]); Yt = torch.from_numpy(Yfull)
            opt_s = torch.optim.SparseAdam(list(model.emb.parameters()), lr=args.lr)
            opt_d = torch.optim.Adam([p for name, p in model.named_parameters() if not name.startswith("emb")], lr=args.lr)
            best = (-1.0, 0, None); since_best = 0; t1 = time.time()
            for ep in range(1, args.epochs + 1):
                model.train(); perm = np.random.permutation(ids); tot = 0.0
                for i in range(0, len(perm), args.batch):
                    b = perm[i:i + args.batch]; bt = torch.from_numpy(b)
                    out = model(*batch_tensors(Xtr, b))
                    if task == "imprisonment":
                        loss = Fn.cross_entropy(out["bin"], yb[bt].to(dev))
                        fm = fin[bt].to(dev)
                        if fm.any():
                            loss = loss + Fn.mse_loss(out["reg"][:, 0][fm], ylog[bt].to(dev)[fm])
                    else:
                        loss = Fn.binary_cross_entropy_with_logits(out["out"], Yt[bt].to(dev), pos_weight=pw)
                    opt_s.zero_grad(); opt_d.zero_grad(); loss.backward(); opt_s.step(); opt_d.step()
                    tot += loss.item() * len(b)
                res = evaluate(task, model, Xval, val, top, mlb)
                res.update(切分=tag, n=n, 任務=task, epoch=ep, loss=tot / len(perm), 秒數=time.time() - t1)
                val_rows.append(res)
                print(f"  [{tag}] {n:,} 筆 {E.TASK_NAMES[task]} epoch {ep}/{args.epochs}（{res['秒數']:.0f}s）：loss {res['loss']:.4f}、"
                      f"驗證分數 {res['驗證分數']:.4f}、" + "、".join(f"{k} {res[k]:.3f}" for k in METRICS[task]), flush=True)
                if res["驗證分數"] > best[0]:
                    best = (res["驗證分數"], ep, copy.deepcopy(model.state_dict())); since_best = 0
                else:
                    since_best += 1
                write_table()
                if since_best >= args.patience:
                    print(f"  驗證分數 {args.patience} 個 epoch 沒進步，提早停止", flush=True)
                    break
            model.load_state_dict(best[2])
            for name, rs in evals.items():
                res = evaluate(task, model, Xev[name], rs, top, mlb)
                res.update(切分=tag, 評分=name, n=n, 任務=task, epoch=best[1], 秒數=time.time() - t1)
                test_rows.append(res)
                print(f"[{tag}] {n:,} 筆 {E.TASK_NAMES[task]} 完成，選用 epoch {best[1]}，{name}："
                      + "、".join(f"{k} {res[k]:.3f}" for k in METRICS[task]), flush=True)
            write_table()
            del model, opt_s, opt_d, best; gc.collect()
            if dev.type == "cuda":
                torch.cuda.empty_cache()


if args.shared:
    rows, assignments, classes = E.load_shared(args.shared, args.article_field)
    folds = E.shared_folds(assignments) if args.folds == "all" else args.folds.split(",")
    mlb = {t: MultiLabelBinarizer(classes=classes[t]).fit([[]]) for t in ("accusation", "article")}
    SPLIT_NOTE.append(f"共用實驗包 {os.path.basename(os.path.normpath(args.shared))}：每一輪用 CSV 的 train 訓練、valid 挑 epoch，"
                      f"評該輪 test 與 2025 holdout；固定類別 罪名 {len(classes['accusation'])}、法條 {len(classes['article'])} 類。")
    for fold in folds:
        sp = E.shared_split(rows, assignments, fold)
        pool = list(sp["train"]); np.random.RandomState(args.seed).shuffle(pool)
        print(f"[{fold}] train {len(pool):,}、valid {len(sp['valid']):,}、test {len(sp['test']):,}、holdout {len(sp['holdout']):,}", flush=True)
        run(pool, sp["valid"], {"test": sp["test"], "holdout": sp["holdout"]}, [len(pool)], mlb, fold)
else:
    rows = E.load(args.data, args.article_field)
    pool, val, test = E.holdout_split(rows, args.test_fold, args.test_n or None, args.val_n)
    sizes = [len(pool) if s == "all" else int(s) for s in args.sizes.split(",")]
    pool = pool[:max(sizes)]
    del rows; gc.collect()
    mlb = {t: MultiLabelBinarizer().fit([r[t] for r in pool + val + test if r["valid"][t]]) for t in ("accusation", "article")}
    SPLIT_NOTE.append(f"test：fold {args.test_fold}（{len(test):,} 筆）；驗證：其他 fold 另抽 {len(val):,} 筆（不參與訓練）。"
                      "每個任務取驗證分數最高的 epoch，在 test 上只算一次。")
    print(f"test {len(test):,}、驗證 {len(val):,}、train 候選 {len(pool):,}；任務：{'、'.join(TASKS)}", flush=True)
    run(pool, val, {"test": test}, sizes, mlb, f"fold {args.test_fold}")
print(open(args.out, encoding="utf-8").read())
