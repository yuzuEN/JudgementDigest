"""
判決導讀「法院怎麼認定」（D3）：讀 annotation/guide_batch.py 匯出的 guide.sqlite，
把每段引文對到導讀頁的段落（guide_paragraphs 的序號）與段落內的位置。

選用的：guide.sqlite 不存在、或這件判決沒有標註時回傳 None，導讀頁照舊只顯示段落標色。

引文位置的對法：
  1. 先檢查匯出時存的位置在目前的判決文字上是否還對得上（同一份 retrieval_civil 資料就會對上）
  2. 對不上（例如資料版本更新、遮名改過）就用 resolve_quote 在整個法院判斷段重新找；找不到就略過該項
  3. 位置落在哪個導讀段落，就掛在那一段（paragraph/start/end 是開頭所在的那一段）；
     引文跨到下一段時（導讀段落是依長度切的，可能切在句子中間），parts 列出每一段要標的範圍
同一標籤、範圍重疊的項目（例如「綜上」重述同一個結論）只留範圍較長的一筆。

briefs()：相似判決列表與「可能的金額」分頁用的精簡版（不對段落，只回傳引文和完整原文），
一次查列表裡的所有判決，沒有標註的判決不會出現在結果裡。
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

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
        if not any(ps <= loc[0] < pe for _, ps, pe in spans):
            continue
        parts = [{"paragraph": i, "start": max(loc[0], ps) - ps, "end": min(loc[1], pe) - ps}
                 for i, ps, pe in spans if ps < loc[1] and loc[0] < pe]
        parts = [x for x in parts if x["end"] > x["start"]]
        first = parts[0]
        items.append({"label": label, "polarity": pol, "basis": basis, "quote": quote,
                      "paragraph": first["paragraph"], "start": first["start"], "end": first["end"], "parts": parts,
                      "_start": loc[0], "_end": loc[1]})
    if not items:
        return None
    for it in (items := _dedupe(items)):
        it.pop("_start"), it.pop("_end")
    return {"labeler": f"llm-{meta.get('prompt_version', '')}", "manual_version": meta.get("manual_version", ""),
            "items": items}


def briefs(db: Optional[Path], case_ids: Iterable[int], court_of: Callable[[int], str]) -> Dict[int, List[Dict]]:
    """
    {case_id: [{"label", "polarity", "basis", "quote", "text"}]}；text 是引文在判決裡的完整原文
    （引文是「開頭〔略〕結尾」時，text 是整段）。court_of(case_id) 回傳該判決的法院判斷段，只對有標註的判決呼叫。
    """
    ids = sorted({int(i) for i in case_ids})
    if db is None or not Path(db).exists() or not ids:
        return {}
    marks = ",".join("?" * len(ids))
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as con:
        rows = con.execute("SELECT case_id, label, polarity, basis, quote, span_start, span_end FROM reasoning "
                           f"WHERE case_id IN ({marks}) ORDER BY case_id, span_start", ids).fetchall()
    by_case: Dict[int, list] = {}
    for r in rows:
        by_case.setdefault(r[0], []).append(r[1:])
    out: Dict[int, List[Dict]] = {}
    for case_id, case_rows in by_case.items():
        court = court_of(case_id)
        if not court:
            continue
        items = []
        for label, pol, basis, quote, start, end in case_rows:
            loc = _locate(court, quote, label, start, end)
            if loc is None:
                continue
            items.append({"label": label, "polarity": pol, "basis": basis, "quote": quote,
                          "text": court[loc[0]:loc[1]], "_start": loc[0], "_end": loc[1]})
        if items:
            for it in (items := _dedupe(items)):
                it.pop("_start"), it.pop("_end")
            out[case_id] = items
    return out
