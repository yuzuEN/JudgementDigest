"""
建立上線用的刑事檢索資料：犯罪事實的 TF-IDF 索引與案件清單。

    python -m retrieval.criminal --data <CAIL 格式 .jsonl>     # 輸出到 artifacts/retrieval_criminal_v1/

語料：CAIL 格式資料集（全國地院第一審有罪、單一被告）裡罪名可用的案件。全量 113 萬件的索引太吃記憶體，
每個主要罪名（第一個罪名）最多取 PER_CHARGE 件、新的判決優先；少見罪名全收。
事實裡的罪名、法條已在資料集遮成「××」；被告姓名換成「被告」，再遮身分證字號、電話等。
輸出：
  index.joblib   犯罪事實（前 INDEX_CHARS 字）的 TF-IDF 索引（列的順序＝cases 表的 row）
  cases.sqlite   cases：字號、法院、年份、罪名、宣告刑、摘要、司法院原文網址
  meta.json      建立時間、件數、資料版本
"""
import argparse
import collections
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

import config
from retrieval.engine import TfidfIndex
from retrieval.masking import mask

NAME = "retrieval_criminal_v1"
PER_CHARGE = 1500
INDEX_CHARS = 600
SUMMARY_LEN = 90
VOCAB_SAMPLE = 60_000


def artifact_dir(base: Optional[Path] = None) -> Path:
    return Path(base or config.ARTIFACTS_DIR) / NAME


def sentence_text(meta: Dict) -> Optional[str]:
    """給人看的宣告刑；資料集沒有可靠單一刑度的（數罪、刑期未明）回傳 None。"""
    kind = meta.get("sentence_kind")
    term = meta.get("term_of_imprisonment") or {}
    if kind == "死刑或無期徒刑":
        return "死刑" if term.get("death_penalty") else "無期徒刑"
    if kind == "有期徒刑" and term.get("imprisonment", 0) > 0:
        y, m = divmod(int(term["imprisonment"]), 12)
        return "有期徒刑 " + " ".join(p for p in (f"{y} 年" if y else "", f"{m} 月" if m else "") if p)
    if kind == "拘役" and (meta.get("detention_days") or 0) > 0:
        return f"拘役 {meta['detention_days']} 日"
    if kind == "刑期未明" and (meta.get("punish_of_money") or 0) > 0 and not (meta.get("detention_days") or 0):
        return f"罰金 {meta['punish_of_money']:,} 元"
    return None


def masked(text: str, defendants: List[str]) -> str:
    for name in sorted({n for n in defendants if n and len(n) >= 2}, key=len, reverse=True):
        text = text.replace(name, "被告")
    return mask(text)[0]


def _valid(meta: Dict) -> bool:
    return bool((meta.get("task_validity") or {}).get("accusation") and meta.get("accusation"))


def load_corpus(path: Path, per_charge: int = PER_CHARGE) -> pd.DataFrame:
    # 第一輪只記行號、日期、主要罪名，挑好再讀事實全文（113 萬件的全文一起放進記憶體要好幾 GB）
    cands = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            m = json.loads(line)["meta"]
            if _valid(m):
                cands.append((str(m.get("judgment_date") or ""), i, m["accusation"][0]))
    cands.sort(reverse=True)                                    # 新的判決優先
    taken, keep = collections.Counter(), set()
    for _, i, charge in cands:
        if taken[charge] < per_charge:
            taken[charge] += 1
            keep.add(i)
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i not in keep:
                continue
            r = json.loads(line)
            m = r["meta"]
            text = masked(r["fact"], m.get("criminals") or [])[:INDEX_CHARS]
            rows.append({"id": i, "case_number": m.get("case_number") or "", "court": m.get("court") or "",
                         "year": str(m.get("year") or ""), "charges": m["accusation"], "sentence": sentence_text(m),
                         "url": m.get("source_url") or "", "text": text, "summary": text[:SUMMARY_LEN]})
    return pd.DataFrame(rows)


def write_artifacts(corpus: pd.DataFrame, out: Path, source: str = "") -> Path:
    corpus = corpus.reset_index(drop=True)
    out.mkdir(parents=True, exist_ok=True)
    params = {} if len(corpus) >= 50 else {"min_df": 1, "max_features": None}   # 測試用的小語料
    TfidfIndex(**params).fit(corpus.text, sample=VOCAB_SAMPLE).save(out / "index.joblib")
    db = out / "cases.sqlite"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    try:
        con.execute("""CREATE TABLE cases (row INTEGER PRIMARY KEY, id INTEGER UNIQUE, case_number TEXT, court TEXT,
                       year TEXT, charges TEXT, sentence TEXT, summary TEXT, url TEXT)""")
        con.executemany("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?)", [
            (i, int(r.id), r.case_number, r.court, r.year, json.dumps(list(r.charges), ensure_ascii=False),
             r.sentence, r.summary, r.url) for i, r in enumerate(corpus.itertuples())])
        con.commit()
    finally:
        con.close()
    meta = {"name": NAME, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source,
            "n_cases": int(len(corpus)), "per_charge": PER_CHARGE,
            "index": f"犯罪事實前 {INDEX_CHARS} 字，字元 1–3 gram TF-IDF", "masking": "被告姓名換成「被告」；罪名、法條沿用資料集的遮蔽"}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="建立上線用的刑事檢索資料")
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    corpus = load_corpus(a.data)
    print(f"語料 {len(corpus):,} 件（{corpus.charges.str[0].nunique()} 個主要罪名）", flush=True)
    print(f"已存到 {write_artifacts(corpus, a.out or artifact_dir(), a.data.name)}")


if __name__ == "__main__":
    main()
