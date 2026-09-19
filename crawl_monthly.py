# -*- coding: utf-8 -*-
"""
逐月爬取並一次匯出 —— 長時間爬取（例如整年）用的執行腳本。

為什麼不直接用 crawl_batched.py 跑整個區間：
  台北地院民事判決實測每個月約需 1 小時，整年約 10 小時，而批次爬取本身沒有斷點續爬 ——
  中途斷掉（電腦睡眠、重開機、斷網）就得從頭重翻所有清單頁。
  本腳本以「月」為單位執行，並把每個月的結果記在狀態檔（JSON）：
    - 已完成的月份，重跑時自動跳過
    - 有「清單頁錯誤未復原」的月份不算完成，重跑時會再試一次
    - 全部月份跑完才解析並匯出成「一份」Excel
  重跑同一個月時，已下載的裁判書會自動跳過，只有清單頁需要重翻。

匯出是依「條件」而非資料標籤篩選（法院＋案件類別＋裁判種類＋月份），
所以先前被其他批次（例如「借名登記」）抓過的同條件判決也會一併匯出。

用法:
    python crawl_monthly.py                       # 預設：2025 年 3~12 月臺灣臺北地方法院民事判決
    python crawl_monthly.py --dry-run             # 只顯示計畫與目前進度，不連網
    python crawl_monthly.py --months 3-7          # 只跑 3~7 月
    python crawl_monthly.py --export-only --export-all   # 不爬，直接匯出全年
"""

import argparse
import io
import json
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import crawler
from crawl_batched import batched_crawl, build_label
from crawler import Pacer, _COURT_CODES, _JUDGMENT_TYPES, _court_code

# 只用於 --dry-run 的預估。2 月未加全文粗篩時實測 55 分鐘／月；加上粗篩後清單頁
# 大幅減少（實測單日 976 → 55 筆），保守估每月 25 分鐘。開跑後會改依實測顯示剩餘時間。
_MINUTES_PER_MONTH_ESTIMATE = 25
# 連續幾個月出現例外（非清單頁錯誤，例如斷網、瀏覽器起不來）就停止，避免一路空轉
_MAX_CONSECUTIVE_ERRORS = 2


# ─── 月份處理 ─────────────────────────────────────────────────────────────────
def parse_months(spec: str) -> List[int]:
    """'3-12' / '3,5,7-9' → 排序去重的月份清單。格式錯誤拋 ValueError。"""
    months = set()
    for part in (p.strip() for p in str(spec).split(",")):
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,2})(?:\s*-\s*(\d{1,2}))?", part)
        if not m:
            raise ValueError(f"月份格式錯誤：{part!r}（例：3-12 或 3,5,7-9）")
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if not (1 <= lo <= 12 and 1 <= hi <= 12) or lo > hi:
            raise ValueError(f"月份超出範圍或順序顛倒：{part!r}")
        months.update(range(lo, hi + 1))
    if not months:
        raise ValueError("至少要指定一個月份")
    return sorted(months)


def month_bounds(year: int, month: int) -> Tuple[date, date]:
    """該月第一天與最後一天。"""
    start = date(year, month, 1)
    nxt   = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, nxt - timedelta(days=1)


def month_key(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


# ─── 狀態檔 ───────────────────────────────────────────────────────────────────
def default_state_path(label: str, year: int) -> str:
    safe = re.sub(r'[\\/*?:"<>|\s]', "_", label)
    return f"crawl_state_{safe}_{year}.json"


def load_state(path: str) -> Dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        state.setdefault("months", {})
        return state
    return {"months": {}}


def save_state(path: str, state: Dict) -> None:
    """先寫暫存檔再取代，避免寫到一半被中斷而把狀態檔弄壞。"""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ─── 防止系統睡眠（僅 Windows）──────────────────────────────────────────────
@contextmanager
def keep_awake(enabled: bool = True):
    """
    執行期間要求 Windows 不要進入閒置睡眠；程序結束（含被中斷）即自動恢復原本設定。
    不會修改電源計畫。注意：闔上筆電蓋子仍可能依「蓋上蓋子時」的設定而睡眠。
    """
    active = False
    if enabled and sys.platform == "win32":
        try:
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            active = bool(ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
        except Exception:
            active = False
    try:
        yield active
    finally:
        if active:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


# ─── 逐月爬取 ─────────────────────────────────────────────────────────────────
def crawl_months(
    year:          int,
    months:        List[int],
    court:         str,
    case_types:    Tuple[str, ...],
    judgment_type: str,
    delay:         float,
    state_path:    str,
    headless:      bool = True,
    force:         bool = False,
) -> Dict:
    """
    依序爬取各月份，每個月結束就更新狀態檔。回傳最新的狀態。

    月份狀態：
      done         完整跑完，重跑時跳過
      incomplete   跑完但有區段清單頁錯誤未復原，重跑時再試
      error        發生例外（斷網、瀏覽器異常等），重跑時再試
      interrupted  被 Ctrl+C 中斷，重跑時再試
    """
    state = load_state(state_path)
    # 整個執行共用一個 Pacer：上個月末被伺服器降速的狀態延續到下個月
    pacer = Pacer(delay=delay)
    todo  = [m for m in months
             if force or state["months"].get(month_key(year, m), {}).get("status") != "done"]
    skipped = [m for m in months if m not in todo]
    if skipped:
        print(f"  已完成、略過：{', '.join(f'{m} 月' for m in skipped)}")

    run_started = time.time()
    consecutive_errors = 0
    for i, m in enumerate(todo, start=1):
        key = month_key(year, m)
        start, end = month_bounds(year, m)
        print(f"\n{'=' * 60}\n  [{i}/{len(todo)}] {key}  （{start} ~ {end}）\n{'=' * 60}")

        record: Dict = {
            "status": "running",
            "range": [start.isoformat(), end.isoformat()],
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        state["months"][key] = record
        save_state(state_path, state)

        stats: Dict = {}
        t0 = time.time()
        try:
            new = batched_crawl(
                keyword="", total_target=0,
                start_date=start, end_date=end, headless=headless,
                court=court, case_types=case_types, judgment_type=judgment_type,
                pacer=pacer, stats=stats,
            )
        except KeyboardInterrupt:
            record.update(status="interrupted",
                          elapsed_min=round((time.time() - t0) / 60, 1))
            save_state(state_path, state)
            print(f"\n  ⏸ 已中斷，{key} 標記為未完成。重新執行同一個指令即可從這個月接續。")
            raise
        except Exception as exc:                      # noqa: BLE001 — 記錄後繼續下個月
            consecutive_errors += 1
            record.update(status="error", error=f"{type(exc).__name__}: {exc}",
                          elapsed_min=round((time.time() - t0) / 60, 1))
            save_state(state_path, state)
            print(f"  ✗ {key} 發生錯誤：{exc}")
            if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                print(f"  連續 {consecutive_errors} 個月發生錯誤，先停止（可能是斷網或瀏覽器問題）。"
                      "排除後重新執行同一個指令即可接續。")
                break
            continue

        consecutive_errors = 0
        failed = stats.get("failed_segments") or []
        record.update(
            status="done" if not failed else "incomplete",
            new=new,
            segments=stats.get("processed", 0),
            failed_segments=[[a.isoformat(), b.isoformat(), n] for a, b, n in failed],
            truncated_days=[d.isoformat() for d in stats.get("truncated_days") or []],
            # 分群桶本身即達 500 上限：重跑救不回，只能記錄下來讓使用者知道哪裡不完整
            truncated_buckets=list(stats.get("truncated_buckets") or []),
            pacer=stats.get("pacer", ""),
            finished_at=datetime.now().isoformat(timespec="seconds"),
            elapsed_min=round((time.time() - t0) / 60, 1),
        )
        save_state(state_path, state)

        done_n = i
        avg    = (time.time() - run_started) / done_n
        eta    = avg * (len(todo) - done_n) / 60
        buckets = record["truncated_buckets"]
        mark   = "✓" if not (failed or buckets) else "⚠"
        print(f"  {mark} {key} 新增 {new} 筆，耗時 {record['elapsed_min']} 分鐘"
              + (f"；{len(failed)} 個區段未翻完，重跑時會再試" if failed else "")
              + (f"｜剩餘約 {eta:.0f} 分鐘" if done_n < len(todo) else ""))
        for b in buckets:
            print(f"    ⚠ 分群桶達 500 上限、較舊部分取不到：{b}")

    return state


# ─── 匯出 ─────────────────────────────────────────────────────────────────────
def _court_full_name(court: str) -> str:
    code = _court_code(court)
    if not code:
        return court
    return {v: k for k, v in _COURT_CODES.items()}[code]


def select_rows(
    db_path:       str,
    year:          int,
    months:        List[int],
    court:         str,
    case_types:    Tuple[str, ...],
    judgment_type: str,
    label:         str,
) -> List[Dict]:
    """
    依條件從 judgments 取出要匯出的資料，依裁判日期排序。

    條件：(本批標籤) 或 (法院＋案件類別＋裁判種類 皆符合)，且裁判日期落在指定月份。
    後者讓先前被其他批次標籤佔住的同條件判決也能被匯出。
    """
    conds, params = [], []
    if court:
        conds.append("court = ?")
        params.append(_court_full_name(court))
    if case_types:
        conds.append("(" + " OR ".join("case_number LIKE ?" for _ in case_types) + ")")
        params.extend(f"%{ct}%" for ct in case_types)
    if judgment_type:
        conds.append("judgment_type = ?")
        params.append(judgment_type)
    match = " AND ".join(conds) if conds else "0"

    keys = [month_key(year, m) for m in months]
    sql = (f"SELECT * FROM judgments "
           f"WHERE (keyword = ? OR ({match})) "
           f"AND substr(judgment_date, 1, 7) IN ({','.join('?' for _ in keys)}) "
           f"ORDER BY judgment_date, case_number")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, [label, *params, *keys])]
    finally:
        conn.close()


def _span_label(covered: List[int]) -> str:
    """
    檔名用的月份標記，依「實際有資料」的月份而非「要求匯出」的月份。

    `--export-all` 要求 1~12 月，但若 1、2 月從未爬過，檔名叫「全年」會誤導——
    三個月後再打開這個檔，沒有人會記得它其實只有 3~12 月。
    連續的月份合併為區間，不連續的以 + 串接：[1, 3, 4, 12] → "01+03-04+12"。
    """
    if not covered:
        return "無資料"
    if covered == list(range(1, 13)):
        return "全年"
    groups: List[Tuple[int, int]] = []
    start = prev = covered[0]
    for m in covered[1:]:
        if m == prev + 1:
            prev = m
            continue
        groups.append((start, prev))
        start = prev = m
    groups.append((start, prev))
    return "+".join(f"{a:02d}" if a == b else f"{a:02d}-{b:02d}" for a, b in groups)


def export_months(
    year:          int,
    months:        List[int],
    court:         str,
    case_types:    Tuple[str, ...],
    judgment_type: str,
    label:         str,
    output:        str = "",
    full_text:     bool = False,
) -> Optional[str]:
    """解析尚未解析的紀錄，再把指定月份匯出成一份 Excel。回傳檔名；無資料回傳 None。"""
    import export_excel
    from html_parser import parse_all_unparsed

    parsed = parse_all_unparsed()
    print(f"  解析新紀錄：{parsed} 筆")

    rows = select_rows(export_excel.DB_PATH, year, months, court, case_types,
                       judgment_type, label)
    per_month = {month_key(year, m): 0 for m in months}
    for r in rows:
        k = (r.get("judgment_date") or "")[:7]
        if k in per_month:
            per_month[k] += 1
    print("  各月筆數：")
    for k, n in per_month.items():
        print(f"    {k}: {n:5d}" + ("   ⚠ 沒有資料" if n == 0 else ""))
    if not rows:
        print("  [WARN] 沒有符合條件的資料，未產生 Excel。")
        return None

    if not output:
        safe = re.sub(r'[\\/*?:"<>|\s]', "_", label)
        covered = [m for m in months if per_month[month_key(year, m)]]
        output = (f"judgments_{safe}_{year}_{_span_label(covered)}"
                  f"_{datetime.now():%Y%m%d_%H%M%S}.xlsx")

    ok = export_excel.export_to_excel(rows, output, include_full_text=full_text)
    if not ok:
        print("  [WARN] 匯出失敗。")
        return None
    print(f"  ✓ 匯出 {len(rows)} 筆 → {output}")
    return output


# ─── 計畫預覽 ─────────────────────────────────────────────────────────────────
def print_plan(year, months, label, state_path, delay, db_path, court, case_types,
               judgment_type) -> None:
    state = load_state(state_path)
    todo = 0
    print(f"  狀態檔：{state_path}{'' if os.path.exists(state_path) else '（尚未建立）'}")
    print(f"  {'月份':8s} {'日期範圍':25s} {'狀態':12s} {'DB 現有筆數':>10s}")
    counts: Dict[str, int] = {}
    if os.path.exists(db_path):
        try:
            for r in select_rows(db_path, year, months, court, case_types, judgment_type, label):
                k = (r.get("judgment_date") or "")[:7]
                counts[k] = counts.get(k, 0) + 1
        except sqlite3.Error:
            pass
    for m in months:
        k = month_key(year, m)
        s, e = month_bounds(year, m)
        st = state["months"].get(k, {}).get("status", "pending")
        todo += st != "done"
        print(f"  {k:8s} {str(s) + ' ~ ' + str(e):25s} {st:12s} {counts.get(k, 0):>10d}")
    print(f"\n  待爬取 {todo} 個月，預估約 {todo * _MINUTES_PER_MONTH_ESTIMATE / 60:.1f} 小時"
          f"（保守估計每月 {_MINUTES_PER_MONTH_ESTIMATE} 分鐘；--delay {delay}；"
          "開跑後會依實測顯示剩餘時間）")


# ─── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        description="逐月爬取裁判書（可中斷後接續），全部完成後匯出成一份 Excel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python crawl_monthly.py                              # 2025 年 3~12 月臺北地院民事判決
  python crawl_monthly.py --dry-run                    # 預覽計畫與進度，不連網
  python crawl_monthly.py --months 8-12                # 只跑 8~12 月
  python crawl_monthly.py --export-only --export-all   # 不爬，匯出全年一份 Excel
        """,
    )
    ap.add_argument("--year", type=int, default=2025, help="西元年（預設: 2025，即民國 114 年）")
    ap.add_argument("--months", default="3-12", help="月份，如 3-12 或 3,5,7-9（預設: 3-12）")
    ap.add_argument("--court", default="臺灣臺北地方法院", help="裁判法院（預設: 臺灣臺北地方法院）")
    ap.add_argument("--case-type", default="民事", help="案件類別，逗號分隔（預設: 民事）")
    ap.add_argument("--judgment-type", default="判決", choices=("", *_JUDGMENT_TYPES),
                    help="裁判種類（預設: 判決；空字串 = 判決與裁定都要）")
    ap.add_argument("--delay", type=float, default=1.5,
                    help="請求基礎間隔秒數（預設: 1.5）；遇錯自動降速")
    ap.add_argument("--state", default="", help="狀態檔路徑（預設依條件與年份自動命名）")
    ap.add_argument("--force", action="store_true", help="忽略狀態檔，已完成的月份也重跑")
    ap.add_argument("--dry-run", action="store_true", help="只顯示計畫與目前進度，不連網")
    ap.add_argument("--export-only", action="store_true", help="不爬取，直接解析並匯出")
    ap.add_argument("--no-export", action="store_true", help="只爬取，不匯出")
    ap.add_argument("--export-all", action="store_true",
                    help="匯出該年 1~12 月全部資料，而非只有 --months 指定的月份")
    ap.add_argument("-o", "--output", default="", help="輸出 Excel 檔名（預設自動命名）")
    ap.add_argument("--full-text", action="store_true", help="Excel 含全文欄位")
    ap.add_argument("--allow-sleep", action="store_true",
                    help="不阻止 Windows 睡眠（預設執行期間會保持喚醒）")
    ap.add_argument("--no-headless", action="store_true", help="顯示瀏覽器視窗（debug 用）")
    args = ap.parse_args(argv)

    try:
        months = parse_months(args.months)
    except ValueError as exc:
        ap.error(str(exc))
    case_types = tuple(t.strip() for t in args.case_type.split(",") if t.strip())
    if args.court and not _court_code(args.court):
        ap.error(f"無法辨識的法院：{args.court}")

    label      = build_label("", args.court, case_types, args.judgment_type)
    state_path = args.state or default_state_path(label, args.year)
    export_m   = list(range(1, 13)) if args.export_all else months

    print("=" * 60)
    print("  逐月爬取")
    print("=" * 60)
    print(f"  條件    : {label}")
    print(f"  年份    : {args.year}（民國 {args.year - 1911} 年）")
    print(f"  月份    : {', '.join(str(m) for m in months)}")
    print(f"  請求間隔: {args.delay} 秒")
    print("=" * 60)

    if args.dry_run:
        print_plan(args.year, months, label, state_path, args.delay, crawler.DB_PATH,
                   args.court, case_types, args.judgment_type)
        return 0

    if not args.export_only:
        with keep_awake(not args.allow_sleep) as awake:
            if awake:
                print("  已要求 Windows 在執行期間保持喚醒（闔上筆電蓋子仍可能睡眠）")
            try:
                state = crawl_months(args.year, months, args.court, case_types,
                                     args.judgment_type, args.delay, state_path,
                                     headless=not args.no_headless, force=args.force)
            except KeyboardInterrupt:
                return 130

        pending = [k for k in (month_key(args.year, m) for m in months)
                   if state["months"].get(k, {}).get("status") != "done"]
        print(f"\n{'=' * 60}")
        if pending:
            print(f"  ⚠ 以下月份尚未完整：{', '.join(pending)}")
            print("    重新執行同一個指令即可只補跑這些月份。")
        else:
            print("  ✓ 所有月份皆已完整爬取")

    if args.no_export:
        return 0

    print(f"\n{'=' * 60}\n  匯出\n{'=' * 60}")
    out = export_months(args.year, export_m, args.court, case_types, args.judgment_type,
                        label, output=args.output, full_text=args.full_text)
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
