"""
用資料庫裡已存的全文重新擷取法官與書記官（judges、clerk 欄位）。

為什麼不用 html_parser.py --reparse
──────────────────────────────────
--reparse 會先清空整個 judgments 表再從 html_cache 重解析；從同學資料庫合併進來的列
不一定有對應的 HTML 檔，重解析會讓它們消失。法官擷取只需要全文，全文已在資料庫裡，
所以只重算這兩欄即可。

全文在解析時截到 10 萬字（_cap），長度剛好 10 萬字的列簽名區可能已被截掉，這些列不動。
更新後請接著跑 backfill_structured.py，judge_count、presiding_judge 等結構化欄位才會跟著更新。

    python refresh_judges.py --dry-run     # 只統計會改幾筆、列出範例
    python refresh_judges.py               # 備份資料庫後寫入
"""
import argparse
import io
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime

from html_parser import DB_PATH, _extract_judges_and_clerk

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

FULL_TEXT_CAP = 100000


def main() -> int:
    ap = argparse.ArgumentParser(description="用已存的全文重新擷取法官與書記官")
    ap.add_argument("--dry-run", action="store_true", help="只統計，不寫入資料庫")
    ap.add_argument("--no-backup", action="store_true", help="略過資料庫備份（不建議）")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, judges, clerk, full_text FROM judgments "
                        "WHERE full_text IS NOT NULL AND length(full_text) < ?",
                        (FULL_TEXT_CAP,))
    changes, stats, examples = [], Counter(), []
    for rid, judges, clerk, full_text in rows:
        new_j, new_c = _extract_judges_and_clerk(full_text)
        if (new_j, new_c) == ((judges or ""), (clerk or "")):
            continue
        before = len([n for n in (judges or "").split("；") if n])
        after = len([n for n in new_j.split("；") if n])
        stats[f"法官 {before} 位 → {after} 位"] += 1
        if len(examples) < 15:
            examples.append((rid, judges, new_j))
        changes.append((new_j, new_c, rid))

    print(f"會更新 {len(changes)} 筆")
    for k, v in stats.most_common(15):
        print(f"  {k}：{v}")
    for rid, old, new in examples:
        print(f"  [{rid}] {old!r} → {new!r}")
    if args.dry_run or not changes:
        return 0

    if not args.no_backup:
        bak = f"{DB_PATH}.bak-{datetime.now():%Y%m%d_%H%M%S}-judges"
        print(f"備份 → {bak}")
        shutil.copy2(DB_PATH, bak)
    conn.executemany("UPDATE judgments SET judges = ?, clerk = ? WHERE id = ?", changes)
    conn.commit()
    print("完成。接著執行 python backfill_structured.py 更新 judge_count 等欄位。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
