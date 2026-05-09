# -*- coding: utf-8 -*-
"""
自動分段批次爬蟲 — 以公曆年度為單位切分搜尋，自動處理每次 500 筆上限。

採用廣度優先（BFS）策略：
  - 初始段落：每段 = 一個公曆年（與 search_and_crawl 的 ROC 年度篩選 URL 對齊）
  - 觸碰 500 上限且跨年的段落，下一輪切為兩半再抓
  - 同一年度內觸碰上限：已無法用年度 URL 細分，記錄警告後跳過

用法:
    python crawl_batched.py 借名登記 -n 2000
    python crawl_batched.py 借名登記 -n 1000 --start-year 2018 --end-year 2023
    python crawl_batched.py 借名登記 -n 1000 --start-date 2020/01/01 --end-date 2024/12/31
"""

import argparse
import logging
import sqlite3
from datetime import date, timedelta

from crawler import search_and_crawl, DB_PATH, init_db

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("crawler_batched.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# search_and_crawl 每次呼叫的最大筆數上限
# 設為 2000：允許每個「法院×年度」群組合計仍在此範圍內完整抓取
# 借名登記每年最多約 900 筆（~25 法院，每法院最多 ~100 筆），故 2000 足夠
MAX_PER_CALL = 2000
# 若某段抓到的筆數 >= HIT_LIMIT，視為可能有資料遺漏，記錄警告
# 以 MAX_PER_CALL 的 95% 為門檻
HIT_LIMIT  = int(MAX_PER_CALL * 0.95)
# 最小切分天數：低於此天數不再切分（避免無限細分）
MIN_SPLIT_DAYS = 7


# ─── 工具函式 ─────────────────────────────────────────────────────────────────
def _db_count(keyword: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute(
        "SELECT COUNT(*) FROM crawl_records WHERE keyword LIKE ?",
        (f"%{keyword}%",),
    ).fetchone()[0]
    conn.close()
    return n


def _fmt(d: date) -> str:
    return d.strftime("%Y/%m/%d")


def _generate_year_chunks(start_date: date, end_date: date) -> list:
    """
    產生公曆年度對齊的 (chunk_start, chunk_end) 列表，由新到舊排序。
    每段恰好對應一個公曆年（或起/迄年的不完整部分），
    與 search_and_crawl 內部的 ROC 年度篩選 URL 完全對齊，避免重複爬取。
    """
    chunks = []
    for year in range(end_date.year, start_date.year - 1, -1):
        cs = max(start_date, date(year, 1, 1))
        ce = min(end_date, date(year, 12, 31))
        if cs <= ce:
            chunks.append((cs, ce))
    return chunks


def _split_chunk(cs: date, ce: date) -> list:
    """將 [cs, ce] 對半切分，回傳 [(newer_half), (older_half)]（新的在前）。"""
    span = (ce - cs).days + 1
    mid  = cs + timedelta(days=span // 2 - 1)
    return [(mid + timedelta(days=1), ce), (cs, mid)]


# ─── 主函式（BFS）────────────────────────────────────────────────────────────
def batched_crawl(
    keyword: str,
    total_target: int,
    start_date: date,
    end_date: date,
    headless: bool,
) -> int:
    """
    廣度優先批次爬取。

    初始段落以公曆年為單位（對齊 search_and_crawl 的 ROC 年度篩選 URL）。
    每一輪依「今年 → 起始年」順序掃過所有待處理段落；
    觸碰 500 上限且跨年的段落才在下一輪被切成兩半重抓。
    累計新增筆數達 total_target 後停止。
    """
    init_db()

    # 初始段落：年度對齊，最新在前
    current_round: list = _generate_year_chunks(start_date, end_date)
    total_new   = 0
    round_no    = 0

    logger.info(
        "開始批次爬取：keyword=%r  target=%d  初始段數=%d（年度對齊）  range=[%s → %s]",
        keyword, total_target, len(current_round),
        _fmt(start_date), _fmt(end_date),
    )

    while current_round and total_new < total_target:
        round_no += 1
        next_round: list = []

        logger.info(
            "\n%s\n第 %d 輪：共 %d 段待處理  (累計 %d / %d)\n%s",
            "=" * 60, round_no, len(current_round), total_new, total_target, "=" * 60,
        )

        for idx, (cs, ce) in enumerate(current_round, 1):
            if total_new >= total_target:
                logger.info("已達目標 %d 筆，本輪提早結束。", total_target)
                break

            span_days = (ce - cs).days + 1
            logger.info(
                "  [%d/%d] %s → %s  (span=%dd)",
                idx, len(current_round), _fmt(cs), _fmt(ce), span_days,
            )

            before    = _db_count(keyword)
            n_fetched = search_and_crawl(
                keyword=keyword,
                max_results=MAX_PER_CALL,
                headless=headless,
                start_date=_fmt(cs),
                end_date=_fmt(ce),
            )
            new        = _db_count(keyword) - before
            total_new += new

            logger.info(
                "  fetched=%d  new=%d  累計=%d/%d",
                n_fetched, new, total_new, total_target,
            )

            # 觸碰上限 → 嘗試切分
            if n_fetched >= HIT_LIMIT and span_days > MIN_SPLIT_DAYS:
                if cs.year == ce.year:
                    # 同一年度：年度 URL 無法細分，記錄警告
                    logger.warning(
                        "  ⚠ 觸碰 500 上限（%d 年），但年度篩選已無法細分，"
                        "此年度可能有資料遺漏。",
                        cs.year,
                    )
                else:
                    # 跨年段落：切為兩半（各自對應不同年度）
                    halves = _split_chunk(cs, ce)
                    next_round.extend(halves)
                    logger.info(
                        "  ⚠ 觸碰 500 上限，下一輪切分為 %s→%s 和 %s→%s",
                        _fmt(halves[0][0]), _fmt(halves[0][1]),
                        _fmt(halves[1][0]), _fmt(halves[1][1]),
                    )
            elif n_fetched >= HIT_LIMIT:
                logger.warning(
                    "  ⚠ 觸碰 500 上限，但段落僅 %d 天，無法再切分，此區間可能有遺漏。",
                    span_days,
                )

        current_round = next_round

    logger.info(
        "\n%s\n批次爬取完成。總輪數=%d  總新增=%d 筆\n%s",
        "=" * 60, round_no, total_new, "=" * 60,
    )
    return total_new


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="自動分段批次爬蟲（廣度優先，年度對齊，自動處理 500 筆上限）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python crawl_batched.py 借名登記 -n 2000
  python crawl_batched.py 借名登記 -n 1000 --start-year 2018 --end-year 2023
  python crawl_batched.py 借名登記 -n 500  --start-date 2024/01/01 --end-date 2025/04/28
        """,
    )
    ap.add_argument("keyword", help="搜尋關鍵字")
    ap.add_argument(
        "-n", "--num", type=int, default=1000,
        help="目標筆數（預設: 1000）",
    )
    ap.add_argument(
        "--start-year", type=int, default=2015,
        help="搜尋起始年（預設: 2015，可被 --start-date 覆蓋）",
    )
    ap.add_argument(
        "--end-year", type=int, default=None,
        help="搜尋結束年（預設: 今年，可被 --end-date 覆蓋）",
    )
    ap.add_argument(
        "--start-date", default="",
        help="起始日期 YYYY/MM/DD（覆蓋 --start-year）",
    )
    ap.add_argument(
        "--end-date", default="",
        help="結束日期 YYYY/MM/DD（覆蓋 --end-year）",
    )
    ap.add_argument(
        "--no-headless", action="store_true",
        help="顯示瀏覽器視窗（debug 用）",
    )
    args = ap.parse_args()

    today = date.today()

    if args.start_date:
        sd = date.fromisoformat(args.start_date.replace("/", "-"))
    else:
        sd = date(args.start_year, 1, 1)

    if args.end_date:
        ed = date.fromisoformat(args.end_date.replace("/", "-"))
    else:
        ed = date(args.end_year, 12, 31) if args.end_year else today

    if sd > ed:
        ap.error(f"起始日期 {_fmt(sd)} 晚於結束日期 {_fmt(ed)}")

    total = batched_crawl(
        keyword=args.keyword,
        total_target=args.num,
        start_date=sd,
        end_date=ed,
        headless=not args.no_headless,
    )
    print(f"\n完成！共新增 {total} 筆裁判書至資料庫。")
