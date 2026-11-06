# -*- coding: utf-8 -*-
"""
平台用的刑度模型：法律 ELECTRA 預測前端的 6 個刑度區間（PyTorch＋transformers，Kaggle GPU 訓練），
訓練完匯出 ONNX，後端用 onnxruntime 在 CPU 上推論，不用裝 PyTorch。

資料：工作檔/資料集產生/electra_bucket_data.py 產生的 criminal_bucket_electra/（train／valid／test.jsonl，
每行 {"line", "fact", "bucket"}；全國 v2 自然分布，區間含拘役、罰金）。
模型設定沿用共用包實驗（electra_term_gpu.py，PR #16）：hfl/chinese-legal-electra-base-discriminator、
微調最後 --last-n 層（6 層在共用包上刑期最好）、[CLS] 向量、MLP（768 → 512 → 256）、encoder 學習率 2e-5、頭 1e-3。
和共用包實驗不同：只有一個 6 類分類頭（平台只顯示區間機率，不需要月數迴歸）；valid 挑 epoch，test 只算一次。

Kaggle notebook：Accelerator 選 GPU T4 x2、Internet 打開（下載模型約 400MB、安裝 onnx／onnxruntime）。
  !pip install -q onnx onnxruntime
  小量測試：!python -W ignore electra_bucket_gpu.py --data <資料夾> --limit 2000 --epochs 1
  正式：    !python -W ignore electra_bucket_gpu.py --data <資料夾>
輸出（--out-dir，預設 /kaggle/working/criminal_term_electra）：
  model.onnx（float32）、model.int8.onnx（動態量化，後端用這個）、tokenizer.json 等斷詞檔、meta.json、results.md
"""

import argparse
import hashlib
import inspect
import json
import os
import time
from datetime import datetime, timezone

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as Fn
from transformers import AutoModel, AutoTokenizer

BUCKETS = ["拘役、罰金", "1～6 個月", "7～12 個月", "1～3 年", "3～10 年", "10 年以上"]   # 與 service.py 相同

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--data", required=True, help="含 train.jsonl、valid.jsonl、test.jsonl 的資料夾")
ap.add_argument("--model", default="hfl/chinese-legal-electra-base-discriminator")
ap.add_argument("--last-n", type=int, default=6, help="微調最後幾層 encoder")
ap.add_argument("--max-len", type=int, default=512)
ap.add_argument("--dropout", type=float, default=0.1)
ap.add_argument("--epochs", type=int, default=3)
ap.add_argument("--patience", type=int, default=1, help="驗證分數連續幾個 epoch 沒進步就停")
ap.add_argument("--batch", type=int, default=16)
ap.add_argument("--encoder-lr", type=float, default=2e-5)
ap.add_argument("--head-lr", type=float, default=1e-3)
ap.add_argument("--weight-decay", type=float, default=0.01)
ap.add_argument("--limit", type=int, default=0, help="小量測試：每份資料只取前幾筆；0 = 全部")
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--out-dir", default="/kaggle/working/criminal_term_electra")
args = ap.parse_args()
dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
N_GPU = torch.cuda.device_count() if dev.type == "cuda" else 0
AMP = dev.type == "cuda"
print("裝置：", dev, f"{torch.cuda.get_device_name(0)} × {N_GPU}" if N_GPU else "", flush=True)
torch.manual_seed(args.seed); np.random.seed(args.seed)
os.makedirs(args.out_dir, exist_ok=True)
tokenizer = AutoTokenizer.from_pretrained(args.model)
SCRIPT_SHA = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:10]


def load(name):
    rows = [json.loads(l) for l in open(os.path.join(args.data, f"{name}.jsonl"), encoding="utf-8")]
    rows = rows[:args.limit] if args.limit else rows
    ids = tokenizer([r["fact"] for r in rows], truncation=True, max_length=args.max_len)["input_ids"]
    return np.array([r["bucket"] for r in rows], dtype=np.int64), ids


class ElectraBucket(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(args.model)
        for p in self.encoder.parameters():
            p.requires_grad = False
        for layer in self.encoder.encoder.layer[-args.last_n:] if args.last_n else []:
            for p in layer.parameters():
                p.requires_grad = True
        d = args.dropout
        self.mlp = nn.Sequential(nn.Linear(self.encoder.config.hidden_size, 512), nn.ReLU(), nn.Dropout(d),
                                 nn.Linear(512, 256), nn.ReLU(), nn.Dropout(d))
        self.head = nn.Linear(256, len(BUCKETS))

    def forward(self, input_ids, attention_mask):
        return self.head(self.mlp(self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state[:, 0]))


class Exported(nn.Module):
    """匯出用：輸出 6 個區間的機率。"""
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, input_ids, attention_mask):
        return torch.softmax(self.m(input_ids, attention_mask), dim=-1)


def batch_tensors(ids, idx, device=dev):
    seqs = [ids[i] for i in idx]
    width = max(len(s) for s in seqs)
    x = np.full((len(seqs), width), tokenizer.pad_token_id, dtype=np.int64)
    m = np.zeros((len(seqs), width), dtype=np.int64)
    for j, s in enumerate(seqs):
        x[j, :len(s)] = s; m[j, :len(s)] = 1
    return torch.from_numpy(x).to(device), torch.from_numpy(m).to(device)


def predict_proba(model, ids):
    model.eval(); out = []
    order = np.argsort([len(s) for s in ids])
    with torch.no_grad(), torch.autocast(dev.type, enabled=AMP):
        for i in range(0, len(order), args.batch * 4):
            out.append(torch.softmax(model(*batch_tensors(ids, order[i:i + args.batch * 4])).float(), -1).cpu())
    p = torch.cat(out).numpy()
    back = np.empty_like(order); back[order] = np.arange(len(order))
    return p[back]


def scores(y, p):
    pred = p.argmax(1)
    f1 = []
    for b in range(len(BUCKETS)):
        tp = ((pred == b) & (y == b)).sum(); d = (pred == b).sum() + (y == b).sum()
        f1.append(2 * tp / d if d else 0.0)
    return {"accuracy": float((pred == y).mean()), "macro F1": float(np.mean(f1)),
            "log loss": float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-9, 1)).mean()),
            "每區間 F1": [round(float(x), 3) for x in f1]}


t0 = time.time()
data = {k: load(k) for k in ("train", "valid", "test")}
print("斷詞完成（%.0fs）：" % (time.time() - t0) + "、".join(f"{k} {len(v[0]):,}" for k, v in data.items()), flush=True)
y_tr, ids_tr = data["train"]
base = ElectraBucket().to(dev)
model = nn.DataParallel(base) if N_GPU > 1 else base
enc = [p for p in base.encoder.parameters() if p.requires_grad]
head = [p for n, p in base.named_parameters() if not n.startswith("encoder.")]
opt = torch.optim.AdamW([{"params": head, "lr": args.head_lr}] + ([{"params": enc, "lr": args.encoder_lr}] if enc else []),
                        weight_decay=args.weight_decay)
scaler = torch.amp.GradScaler(dev.type, enabled=AMP)
best, since_best, log = (-1.0, 0, None), 0, []
for ep in range(1, args.epochs + 1):
    model.train()
    perm = np.random.permutation(len(y_tr)); tot = 0.0
    for i in range(0, len(perm), args.batch):
        b = perm[i:i + args.batch]
        with torch.autocast(dev.type, enabled=AMP):
            logits = model(*batch_tensors(ids_tr, b))
        loss = Fn.cross_entropy(logits.float(), torch.from_numpy(y_tr[b]).to(dev))
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(head + enc, 1.0)
        scaler.step(opt); scaler.update()
        tot += loss.item() * len(b)
        if (i // args.batch) % 500 == 0:
            print(f"    epoch {ep} {i:,}/{len(perm):,}（{time.time() - t0:.0f}s）loss {loss.item():.4f}", flush=True)
    s = scores(data["valid"][0], predict_proba(model, data["valid"][1]))
    log.append({"epoch": ep, "loss": tot / len(perm), **s, "秒數": time.time() - t0})
    print(f"  epoch {ep}：loss {tot / len(perm):.4f}、valid accuracy {s['accuracy']:.3f}、macro F1 {s['macro F1']:.3f}、"
          f"log loss {s['log loss']:.3f}（{time.time() - t0:.0f}s）", flush=True)
    if s["accuracy"] > best[0]:
        best = (s["accuracy"], ep, {k: v.detach().cpu().clone() for k, v in base.state_dict().items()}); since_best = 0
    else:
        since_best += 1
        if since_best >= args.patience:
            print("  驗證分數沒進步，提早停止", flush=True)
            break
base.load_state_dict(best[2])
p_test = predict_proba(model, data["test"][1])
test = scores(data["test"][0], p_test)
print(f"test（epoch {best[1]}）：accuracy {test['accuracy']:.3f}、macro F1 {test['macro F1']:.3f}、log loss {test['log loss']:.3f}", flush=True)
np.save(os.path.join(args.out_dir, "test_proba.npy"), p_test)

# ── 匯出 ONNX ──
cpu = Exported(base).cpu().float().eval()
x, m = batch_tensors(data["test"][1], range(min(4, len(data["test"][1]))), torch.device("cpu"))
onnx_path = os.path.join(args.out_dir, "model.onnx")
torch.onnx.export(cpu, (x, m), onnx_path, input_names=["input_ids", "attention_mask"], output_names=["proba"],
                  dynamic_axes={"input_ids": {0: "batch", 1: "seq"}, "attention_mask": {0: "batch", 1: "seq"},
                                "proba": {0: "batch"}}, opset_version=14,
                  # 新版 PyTorch 預設改用 dynamo 匯出，dynamic_axes 的寫法要舊的匯出器
                  **({"dynamo": False} if "dynamo" in inspect.signature(torch.onnx.export).parameters else {}))
tokenizer.save_pretrained(args.out_dir)
check = {}
try:
    import onnxruntime as ort
    from onnxruntime.quantization import QuantType, quantize_dynamic
    int8_path = os.path.join(args.out_dir, "model.int8.onnx")
    quantize_dynamic(onnx_path, int8_path, weight_type=QuantType.QInt8)
    sample = list(range(min(300, len(data["test"][1]))))
    for name, path in (("float32", onnx_path), ("int8", int8_path)):
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        t1 = time.time()
        p = np.vstack([sess.run(None, {"input_ids": a.numpy(), "attention_mask": b.numpy()})[0] for a, b in
                       (batch_tensors(data["test"][1], [i], torch.device("cpu")) for i in sample)])
        check[name] = {"與 PyTorch 同區間比例": float((p.argmax(1) == p_test[sample].argmax(1)).mean()),
                       "最大機率差": float(np.abs(p - p_test[sample]).max()),
                       "每筆秒數（CPU）": (time.time() - t1) / len(sample),
                       "檔案 MB": os.path.getsize(path) / 2 ** 20}
        print(name, check[name], flush=True)
except ImportError as e:
    print("沒有 onnxruntime，略過量化與核對：", e, flush=True)

meta = {"name": "criminal_term_electra_v1", "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script_sha256": SCRIPT_SHA, "args": vars(args), "buckets": BUCKETS, "max_len": args.max_len,
        "epoch": best[1], "n_train": int(len(y_tr)), "test": test, "onnx_check": check}
json.dump(meta, open(os.path.join(args.out_dir, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
L = ["# 平台刑度 ELECTRA（6 區間）", "", f"程式 electra_bucket_gpu.py（sha256 {SCRIPT_SHA}）；參數："
     + "、".join(f"{k}={v}" for k, v in sorted(vars(args).items())), "",
     f"train {len(y_tr):,}、valid {len(data['valid'][0]):,}、test {len(data['test'][0]):,}；選用 epoch {best[1]}。", "",
     "| 資料 | accuracy | macro F1 | log loss | 每區間 F1（" + "／".join(BUCKETS) + "） |", "|---|---|---|---|---|",
     f"| test | {test['accuracy']:.3f} | {test['macro F1']:.3f} | {test['log loss']:.3f} | {test['每區間 F1']} |", "",
     "| epoch | loss | valid accuracy | valid macro F1 | valid log loss | 累計秒數 |", "|---|---|---|---|---|---|"]
L += [f"| {r['epoch']} | {r['loss']:.4f} | {r['accuracy']:.3f} | {r['macro F1']:.3f} | {r['log loss']:.3f} | {r['秒數']:.0f} |" for r in log]
L += ["", "ONNX 核對（test 前 300 筆，CPU）：", "", "```", json.dumps(check, ensure_ascii=False, indent=2), "```"]
open(os.path.join(args.out_dir, "results.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L))
