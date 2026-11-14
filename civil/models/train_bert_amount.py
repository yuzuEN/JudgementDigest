"""
金額任務的 BERT：只用兩造主張的文字（v4，沒有聲明），預測一部勝訴案件的獲償比例（迴歸）。用 .venv-bert 執行。

    .venv-bert\\Scripts\\python -m civil.models.train_bert_amount --fold 0
    .venv-bert\\Scripts\\python -m civil.models.train_bert_amount --fold 0 --limit 32 --epochs 1   # 試跑

樣本與切分：和 amount_tfidf.py 相同（先跑它，讀 output/amount_oof_main.csv 的 id 與 grant_ratio）：
  v4 中一部勝訴一部敗訴、獲償比例是算出來的 10,032 件；測試折＝v4 的 fold 欄。
設定：和 v4 勝敗 BERT 相同（ckiplab/bert-base-chinese、句對、頭尾截斷、轉小寫、lr 2e-5、有效 batch 32、
      最多 3 個 epoch、fp16、種子 42），只差在輸出：
  - 分類頭改成 1 個輸出（num_labels=1，Hugging Face 自動用 MSE 損失），預測值裁到 0–1
  - 驗證集＝fold==(測試折+1)%5 且 val_half==1（同勝敗 BERT），**用驗證集的 Spearman 選 epoch**
輸出：output/bert_amount_pd_fold{k}_v4_headtail_val/metrics.json、pred.csv、val_pred.csv、train.log
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from scipy.stats import spearmanr
from torch.utils.data import DataLoader

import config  # noqa: E402
from civil.models.train_bert import Texts, make_collate_ids



@torch.no_grad()
def predict(model, loader, device):
    model.eval()
    out = []
    for b in loader:
        b = {k: v.to(device) for k, v in b.items() if k != "labels"}
        with torch.autocast("cuda", dtype=torch.float16):
            out.append(model(**b).logits.float()[:, 0].cpu().numpy())
    model.train()
    return np.clip(np.concatenate(out), 0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fold", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--max_len", type=int, default=512)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--model", default="ckiplab/bert-base-chinese")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--suffix", default="", help="加在輸出資料夾名稱後面（例如 _ep5），不蓋掉原本的結果")
    a = ap.parse_args()

    # Load training dependencies only when training starts, not when importing helpers.
    from transformers import AutoModelForSequenceClassification, BertTokenizerFast, get_linear_schedule_with_warmup

    torch.manual_seed(42)
    np.random.seed(42)
    device = "cuda"
    assert torch.cuda.is_available(), "抓不到 GPU"
    tag = f"bert_amount_pd_fold{a.fold}_v4_headtail_val" + a.suffix + (f"_limit{a.limit}" if a.limit else "")
    out = config.OUTPUT_DIR / tag
    out.mkdir(parents=True, exist_ok=True)
    log = open(out / "train.log", "a", encoding="utf-8")

    def say(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log.write(line + "\n"); log.flush()

    df = pd.read_csv(config.dataset_path("v4"), encoding="utf-8")
    amt = pd.read_csv(config.OUTPUT_DIR / "amount_oof_main.csv", usecols=["id", "grant_ratio"])
    df = df.merge(amt, on="id", how="inner", validate="1:1")
    df["y"] = df.grant_ratio.astype(np.float32)               # Texts 讀 y 欄；這裡的 y 是獲償比例
    vmask = (df.fold == (a.fold + 1) % 5) & (df.val_half == 1)
    tr, va, te = df[(df.fold != a.fold) & ~vmask].copy(), df[vmask].copy(), df[df.fold == a.fold].copy()
    if a.limit:
        tr, va, te = (x.sample(min(a.limit, len(x)), random_state=42) for x in (tr, va, te))
    say(f"{tag}：訓練 {len(tr):,}、驗證 {len(va):,}、測試 {len(te):,} 筆，模型 {a.model}，max_len {a.max_len}，"
        f"batch {a.batch}×{a.accum}，lr {a.lr}，epochs {a.epochs}")

    tok = BertTokenizerFast.from_pretrained("bert-base-chinese", do_lower_case=True)
    for part in (tr, va, te):
        for c in ("plaintiff_claim_text", "defendant_defense_text"):
            ids = tok(part[c].fillna("").tolist(), add_special_tokens=False)["input_ids"]
            part[c] = pd.Series(ids, index=part.index, dtype=object)
    collate = make_collate_ids(tok, "pd", a.max_len, "headtail", 0)
    model = AutoModelForSequenceClassification.from_pretrained(a.model, num_labels=1).to(device)
    tr_loader = DataLoader(Texts(tr, "pd"), batch_size=a.batch, shuffle=True, collate_fn=collate, num_workers=0)
    te_loader = DataLoader(Texts(te, "pd"), batch_size=a.batch * 4, shuffle=False, collate_fn=collate, num_workers=0)
    va_loader = DataLoader(Texts(va, "pd"), batch_size=a.batch * 4, shuffle=False, collate_fn=collate, num_workers=0)
    steps = math.ceil(len(tr_loader) / a.accum) * a.epochs
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * steps), steps)
    scaler = torch.cuda.amp.GradScaler()

    hist, best, t0, step = [], None, time.time(), 0
    model.train()
    for ep in range(1, a.epochs + 1):
        for i, b in enumerate(tr_loader, 1):
            b = {k: v.to(device) for k, v in b.items()}
            b["labels"] = b["labels"].float()
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
        prob, vprob = predict(model, te_loader, device), predict(model, va_loader, device)
        h = {"epoch": ep, "spearman": round(spearmanr(te.y, prob).statistic, 4),
             "mae": round(float(np.abs(te.y.values - prob).mean()), 4),
             "val_spearman": round(spearmanr(va.y, vprob).statistic, 4), "minutes": round((time.time() - t0) / 60, 1)}
        if best is None or h["val_spearman"] > max(x["val_spearman"] for x in hist):   # 只看驗證集選 epoch
            best = (ep, prob, vprob)
        hist.append(h)
        say(f"epoch {ep} 測試折 Spearman {h['spearman']:.4f}、MAE {h['mae']:.4f}、驗證集 Spearman {h['val_spearman']:.4f}")

    ep_sel, prob, vprob = best
    pd.DataFrame({"id": te.id.values, "y": te.y.values, "pred": prob}).to_csv(out / "pred.csv", index=False)
    pd.DataFrame({"id": va.id.values, "y": va.y.values, "pred": vprob}).to_csv(out / "val_pred.csv", index=False)
    metrics = {"tag": tag, "fold": a.fold, "n_train": len(tr), "n_val": len(va), "n_test": len(te), "history": hist,
               "epoch_selected_by_val": ep_sel, "spearman_selected": hist[ep_sel - 1]["spearman"],
               "mae_selected": hist[ep_sel - 1]["mae"], "args": vars(a)}
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"完成：驗證集選第 {ep_sel} 個 epoch，測試 Spearman {hist[ep_sel - 1]['spearman']:.4f}，"
        f"共 {(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()
