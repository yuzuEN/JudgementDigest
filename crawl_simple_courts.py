"""
本機腳本：補爬各簡易庭的民事簡易判決（2022–2025）。

大多數簡易庭（臺北簡易庭 TPEV、板橋簡易庭 PCEV…）的判決不在一般「裁判書查詢」的索引裡，
只能從「簡易案件查詢」（Defaulte_AD.aspx）查到；crawler.py 遇到簡易庭名稱會自動改用那個查詢頁。
新竹、苗栗、基隆簡易庭沿用地院代碼，判決早就跟著地院一起爬到，不在這裡的清單內。

預設略過小額案件（北小、勞小…）：簡易庭判決約四分之三是小額，小額判決多半只有主文與
理由要領，分析用不到；略過可把爬取時間從約 11 天縮到 3 天左右。要連小額一起爬時加 --with-small-claims。

    python crawl_simple_courts.py                      # 開始／接續
    python crawl_simple_courts.py --dry-run            # 只看各簡易庭各年度還剩哪些月份
    python crawl_simple_courts.py --courts 臺北簡易庭,板橋簡易庭 --years 2024

中斷：隨時按 Ctrl+C，重跑同一個指令會從中斷的月份接續（進度記在 crawl_state_*簡易庭*_無小額.json）。
注意：執行期間不要切換 git 分支（子程序每次啟動都會讀當下的 crawler.py）。
"""
import argparse
import sys
import time

import crawl_monthly
from crawl_refresh import Interrupted, now, parse_new, record_count, run_child
from crawler import SIMPLE_ONLY_COURTS

YEARS          = (2025, 2024, 2023, 2022)
CASE_TYPE      = "民事"
JUDGMENT_TYPE  = "判決"
DELAY          = 1.5
MAX_ATTEMPTS   = 3
RETRY_WAIT_MIN = 10


def state_path(court: str, year: int, skip_small: bool) -> str:
    label = crawl_monthly.build_label("", court, (CASE_TYPE,), JUDGMENT_TYPE)
    path = crawl_monthly.default_state_path(label, year)
    return path.replace(".json", "_無小額.json") if skip_small else path


def pending_months(court: str, year: int, skip_small: bool) -> list:
    state = crawl_monthly.load_state(state_path(court, year, skip_small))
    return [m for m in range(1, 13)
            if state["months"].get(crawl_monthly.month_key(year, m), {}).get("status") != "done"]


def crawl_year(court: str, year: int, skip_small: bool) -> int:
    args = ["crawl_monthly.py",
            "--court", court, "--case-type", CASE_TYPE, "--judgment-type", JUDGMENT_TYPE,
            "--year", str(year), "--months", "1-12", "--delay", str(DELAY), "--no-export",
            "--state", state_path(court, year, skip_small)]
    if skip_small:
        args.append("--skip-small-claims")
    return run_child(args)


def main() -> int:
    ap = argparse.ArgumentParser(description="補爬各簡易庭的民事簡易判決")
    ap.add_argument("--dry-run", action="store_true", help="只顯示各簡易庭各年度待爬月份")
    ap.add_argument("--courts", default="", help="只爬這些簡易庭（逗號分隔），預設全部")
    ap.add_argument("--years", default="", help="只爬這些年份（逗號分隔），預設 2022–2025")
    ap.add_argument("--with-small-claims", action="store_true", help="連小額案件一起爬")
    args = ap.parse_args()

    courts = [c.strip() for c in args.courts.split(",") if c.strip()] or SIMPLE_ONLY_COURTS
    unknown = [c for c in courts if c not in SIMPLE_ONLY_COURTS]
    if unknown:
        ap.error(f"不在簡易庭清單內：{unknown}（可用：{'、'.join(SIMPLE_ONLY_COURTS)}）")
    years = tuple(int(y) for y in args.years.split(",") if y.strip()) or YEARS
    skip_small = not args.with_small_claims

    if args.dry_run:
        for court in courts:
            for year in years:
                pend = pending_months(court, year, skip_small)
                print(f"  {court} {year}：" + (f"待爬 {pend}" if pend else "✓ 完成"))
        return 0

    summary = {}
    start_n = record_count()
    with crawl_monthly.keep_awake(True):
        parse_new()
        for court in courts:
            for year in years:
                before = record_count()
                for attempt in range(1, MAX_ATTEMPTS + 1):
                    if not pending_months(court, year, skip_small):
                        break
                    print(f"\n##### [{now()}] {court} {year} 年 第 {attempt}/{MAX_ATTEMPTS} 次 #####",
                          flush=True)
                    crawl_year(court, year, skip_small)
                    parse_new()
                    if pending_months(court, year, skip_small) and attempt < MAX_ATTEMPTS:
                        print(f"\n[{now()}] {court} {year} 年尚有未完成月份，"
                              f"{RETRY_WAIT_MIN} 分鐘後重試……", flush=True)
                        time.sleep(RETRY_WAIT_MIN * 60)
                summary[(court, year)] = pending_months(court, year, skip_small)
                print(f"[{now()}] {court} {year}：本次新增 {record_count() - before} 筆", flush=True)

    print(f"\n{'=' * 60}\n  [{now()}] 總結：共新增 {record_count() - start_n} 筆\n{'=' * 60}")
    for (court, year), pend in summary.items():
        print(f"  ⚠ {court} {year}：以下月份未完成 {pend}，重新執行本腳本即可補跑" if pend
              else f"  ✓ {court} {year}：12 個月全部完成")
    return 1 if any(summary.values()) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, Interrupted):
        print(f"\n[{now()}] 已安全中斷。重新執行 python crawl_simple_courts.py 即可接續。")
        sys.exit(130)
