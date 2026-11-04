# -*- coding: utf-8 -*-
"""
線上煙霧測試 —— 會連線司法院裁判書系統並開啟 Chrome，故「不」納入 unittest 自動測試。

用途：改動查詢表單相關程式碼、或懷疑對方網站改版時，手動跑一次確認端到端仍可用。
所有資料寫入暫存 DB 與暫存目錄，不會污染 judgments.db 與 html_cache/。

    python tests/live_check.py           # 全部檢查（約 2-4 分鐘）
    python tests/live_check.py --quick   # 只跑查詢條件相關的檢查（不下載裁判書）
"""

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))

import crawler  # noqa: E402
from crawler import (  # noqa: E402
    _RESULT_LIMIT, _ad_search, _collect_year_links, _get_results_list_url,
    _parse_case_rows, build_driver, crawl_detail_page, _is_html_complete,
)

PASS, FAIL = "  [PASS]", "  [FAIL]"
_results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok))
    print(f"{PASS if ok else FAIL} {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="略過下載裁判書的檢查")
    ap.add_argument("--no-headless", action="store_true")
    args = ap.parse_args()

    tmp = tempfile.TemporaryDirectory()
    crawler.DB_PATH  = os.path.join(tmp.name, "live.db")
    crawler.HTML_DIR = os.path.join(tmp.name, "html")
    os.makedirs(crawler.HTML_DIR, exist_ok=True)
    crawler.init_db()

    driver = build_driver(headless=not args.no_headless)
    try:
        # ── 1. 舊功能：關鍵字 + 裁判日期 ─────────────────────────────
        url_kw, total_kw = _ad_search(driver, "借名登記", "2025/01/01", "2025/01/31")
        check("關鍵字 + 裁判日期查詢可取得結果頁",
              bool(url_kw) and total_kw is not None, f"total={total_kw}")

        # ── 2. 舊功能：日期條件確實生效（區間變小，筆數應下降）───────
        _, total_day = _ad_search(driver, "借名登記", "2025/01/01", "2025/01/02")
        check("裁判日期區間縮小後筆數下降（伺服器端篩選生效）",
              total_day is not None and total_kw is not None and total_day < total_kw,
              f"{total_kw} → {total_day}")

        # ── 3. 新功能：法院條件 ──────────────────────────────────────
        _, total_all = _ad_search(driver, "", "2025/01/08", "2025/01/08")
        _, total_tpd = _ad_search(driver, "", "2025/01/08", "2025/01/08", "TPD")
        check("指定法院後筆數下降（jud_court 生效）",
              total_all is not None and total_tpd is not None and total_tpd < total_all,
              f"所有法院 {total_all} → 臺北地院 {total_tpd}")

        # ── 4. 新功能：案件類別 ──────────────────────────────────────
        url_v, total_v = _ad_search(
            driver, "", "2025/01/08", "2025/01/08", "臺灣臺北地方法院", ("民事",))
        check("指定案件類別後筆數下降（jud_sys 生效）",
              total_v is not None and total_tpd is not None and total_v < total_tpd,
              f"全類別 {total_tpd} → 民事 {total_v}")

        # ── 5. 新功能：法院名稱寫法（中文全名）與代碼等價 ────────────
        _, total_code = _ad_search(
            driver, "", "2025/01/08", "2025/01/08", "TPD", ("民事",))
        check("法院用中文全名與用代碼查詢結果一致",
              total_code == total_v, f"{total_v} vs {total_code}")

        # ── 6. 結果清單頁：法院／裁判種類正確 ────────────────────────
        list_url = _get_results_list_url(driver)
        driver.get(list_url)
        time.sleep(2.5)
        rows = _parse_case_rows(driver)
        check("結果清單可解析出案件列", bool(rows), f"{len(rows)} 筆/頁")
        check("清單各筆均為指定法院",
              all("臺北地方法院" in r["case_number"] for r in rows))
        judgments = [r for r in rows if "判決" in r["case_number"]]
        rulings   = [r for r in rows if "裁定" in r["case_number"]]
        check("清單同時含判決與裁定（--judgment-type 才有意義）",
              bool(judgments) and bool(rulings),
              f"判決 {len(judgments)}／裁定 {len(rulings)}")

        # ── 6b. 清單頁可用頁碼定址（錯誤頁復原機制的前提）─────────────
        from crawler import _list_page_error, _page_url
        check("正常清單頁不會被誤判為錯誤頁", _list_page_error(driver) == "",
              _list_page_error(driver) or "(乾淨)")
        driver.get(_page_url(list_url, 2))
        time.sleep(2.0)
        page2 = _parse_case_rows(driver)
        check("清單頁可用 &page=N 直接定址（復原時跳回中斷頁靠它）",
              bool(page2) and {r["url"] for r in page2} != {r["url"] for r in rows},
              f"第 2 頁 {len(page2)} 筆")

        # ── 7. 舊功能：案號年度分群連結仍存在 ────────────────────────
        _ad_search(driver, "", "2025/01/08", "2025/01/08", "臺灣臺北地方法院", ("民事",))
        year_links = _collect_year_links(driver)
        check("摘要頁仍提供案號年度分群連結（gy=jyear）",
              bool(year_links), f"{len(year_links)} 個年度桶")

        # ── 8. 端到端：judgment_type 過濾 + 下載 ─────────────────────
        if not args.quick:
            res = crawler.search_and_crawl(
                keyword="", max_results=3, start_date="2025/01/08", end_date="2025/01/08",
                court="臺灣臺北地方法院", case_types=("民事",), judgment_type="判決",
                keyword_label="LIVECHECK", driver=driver,
            )
            check("search_and_crawl 取得指定筆數", res["collected"] == 3, str(res))

            import sqlite3
            conn = sqlite3.connect(crawler.DB_PATH)
            saved = conn.execute(
                "SELECT case_number, html_file, keyword FROM crawl_records").fetchall()
            conn.close()
            check("下載後有寫入 DB", bool(saved), f"{len(saved)} 筆")
            check("僅收錄判決（裁定已在下載前濾掉）",
                  bool(saved) and all("判決" in cn for cn, _f, _k in saved),
                  "; ".join(cn[-12:] for cn, _f, _k in saved))
            check("keyword 欄寫入標籤",
                  bool(saved) and all(k == "LIVECHECK" for _c, _f, k in saved))
            check("下載的 HTML 為完整裁判書（非 stub）",
                  bool(saved) and all(_is_html_complete(f) for _c, f, _k in saved))

            # 解析一份下載結果，確認 parser 仍吃得下現行版型
            if saved:
                from html_parser import parse_html
                html = Path(saved[0][1]).read_text(encoding="utf-8")
                data = parse_html(html, crawl_id=1, case_number_hint=saved[0][0])
                check("解析下載的裁判書可取得主文與法院",
                      bool(data["verdict"]) and "法院" in data["court"],
                      f"{data['court']} / 主文 {len(data['verdict'])} 字")
                check("解析出的裁判種類為判決", data["judgment_type"] == "判決")

        # ── 9. 上限常數與實際頁面一致性提醒 ──────────────────────────
        check("單一結果集上限常數未被改動", _RESULT_LIMIT == 500, str(_RESULT_LIMIT))
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        tmp.cleanup()

    failed = [n for n, ok in _results if not ok]
    print("\n" + "=" * 60)
    print(f"  通過 {len(_results) - len(failed)} / {len(_results)}")
    if failed:
        print("  失敗項目：" + "、".join(failed))
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
