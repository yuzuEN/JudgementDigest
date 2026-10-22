# -*- coding: utf-8 -*-
"""
CAIL 格式資料集的共用讀取、切分與評估（所有模型共用，分數才能互相比較）。

只依賴 numpy；訓練腳本另外需要 scikit-learn／PyTorch（見 models/README.md）。

資料：CAIL 格式 jsonl（或含一個 .jsonl 的 .zip），每行 {"fact": ..., "meta": {...}}。
  - meta.fold：0–9，依 jid／裁判字號雜湊固定分組
  - meta.task_validity：{"accusation", "article", "imprisonment"}，該任務標籤是否可用（v2 起才有）
    不合格的任務標籤是空的，要從該任務的訓練與評分排除，不能當成「全部都不是」的負例。
    沒有這個欄位的舊版（v1.1）：罪名、法條有標籤就算可用；刑期看 meta.term_task。

切分：
  holdout_split：開發／調參數用。test = 指定 fold 隨機抽 test_n 筆；驗證 = 其他 fold 打亂後的最後 val_n 筆；
                 train = 其他 fold 打亂後的其餘部分（取前 n 筆即為巢狀子集）。seed 42、test fold 0 時與
                 先前學習曲線、fastText 實驗的切法完全相同。
  正式 10-fold：test_fold 輪流 0–9（test_n=None 用整個 fold），報告平均 ± 標準差。

評分：
  罪名、法條（多標籤）：micro-F1、macro-F1（所有類別平均，沒出現也算 0，與 sklearn zero_division=0 相同）、
                       其餘 macro（扣掉訓練集前十大類別、且測試集有出現的類別）
  刑期：區間 accuracy（7 類：1–2、3–6、7–12、13–36、37–120、>120 個月、無期／死刑）、
        CAIL 分數（|log(y+1) − log(ŷ+1)| ≤ 0.2 得 1 分、≤ 0.4 得 0.8 …、> 1 得 0；死刑、無期要猜中才得分）
"""

import io
import json
import math
import random
import zipfile
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

TASKS = ("accusation", "article", "imprisonment")
TASK_NAMES = {"accusation": "罪名", "article": "法條", "imprisonment": "刑期"}
BINS = [(1, 2, "1–2"), (3, 6, "3–6"), (7, 12, "7–12"), (13, 36, "13–36"), (37, 120, "37–120"), (121, 10**6, ">120")]
BIN_NAMES = [b[2] for b in BINS] + ["無期／死刑"]
DEATH, LIFE = -2, -1


def read_lines(path: str) -> Iterator[str]:
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.endswith(".jsonl"))
            with z.open(name) as f:
                yield from io.TextIOWrapper(f, encoding="utf-8")
    else:
        with open(path, encoding="utf-8") as f:
            yield from f


def months_of(meta: dict) -> float:
    """有期徒刑月數；死刑 −2、無期 −1。"""
    t = meta["term_of_imprisonment"]
    return DEATH if t["death_penalty"] else (LIFE if t["life_imprisonment"] else t["imprisonment"])


def validity_of(meta: dict) -> Dict[str, bool]:
    if "task_validity" in meta:
        return {k: bool(meta["task_validity"].get(k)) for k in TASKS}
    return {"accusation": bool(meta.get("accusation")), "article": bool(meta.get("relevant_articles")),
            "imprisonment": bool(meta.get("term_task"))}


def to_row(record: dict, article_field: str = "relevant_articles") -> dict:
    m = record["meta"]
    return {"fact": record["fact"], "accusation": m.get("accusation") or [], "article": m.get(article_field) or [],
            "months": months_of(m), "valid": validity_of(m), "fold": m["fold"], "year": m.get("year")}


def load(path: str, article_field: str = "relevant_articles") -> List[dict]:
    """article_field="relevant_articles_merged" 可用修法換條號合併後的法條（v2 起才有）。"""
    return [to_row(json.loads(line), article_field) for line in read_lines(path)]


def holdout_split(rows: Sequence[dict], test_fold: int = 0, test_n: Optional[int] = 50_000,
                  val_n: int = 0, seed: int = 42) -> Tuple[list, list, list]:
    """回傳 (train 候選, 驗證, test)；train 候選已打亂，取前 n 筆即為巢狀子集。"""
    test = [r for r in rows if r["fold"] == test_fold]
    pool = [r for r in rows if r["fold"] != test_fold]
    rng = random.Random(seed)
    rng.shuffle(test)
    if test_n is not None:
        test = test[:test_n]
    rng.shuffle(pool)
    val = pool[len(pool) - val_n:] if val_n else []
    pool = pool[:len(pool) - val_n] if val_n else pool
    return pool, val, test


def task_rows(rows: Sequence[dict], task: str) -> list:
    return [r for r in rows if r["valid"][task]]


def bin_of(m: float) -> int:
    """刑期區間編號；只看上限，所以非刑期任務的 0 個月也不會出錯（那些案件本來就不參與刑期評分）。"""
    return len(BINS) if m < 0 else next(i for i, (_, hi, _) in enumerate(BINS) if m <= hi)


def cail_score(y: Sequence[float], p: Sequence[float]) -> float:
    s = []
    for a, b in zip(y, p):
        if a < 0 or b < 0:
            s.append(1.0 if a == b else 0.0)
            continue
        v = abs(math.log(a + 1) - math.log(b + 1))
        s.append(1.0 if v <= .2 else .8 if v <= .4 else .6 if v <= .6 else .4 if v <= .8 else .2 if v <= 1 else 0.0)
    return float(np.mean(s)) if s else float("nan")


def at_least_one(scores: np.ndarray, threshold: float = 0.0) -> np.ndarray:
    """多標籤預測：分數 > threshold 為有；一個都沒有時取最高的。"""
    p = (scores > threshold).astype(int)
    p[np.arange(len(p)), scores.argmax(1)] = 1
    return p


def _f1(tp, fp, fn):
    d = 2 * tp + fp + fn
    return np.where(d > 0, 2 * tp / np.maximum(d, 1), 0.0)


def multilabel_scores(Y: np.ndarray, P: np.ndarray, top: Sequence[int] = ()) -> Dict[str, float]:
    """Y、P 是 0／1 矩陣（筆數 × 類別）。top：訓練集最常見的類別編號，「其餘 macro」會扣掉它們。"""
    Y = np.asarray(Y, dtype=bool); P = np.asarray(P, dtype=bool)
    tp = (Y & P).sum(0); fp = (~Y & P).sum(0); fn = (Y & ~P).sum(0)
    per = _f1(tp, fp, fn)
    top = set(int(j) for j in top)
    rest = [j for j in range(Y.shape[1]) if j not in top and Y[:, j].any()]
    return {"micro": float(_f1(tp.sum(), fp.sum(), fn.sum())), "macro": float(per.mean()) if len(per) else 0.0,
            "其餘 macro": float(per[rest].mean()) if rest else float("nan")}


def top_classes(Y_train: np.ndarray, k: int = 10) -> List[int]:
    return [int(j) for j in np.argsort(-np.asarray(Y_train).sum(0), kind="stable")[:k]]


def term_scores(months_true: Sequence[float], bins_pred: Sequence[int], months_pred: Sequence[float]) -> Dict[str, float]:
    yb = np.array([bin_of(m) for m in months_true])
    return {"區間 accuracy": float((yb == np.asarray(bins_pred)).mean()) if len(yb) else float("nan"),
            "CAIL 分數": cail_score(months_true, months_pred)}


def config_header(script_path: str, args) -> str:
    """結果檔開頭：程式內容雜湊＋所有參數，之後看結果就知道是哪一版、怎麼跑的。"""
    import hashlib
    digest = hashlib.sha256(open(script_path, "rb").read()).hexdigest()[:10]
    opts = "、".join(f"{k}={v}" for k, v in sorted(vars(args).items()))
    return f"程式 {script_path.replace(chr(92), '/').split('/')[-1]}（sha256 {digest}）；參數：{opts}"
