# -*- coding: utf-8 -*-
"""
crawl_monthly.py 的離線測試。

這支腳本存在的理由是「10 小時的任務要能中斷後接續，而且匯出要完整」，
所以重點在：月份切分正確、狀態檔讓已完成的月份被跳過、不完整的月份會重試、
中斷時不會把跑到一半的月份誤標為完成，以及匯出能撈到被其他標籤佔住的同條件判決。
"""

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import crawl_monthly  # noqa: E402
import html_parser  # noqa: E402
from crawl_monthly import (  # noqa: E402
    _span_label, crawl_months, export_months, load_state, month_bounds,
    parse_months, select_rows,
)

LABEL = "臺灣臺北地方法院-民事-判決"
COURT = "臺灣臺北地方法院"


class TestParseMonths(unittest.TestCase):
    def test_range(self):
        self.assertEqual(parse_months("3-12"), list(range(3, 13)))

    def test_mixed(self):
        self.assertEqual(parse_months("3,5,7-9"), [3, 5, 7, 8, 9])

    def test_dedup_and_sort(self):
        self.assertEqual(parse_months("9, 3-4, 3"), [3, 4, 9])

    def test_invalid(self):
        for bad in ("0", "13", "5-3", "abc", "", "3-"):
            with self.assertRaises(ValueError, msg=bad):
                parse_months(bad)


class TestMonthBounds(unittest.TestCase):
    def test_lengths(self):
        self.assertEqual(month_bounds(2025, 2), (date(2025, 2, 1), date(2025, 2, 28)))
        self.assertEqual(month_bounds(2024, 2), (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertEqual(month_bounds(2025, 4), (date(2025, 4, 1), date(2025, 4, 30)))
        self.assertEqual(month_bounds(2025, 12), (date(2025, 12, 1), date(2025, 12, 31)))


class _FakeBatched:
    """取代 batched_crawl：可指定某個月回報未翻完區段、丟例外或模擬 Ctrl+C。"""

    def __init__(self, incomplete=(), errors=(), interrupt=None):
        self.calls = []
        self.incomplete, self.errors, self.interrupt = set(incomplete), set(errors), interrupt

    def __call__(self, **kw):
        m = kw["start_date"].month
        self.calls.append(kw)
        if m == self.interrupt:
            raise KeyboardInterrupt
        if m in self.errors:
            raise RuntimeError("模擬斷網")
        stats = kw["stats"]
        stats["processed"] = 3
        stats["failed_segments"] = (
            [(kw["start_date"], kw["start_date"], 2)] if m in self.incomplete else [])
        stats["truncated_days"] = []
        stats["pacer"] = "fake"
        return 10


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state.json")
        self._orig = crawl_monthly.batched_crawl

    def tearDown(self):
        crawl_monthly.batched_crawl = self._orig
        self.tmp.cleanup()

    def run_months(self, fake, months, force=False):
        crawl_monthly.batched_crawl = fake
        with redirect_stdout(io.StringIO()):
            return crawl_months(2025, months, COURT, ("民事",), "判決", 1.5,
                                self.state, force=force)


class TestCrawlLoop(_Base):
    def test_calls_each_month_with_correct_range_and_filters(self):
        fake = _FakeBatched()
        self.run_months(fake, [3, 4, 12])
        ranges = [(c["start_date"], c["end_date"]) for c in fake.calls]
        self.assertEqual(ranges, [
            (date(2025, 3, 1), date(2025, 3, 31)),
            (date(2025, 4, 1), date(2025, 4, 30)),
            (date(2025, 12, 1), date(2025, 12, 31)),
        ])
        for c in fake.calls:
            self.assertEqual(c["court"], COURT)
            self.assertEqual(c["case_types"], ("民事",))
            self.assertEqual(c["judgment_type"], "判決")     # 只爬判決
            self.assertEqual(c["total_target"], 0)           # 不設上限
        # 跨月份共用同一個 Pacer，降速狀態才會延續
        self.assertEqual(len({id(c["pacer"]) for c in fake.calls}), 1)
        self.assertEqual(fake.calls[0]["pacer"].delay, 1.5)

    def test_state_marks_done_and_rerun_skips(self):
        self.run_months(_FakeBatched(), [3, 4])
        st = load_state(self.state)
        self.assertEqual(st["months"]["2025-03"]["status"], "done")
        self.assertEqual(st["months"]["2025-04"]["new"], 10)

        again = _FakeBatched()
        self.run_months(again, [3, 4, 5])
        self.assertEqual([c["start_date"].month for c in again.calls], [5])

    def test_incomplete_month_is_retried(self):
        self.run_months(_FakeBatched(incomplete={4}), [3, 4])
        st = load_state(self.state)
        self.assertEqual(st["months"]["2025-04"]["status"], "incomplete")
        self.assertEqual(st["months"]["2025-04"]["failed_segments"],
                         [["2025-04-01", "2025-04-01", 2]])

        again = _FakeBatched()
        self.run_months(again, [3, 4])
        self.assertEqual([c["start_date"].month for c in again.calls], [4])

    def test_force_reruns_done_months(self):
        self.run_months(_FakeBatched(), [3])
        again = _FakeBatched()
        self.run_months(again, [3], force=True)
        self.assertEqual(len(again.calls), 1)

    def test_interrupt_keeps_earlier_months_and_marks_current_unfinished(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_months(_FakeBatched(interrupt=5), [3, 4, 5, 6])
        st = load_state(self.state)
        self.assertEqual(st["months"]["2025-03"]["status"], "done")
        self.assertEqual(st["months"]["2025-04"]["status"], "done")
        self.assertEqual(st["months"]["2025-05"]["status"], "interrupted")
        self.assertNotIn("2025-06", st["months"])

        # 重跑從中斷的月份接續
        again = _FakeBatched()
        self.run_months(again, [3, 4, 5, 6])
        self.assertEqual([c["start_date"].month for c in again.calls], [5, 6])

    def test_single_error_continues_but_two_in_a_row_stops(self):
        fake = _FakeBatched(errors={4})
        self.run_months(fake, [3, 4, 5])
        self.assertEqual([c["start_date"].month for c in fake.calls], [3, 4, 5])
        self.assertEqual(load_state(self.state)["months"]["2025-04"]["status"], "error")

        os.remove(self.state)
        fake = _FakeBatched(errors={3, 4})
        self.run_months(fake, [3, 4, 5, 6])
        # 連續兩個月出錯就停，避免斷網時一路空轉把所有月份都標成錯誤
        self.assertEqual([c["start_date"].month for c in fake.calls], [3, 4])

    def test_state_file_is_valid_json_after_each_month(self):
        self.run_months(_FakeBatched(), [3])
        with open(self.state, encoding="utf-8") as f:
            json.load(f)
        self.assertFalse(os.path.exists(self.state + ".tmp"))


class TestSelectRows(unittest.TestCase):
    """匯出要依條件撈資料，不能只看標籤。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self._orig = html_parser.DB_PATH
        html_parser.DB_PATH = self.db
        html_parser.init_db()
        rows = [
            # (case_number, court, date, judgment_type, keyword)
            ("臺灣臺北地方法院 113 年度 訴 字第 1 號民事判決", COURT, "2025-03-05", "判決", LABEL),
            ("臺灣臺北地方法院 113 年度 訴 字第 2 號民事判決", COURT, "2025-12-31", "判決", LABEL),
            # 同條件但被其他批次標籤佔住 → 仍要匯出
            ("臺灣臺北地方法院 112 年度 重訴 字第 3 號民事判決", COURT, "2025-04-10", "判決", "借名登記"),
            # 以下都不該匯出
            ("臺灣臺北地方法院 114 年度 司票 字第 4 號民事裁定", COURT, "2025-03-06", "裁定", "借名登記"),
            ("臺灣臺北地方法院 113 年度 易 字第 5 號刑事判決", COURT, "2025-03-07", "判決", "詐欺"),
            ("臺灣新北地方法院 113 年度 訴 字第 6 號民事判決", "臺灣新北地方法院", "2025-03-08", "判決", "借名登記"),
            ("臺灣臺北地方法院 113 年度 訴 字第 7 號民事判決", COURT, "2025-01-15", "判決", LABEL),
        ]
        conn = sqlite3.connect(self.db)
        conn.executemany(
            "INSERT INTO judgments (crawl_id, case_number, court, judgment_date, judgment_type, keyword) "
            "VALUES (?,?,?,?,?,?)",
            [(i, *r) for i, r in enumerate(rows, start=1)])
        conn.commit()
        conn.close()

    def tearDown(self):
        html_parser.DB_PATH = self._orig
        self.tmp.cleanup()

    def _select(self, months, court=COURT):
        return select_rows(self.db, 2025, months, court, ("民事",), "判決", LABEL)

    def test_selects_by_conditions_including_other_labels(self):
        got = [r["case_number"] for r in self._select(list(range(3, 13)))]
        self.assertEqual(len(got), 3, got)
        self.assertTrue(any("重訴 字第 3 號" in c for c in got), "被其他標籤佔住的判決應被匯出")

    def test_excludes_rulings_criminal_other_court_and_other_months(self):
        got = " ".join(r["case_number"] for r in self._select(list(range(3, 13))))
        self.assertNotIn("民事裁定", got)
        self.assertNotIn("刑事判決", got)
        self.assertNotIn("新北", got)
        self.assertNotIn("第 7 號", got)           # 1 月不在 3~12 月範圍內

    def test_sorted_by_date(self):
        dates = [r["judgment_date"] for r in self._select(list(range(1, 13)))]
        self.assertEqual(dates, sorted(dates))

    def test_export_all_months_includes_january(self):
        self.assertEqual(len(self._select(list(range(1, 13)))), 4)

    def test_court_code_is_accepted(self):
        self.assertEqual(len(self._select(list(range(3, 13)), court="TPD")), 3)

    def test_filename_reflects_months_with_data_not_months_requested(self):
        """
        REGRESSION：`--export-all` 要求 1~12 月時，檔名原本一律寫「全年」，
        即使其中好幾個月從來沒爬過。檔名要說實話，否則三個月後沒人分得出來。
        本組資料只有 1、3、4、12 月有判決。
        """
        import export_excel
        orig, cwd = export_excel.DB_PATH, os.getcwd()
        export_excel.DB_PATH = self.db
        os.chdir(self.tmp.name)                 # 檔名未指定時會寫進 CWD
        try:
            with redirect_stdout(io.StringIO()):
                out = export_months(2025, list(range(1, 13)), COURT, ("民事",),
                                    "判決", LABEL)
        finally:
            os.chdir(cwd)
            export_excel.DB_PATH = orig

        self.assertIsNotNone(out, "應該有資料可匯出")
        self.assertIn("_2025_01+03-04+12_", out)
        self.assertNotIn("全年", out)


class TestSpanLabel(unittest.TestCase):
    """檔名的月份標記。"""

    def test_full_year(self):
        self.assertEqual(_span_label(list(range(1, 13))), "全年")

    def test_contiguous_run(self):
        self.assertEqual(_span_label(list(range(3, 13))), "03-12")

    def test_single_month(self):
        self.assertEqual(_span_label([5]), "05")

    def test_gaps_are_spelled_out(self):
        self.assertEqual(_span_label([1, 3, 4, 12]), "01+03-04+12")
        self.assertEqual(_span_label([1, 2, 5, 8, 9, 10]), "01-02+05+08-10")

    def test_empty(self):
        self.assertEqual(_span_label([]), "無資料")

    def test_is_filename_safe(self):
        # Windows 禁用字元一個都不能出現，否則檔案開不起來
        for covered in ([1, 3, 4, 12], list(range(1, 13)), [7]):
            self.assertFalse(set(_span_label(covered)) & set('\\/*?:"<>|'),
                             msg=covered)


class TestDryRun(_Base):
    def test_dry_run_does_not_crawl(self):
        fake = _FakeBatched()
        crawl_monthly.batched_crawl = fake
        with redirect_stdout(io.StringIO()) as out:
            code = crawl_monthly.main(["--dry-run", "--state", self.state])
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls, [])
        self.assertIn("待爬取 10 個月", out.getvalue())

    def test_invalid_court_rejected(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            with unittest.mock.patch("sys.stderr", io.StringIO()):
                crawl_monthly.main(["--dry-run", "--court", "不存在的法院"])


class TestKeepAwake(unittest.TestCase):
    def test_context_manager_is_safe(self):
        # 非 Windows 為 no-op；Windows 上會設定並在結束時還原，兩者都不應拋錯
        with crawl_monthly.keep_awake(True):
            pass
        with crawl_monthly.keep_awake(False) as active:
            self.assertFalse(active)


if __name__ == "__main__":
    unittest.main()
