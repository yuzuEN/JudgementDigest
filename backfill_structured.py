"""
Part 3b — 對既有資料庫回填結構化欄位

為什麼需要這支程式
──────────────────
`html_parser.py` 在解析當下就會產生結構化欄位，所以**新爬**的資料不需要回填。
但資料庫裡已經有一萬多筆在規則上線前解析的舊資料，需要補上。

重現性設計
──────────
1. 只從 `judgments` 資料表讀取已解析的文字欄位，**不重新解析 HTML**。
   因此執行結果只取決於 DB 內容與 `structuring.py` 的規則版本，
   在任何機器上重跑都會得到相同結果。
2. 只寫入 `structuring.STRUCTURED_COLUMNS` 列出的欄位，
   絕不碰主文、理由等原始欄位——原始資料永遠是唯一的事實來源。
3. 冪等：重跑不會累積副作用。規則改版後直接重跑即可全量刷新。

使用方式
────────
    python backfill_structured.py --dry-run          # 只統計，不寫入
    python backfill_structured.py                    # 全量回填
    python backfill_structured.py --court 臺北 --year 2025
    python backfill_structured.py --only-missing     # 只補尚未回填的列
"""

from __future__ import annotations

import argparse
import io
import logging
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from html_parser import DB_PATH, init_db
from structuring import (SOURCE_COLUMNS, STRUCTURED_COLUMNS, STRUCTURING_VERSION,
                         derive_structured_fields)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 讀取推導所需的欄位。只取需要的欄位而非 SELECT *，
# 是為了避免把 full_text 以外的大欄位一次全載入造成記憶體壓力。
# 清單由 structuring.SOURCE_COLUMNS 提供，不在這裡另外維護一份。
_SOURCE_COLUMNS = ["id"] + SOURCE_COLUMNS

BATCH = 500


def backup_db(db_path: str) -> str:
    """
    回填前先複製一份資料庫。這是不可逆寫入前唯一的後路。

    檔名必須是 `judgments.db.bak-<時間>` 而不是 `judgments.bak-<時間>.db`：
    .gitignore 的規則是 `judgments.db*`，後者不符合，290 MB 的備份會變成
    未追蹤檔案，`git add .` 就會把它加進版控。
    """
    src = Path(db_path)
    dst = src.with_name(f"{src.name}.bak-{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(src, dst)
    return str(dst)


def build_where(court: str | None, year: str | None, only_missing: bool) -> tuple[str, list]:
    where, params = ["1=1"], []
    if court:
        where.append("court LIKE ?")
        params.append(f"%{court}%")
    if year:
        where.append("judgment_date LIKE ?")
        params.append(f"{year}%")
    if only_missing:
        # 規則版本不同也算「需要更新」，這樣規則改版後 --only-missing
        # 依然會把舊版本的列刷新，不會留下混版資料。
        where.append("(structuring_version IS NULL OR structuring_version != ?)")
        params.append(STRUCTURING_VERSION)
    return " AND ".join(where), params


def run(court=None, year=None, only_missing=False, dry_run=False, no_backup=False) -> int:
    init_db()   # 確保結構化欄位都已存在（ALTER TABLE 冪等）

    if not dry_run and not no_backup:
        logger.info("備份資料庫 → %s", backup_db(DB_PATH))

    where, params = build_where(court, year, only_missing)

    # 讀寫一律走**同一條連線**。
    #
    # 早期版本用兩條連線（一條串流 SELECT、一條 UPDATE），在 SQLite 的
    # rollback journal 模式下會自我死鎖：讀取連線持有 SHARED 鎖，寫入連線
    # 要 commit 就得取得 EXCLUSIVE 鎖，永遠等不到對方釋放。症狀是行程不會
    # 報錯、CPU 幾乎為零、只是無限期卡住。單一連線把讀寫序列化，
    # 沒有這個問題，也不需要改動資料庫的 journal_mode。
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    ids = [r[0] for r in conn.execute(
        f"SELECT id FROM judgments WHERE {where}", params).fetchall()]
    total = len(ids)
    logger.info("符合條件的紀錄：%d 筆（規則版本 %s）", total, STRUCTURING_VERSION)
    if total == 0:
        conn.close()
        return 0

    cols = [c for c, _ in STRUCTURED_COLUMNS]
    set_clause = ",".join(f"{c}=?" for c in cols)

    stats: Counter = Counter()
    flag_stats: Counter = Counter()
    done = 0

    for start in range(0, total, BATCH):
        chunk = ids[start: start + BATCH]
        qmarks = ",".join("?" * len(chunk))
        # fetchall() 讓游標立即結束，讀取的鎖不會延續到接下來的 UPDATE
        rows = conn.execute(
            f"SELECT {','.join(_SOURCE_COLUMNS)} FROM judgments WHERE id IN ({qmarks})",
            chunk).fetchall()

        pending = []
        for row in rows:
            d = dict(row)
            derived = derive_structured_fields(d)

            stats[derived["case_kind_category"]] += 1
            if derived["outcome"]:
                stats["outcome:" + derived["outcome"]] += 1
            if derived["awarded_amount"] is not None:
                stats["有判准金額"] += 1
            if derived["law_n_citations"]:
                stats["有法條引用"] += 1
            for f in (derived["quality_flags"].split("|") if derived["quality_flags"] else []):
                flag_stats[f] += 1

            pending.append(tuple(derived[c] for c in cols) + (d["id"],))

        if not dry_run and pending:
            conn.executemany(f"UPDATE judgments SET {set_clause} WHERE id=?", pending)
            conn.commit()
        done += len(pending)
        logger.info("  已處理 %d / %d", done, total)

    conn.close()

    logger.info("%s 完成：%d 筆", "（試跑）" if dry_run else "回填", done)
    print("\n── 統計 ──")
    for k, v in sorted(stats.items()):
        print(f"  {k:<26}{v:>7}  ({v / done * 100:5.1f}%)")
    print("\n── 品質旗標 ──")
    for k, v in flag_stats.most_common():
        print(f"  {k:<26}{v:>7}  ({v / done * 100:5.1f}%)")
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description="回填結構化欄位（不重新解析 HTML）")
    ap.add_argument("--court", help="法院名稱關鍵字，如 臺北")
    ap.add_argument("--year", help="裁判年份，如 2025")
    ap.add_argument("--only-missing", action="store_true",
                    help="只處理尚未回填或規則版本較舊的紀錄")
    ap.add_argument("--dry-run", action="store_true", help="只統計，不寫入資料庫")
    ap.add_argument("--no-backup", action="store_true", help="略過資料庫備份（不建議）")
    a = ap.parse_args()
    run(a.court, a.year, a.only_missing, a.dry_run, a.no_backup)


if __name__ == "__main__":
    main()
