"""
完整流程執行腳本（Pipeline）

步驟 1: crawl_batched  — 自動分段爬取（突破 500 筆上限）
步驟 2: html_parser    — 解析 HTML，結構化存入 SQLite
步驟 3: export_excel   — 匯出 Excel

使用方式:
    python pipeline.py [關鍵字] [-n 筆數] [選項]

範例:
    python pipeline.py 借名登記 -n 1000
    python pipeline.py 借名登記 -n 2000 --start-year 2018
    python pipeline.py 借名登記 -n 500  --start-date 2024/01/01 --end-date 2025/04/28
    python pipeline.py 借名登記 -n 100  --no-headless
    python pipeline.py 借名登記 -n 1000 --skip-crawl   # 只重新解析 + 匯出
    python pipeline.py -n 0 --court 臺灣臺北地方法院 --case-type 民事 \
                       --judgment-type 判決 --start-date 2025/01/01 --end-date 2025/12/31
"""

import argparse
import re
import sys
import io
import time
from datetime import date, datetime
from typing import Optional, Tuple

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def run(
    keyword: str,
    max_results: int,
    headless: bool,
    output: str,
    full_text: bool,
    start_date: date,
    end_date: date,
    skip_crawl: bool,
    case_year_start: Optional[int] = None,
    case_year_end:   Optional[int] = None,
    court:         str = "",
    case_types:    Tuple[str, ...] = (),
    judgment_type: str = "",
    delay:         float = 1.0,
) -> None:
    sep = "=" * 60

    # 匯出與檔名都以 label 為準 —— 無關鍵字查詢時 DB 的 keyword 欄存的就是它。
    # 完全沒有條件時（例如只下 --skip-crawl）label 為 LABEL_ALL，代表匯出全部不篩選。
    from crawl_batched import LABEL_ALL, build_label
    label = build_label(keyword, court, case_types, judgment_type)
    export_filter = None if label == LABEL_ALL else label

    print(sep)
    print("  司法院裁判書自動化流程")
    print(sep)
    print(f"  關鍵字    : {keyword or '（未指定）'}")
    print(f"  法院      : {court or '所有法院'}")
    print(f"  案件類別  : {'/'.join(case_types) or '全部'}")
    print(f"  裁判種類  : {judgment_type or '全部'}")
    print(f"  資料標籤  : {label}" + ("（匯出不篩選）" if export_filter is None else ""))
    print(f"  目標筆數  : {max_results if max_results > 0 else '不設上限'}")
    print(f"  日期範圍  : {start_date.strftime('%Y/%m/%d')} → {end_date.strftime('%Y/%m/%d')}")
    print(f"  請求間隔  : {delay} 秒（遇錯自動降速）")
    print(f"  無頭模式  : {headless}")
    if skip_crawl:
        print("  ⚠ --skip-crawl：跳過爬取，直接解析 + 匯出")
    print(sep)

    # ── Step 1: 爬取（自動分段）────────────────────────────────────
    if not skip_crawl:
        print(f"\n【步驟 1/3】分段爬取裁判書…")
        t0 = time.time()
        try:
            from crawl_batched import batched_crawl
            crawled = batched_crawl(
                keyword=keyword,
                total_target=max_results,
                start_date=start_date,
                end_date=end_date,
                headless=headless,
                case_year_start=case_year_start,
                case_year_end=case_year_end,
                court=court,
                case_types=case_types,
                judgment_type=judgment_type,
                delay=delay,
            )
        except Exception as exc:
            print(f"  [ERROR] 爬取失敗: {exc}")
            sys.exit(1)
        print(f"  完成：新增 {crawled} 筆  ({time.time()-t0:.1f}s)")
    else:
        print(f"\n【步驟 1/3】已跳過（--skip-crawl）")

    # ── Step 2: 解析 ──────────────────────────────────────────────
    print(f"\n【步驟 2/3】解析 HTML 並結構化…")
    t0 = time.time()
    try:
        from html_parser import parse_all_unparsed
        parsed = parse_all_unparsed()
    except Exception as exc:
        print(f"  [ERROR] 解析失敗: {exc}")
        sys.exit(1)
    print(f"  完成：解析 {parsed} 筆  ({time.time()-t0:.1f}s)")

    # ── Step 3: 匯出 ──────────────────────────────────────────────
    safe_label = re.sub(r'[\\/*?:"<>|\s]', "_", label)
    out_path = output or f"judgments_{safe_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    print(f"\n【步驟 3/3】匯出 Excel → {out_path}…")
    t0 = time.time()
    try:
        from export_excel import fetch_judgments, export_to_excel
        # limit=0 → 匯出所有符合標籤的資料（不受 -n 限制）
        rows = fetch_judgments(limit=0, keyword=export_filter)
        if not rows:
            print("  [WARN] 資料庫無資料，跳過匯出。")
        else:
            ok = export_to_excel(rows, out_path, include_full_text=full_text)
            if ok:
                print(f"  完成：匯出 {len(rows)} 筆  ({time.time()-t0:.1f}s)")
            else:
                print("  [WARN] 匯出失敗。")
    except Exception as exc:
        print(f"  [ERROR] 匯出失敗: {exc}")

    print(f"\n{sep}")
    print("  全部流程完成！")
    print(sep)


if __name__ == "__main__":
    today = date.today()

    ap = argparse.ArgumentParser(
        description="司法院裁判書完整自動化流程（含自動分段突破 500 筆上限）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python pipeline.py 借名登記 -n 1000
  python pipeline.py 借名登記 -n 2000 --start-year 2018 --end-year 2023
  python pipeline.py 借名登記 -n 500  --start-date 2024/01/01 --end-date 2025/04/28
  python pipeline.py 借名登記 -n 1000 --skip-crawl        # 只重解析 + 匯出
  python pipeline.py -n 0 --court 臺灣臺北地方法院 --case-type 民事 \\
                     --judgment-type 判決 --start-date 2025/01/01 --end-date 2025/12/31
        """,
    )
    ap.add_argument("keyword", nargs="?", default="",
                    help="搜尋關鍵字（指定 --court／--case-type 時可省略）")
    ap.add_argument(
        "-n", "--num", type=int, default=100,
        help="目標爬取筆數（預設: 100；0 = 不設上限，把範圍內全部爬完）",
    )

    # 日期選項
    date_grp = ap.add_argument_group("裁判日期範圍（二擇一）")
    date_grp.add_argument(
        "--start-year", type=int, default=2015,
        help="裁判日期起始年（西元，預設: 2015）",
    )
    date_grp.add_argument(
        "--end-year", type=int, default=None,
        help="裁判日期結束年（西元，預設: 今年）",
    )
    date_grp.add_argument(
        "--start-date", default="",
        help="裁判日期起 YYYY/MM/DD（西元；覆蓋 --start-year）",
    )
    date_grp.add_argument(
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
    # 查詢條件（伺服器端）
    ap.add_argument("--court", default="",
                    help="裁判法院（名稱或代碼，如「臺灣臺北地方法院」或 TPD）")
    ap.add_argument("--case-type", default="",
                    help="案件類別，逗號分隔（憲法/民事/刑事/行政/懲戒）")
    ap.add_argument("--judgment-type", default="", choices=("", "判決", "裁定"),
                    help="裁判種類（判決／裁定）；於結果清單頁過濾，下載前就濾掉")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="請求基礎間隔秒數（預設: 1.0）；長時間爬取建議 1.5~2")

    # 其他選項
    ap.add_argument("--no-headless", action="store_true", help="顯示瀏覽器視窗（debug 用）")
    ap.add_argument("-o", "--output", default="",         help="輸出 Excel 檔名")
    ap.add_argument("--full-text",   action="store_true", help="Excel 含全文欄位")
    ap.add_argument(
        "--skip-crawl", action="store_true",
        help="跳過爬取步驟，直接重新解析 + 匯出（用於只更新解析結果時）",
    )
    args = ap.parse_args()

    case_types = tuple(t.strip() for t in args.case_type.split(",") if t.strip())
    if not args.keyword and not args.court and not case_types and not args.skip_crawl:
        ap.error("請至少指定 關鍵字、--court 或 --case-type 其中之一")

    # 解析日期。格式錯誤要在這裡就擋下來——不然不是噴 traceback，
    # 就是到了查詢表單才被静默忽略成「沒有日期範圍」。
    from crawler import resolve_date_range
    try:
        sd, ed = resolve_date_range(
            args.start_date, args.end_date, args.start_year, args.end_year, today)
    except ValueError as exc:
        ap.error(str(exc))

    run(
        keyword=args.keyword,
        max_results=args.num,
        headless=not args.no_headless,
        output=args.output,
        full_text=args.full_text,
        case_year_start=args.case_year_start,
        case_year_end=args.case_year_end,
        court=args.court,
        case_types=case_types,
        judgment_type=args.judgment_type,
        delay=args.delay,
        start_date=sd,
        end_date=ed,
        skip_crawl=args.skip_crawl,
    )
