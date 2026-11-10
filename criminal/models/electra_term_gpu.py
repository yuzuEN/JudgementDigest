# -*- coding: utf-8 -*-
"""
法律 ELECTRA 預測刑期（PyTorch＋transformers，Kaggle GPU 用），只跑共用實驗包（--shared）。

設定照芸菲 PR #15 的罪名、法條 ELECTRA（configs/accusation_electra.json），刑期結果才能和她的放在一起看：
  hfl/chinese-legal-electra-base-discriminator、只微調最後 --last-n 層、[CLS] 向量、
  MLP（768 → 512 → 256，ReLU、dropout 0.1）、事實截到 --max-len 個 token、
  encoder 學習率 2e-5、頭 1e-3、weight decay 0.01、梯度裁到 1.0、最多 5 epoch、驗證 2 個 epoch 沒進步就停
輸出頭與評分和 textcnn_gpu.py 相同，分數才能和 SVM、fastText、TextCNN 直接比：
  區間分類（7 類）＋ log(月數 + 1) 迴歸兩個頭；驗證分數 = CAIL 分數；只在 test 與 2025 holdout 各算一次
GPU 上用混合精度；有兩張 GPU（Kaggle T4 x2）時自動用 DataParallel。

Kaggle notebook：Accelerator 選 GPU T4 x2、Internet 要打開（第一次會下載模型約 400MB），evaluate.py 放在同一個資料夾。
  小量測試：!python -W ignore electra_term_gpu.py --shared <共用包> --folds fold_01 --limit 2000 --epochs 1
  先跑一折：!python -W ignore electra_term_gpu.py --shared <共用包> --folds fold_01 --out electra_term_fold01.md
  全部 5 折：!python -W ignore electra_term_gpu.py --shared <共用包> --out electra_term_shared.md
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
from transformers import AutoModel, AutoTokenizer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluate as E  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--shared", required=True, help="共用實驗包資料夾（含 shared_100k.jsonl、shared_fold_assignments.csv、fixed_classes.json）")
ap.add_argument("--folds", default="all", help="要跑的輪，例如 fold_01,fold_02；all = 全部")
ap.add_argument("--model", default="hfl/chinese-legal-electra-base-discriminator")
ap.add_argument("--last-n", type=int, default=2, help="微調最後幾層 encoder；0 = 全部凍結、只訓練頭")
ap.add_argument("--max-len", type=int, default=512, help="事實最多取幾個 token（含 [CLS]、[SEP]）")
ap.add_argument("--dropout", type=float, default=0.1)
ap.add_argument("--epochs", type=int, default=5, help="最多幾個 epoch")
ap.add_argument("--patience", type=int, default=2, help="驗證分數連續幾個 epoch 沒進步就停")
ap.add_argument("--batch", type=int, default=16, help="芸菲的 batch 4 × 累積 4 = 16")
ap.add_argument("--encoder-lr", type=float, default=2e-5)
ap.add_argument("--head-lr", type=float, default=1e-3)
ap.add_argument("--weight-decay", type=float, default=0.01)
ap.add_argument("--limit", type=int, default=0, help="小量測試：每個角色只取前幾筆；0 = 全部")
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--out", default="electra_term.md")
args = ap.parse_args()
dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
N_GPU = torch.cuda.device_count() if dev.type == "cuda" else 0
print("裝置：", dev, f"{torch.cuda.get_device_name(0)} × {N_GPU}" if N_GPU else "", flush=True)
torch.manual_seed(args.seed); np.random.seed(args.seed)
HEADER = E.config_header(__file__, args)
AMP = dev.type == "cuda"
METRICS = ["區間 accuracy", "CAIL 分數"]
TASK = "imprisonment"
tokenizer = AutoTokenizer.from_pretrained(args.model)


TOKENS = {}                                                   # jid → token，各輪共用，只斷詞一次


def encode(rs):
    """只取刑期任務可用的案件；token 存成 list，每批再補白到該批最長。"""
    rs = [r for r in rs if r["valid"][TASK]]
    new = [r for r in rs if r["jid"] not in TOKENS]
    if new:
        for r, t in zip(new, tokenizer([r["fact"] for r in new], truncation=True, max_length=args.max_len)["input_ids"]):
            TOKENS[r["jid"]] = t
    return rs, [TOKENS[r["jid"]] for r in rs]


# ── 模型 ──
class ElectraTerm(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(args.model)
        for p in self.encoder.parameters():
            p.requires_grad = False
        if args.last_n:
            for layer in self.encoder.encoder.layer[-args.last_n:]:
                for p in layer.parameters():
                    p.requires_grad = True
        hidden = self.encoder.config.hidden_size
        d = args.dropout
        self.mlp = nn.Sequential(nn.Linear(hidden, 512), nn.ReLU(), nn.Dropout(d), nn.Linear(512, 256), nn.ReLU(), nn.Dropout(d))
        self.bin = nn.Linear(256, len(E.BINS) + 1)
        self.reg = nn.Linear(256, 1)

    def forward(self, input_ids, attention_mask):
        h = self.mlp(self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state[:, 0])
        return {"bin": self.bin(h), "reg": self.reg(h)}


def batch_tensors(ids, idx):
    seqs = [ids[i] for i in idx]
    width = max(len(s) for s in seqs)
    x = np.full((len(seqs), width), tokenizer.pad_token_id, dtype=np.int64)
    m = np.zeros((len(seqs), width), dtype=np.int64)
    for j, s in enumerate(seqs):
        x[j, :len(s)] = s; m[j, :len(s)] = 1
    return torch.from_numpy(x).to(dev, non_blocking=True), torch.from_numpy(m).to(dev, non_blocking=True)


def predict(model, ids):
    model.eval(); outs = {}
    order = np.argsort([len(s) for s in ids])                # 長度相近的放同一批，少補白
    with torch.no_grad(), torch.autocast(dev.type, enabled=AMP):
        for i in range(0, len(order), args.batch * 4):
            for k, t in model(*batch_tensors(ids, order[i:i + args.batch * 4])).items():
                outs.setdefault(k, []).append(t.float().cpu())
    out = {k: torch.cat(v).numpy() for k, v in outs.items()}
    back = np.empty_like(order); back[order] = np.arange(len(order))
    return {k: v[back] for k, v in out.items()}


def evaluate(model, rs, ids):
    out = predict(model, ids)
    res = E.term_scores([r["months"] for r in rs], out["bin"].argmax(1), np.clip(np.expm1(out["reg"][:, 0]), 0, None).round())
    res["驗證分數"] = res["CAIL 分數"]
    return res


val_rows, test_rows = [], []


def write_table():
    L = ["# 法律 ELECTRA 刑期（GPU）", "", HEADER, "",
         f"共用實驗包 {os.path.basename(os.path.normpath(args.shared))}：每一輪用 CSV 的 train 訓練、valid 挑 epoch，"
         "評該輪 test 與 2025 holdout；只用刑期任務可用的案件。", "", "## test 結果", "",
         "| 切分 | 評分資料 | 訓練筆數 | 選用 epoch | " + " | ".join(METRICS) + " | 訓練秒數 |", "|---" * (len(METRICS) + 5) + "|"]
    L += [f"| {r['切分']} | {r['評分']} | {r['n']:,} | {r['epoch']} | " + " | ".join(f"{r[k]:.3f}" for k in METRICS)
          + f" | {r['秒數']:.0f} |" for r in test_rows]
    L.append("")
    if len({r["切分"] for r in test_rows}) > 1:               # 多輪：平均 ± 樣本標準差
        L += ["## 各輪平均 ± 樣本標準差", "", "| 評分資料 | 指標 | 平均 | 標準差 | 輪數 |", "|---|---|---|---|---|"]
        for split in ("test", "holdout"):
            rs = [r for r in test_rows if r["評分"] == split]
            for k in METRICS if rs else []:
                m, s = E.mean_std([r[k] for r in rs])
                L.append(f"| {split} | {k} | {m:.3f} | {s:.3f} | {len(rs)} |")
        L.append("")
    L += ["## 驗證集（每個 epoch）", "", "| 切分 | 訓練筆數 | epoch | loss | 驗證分數 | 指標 | 累計秒數 |", "|---|---|---|---|---|---|---|"]
    L += [f"| {r['切分']} | {r['n']:,} | {r['epoch']} | {r['loss']:.4f} | {r['驗證分數']:.4f} | "
          + "、".join(f"{k} {r[k]:.3f}" for k in METRICS) + f" | {r['秒數']:.0f} |" for r in val_rows]
    open(args.out, "w", encoding="utf-8").write("\n".join(L) + "\n")


def run(sp, tag):
    t0 = time.time()
    data = {k: encode(v[:args.limit] if args.limit else v) for k, v in sp.items()}
    tr, tr_ids = data["train"]
    lens = np.array([len(s) for s in tr_ids])
    print(f"[{tag}] 刑期可用：train {len(tr):,}、valid {len(data['valid'][0]):,}、test {len(data['test'][0]):,}、"
          f"holdout {len(data['holdout'][0]):,}；斷詞完成（{time.time() - t0:.0f}s）；token 長度中位數 {int(np.median(lens))}，"
          f"截到 {args.max_len} 的占 {np.mean(lens >= args.max_len):.1%}", flush=True)
    mon = np.array([r["months"] for r in tr], dtype=np.float64)
    yb = torch.from_numpy(np.array([E.bin_of(m) for m in mon], dtype=np.int64))
    ylog = torch.from_numpy(np.log1p(np.clip(mon, 0, None)).astype(np.float32))
    fin = torch.from_numpy(mon >= 0)                         # 迴歸不含死刑／無期

    base = ElectraTerm().to(dev)
    model = nn.DataParallel(base) if N_GPU > 1 else base
    enc = [p for p in base.encoder.parameters() if p.requires_grad]
    head = [p for n, p in base.named_parameters() if not n.startswith("encoder.")]
    groups = [{"params": head, "lr": args.head_lr}] + ([{"params": enc, "lr": args.encoder_lr}] if enc else [])
    opt = torch.optim.AdamW(groups, weight_decay=args.weight_decay)
    scaler = torch.amp.GradScaler(dev.type, enabled=AMP)
    best = (-1.0, 0, None); since_best = 0; t1 = time.time()
    for ep in range(1, args.epochs + 1):
        model.train()
        if args.last_n == 0:
            base.encoder.eval()                              # 全凍結時 encoder 的 dropout 不能開
        perm = np.random.permutation(len(tr)); tot = 0.0
        for i in range(0, len(perm), args.batch):
            b = perm[i:i + args.batch]; bt = torch.from_numpy(b)
            with torch.autocast(dev.type, enabled=AMP):
                out = model(*batch_tensors(tr_ids, b))
            out = {k: v.float() for k, v in out.items()}       # 損失用 float32 算，避免溢位
            loss = Fn.cross_entropy(out["bin"], yb[bt].to(dev))
            fm = fin[bt].to(dev)
            if fm.any():
                loss = loss + Fn.mse_loss(out["reg"][:, 0][fm], ylog[bt].to(dev)[fm])
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(head + enc, 1.0)
            scaler.step(opt); scaler.update()
            tot += loss.item() * len(b)
            if (i // args.batch) % 500 == 0:
                print(f"    [{tag}] epoch {ep} {i:,}/{len(perm):,}（{time.time() - t1:.0f}s）loss {loss.item():.4f}", flush=True)
        res = evaluate(model, *data["valid"])
        res.update(切分=tag, n=len(tr), epoch=ep, loss=tot / len(perm), 秒數=time.time() - t1)
        val_rows.append(res)
        print(f"  [{tag}] {len(tr):,} 筆 刑期 epoch {ep}/{args.epochs}（{res['秒數']:.0f}s）：loss {res['loss']:.4f}、"
              f"驗證分數 {res['驗證分數']:.4f}、" + "、".join(f"{k} {res[k]:.3f}" for k in METRICS), flush=True)
        if res["驗證分數"] > best[0]:
            state = {k: v.detach().cpu().clone() for k, v in base.state_dict().items()}
            best = (res["驗證分數"], ep, state); since_best = 0
        else:
            since_best += 1
        write_table()
        if since_best >= args.patience:
            print(f"  驗證分數 {args.patience} 個 epoch 沒進步，提早停止", flush=True)
            break
    base.load_state_dict(best[2])
    for name in ("test", "holdout"):
        res = evaluate(model, *data[name])
        res.update(切分=tag, 評分=name, n=len(tr), epoch=best[1], 秒數=time.time() - t1)
        test_rows.append(res)
        print(f"[{tag}] {len(tr):,} 筆 刑期 完成，選用 epoch {best[1]}，{name}：" + "、".join(f"{k} {res[k]:.3f}" for k in METRICS), flush=True)
    write_table()
    del model, base, opt, best; gc.collect()
    if dev.type == "cuda":
        torch.cuda.empty_cache()


rows, assignments, _ = E.load_shared(args.shared)
folds = E.shared_folds(assignments) if args.folds == "all" else args.folds.split(",")
for fold in folds:
    sp = E.shared_split(rows, assignments, fold)
    sp["train"] = list(sp["train"]); np.random.RandomState(args.seed).shuffle(sp["train"])
    run(sp, fold)
print(open(args.out, encoding="utf-8").read())
