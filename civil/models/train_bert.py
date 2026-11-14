"""
BERT 微調：只用兩造主張的文字預測勝敗（M8）。用 .venv-bert 執行（爬蟲的 .venv 不裝 torch）。

    .venv-bert\\Scripts\\python -m civil.models.train_bert --input pd --fold 0
    .venv-bert\\Scripts\\python -m civil.models.train_bert --input pd --limit 400 --epochs 1   # 試跑

模型：ckiplab/bert-base-chinese（中研院 CKIP 的繁體中文 BERT；依其說明使用 bert-base-chinese 的 tokenizer）。
輸入（--input）：p＝只用原告主張、d＝只用被告答辯、pd＝兩者（句對，總長截斷到 --max_len）。
切分：資料集的 fold 欄（與 TF-IDF 相同）。以 --fold 為測試折，其餘四折訓練；單折是試做，不是 5 折平均。
評估：**事先固定**訓練 --epochs 個 epoch 後，在測試折算 AUC。每個 epoch 的 AUC 都記錄，
      但報告只用最後一個 epoch，不從測試折挑最好的 epoch（否則等於用測試資料調參）。
輸出：output/bert_{input}_fold{k}_{版本}/metrics.json、pred.csv、train.log

截斷實驗（10/14 加入；預設值與原本完全相同）：
  --trunc headtail：每段超過預算時保留開頭 1/4、結尾 3/4（Sun et al. 2019 在長文分類上最好的組合）。
                    兩造的預算分配和原本的 longest_first 相同。
  --chunks N：讀全文。原告＋[SEP]＋被告接成一串，前 N×510 個 token 切成 N 段，各段經 BERT 後
              把 [CLS] 向量平均再分類（Pappagari et al. 2019 階層式長文分類的最簡版本）。
              每案最多 N 段，用 --batch 2 --accum 16 讓記憶體與有效 batch 和原本相同。
  輸出資料夾加後綴，例如 bert_pd_fold0_v3_headtail、bert_pd_fold0_v3_chunk4（不會混進 summarize_bert.py）。

v4 加入（預設關閉，v3 的執行方式不變）：
  --val：驗證集＝fold==(測試折+1)%5 且 val_half==1 的案件（資料集 v4 才有 val_half），從訓練資料中拿掉。
         每個 epoch 都在驗證集和測試折上預測，**用驗證集 AUC 選 epoch**，報告該 epoch 的測試 AUC；
         測試折的分數不參與任何選擇。另存驗證集的預測（val_pred.csv），給之後的合併模型決定權重。
  --lower：tokenizer 轉小寫。bert-base-chinese 的 tokenizer 設定是 do_lower_case=False，
           但字典裡只有小寫英文字母，大寫字母（「A公司」）都會變成 [UNK]。

10/21 加入（預設關閉）：
  --split time：時間切分，2022–2024 訓練、2025 全部當測試（不用 fold 欄決定測試）。驗證集＝2022–2024 中
               fold==0 且 val_half==1（約 10%），不碰 2025。要搭配 --val。輸出資料夾 bert_pd_time2025_v4_...
"""
import argparse
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import roc_auc_score
from torch import nn
from torch.utils.data import DataLoader, Dataset

import config  # noqa: E402


class Texts(Dataset):
    def __init__(self, df, mode):
        self.p = df.plaintiff_claim_text.fillna("").tolist()
        self.d = df.defendant_defense_text.fillna("").tolist()
        self.y = df.y.tolist()
        self.mode = mode

    def __len__(self):
        return len(self.y)

    def __getitem__(self, i):
        return self.p[i], self.d[i], self.y[i]


def make_collate(tok, mode, max_len):
    def collate(batch):
        p, d, y = zip(*batch)
        if mode == "p":
            enc = tok(list(p), truncation=True, max_length=max_len, padding=True, return_tensors="pt")
        elif mode == "d":
            enc = tok(list(d), truncation=True, max_length=max_len, padding=True, return_tensors="pt")
        else:
            enc = tok(list(p), list(d), truncation="longest_first", max_length=max_len,
                      padding=True, return_tensors="pt")
        enc["labels"] = torch.tensor(y)
        return enc
    return collate


def budget(lp, ld, n):
    """兩段合計不超過 n 個 token 時各留多少：和 longest_first 一樣，先從較長的一段砍。"""
    if lp + ld <= n:
        return lp, ld
    h = n // 2
    if lp <= h:
        return lp, n - lp
    if ld <= h:
        return n - ld, ld
    return (n - h, h) if lp > ld else (h, n - h)  # 多出的 1 個給較長的一段，和 HF 相同


def cut(ids, k, how):
    if len(ids) <= k:
        return ids
    if how == "head":
        return ids[:k]
    h = k // 4                                    # 開頭 1/4、結尾 3/4
    return ids[:h] + ids[len(ids) - (k - h):]


def pad(seqs, types, pad_id):
    L = max(len(s) for s in seqs)
    ids = torch.full((len(seqs), L), pad_id, dtype=torch.long)
    tt = torch.zeros((len(seqs), L), dtype=torch.long)
    am = torch.zeros((len(seqs), L), dtype=torch.long)
    for i, (s, t) in enumerate(zip(seqs, types)):
        ids[i, :len(s)] = torch.tensor(s); tt[i, :len(t)] = torch.tensor(t); am[i, :len(s)] = 1
    return {"input_ids": ids, "token_type_ids": tt, "attention_mask": am}


def make_collate_ids(tok, mode, max_len, trunc, chunks):
    """先斷好詞的 token id（Texts 裡放的是 id list），自己組序列；用在 headtail 和 chunks。"""
    CLS, SEP, PAD = tok.cls_token_id, tok.sep_token_id, tok.pad_token_id

    def one(p, d):
        if mode == "p":
            return [CLS] + cut(p, max_len - 2, trunc) + [SEP], None
        if mode == "d":
            return [CLS] + cut(d, max_len - 2, trunc) + [SEP], None
        bp, bd = budget(len(p), len(d), max_len - 3)
        a, b = cut(p, bp, trunc), cut(d, bd, trunc)
        return [CLS] + a + [SEP] + b + [SEP], [0] * (len(a) + 2) + [1] * (len(b) + 1)

    def collate(batch):
        p, d, y = zip(*batch)
        seqs, types, owner = [], [], []
        for i, (pi, di) in enumerate(zip(p, d)):
            if not chunks:
                s, t = one(pi, di)
                seqs.append(s); types.append(t or [0] * len(s))
                continue
            if mode == "p":
                full, ft = pi, [0] * len(pi)
            elif mode == "d":
                full, ft = di, [0] * len(di)
            else:
                full, ft = pi + [SEP] + di, [0] * (len(pi) + 1) + [1] * len(di)
            w = max_len - 2
            full, ft = full[:chunks * w], ft[:chunks * w]
            for j in range(0, max(len(full), 1), w):
                piece, pt = full[j:j + w], ft[j:j + w] or [0]
                seqs.append([CLS] + piece + [SEP]); types.append([pt[0]] + pt + [pt[-1]])
                owner.append(i)
        enc = pad(seqs, types, PAD)
        if chunks:
            enc["owner"] = torch.tensor(owner)
        enc["labels"] = torch.tensor(y)
        return enc
    return collate


class ChunkPool(nn.Module):
    """每段的 [CLS] 向量依案件平均後分類。"""
    def __init__(self, name):
        super().__init__()
        from transformers import AutoModel

        self.bert = AutoModel.from_pretrained(name, add_pooling_layer=False)
        self.drop = nn.Dropout(0.1)
        self.head = nn.Linear(self.bert.config.hidden_size, 2)

    def forward(self, input_ids, attention_mask, token_type_ids, owner, labels=None):
        h = self.bert(input_ids=input_ids, attention_mask=attention_mask,
                      token_type_ids=token_type_ids).last_hidden_state[:, 0].float()
        n = int(owner.max()) + 1
        cnt = torch.bincount(owner, minlength=n).unsqueeze(1).float()
        pooled = torch.zeros(n, h.size(1), device=h.device).index_add_(0, owner, h) / cnt
        logits = self.head(self.drop(pooled))
        loss = nn.functional.cross_entropy(logits, labels) if labels is not None else None
        return SimpleNamespace(logits=logits, loss=loss)


@torch.no_grad()
def predict(model, loader, device):
    model.eval()
    out = []
    for b in loader:
        b = {k: v.to(device) for k, v in b.items() if k != "labels"}
        with torch.autocast("cuda", dtype=torch.float16):
            logits = model(**b).logits
        out.append(torch.softmax(logits.float(), -1)[:, 1].cpu().numpy())
    model.train()
    return np.concatenate(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v0")
    ap.add_argument("--input", choices=["p", "d", "pd"], default="pd")
    ap.add_argument("--fold", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--max_len", type=int, default=512)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--accum", type=int, default=4)        # 有效 batch 32
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--model", default="ckiplab/bert-base-chinese")
    ap.add_argument("--limit", type=int, default=0, help="試跑：訓練與測試各只取這麼多筆")
    ap.add_argument("--trunc", choices=["head", "headtail"], default="head")
    ap.add_argument("--chunks", type=int, default=0, help="讀全文：每案最多切幾段 512")
    ap.add_argument("--val", action="store_true", help="用驗證集選 epoch（資料集要有 val_half 欄）")
    ap.add_argument("--lower", action="store_true", help="tokenizer 轉小寫")
    ap.add_argument("--split", choices=["fold", "time"], default="fold",
                    help="time：2022–2024 訓練、2025 測試（10/21 加入）；驗證集＝2022–2024 中 fold==0 且 val_half==1")
    a = ap.parse_args()

    # Load training dependencies only when training starts, not when importing helpers.
    from transformers import (AutoModelForSequenceClassification, BertTokenizerFast,
                              get_linear_schedule_with_warmup)

    torch.manual_seed(42)
    np.random.seed(42)
    device = "cuda"
    assert torch.cuda.is_available(), "抓不到 GPU"
    split_tag = "time2025" if a.split == "time" else f"fold{a.fold}"
    tag = (f"bert_{a.input}_{split_tag}_{a.version}" + (f"_{a.trunc}" if a.trunc != "head" else "")
           + (f"_chunk{a.chunks}" if a.chunks else "") + ("_val" if a.val else "")
           + (f"_limit{a.limit}" if a.limit else ""))
    out = config.OUTPUT_DIR / tag
    out.mkdir(parents=True, exist_ok=True)
    log = open(out / "train.log", "a", encoding="utf-8")

    def say(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log.write(line + "\n"); log.flush()

    df = pd.read_csv(config.dataset_path(a.version), encoding="utf-8")
    tr, te = df[df.fold != a.fold].copy(), df[df.fold == a.fold].copy()
    va = None
    if a.split == "time":
        # 時間切分：用過去預測未來。測試＝2025 年全部；驗證集從 2022–2024 取（不碰 2025）
        assert a.val, "時間切分要搭配 --val"
        past = df.year.astype(int) <= 2024
        vmask = past & (df.fold == 0) & (df.val_half == 1)
        tr, va, te = df[past & ~vmask].copy(), df[vmask].copy(), df[~past].copy()
    elif a.val:
        assert "val_half" in df.columns, "資料集沒有 val_half 欄（要用 v4 以後的版本）"
        vmask = (df.fold == (a.fold + 1) % 5) & (df.val_half == 1)
        va = df[vmask].copy()
        tr = df[(df.fold != a.fold) & ~vmask].copy()
    if a.limit:
        tr, te = tr.sample(a.limit, random_state=42), te.sample(a.limit, random_state=42)
        if va is not None:
            va = va.sample(min(a.limit, len(va)), random_state=42)
    say(f"{tag}：訓練 {len(tr):,} 筆、測試 {len(te):,} 筆" + (f"、驗證 {len(va):,} 筆" if va is not None else "")
        + f"，模型 {a.model}，max_len {a.max_len}，batch {a.batch}×{a.accum}，lr {a.lr}，epochs {a.epochs}，"
        f"trunc {a.trunc}，chunks {a.chunks}，lower {a.lower}")

    tok = BertTokenizerFast.from_pretrained("bert-base-chinese", **({"do_lower_case": True} if a.lower else {}))
    if a.trunc == "head" and not a.chunks:        # 原本的做法，保持不變
        collate = make_collate(tok, a.input, a.max_len)
    else:
        for part in [p for p in (tr, te, va) if p is not None]:   # 先斷好詞，collate 裡只做截斷與組序列
            for c in ("plaintiff_claim_text", "defendant_defense_text"):
                ids = tok(part[c].fillna("").tolist(), add_special_tokens=False)["input_ids"]
                part[c] = pd.Series(ids, index=part.index, dtype=object)
        collate = make_collate_ids(tok, a.input, a.max_len, a.trunc, a.chunks)
    if a.chunks:
        model = ChunkPool(a.model).to(device)
    else:
        model = AutoModelForSequenceClassification.from_pretrained(a.model, num_labels=2).to(device)
    tr_loader = DataLoader(Texts(tr, a.input), batch_size=a.batch, shuffle=True, collate_fn=collate,
                           num_workers=0)
    te_loader = DataLoader(Texts(te, a.input), batch_size=a.batch * 4, shuffle=False, collate_fn=collate,
                           num_workers=0)
    va_loader = (DataLoader(Texts(va, a.input), batch_size=a.batch * 4, shuffle=False, collate_fn=collate,
                            num_workers=0) if va is not None else None)
    steps = math.ceil(len(tr_loader) / a.accum) * a.epochs
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * steps), steps)
    scaler = torch.cuda.amp.GradScaler()

    hist, t0, step = [], time.time(), 0
    model.train()
    for ep in range(1, a.epochs + 1):
        for i, b in enumerate(tr_loader, 1):
            b = {k: v.to(device) for k, v in b.items()}
            with torch.autocast("cuda", dtype=torch.float16):
                loss = model(**b).loss / a.accum
            scaler.scale(loss).backward()
            if i % a.accum == 0 or i == len(tr_loader):
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt); scaler.update(); opt.zero_grad(); sched.step()
                step += 1
                if step % 50 == 0:
                    el = time.time() - t0
                    say(f"epoch {ep} step {step}/{steps} loss {loss.item() * a.accum:.4f} "
                        f"已 {el / 60:.1f} 分，預估剩 {el / step * (steps - step) / 60:.0f} 分")
        prob = predict(model, te_loader, device)
        auc = roc_auc_score(te.y, prob)
        h = {"epoch": ep, "auc": round(auc, 4), "minutes": round((time.time() - t0) / 60, 1)}
        if va_loader is not None:
            vprob = predict(model, va_loader, device)
            h["val_auc"] = round(roc_auc_score(va.y, vprob), 4)
            if not hist or h["val_auc"] > max(x["val_auc"] for x in hist):   # 只看驗證集決定保留哪個 epoch
                best = (ep, prob, vprob)
        hist.append(h)
        say(f"epoch {ep} 測試折 AUC {auc:.4f}" + (f"、驗證集 AUC {h['val_auc']:.4f}" if "val_auc" in h else ""))

    if va_loader is not None:
        ep_sel, prob, vprob = best
        pd.DataFrame({"id": va.id.values, "y": va.y.values, "prob": vprob}).to_csv(out / "val_pred.csv", index=False)
    pd.DataFrame({"id": te.id.values, "y": te.y.values, "prob": prob}).to_csv(out / "pred.csv", index=False)
    metrics = {"tag": tag, "input": a.input, "fold": a.fold, "n_train": len(tr), "n_test": len(te),
               "auc_final_epoch": hist[-1]["auc"], "history": hist, "args": vars(a)}
    if va_loader is not None:
        metrics.update({"n_val": len(va), "epoch_selected_by_val": ep_sel,
                        "auc_selected": hist[ep_sel - 1]["auc"]})
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"完成：最後一個 epoch 的 AUC {hist[-1]['auc']:.4f}"
        + (f"；驗證集選第 {ep_sel} 個 epoch，測試 AUC {hist[ep_sel - 1]['auc']:.4f}" if va_loader is not None else "")
        + f"，共 {(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()
