# -*- coding: utf-8 -*-
"""
TextCNN（Kim 2014；PyTorch，Kaggle GPU 用），每個任務各訓練一個模型。

輸入：事實逐字查字向量（字表從訓練資料建，出現少於 --vocab-min 次的字當 <UNK>），截到 --max-len 字
模型：寬 --kernels 個字的卷積窗口（每種寬度 --filters 個），ReLU，對每個窗口取整篇最大值（不含補白的位置），
      串起來 → dropout → 輸出頭
  罪名、法條：多標籤（BCE，pos_weight = sqrt(負例／正例)，上限 30）；驗證分數 = micro 與 macro 的平均
  刑期：區間分類（7 類）＋ log(月數 + 1) 迴歸兩個頭；驗證分數 = CAIL 分數
其餘（切分、task_validity 篩選、提早停止、只在 test 算一次、每個 epoch 寫檔）與 fasttext_gpu.py 相同。

用法（Kaggle notebook，Accelerator 選 GPU；evaluate.py 要放在同一個資料夾）：
  小量測試：!python -W ignore textcnn_gpu.py --data cail_v2.jsonl --sizes 50000 --epochs 1
  開發：    !python -W ignore textcnn_gpu.py --data cail_v2.jsonl --out /kaggle/working/textcnn.md
  10-fold： !python -W ignore textcnn_gpu.py --data cail_v2.jsonl --sizes all --test-fold 3 --test-n 0 --out fold3.md
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
ap.add_argument("--data", required=True, help="CAIL 格式 .jsonl 或 .zip")
ap.add_argument("--sizes", default="50000,200000,all", help="訓練筆數，逗號分隔；all = 扣掉驗證集的全部")
ap.add_argument("--tasks", default="accusation,article,imprisonment", help="要跑的任務，逗號分隔")
ap.add_argument("--test-fold", type=int, default=0, help="當測試集的 fold")
ap.add_argument("--test-n", type=int, default=50_000, help="測試集筆數；0 = 整個 fold")
ap.add_argument("--val-n", type=int, default=50_000, help="驗證集筆數（從其他 fold 抽）")
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
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--out", default="textcnn.md")
args = ap.parse_args()
dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("裝置：", dev, torch.cuda.get_device_name(0) if dev.type == "cuda" else "", flush=True)
torch.manual_seed(args.seed); np.random.seed(args.seed)
TASKS = [t for t in args.tasks.split(",") if t]
KERNELS = [int(k) for k in args.kernels.split(",")]
HEADER = E.config_header(__file__, args)
AMP = dev.type == "cuda"                                  # GPU 上用混合精度，T4 快很多

# ── 資料 ──
rows = E.load(args.data, args.article_field)
pool, val, test = E.holdout_split(rows, args.test_fold, args.test_n or None, args.val_n)
sizes = [len(pool) if s == "all" else int(s) for s in args.sizes.split(",")]
pool = pool[:max(sizes)]
del rows; gc.collect()
print(f"test {len(test):,}、驗證 {len(val):,}、train 候選 {len(pool):,}；任務：{'、'.join(TASKS)}", flush=True)

# 字表只用訓練資料建（最大訓練量那一份），0 = 補白、1 = <UNK>
t0 = time.time()
counts = collections.Counter()
for r in pool:
    counts.update(r["fact"][:args.max_len])
chars = [c for c, n in counts.most_common() if n >= args.vocab_min]
vocab = {c: i + 2 for i, c in enumerate(chars)}
dtype = np.uint16 if len(vocab) + 2 < 65536 else np.int32


def encode(rs):
    X = np.zeros((len(rs), args.max_len), dtype=dtype)
    L = np.zeros(len(rs), dtype=np.int32)
    for i, r in enumerate(rs):
        ids = [vocab.get(c, 1) for c in r["fact"][:args.max_len]]
        X[i, :len(ids)] = ids; L[i] = max(len(ids), 1)
    return X, L


(Xpool, Lpool), (Xval, Lval), (Xte, Lte) = encode(pool), encode(val), encode(test)
print(f"字表 {len(vocab):,} 字（出現 ≥ {args.vocab_min} 次）；編碼完成（{time.time() - t0:.0f}s）；"
      f"事實長度中位數 {int(np.median(Lpool))} 字，超過 {args.max_len} 字被截斷的占 {np.mean(Lpool >= args.max_len):.1%}", flush=True)
mlb = {t: MultiLabelBinarizer().fit([r[t] for r in pool + val + test if r["valid"][t]]) for t in ("accusation", "article")}


def index_of(rs, task):
    return np.array([i for i, r in enumerate(rs) if r["valid"][task]], dtype=np.int64)


# ── 模型 ──
class TextCNN(nn.Module):
    def __init__(self, heads):
        super().__init__()
        self.emb = nn.Embedding(len(vocab) + 2, args.emb_dim, padding_idx=0)
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


def evaluate(task, model, X, L, rs, top):
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


METRICS = {"accusation": ["micro", "macro", "其餘 macro"], "article": ["micro", "macro", "其餘 macro"],
           "imprisonment": ["區間 accuracy", "CAIL 分數"]}


def write_table(val_rows, test_rows):
    L = [f"# TextCNN（GPU；每個任務各一個模型）", "", HEADER, "",
         f"test：fold {args.test_fold}（{len(test):,} 筆）；驗證：其他 fold 另抽 {len(val):,} 筆（不參與訓練）。"
         "每個任務取驗證分數最高的 epoch，在 test 上只算一次。", "", "## test 結果", ""]
    for task in TASKS:
        rs = [r for r in test_rows if r["任務"] == task]
        if rs:
            L += [f"### {E.TASK_NAMES[task]}", "", "| 訓練筆數 | 選用 epoch | " + " | ".join(METRICS[task]) + " | 訓練秒數 |",
                  "|---" * (len(METRICS[task]) + 3) + "|"]
            L += [f"| {r['n']:,} | {r['epoch']} | " + " | ".join(f"{r[k]:.3f}" for k in METRICS[task]) + f" | {r['秒數']:.0f} |" for r in rs]
            L.append("")
    L += ["## 驗證集（每個 epoch）", "", "| 訓練筆數 | 任務 | epoch | loss | 驗證分數 | 指標 | 累計秒數 |", "|---|---|---|---|---|---|---|"]
    L += [f"| {r['n']:,} | {E.TASK_NAMES[r['任務']]} | {r['epoch']} | {r['loss']:.4f} | {r['驗證分數']:.4f} | "
          + "、".join(f"{k} {r[k]:.3f}" for k in METRICS[r["任務"]]) + f" | {r['秒數']:.0f} |" for r in val_rows]
    open(args.out, "w", encoding="utf-8").write("\n".join(L) + "\n")


def pos_weight(Y):
    pos = Y.sum(0); neg = len(Y) - pos
    return torch.tensor(np.clip(np.sqrt(neg / np.maximum(pos, 1)), 1, 30), dtype=torch.float32, device=dev)


# ── 訓練 ──
val_rows, test_rows = [], []
for n in sizes:
    tr = pool[:n]
    for task in TASKS:
        ids = index_of(tr, task)
        if task == "imprisonment":
            top = []
            model = TextCNN({"bin": len(E.BINS) + 1, "reg": 1}).to(dev)
            mon = np.zeros(n); mon[ids] = [tr[i]["months"] for i in ids]
            yb = torch.from_numpy(np.array([E.bin_of(m) for m in mon], dtype=np.int64))
            ylog = torch.from_numpy(np.log1p(np.clip(mon, 0, None)).astype(np.float32))
            fin = torch.from_numpy(mon >= 0)                     # 迴歸不含死刑／無期
        else:
            Yfull = np.zeros((n, len(mlb[task].classes_)), dtype=np.float32)
            Yfull[ids] = mlb[task].transform([tr[i][task] for i in ids])
            top = E.top_classes(Yfull[ids])
            model = TextCNN({"out": Yfull.shape[1]}).to(dev)
            pw = pos_weight(Yfull[ids]); Yt = torch.from_numpy(Yfull)
        opt = torch.optim.Adam(model.parameters(), lr=args.lr)
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
            res = evaluate(task, model, Xval, Lval, val, top)
            res.update(n=n, 任務=task, epoch=ep, loss=tot / len(perm), 秒數=time.time() - t1)
            val_rows.append(res)
            print(f"  {n:,} 筆 {E.TASK_NAMES[task]} epoch {ep}/{args.epochs}（{res['秒數']:.0f}s）：loss {res['loss']:.4f}、"
                  f"驗證分數 {res['驗證分數']:.4f}、" + "、".join(f"{k} {res[k]:.3f}" for k in METRICS[task]), flush=True)
            if res["驗證分數"] > best[0]:
                best = (res["驗證分數"], ep, copy.deepcopy(model.state_dict())); since_best = 0
            else:
                since_best += 1
            write_table(val_rows, test_rows)
            if since_best >= args.patience:
                print(f"  驗證分數 {args.patience} 個 epoch 沒進步，提早停止", flush=True)
                break
        model.load_state_dict(best[2])
        res = evaluate(task, model, Xte, Lte, test, top)
        res.update(n=n, 任務=task, epoch=best[1], 秒數=time.time() - t1)
        test_rows.append(res)
        print(f"{n:,} 筆 {E.TASK_NAMES[task]} 完成，選用 epoch {best[1]}，test："
              + "、".join(f"{k} {res[k]:.3f}" for k in METRICS[task]), flush=True)
        write_table(val_rows, test_rows)
        del model, opt, best; gc.collect()
        if dev.type == "cuda":
            torch.cuda.empty_cache()
print(open(args.out, encoding="utf-8").read())
