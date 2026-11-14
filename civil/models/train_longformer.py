"""
Longformer 微調：讀兩造主張的全文（最長 4096 token）預測勝敗。和 train_bert.py 的 v4 設定對齊，結果可直接比較。

    python -m civil.models.train_longformer --fold 0                         # 正式：第 0 折（在 repo 根目錄）
    python -m civil.models.train_longformer --fold 0 --limit 32 --epochs 1   # 試跑：確認環境、量記憶體與速度
    python train_longformer.py --fold 0      # 單獨上傳到雲端 GPU 時：資料與輸出預設在程式旁邊

和 v4 BERT（train_bert.py --version v4 --input pd --trunc headtail --val --lower --epochs 3）相同的地方：
  - 資料：text_dataset_v4.csv 的 fold 欄當測試折；驗證集＝fold==(測試折+1)%5 且 val_half==1，從訓練資料拿掉
  - 每個 epoch 在驗證集與測試折上預測，**只用驗證集 AUC 選 epoch**，報告該 epoch 的測試 AUC
  - 輸入：原告主張 [SEP] 被告答辯；超過長度時兩段的預算分配與 BERT 相同（先砍較長的一段），每段保留開頭 1/4、結尾 3/4
  - 學習率 2e-5、warmup 10%、weight decay 0.01、有效 batch 32、最多 3 個 epoch、fp16、種子 42
不同的地方：
  - 模型：預設 thunlp/Lawformer（中國法律長文書預訓練的 Longformer，最長 4096；Xiao et al. 2021）
  - 長度：預設 --max_len 4096（v4 的兩造合計 token 數中位數約 900、90% 分位約 2,100，4096 幾乎都讀得完）
  - --t2s：先把文字轉成簡體再斷詞（Lawformer 是用簡體法律文書訓練的）。預設開啟，--no_t2s 關閉
  - 記憶體：batch 1 × accum 32、gradient checkpointing；只在 [CLS] 用全域注意力（模型預設）
  - 每個 epoch 的預測都另存（pred_epoch{n}.csv、val_pred_epoch{n}.csv），中途當掉時已完成的 epoch 不會白跑
輸出：output/longformer_pd_fold{k}_{版本}_L{max_len}[_t2s]/metrics.json、pred.csv、val_pred.csv、train.log

10/21 加入（預設不變）：
  --task amount：金額任務。樣本與答案讀 --amount_file（amount_tfidf.py 的 amount_oof_main.csv：一部勝訴 10,032 件的
                id 與 grant_ratio），輸出 1 個值（MSE 損失），預測裁到 0–1，用驗證集 Spearman 選 epoch。
                輸出資料夾 longformer_amount_pd_fold{k}_...；pred.csv 的欄位是 pred（不是 prob）
  --suffix：加在輸出資料夾名稱後面（例如 _ep3），換設定時不會蓋掉原本的結果
  --split time：時間切分，2022–2024 訓練、2025 全部當測試；驗證集只從 2022–2024 取（同 train_bert.py）。
                輸出資料夾 longformer_pd_time2025_...
  --input p／d：只用原告主張／只用被告答辯（10/24 加入），和 train_bert.py 的 --input 相同。輸出資料夾 longformer_p_…、longformer_d_…
10/28 加入（預設不變）：
  --train_last N：只微調最後 N 層 encoder 與分類頭；詞向量與前面的層凍結。0＝全部微調（原本的設定）。
                  凍結時 gradient checkpointing 改用 use_reentrant=False，否則凍結層之後的輸入沒有梯度，
                  被 checkpoint 的可訓練層會拿不到梯度；第一個 batch 會檢查「最後一層有梯度、凍結層沒有」。
                  輸出資料夾名稱不會自動改，請用 --suffix（例如 _last4）區分。
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
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, Dataset

HERE = Path(__file__).resolve().parent
try:   # 在 repo 裡執行時用 config.py 的路徑；單獨上傳到雲端執行時沒有 config，資料與輸出放在程式旁邊
    import config
    DEFAULT_DATA_DIR, DEFAULT_OUT_DIR = config.DATASET_DIR, config.OUTPUT_DIR
except ImportError:
    DEFAULT_DATA_DIR, DEFAULT_OUT_DIR = HERE, HERE / "output"


def budget(lp, ld, n):
    """兩段合計不超過 n 個 token 時各留多少：和 train_bert.py 相同，先從較長的一段砍。"""
    if lp + ld <= n:
        return lp, ld
    h = n // 2
    if lp <= h:
        return lp, n - lp
    if ld <= h:
        return n - ld, ld
    return (n - h, h) if lp > ld else (h, n - h)


def cut(ids, k):
    """超過 k 個 token 時保留開頭 1/4、結尾 3/4（和 BERT 的 headtail 相同）。"""
    if len(ids) <= k:
        return ids
    h = k // 4
    return ids[:h] + ids[len(ids) - (k - h):]


class Pairs(Dataset):
    def __init__(self, df, tok, max_len, mode="pd"):
        CLS, SEP = tok.cls_token_id, tok.sep_token_id
        P = tok(df.plaintiff_claim_text.fillna("").tolist(), add_special_tokens=False)["input_ids"]
        D = tok(df.defendant_defense_text.fillna("").tolist(), add_special_tokens=False)["input_ids"]
        self.seqs, self.full_len = [], []
        for p, d in zip(P, D):
            if mode == "p":                       # 只用原告主張
                self.seqs.append([CLS] + cut(p, max_len - 2) + [SEP]); self.full_len.append(len(p) + 2)
            elif mode == "d":                     # 只用被告答辯
                self.seqs.append([CLS] + cut(d, max_len - 2) + [SEP]); self.full_len.append(len(d) + 2)
            else:
                bp, bd = budget(len(p), len(d), max_len - 3)
                self.seqs.append([CLS] + cut(p, bp) + [SEP] + cut(d, bd) + [SEP])
                self.full_len.append(len(p) + len(d) + 3)
        self.y = df.y.tolist()

    def __len__(self):
        return len(self.y)

    def __getitem__(self, i):
        return self.seqs[i], self.y[i]


def make_collate(pad_id):
    def collate(batch):
        seqs, y = zip(*batch)
        L = max(len(s) for s in seqs)
        ids = torch.full((len(seqs), L), pad_id, dtype=torch.long)
        am = torch.zeros((len(seqs), L), dtype=torch.long)
        for i, s in enumerate(seqs):
            ids[i, :len(s)] = torch.tensor(s)
            am[i, :len(s)] = 1
        return {"input_ids": ids, "attention_mask": am, "labels": torch.tensor(y)}
    return collate


@torch.no_grad()
def predict(model, ds, collate, device, bs, regress=False):
    # 依長度排序後分批，減少補零；結果再依原順序放回
    order = np.argsort([len(s) for s in ds.seqs])
    out = np.zeros(len(ds))
    model.eval()
    for j in range(0, len(order), bs):
        idx = order[j:j + bs]
        b = collate([ds[i] for i in idx])
        b = {k: v.to(device) for k, v in b.items() if k != "labels"}
        with torch.autocast("cuda", dtype=torch.float16):
            logits = model(**b).logits
        out[idx] = (logits.float()[:, 0] if regress else torch.softmax(logits.float(), -1)[:, 1]).cpu().numpy()
    model.train()
    return np.clip(out, 0, 1) if regress else out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v4")
    ap.add_argument("--data", default=None, help="text_dataset_{版本}.csv 的路徑；預設見 config.py（單獨執行時是程式旁邊）")
    ap.add_argument("--out", default=None, help="輸出資料夾的上層；預設見 config.py（單獨執行時是程式旁邊的 output/）")
    ap.add_argument("--fold", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--max_len", type=int, default=4096)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--accum", type=int, default=32)       # 有效 batch 32，和 BERT 相同
    ap.add_argument("--eval_batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--model", default="thunlp/Lawformer")
    ap.add_argument("--no_t2s", action="store_true", help="不轉簡體")
    ap.add_argument("--limit", type=int, default=0, help="試跑：訓練、驗證、測試各只取這麼多筆")
    ap.add_argument("--task", choices=["winloss", "amount"], default="winloss")
    ap.add_argument("--amount_file", default=None, help="--task amount 時：amount_oof_main.csv 的路徑")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--input", choices=["p", "d", "pd"], default="pd", help="p＝只用原告主張、d＝只用被告答辯（10/24 加入）")
    ap.add_argument("--split", choices=["fold", "time"], default="fold",
                    help="time：2022–2024 訓練、2025 測試；驗證集＝2022–2024 中 fold==0 且 val_half==1（同 train_bert.py）")
    ap.add_argument("--train_last", type=int, default=0, help="只微調最後 N 層 encoder（加上分類頭）；0＝全部微調")
    a = ap.parse_args()

    # Load training dependencies only when training starts, not when importing helpers.
    from transformers import AutoModelForSequenceClassification, BertTokenizerFast, get_linear_schedule_with_warmup
    t2s = not a.no_t2s
    regress = a.task == "amount"

    torch.manual_seed(42)
    np.random.seed(42)
    device = "cuda"
    assert torch.cuda.is_available(), "抓不到 GPU"
    tag = (f"longformer{'_amount' if regress else ''}_{a.input}_{'time2025' if a.split == 'time' else f'fold{a.fold}'}_{a.version}_L{a.max_len}" + ("_t2s" if t2s else "")
           + a.suffix + (f"_limit{a.limit}" if a.limit else ""))
    out = Path(a.out or DEFAULT_OUT_DIR) / tag
    out.mkdir(parents=True, exist_ok=True)
    log = open(out / "train.log", "a", encoding="utf-8")

    def say(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log.write(line + "\n"); log.flush()

    df = pd.read_csv(a.data or DEFAULT_DATA_DIR / f"text_dataset_{a.version}.csv", encoding="utf-8")
    if regress:
        amt = pd.read_csv(a.amount_file, usecols=["id", "grant_ratio"])
        df = df.merge(amt, on="id", how="inner", validate="1:1")
        df["y"] = df.grant_ratio.astype(np.float32)          # 金額任務的 y 是獲償比例
    if a.split == "time":
        past = df.year.astype(int) <= 2024
        vmask = past & (df.fold == 0) & (df.val_half == 1)
        tr, va, te = df[past & ~vmask].copy(), df[vmask].copy(), df[~past].copy()
    else:
        vmask = (df.fold == (a.fold + 1) % 5) & (df.val_half == 1)
        tr, va, te = df[(df.fold != a.fold) & ~vmask].copy(), df[vmask].copy(), df[df.fold == a.fold].copy()
    if a.limit:
        tr, va, te = (x.sample(min(a.limit, len(x)), random_state=42) for x in (tr, va, te))
    say(f"{tag}：訓練 {len(tr):,}、驗證 {len(va):,}、測試 {len(te):,} 筆，模型 {a.model}，max_len {a.max_len}，"
        f"batch {a.batch}×{a.accum}，lr {a.lr}，epochs {a.epochs}，t2s {t2s}，GPU {torch.cuda.get_device_name(0)}")

    if t2s:
        from opencc import OpenCC                      # pip install opencc-python-reimplemented
        cc = OpenCC("t2s")
        for x in (tr, va, te):
            for c in ("plaintiff_claim_text", "defendant_defense_text"):
                x[c] = x[c].fillna("").map(cc.convert)
        say("已轉成簡體")
    tok = BertTokenizerFast.from_pretrained(a.model)
    ds_tr, ds_va, ds_te = Pairs(tr, tok, a.max_len, a.input), Pairs(va, tok, a.max_len, a.input), Pairs(te, tok, a.max_len, a.input)
    fl = np.array(ds_te.full_len)
    say(f"測試折：兩造合計 token 中位數 {int(np.median(fl))}，超過 {a.max_len} 的比例 {(fl > a.max_len).mean():.1%}")

    model = AutoModelForSequenceClassification.from_pretrained(a.model, num_labels=1 if regress else 2).to(device)
    layers = model.base_model.encoder.layer
    if a.train_last:
        assert 0 < a.train_last < len(layers), f"--train_last 要在 1 到 {len(layers) - 1} 之間"
        for p in model.base_model.embeddings.parameters():
            p.requires_grad = False
        for layer in layers[:len(layers) - a.train_last]:
            for p in layer.parameters():
                p.requires_grad = False
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    else:
        model.gradient_checkpointing_enable()
    n_all = sum(p.numel() for p in model.parameters())
    n_tr = sum(p.numel() for p in model.parameters() if p.requires_grad)
    say(f"可訓練參數 {n_tr / 1e6:.1f}M / {n_all / 1e6:.1f}M（{n_tr / n_all:.1%}）；"
        + (f"只微調最後 {a.train_last} 層（共 {len(layers)} 層）與分類頭" if a.train_last else "全部微調"))
    collate = make_collate(tok.pad_token_id)
    tr_loader = DataLoader(ds_tr, batch_size=a.batch, shuffle=True, collate_fn=collate, num_workers=0)
    steps = math.ceil(len(tr_loader) / a.accum) * a.epochs
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.01)
    sched = get_linear_schedule_with_warmup(opt, int(0.1 * steps), steps)
    scaler = torch.cuda.amp.GradScaler()

    hist, best, t0, step = [], None, time.time(), 0
    model.train()
    for ep in range(1, a.epochs + 1):
        for i, b in enumerate(tr_loader, 1):
            b = {k: v.to(device) for k, v in b.items()}
            if regress:
                b["labels"] = b["labels"].float()
            with torch.autocast("cuda", dtype=torch.float16):
                loss = model(**b).loss / a.accum
            scaler.scale(loss).backward()
            if a.train_last and ep == 1 and i == 1:      # 確認梯度真的只流到最後幾層
                got = all(p.grad is not None for p in layers[-1].parameters())
                frozen = all(p.grad is None for p in layers[0].parameters())
                say(f"梯度檢查：最後一層有梯度 {got}、第一層沒有梯度 {frozen}")
                assert got and frozen, "凍結設定沒有生效"
            if i % a.accum == 0 or i == len(tr_loader):
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt); scaler.update(); opt.zero_grad(); sched.step()
                step += 1
                if step % 20 == 0 or step == 2:
                    el = time.time() - t0
                    say(f"epoch {ep} step {step}/{steps} loss {loss.item() * a.accum:.4f} "
                        f"GPU 記憶體峰值 {torch.cuda.max_memory_allocated() / 2**30:.1f} GB，"
                        f"已 {el / 60:.1f} 分，預估剩 {el / step * (steps - step) / 60:.0f} 分")
        prob = predict(model, ds_te, collate, device, a.eval_batch, regress)
        vprob = predict(model, ds_va, collate, device, a.eval_batch, regress)
        score = (lambda yy, pp: spearmanr(yy, pp).statistic) if regress else roc_auc_score   # 金額用 Spearman
        # 欄位名稱沿用 auc／val_auc，金額任務時存的是 Spearman（metrics.json 的 task 欄註明）
        h = {"epoch": ep, "auc": round(score(te.y, prob), 4), "val_auc": round(score(va.y, vprob), 4),
             "minutes": round((time.time() - t0) / 60, 1)}
        pd.DataFrame({"id": te.id.values, "y": te.y.values, ("pred" if regress else "prob"): prob}).to_csv(out / f"pred_epoch{ep}.csv", index=False)
        pd.DataFrame({"id": va.id.values, "y": va.y.values, ("pred" if regress else "prob"): vprob}).to_csv(out / f"val_pred_epoch{ep}.csv",
                                                                                   index=False)
        if best is None or h["val_auc"] > max(x["val_auc"] for x in hist):   # 只看驗證集決定保留哪個 epoch
            best = (ep, prob, vprob)
        hist.append(h)
        nm = "Spearman" if regress else "AUC"
        say(f"epoch {ep} 測試折 {nm} {h['auc']:.4f}、驗證集 {nm} {h['val_auc']:.4f}（{h['minutes']} 分）")

    ep_sel, prob, vprob = best
    pd.DataFrame({"id": te.id.values, "y": te.y.values, ("pred" if regress else "prob"): prob}).to_csv(out / "pred.csv", index=False)
    pd.DataFrame({"id": va.id.values, "y": va.y.values, ("pred" if regress else "prob"): vprob}).to_csv(out / "val_pred.csv", index=False)
    metrics = {"tag": tag, "task": a.task, "score": "spearman" if regress else "auc", "fold": a.fold, "n_train": len(tr), "n_val": len(va), "n_test": len(te),
               "history": hist, "epoch_selected_by_val": ep_sel, "auc_selected": hist[ep_sel - 1]["auc"],
               "gpu": torch.cuda.get_device_name(0), "gpu_peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
               "args": vars(a)}
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    say(f"完成：驗證集選第 {ep_sel} 個 epoch，測試 {'Spearman' if regress else 'AUC'} {hist[ep_sel - 1]['auc']:.4f}，共 {(time.time() - t0) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()
