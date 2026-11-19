"""
判決導讀「法院怎麼認定」（D3）：讀 annotation/guide_batch.py 匯出的 guide.sqlite，
把每段引文對到導讀頁的段落（guide_paragraphs 的序號）與段落內的位置。

選用的：guide.sqlite 不存在、或這件判決沒有標註時回傳 None，導讀頁照舊只顯示段落標色。

引文位置的對法：
  1. 先檢查匯出時存的位置在目前的判決文字上是否還對得上（同一份 retrieval_civil 資料就會對上）
  2. 對不上（例如資料版本更新、遮名改過）就用 resolve_quote 在整個法院判斷段重新找；找不到就略過該項
  3. 位置落在哪個導讀段落，就掛在那一段；跨到下一段的部分不標色（只標開頭所在的那一段）
同一標籤、範圍重疊的項目（例如「綜上」重述同一個結論）只留範圍較長的一筆。
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional

from annotation.quotes import resolve_quote

GUIDE_DIR = "annotation_guide_v1"
GUIDE_DB = "guide.sqlite"
COURT_FUNCTIONS = ("issue", "evidence", "court")   # guide_paragraphs 裡，來自法院判斷段的段落


def db_path(artifacts_dir: Path) -> Path:
    return Path(artifacts_dir) / GUIDE_DIR / GUIDE_DB


def _court_spans(court: str, paragraphs: List[Dict]) -> List[tuple]:
    """[(導讀段落序號, 在法院判斷段的起, 迄)]：法院判斷段的段落依序在原文裡找回位置。"""
    spans, pos = [], 0
    for i, p in enumerate(paragraphs):
        if p["function"] not in COURT_FUNCTIONS:
            continue
        s = court.find(p["text"], pos)
        if s < 0:
            continue
        spans.append((i, s, s + len(p["text"])))
        pos = s + len(p["text"])
    return spans


def _locate(court: str, quote: str, label: str, start: int, end: int) -> Optional[tuple]:
    if 0 <= start < end <= len(court) and resolve_quote(quote, court[start:end], label) == (0, end - start):
        return (start, end)
    return resolve_quote(quote, court, label)


def _dedupe(items: List[Dict]) -> List[Dict]:
    keep: List[Dict] = []
    for it in sorted(items, key=lambda x: x["_end"] - x["_start"], reverse=True):
        if any(k["label"] == it["label"] and k["_start"] < it["_end"] and it["_start"] < k["_end"] for k in keep):
            continue
        keep.append(it)
    return sorted(keep, key=lambda x: x["_start"])


def for_case(db: Optional[Path], case_id: int, court: str, paragraphs: List[Dict]) -> Optional[Dict]:
    """{"labeler", "manual_version", "items": [...]}；沒有資料時回傳 None。"""
    if db is None or not Path(db).exists() or not court:
        return None
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as con:
        rows = con.execute("SELECT label, polarity, basis, quote, span_start, span_end FROM reasoning "
                           "WHERE case_id = ? ORDER BY span_start", (case_id,)).fetchall()
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    if not rows:
        return None
    spans = _court_spans(court, paragraphs)
    items = []
    for label, pol, basis, quote, start, end in rows:
        loc = _locate(court, quote, label, start, end)
        if loc is None:
            continue
        hit = next(((i, ps, pe) for i, ps, pe in spans if ps <= loc[0] < pe), None)
        if hit is None:
            continue
        i, ps, pe = hit
        items.append({"label": label, "polarity": pol, "basis": basis, "quote": quote,
                      "paragraph": i, "start": loc[0] - ps, "end": min(loc[1], pe) - ps,
                      "_start": loc[0], "_end": loc[1]})
    if not items:
        return None
    for it in (items := _dedupe(items)):
        it.pop("_start"), it.pop("_end")
    return {"labeler": f"llm-{meta.get('prompt_version', '')}", "manual_version": meta.get("manual_version", ""),
            "items": items}
