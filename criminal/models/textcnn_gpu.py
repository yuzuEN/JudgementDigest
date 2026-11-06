# -*- coding: utf-8 -*-
"""
TextCNN（Kim 2014；PyTorch，Kaggle GPU 用），每個任務各訓練一個模型。

輸入：事實逐字查字向量（字表從該次訓練資料建，出現少於 --vocab-min 次的字當 <UNK>），截到 --max-len 字
模型：寬 --kernels 個字的卷積窗口（每種寬度 --filters 個），ReLU，對每個窗口取整篇最大值（不含補白的位置），
      串起來 → dropout → 輸出頭
  罪名、法條：多標籤（BCE，pos_weight = sqrt(負例／正例)，上限 30）；驗證分數 = micro 與 macro 的平均
  刑期：區間分類（7 類）＋ log(月數 + 1) 迴歸兩個頭；驗證分數 = CAIL 分數
其餘（兩種切分 --data／--shared、task_validity 篩選、提早停止、只在 test 算一次、每個 epoch 寫檔）與 fasttext_gpu.py 相同。

20 萬筆實測（2026-10-22）：罪名、法條學習率 1e-3 驗證最好、刑期 3e-4 最好（--lr-term），最佳 epoch 在上限 10 附近，
學習曲線改用 --epochs 20。

用法（Kaggle notebook，Accelerator 選 GPU；evaluate.py 要放在同一個資料夾）：
  小量測試：!python -W ignore textcnn_gpu.py --data cail_v2.jsonl --sizes 50000 --epochs 1
  學習曲線：!python -W ignore textcnn_gpu.py --data cail_v2.jsonl --epochs 20 --patience 4 --lr-term 0.0003 --out textcnn.md
  10-fold： !python -W ignore textcnn_gpu.py --data cail_v2.jsonl --sizes all --test-fold 3 --test-n 0 --out fold3.md
  共用包：  !python -W ignore textcnn_gpu.py --shared share_national150_100k_5fold_20261022 --epochs 20 --patience 4 --lr-term 0.0003 --out textcnn_shared.md
"""

import argparse
import collections
import copy
import gc
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as Fn
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
ap.add_argument("--max-len", type=int, default=512, help="事實最多取幾個字")
ap.add_argument("--vocab-min", type=int, default=3, help="字在訓練資料出現少於幾次就當 <UNK>")
ap.add_argument("--emb-dim", type=int, default=200)
ap.add_argument("--kernels", default="2,3,4,5", help="卷積窗口寬度（字數），逗號分隔")
ap.add_argument("--filters", type=int, default=256, help="每種寬度幾個卷積核")
ap.add_argument("--dropout", type=float, default=0.5)
ap.add_argument("--epochs", type=int, default=10, help="最多幾個 epoch")
ap.add_argument("--patience", type=int, default=3, help="驗證分數連續幾個 epoch 沒進步就停")
ap.add_argument("--batch", type=int, default=256)
ap.add_argument("--lr", type=float, default=1e-3)
ap.add_argument("--lr-term", type=float, default=None, help="刑期任務另用的學習率；不給就用 --lr")
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--out", default="textcnn.md")
args = ap.parse_args()
if bool(args.data) == bool(args.shared):
    ap.error("--data 與 --shared 要擇一")
dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("裝置：", dev, torch.cuda.get_device_name(0) if dev.type == "cuda" else "", flush=True)
torch.manual_seed(args.seed); np.random.seed(args.seed)
TASKS = [t for t in args.tasks.split(",") if t]
KERNELS = [int(k) for k in args.kernels.split(",")]
HEADER = E.config_header(__file__, args)
AMP = dev.type == "cuda"                                  # GPU 上用混合精度，T4 快很多
METRICS = {"accusation": ["micro", "macro", "其餘 macro"], "article": ["micro", "macro", "其餘 macro"],
           "imprisonment": ["區間 accuracy", "CAIL 分數"]}


def build_vocab(rs):
    """字表只用訓練資料建，0 = 補白、1 = <UNK>。"""
    counts = collections.Counter()
    for r in rs:
        counts.update(r["fact"][:args.max_len])
    return {c: i + 2 for i, (c, n) in enumerate((c, n) for c, n in counts.most_common() if n >= args.vocab_min)}


def encode(rs, vocab):
    dtype = np.uint16 if len(vocab) + 2 < 65536 else np.int32
    X = np.zeros((len(rs), args.max_len), dtype=dtype)
    L = np.zeros(len(rs), dtype=np.int32)
    for i, r in enumerate(rs):
        ids = [vocab.get(c, 1) for c in r["fact"][:args.max_len]]
        X[i, :len(ids)] = ids; L[i] = max(len(ids), 1)
    return X, L


def index_of(rs, task):
    return np.array([i for i, r in enumerate(rs) if r["valid"][task]], dtype=np.int64)


# ── 模型 ──
class TextCNN(nn.Module):
    def __init__(self, vocab_size, heads):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, args.emb_dim, padding_idx=0)
        self.convs = nn.ModuleList([nn.Conv1d(args.emb_dim, args.filters, k) for k in KERNELS])
        self.drop = nn.Dropout(args.dropout)
        self.heads = nn.ModuleDict({k: nn.Linear(args.filters * len(KERNELS), d) for k, d in heads.items()})

    def forward(self, x, lengths):
        e = self.emb(x).transpose(1, 2)                       # (batch, 字向量, 字數)
        pooled = []
        for k, conv in zip(KERNELS, self.convs):
            c = Fn.relu(conv(e))                              # (batch, filters, 字數 − k + 1)
            # 只在真正的字上取最大值：超出事實長度的窗口（全是補白）不算
            valid = torch.arange(c.shape[2], device=c.device)[None, :] <= (lengths[:, None] - k).clamp(min=0)
            pooled.append(c.masked_fill(~valid[:, None, :], float("-inf")).max(2).values)
        h = self.drop(torch.cat(pooled, 1))
        return {k: head(h) for k, head in self.heads.items()}


def batch_tensors(X, L, ids):
    lengths = L[ids]
    width = max(int(lengths.max()), max(KERNELS))             # 只補到這批最長的那篇
    x = torch.from_numpy(X[ids, :width].astype(np.int64)).to(dev, non_blocking=True)
    return x, torch.from_numpy(lengths.astype(np.int64)).to(dev, non_blocking=True)


def predict(model, X, L, ids):
    model.eval(); outs = {}
    with torch.no_grad(), torch.autocast(dev.type, enabled=AMP):
        for i in range(0, len(ids), 1024):
            for k, t in model(*batch_tensors(X, L, ids[i:i + 1024])).items():
                outs.setdefault(k, []).append(t.float().cpu())
    return {k: torch.cat(v).numpy() for k, v in outs.items()}


def evaluate(task, model, X, L, rs, top, mlb):
    ids = index_of(rs, task)
    out = predict(model, X, L, ids)
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
    L = ["# TextCNN（GPU；每個任務各一個模型）", "", HEADER, ""] + SPLIT_NOTE + ["", "## test 結果", ""]
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
    """pool 已打亂；sizes 為訓練筆數（取 pool 前 n 筆）；evals = {名稱: 評分資料}。字表用 pool（最大訓練量）建。"""
    t0 = time.time()
    vocab = build_vocab(pool)
    Xpool, Lpool = encode(pool, vocab); Xval, Lval = encode(val, vocab)
    Xev = {k: encode(v, vocab) for k, v in evals.items()}
    print(f"[{tag}] 字表 {len(vocab):,} 字（出現 ≥ {args.vocab_min} 次）；編碼完成（{time.time() - t0:.0f}s）；"
          f"事實長度中位數 {int(np.median(Lpool))} 字，超過 {args.max_len} 字被截斷的占 {np.mean(Lpool >= args.max_len):.1%}", flush=True)
    for n in sizes:
        tr = pool[:n]
        for task in TASKS:
            ids = index_of(tr, task)
            if task == "imprisonment":
                top = []
                model = TextCNN(len(vocab) + 2, {"bin": len(E.BINS) + 1, "reg": 1}).to(dev)
                mon = np.zeros(n); mon[ids] = [tr[i]["months"] for i in ids]
                yb = torch.from_numpy(np.array([E.bin_of(m) for m in mon], dtype=np.int64))
                ylog = torch.from_numpy(np.log1p(np.clip(mon, 0, None)).astype(np.float32))
                fin = torch.from_numpy(mon >= 0)                     # 迴歸不含死刑／無期
            else:
                Yfull = np.zeros((n, len(mlb[task].classes_)), dtype=np.float32)
                Yfull[ids] = mlb[task].transform([tr[i][task] for i in ids])
                top = E.top_classes(Yfull[ids])
                model = TextCNN(len(vocab) + 2, {"out": Yfull.shape[1]}).to(dev)
                pw = pos_weight(Yfull[ids]); Yt = torch.from_numpy(Yfull)
            lr = args.lr_term if task == "imprisonment" and args.lr_term else args.lr
            opt = torch.optim.Adam(model.parameters(), lr=lr)
            scaler = torch.amp.GradScaler(dev.type, enabled=AMP)
            best = (-1.0, 0, None); since_best = 0; t1 = time.time()
            for ep in range(1, args.epochs + 1):
                model.train(); perm = np.random.permutation(ids); tot = 0.0
                for i in range(0, len(perm), args.batch):
                    b = perm[i:i + args.batch]; bt = torch.from_numpy(b)
                    with torch.autocast(dev.type, enabled=AMP):
                        out = model(*batch_tensors(Xpool, Lpool, b))
                    out = {k: v.float() for k, v in out.items()}       # 損失用 float32 算，避免溢位
                    if task == "imprisonment":
                        loss = Fn.cross_entropy(out["bin"], yb[bt].to(dev))
                        fm = fin[bt].to(dev)
                        if fm.any():
                            loss = loss + Fn.mse_loss(out["reg"][:, 0][fm], ylog[bt].to(dev)[fm])
                    else:
                        loss = Fn.binary_cross_entropy_with_logits(out["out"], Yt[bt].to(dev), pos_weight=pw)
                    opt.zero_grad(set_to_none=True)
                    scaler.scale(loss).backward(); scaler.step(opt); scaler.update()
                    tot += loss.item() * len(b)
                res = evaluate(task, model, Xval, Lval, val, top, mlb)
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
            for name, (Xe, Le) in Xev.items():
                res = evaluate(task, model, Xe, Le, evals[name], top, mlb)
                res.update(切分=tag, 評分=name, n=n, 任務=task, epoch=best[1], 秒數=time.time() - t1)
                test_rows.append(res)
                print(f"[{tag}] {n:,} 筆 {E.TASK_NAMES[task]} 完成，選用 epoch {best[1]}，{name}："
                      + "、".join(f"{k} {res[k]:.3f}" for k in METRICS[task]), flush=True)
            write_table()
            del model, opt, best; gc.collect()
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
