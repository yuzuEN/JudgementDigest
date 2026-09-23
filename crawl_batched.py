# -*- coding: utf-8 -*-
"""
自動分段批次爬蟲 — 依裁判日期遞迴細分，突破單一查詢 500 筆上限。

為什麼需要切分：
  司法院裁判書系統對「單一查詢結果集」有 500 筆的硬性上限（翻到第 25 頁即無下一頁），
  且結果按裁判日期由新到舊排序，被截斷的永遠是最舊的部分。
  結果頁的分群參數 gy/gc（法院 / 年度 / 審級）是單一互斥軸且不能疊加，
  各分群桶同樣受 500 限制，因此光靠分群無法取得完整資料。

解法：
  進階搜尋（default_AD.aspx）可把裁判日期寫進查詢本身，
  每個日期區間都會產生獨立的 q= hash、各自享有自己的 500 額度。
  因此只要把日期區間切到每段結果 < 500，就能完整取得。

策略（深度優先，嚴格由新到舊）：
  1. 初始段落：每段 = 一個公曆年，最新年在前
  2. 每段先讀摘要頁「查詢結果 N」：N >= 500 代表會被截斷 → 對半切分，較新的半段先處理
  3. N < 500 → 完整翻頁收集並下載
  4. 切到單日仍 >= 500 → 日期無法再細分，改用結果頁分群在該日內逐桶收集：
     未指定法院時用法院分群（gy=jcourt），已指定法院時用案號年度分群（gy=jyear）。
     分群與日期條件不衝突，每個桶各自獨立計算 500 額度；桶本身仍 >= 500 則記入
     truncated_buckets 並在結束時列出

用法:
    python crawl_batched.py 借名登記 -n 2000
    python crawl_batched.py 借名登記 -n 1000 --start-year 2018 --end-year 2023
    python crawl_batched.py 借名登記 -n 1000 --start-date 2020/01/01 --end-date 2024/12/31
"""

import argparse
import logging
import sqlite3
from datetime import date, timedelta
from typing import List, Optional, Tuple

from crawler import (
    search_and_crawl, build_driver, DB_PATH, init_db, Pacer, _RESULT_LIMIT,
    _DEFAULT_DELAY, _JUDGMENT_TYPES, resolve_date_range,
)

# ─── Logging ─────────────────────────────────────────────────────────────────
# 日誌設定沿用 crawler.py（上方 import 時即已設定：主控台 + crawler.log）。
# 這裡若再呼叫 basicConfig 不會生效 —— 根 logger 已有 handler 時 basicConfig 是 no-op，
# 過去寫在這裡的 crawler_batched.log 因此一直是空檔。
logger = logging.getLogger(__name__)

# 每個日期區間一次最多取回的筆數；設為結果集上限，代表「該區間能拿的全部拿走」
MAX_PER_CALL = _RESULT_LIMIT


# ─── 工具函式 ─────────────────────────────────────────────────────────────────
def _db_count(label: str) -> int:
    """本批資料在 DB 的現有筆數。label 即寫入 keyword 欄的標記（見 build_label）。"""
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute(
        "SELECT COUNT(*) FROM crawl_records WHERE keyword LIKE ?",
        (f"%{label}%",),
    ).fetchone()[0]
    conn.close()
    return n


# 完全未指定任何條件時的標籤。匯出端看到它就代表「不要篩選」。
LABEL_ALL = "全部"


def build_label(
    keyword:       str,
    court:         str = "",
    case_types:    Tuple[str, ...] = (),
    judgment_type: str = "",
) -> str:
    """
    這批資料在 DB keyword 欄的標記。

    有關鍵字時沿用關鍵字（維持既有行為）；無關鍵字（僅法院／類別查詢）時，
    以條件組出標籤（例：「臺灣臺北地方法院-民事-判決」），
    否則 keyword 欄會是空字串，進度統計與 export_excel -k 都會失準。
    """
    if keyword:
        return keyword
    parts = [p for p in (court, *case_types, judgment_type) if p]
    return "-".join(parts) if parts else LABEL_ALL


def _fmt(d: date) -> str:
    return d.strftime("%Y/%m/%d")


def _generate_year_chunks(start_date: date, end_date: date) -> List[Tuple[date, date]]:
    """
    產生公曆年度對齊的 (chunk_start, chunk_end) 列表，由新到舊排序。
    只是初始種子，用來降低遞迴深度；真正的細分由 batched_crawl 依實際筆數決定。
    """
    chunks = []
    for year in range(end_date.year, start_date.year - 1, -1):
        cs = max(start_date, date(year, 1, 1))
        ce = min(end_date, date(year, 12, 31))
        if cs <= ce:
            chunks.append((cs, ce))
    return chunks


def _split_chunk(cs: date, ce: date) -> List[Tuple[date, date]]:
    """將 [cs, ce] 對半切分，回傳 [(較新的半段), (較舊的半段)]。"""
    span = (ce - cs).days + 1
    mid  = cs + timedelta(days=span // 2 - 1)
    return [(mid + timedelta(days=1), ce), (cs, mid)]


# ─── 主函式（深度優先，新 → 舊）──────────────────────────────────────────────
def batched_crawl(
    keyword: str,
    total_target: int,
    start_date: date,
    end_date: date,
    headless: bool,
    case_year_start: Optional[int] = None,
    case_year_end:   Optional[int] = None,
    court:         str = "",
    case_types:    Tuple[str, ...] = (),
    judgment_type: str = "",
    delay:         float = _DEFAULT_DELAY,
    pacer:         Optional[Pacer] = None,
    stats:         Optional[dict] = None,
) -> int:
    """
    依裁判日期遞迴細分爬取，嚴格由新到舊。

    使用 LIFO 堆疊：切分後把「較舊的半段」先推入、「較新的半段」後推入，
    於是較新的半段會先被彈出處理，確保整體順序始終是新 → 舊。

    case_year_start / case_year_end 為案號年度（民國年），與裁判日期是獨立維度，
    原樣傳給 search_and_crawl 由伺服器端年度分群處理。
    注意：切分決策看的是「未經案號年度過濾」的 total，
    因此即使過濾後筆數不多，原區間仍可能被切開 —— 多切幾次而已，正確性不受影響。

    court / case_types 是伺服器端查詢條件，會壓低每段的 total，切分次數因而變少。
    judgment_type（判決／裁定）則是清單頁過濾，不影響 total，也不影響切分決策。

    delay 為請求基礎間隔（秒）。整個批次共用同一個 Pacer —— 降速狀態必須跨區段延續，
    否則每段都從全速重新開始，被擋之後會反覆踩同一個坑。
    傳入 pacer 則沿用呼叫端的實例（例如跨月份連續爬取時延續降速狀態），此時忽略 delay。

    stats 若提供，會就地填入本次批次的結果，供呼叫端判斷是否完整：
      processed / total_new / failed_segments（未翻完的區段）/ truncated_days / pacer
    清單在批次過程中即時更新，即使中途被中斷，呼叫端仍能看到已發生的部分。
    """
    init_db()
    label = build_label(keyword, court, case_types, judgment_type)
    if total_target <= 0:
        total_target = 10 ** 9      # 0 或負數 = 不設上限，把日期範圍內全部爬完

    # 堆疊頂端 = 下一個要處理的段落。初始種子為年度對齊段落，
    # 最舊的年先推入，最新的年最後推入（故最先處理）。
    stack: List[Tuple[date, date]] = list(reversed(_generate_year_chunks(start_date, end_date)))
    total_new = 0
    processed = 0
    truncated_days: List[date] = []
    # 清單頁錯誤且復原失敗的區段 —— 這些區段沒有翻完，資料不完整，需要重跑
    failed_segments: List[Tuple[date, date, int]] = []
    # 單日改用分群後，某個分群桶本身仍 >= 500 筆 → 該桶較舊的部分取不到
    truncated_buckets: List[str] = []
    if stats is not None:
        stats.update(processed=0, total_new=0, failed_segments=failed_segments,
                     truncated_days=truncated_days, truncated_buckets=truncated_buckets)

    logger.info(
        "開始批次爬取：keyword=%r  label=%r  court=%s  sys=%s  type=%s  "
        "target=%d  初始段數=%d  range=[%s → %s]  單段上限=%d",
        keyword, label, court or "*", "/".join(case_types) or "*", judgment_type or "*",
        total_target, len(stack), _fmt(start_date), _fmt(end_date), MAX_PER_CALL,
    )

    # 整個批次共用一個 WebDriver 與一個 Pacer（降速狀態要跨區段延續）
    driver = build_driver(headless)
    pacer  = pacer if pacer is not None else Pacer(delay=delay)
    try:
        while stack and total_new < total_target:
            cs, ce = stack.pop()
            processed += 1
            span_days = (ce - cs).days + 1
            single_day = span_days <= 1

            logger.info(
                "[段 %d] %s → %s (%d 天)  剩餘堆疊=%d  累計=%d/%d",
                processed, _fmt(cs), _fmt(ce), span_days, len(stack), total_new, total_target,
            )

            before = _db_count(label)
            # 只取到還差的筆數為止，避免最後一段大幅超收
            remaining = min(MAX_PER_CALL, total_target - total_new)
            res = search_and_crawl(
                keyword=keyword,
                max_results=remaining,
                headless=headless,
                start_date=_fmt(cs),
                end_date=_fmt(ce),
                driver=driver,
                case_year_start=case_year_start,
                case_year_end=case_year_end,
                court=court,
                case_types=tuple(case_types),
                judgment_type=judgment_type,
                keyword_label=label,
                pacer=pacer,
                # 單日已無法再細分 → 不再探測，直接把能拿的拿走
                skip_if_truncated=not single_day,
            )
            # Phase B 每 80 筆會重建 WebDriver session，舊的已被 quit
            # → 必須換用回傳的 driver，否則下一段會用到失效的 session
            driver = res.get("driver") or driver
            new = _db_count(label) - before

            truncated_buckets.extend(res.get("truncated_buckets") or [])
            errs = int(res.get("page_errors", 0) or 0)
            if errs:
                failed_segments.append((cs, ce, errs))
                logger.error(
                    "  ✗ %s → %s 有 %d 次清單頁錯誤無法復原 —— 此區段資料不完整",
                    _fmt(cs), _fmt(ce), errs,
                )
            total_new += new

            if res["truncated"] and not single_day:
                # 該區間超過 500 筆 → 對半切，較新的半段先處理
                newer, older = _split_chunk(cs, ce)
                stack.append(older)
                stack.append(newer)
                logger.info(
                    "  ↳ total=%s >= %d，切分為 %s→%s（先）與 %s→%s（後）",
                    res["total"], _RESULT_LIMIT,
                    _fmt(newer[0]), _fmt(newer[1]), _fmt(older[0]), _fmt(older[1]),
                )
                continue

            if res["truncated"] and single_day:
                truncated_days.append(cs)
                logger.warning(
                    "  ⚠ %s 單日即有 %s 筆（>= %d），日期已無法再細分 → "
                    "已改用%s逐桶收集，取得 %d 筆",
                    _fmt(cs), res["total"], _RESULT_LIMIT,
                    "案號年度分群" if court else "法院分群", res["collected"],
                )

            logger.info(
                "  ✓ total=%s  下載=%d  新增=%d  累計=%d/%d",
                res["total"], res["collected"], new, total_new, total_target,
            )
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    logger.info("=" * 60)
    logger.info("批次爬取完成。處理段數=%d  總新增=%d 筆", processed, total_new)
    logger.info("請求節奏：%s", pacer.summary())
    logger.info("=" * 60)
    if truncated_days:
        logger.warning(
            "以下 %d 個單日超過 %d 筆上限，資料可能不完整：%s",
            len(truncated_days), _RESULT_LIMIT,
            ", ".join(_fmt(d) for d in truncated_days[:10]),
        )
    if truncated_buckets:
        logger.warning(
            "以下 %d 個分群桶本身即達 %d 筆上限，較舊的部分取不到（重跑無法補救）：\n%s",
            len(truncated_buckets), _RESULT_LIMIT,
            "\n".join(f"  {b}" for b in truncated_buckets),
        )
    if failed_segments:
        logger.error(
            "以下 %d 個區段因清單頁錯誤未翻完，請以相同條件重跑這些日期：\n%s",
            len(failed_segments),
            "\n".join(f"  --start-date {_fmt(a)} --end-date {_fmt(b)}（{n} 次錯誤）"
                      for a, b, n in failed_segments),
        )
    if stats is not None:
        stats.update(processed=processed, total_new=total_new, pacer=pacer.summary())
    return total_new


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="自動分段批次爬蟲（依裁判日期遞迴細分，由新到舊，突破 500 筆上限）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python crawl_batched.py 借名登記 -n 2000
  python crawl_batched.py 借名登記 -n 1000 --start-year 2018 --end-year 2023
  python crawl_batched.py 借名登記 -n 500  --start-date 2024/01/01 --end-date 2025/04/28
  python crawl_batched.py -n 0 --court 臺灣臺北地方法院 --case-type 民事 \\
                          --judgment-type 判決 --start-date 2025/01/01 --end-date 2025/12/31
        """,
    )
    ap.add_argument("keyword", nargs="?", default="",
                    help="搜尋關鍵字（指定 --court／--case-type 時可省略）")
    ap.add_argument(
        "-n", "--num", type=int, default=1000,
        help="目標筆數（預設: 1000；0 = 不設上限，把範圍內全部爬完）",
    )
    ap.add_argument(
        "--start-year", type=int, default=2015,
        help="裁判日期起始年（西元，預設: 2015，可被 --start-date 覆蓋）",
    )
    ap.add_argument(
        "--end-year", type=int, default=None,
        help="裁判日期結束年（西元，預設: 今年，可被 --end-date 覆蓋）",
    )
    ap.add_argument(
        "--start-date", default="",
        help="裁判日期起 YYYY/MM/DD（西元；覆蓋 --start-year）",
    )
    ap.add_argument(
        "--end-date", default="",
        help="裁判日期迄 YYYY/MM/DD（西元；覆蓋 --end-year）",
    )
    ap.add_argument(
        "--case-year-start", type=int, default=None,
        help="案號年度起（民國年，如 113）；與裁判日期是不同維度，伺服器端分群",
    )
    ap.add_argument(
        "--case-year-end", type=int, default=None,
        help="案號年度迄（民國年，如 115）；與裁判日期是不同維度，伺服器端分群",
    )
    ap.add_argument(
        "--court", default="",
        help="裁判法院（名稱或代碼，如「臺灣臺北地方法院」或 TPD），伺服器端篩選",
    )
    ap.add_argument(
        "--case-type", default="",
        help="案件類別，逗號分隔（憲法/民事/刑事/行政/懲戒），伺服器端篩選",
    )
    ap.add_argument(
        "--judgment-type", default="", choices=("", *_JUDGMENT_TYPES),
        help="裁判種類（判決／裁定）；於結果清單頁過濾，下載前就濾掉",
    )
    ap.add_argument(
        "--delay", type=float, default=_DEFAULT_DELAY,
        help="請求基礎間隔秒數（預設: 1.0）。遇錯自動加倍降速、連續失敗長暫停；"
             "長時間爬取建議 1.5~2",
    )
    ap.add_argument(
        "--no-headless", action="store_true",
        help="顯示瀏覽器視窗（debug 用）",
    )
    args = ap.parse_args()

    case_types = tuple(t.strip() for t in args.case_type.split(",") if t.strip())
    if not args.keyword and not args.court and not case_types:
        ap.error("請至少指定 關鍵字、--court 或 --case-type 其中之一")

    today = date.today()

    try:
        sd, ed = resolve_date_range(
            args.start_date, args.end_date, args.start_year, args.end_year, today)
    except ValueError as exc:
        ap.error(str(exc))

    total = batched_crawl(
        keyword=args.keyword,
        total_target=args.num,
        start_date=sd,
        end_date=ed,
        headless=not args.no_headless,
        case_year_start=args.case_year_start,
        case_year_end=args.case_year_end,
        court=args.court,
        case_types=case_types,
        judgment_type=args.judgment_type,
        delay=args.delay,
    )
    print(f"\n完成！共新增 {total} 筆裁判書至資料庫。")
