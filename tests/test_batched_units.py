# -*- coding: utf-8 -*-
"""
crawl_batched.py 的離線測試。

日期切分策略（新 → 舊、遞迴對半）是整個爬蟲正確性的核心，
因此除了純函式，這裡也用假的 search_and_crawl 驅動 batched_crawl，
在不連網的情況下驗證切分順序、切分條件與參數透傳。
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))

import crawl_batched  # noqa: E402
from crawl_batched import (  # noqa: E402
    _db_count, _fmt, _generate_year_chunks, _split_chunk, build_label,
)


class TestYearChunks(unittest.TestCase):
    def test_descending_and_year_aligned(self):
        chunks = _generate_year_chunks(date(2022, 1, 1), date(2024, 12, 31))
        self.assertEqual(chunks, [
            (date(2024, 1, 1), date(2024, 12, 31)),
            (date(2023, 1, 1), date(2023, 12, 31)),
            (date(2022, 1, 1), date(2022, 12, 31)),
        ])

    def test_clipped_to_requested_range(self):
        chunks = _generate_year_chunks(date(2024, 3, 5), date(2025, 2, 10))
        self.assertEqual(chunks, [
            (date(2025, 1, 1), date(2025, 2, 10)),
            (date(2024, 3, 5), date(2024, 12, 31)),
        ])

    def test_single_day(self):
        d = date(2025, 1, 8)
        self.assertEqual(_generate_year_chunks(d, d), [(d, d)])


class TestSplitChunk(unittest.TestCase):
    def test_newer_half_first(self):
        newer, older = _split_chunk(date(2025, 1, 1), date(2025, 1, 10))
        self.assertEqual(newer, (date(2025, 1, 6), date(2025, 1, 10)))
        self.assertEqual(older, (date(2025, 1, 1), date(2025, 1, 5)))

    def test_two_day_span_splits_into_two_single_days(self):
        newer, older = _split_chunk(date(2025, 1, 1), date(2025, 1, 2))
        self.assertEqual(newer, (date(2025, 1, 2), date(2025, 1, 2)))
        self.assertEqual(older, (date(2025, 1, 1), date(2025, 1, 1)))

    def test_halves_cover_range_without_gap_or_overlap(self):
        cs, ce = date(2024, 1, 1), date(2024, 12, 31)
        newer, older = _split_chunk(cs, ce)
        self.assertEqual(older[0], cs)
        self.assertEqual(newer[1], ce)
        self.assertEqual((newer[0] - older[1]).days, 1)

    def test_fmt(self):
        self.assertEqual(_fmt(date(2025, 1, 8)), "2025/01/08")


class TestBuildLabel(unittest.TestCase):
    def test_keyword_wins(self):
        # 有關鍵字時維持既有行為，不因新參數改變舊資料的標記
        self.assertEqual(build_label("借名登記"), "借名登記")
        self.assertEqual(
            build_label("借名登記", "臺灣臺北地方法院", ("民事",), "判決"),
            "借名登記",
        )

    def test_conditions_when_no_keyword(self):
        self.assertEqual(
            build_label("", "臺灣臺北地方法院", ("民事",), "判決"),
            "臺灣臺北地方法院-民事-判決",
        )
        self.assertEqual(build_label("", "臺灣臺北地方法院"), "臺灣臺北地方法院")
        self.assertEqual(build_label("", "", ("民事", "刑事")), "民事-刑事")

    def test_nothing_specified(self):
        self.assertEqual(build_label(""), "全部")


class TestDbCount(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._db = crawl_batched.DB_PATH
        crawl_batched.DB_PATH = os.path.join(self.tmp.name, "t.db")
        conn = sqlite3.connect(crawl_batched.DB_PATH)
        conn.execute("CREATE TABLE crawl_records (id INTEGER PRIMARY KEY, keyword TEXT)")
        conn.executemany(
            "INSERT INTO crawl_records (keyword) VALUES (?)",
            [("借名登記",), ("借名登記",), ("臺灣臺北地方法院-民事-判決",)],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        crawl_batched.DB_PATH = self._db
        self.tmp.cleanup()

    def test_counts_only_matching_label(self):
        self.assertEqual(_db_count("借名登記"), 2)
        self.assertEqual(_db_count("臺灣臺北地方法院-民事-判決"), 1)
        self.assertEqual(_db_count("不存在"), 0)


class _FakeDriver:
    def quit(self):
        pass


class TestBatchedCrawlFlow(unittest.TestCase):
    """用假的 search_and_crawl 驅動切分邏輯（完全離線）。"""

    def setUp(self):
        self.calls = []
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = (
            crawl_batched.search_and_crawl,
            crawl_batched.build_driver,
            crawl_batched.init_db,
            crawl_batched._db_count,
            crawl_batched.DB_PATH,
        )
        crawl_batched.build_driver = lambda headless: _FakeDriver()
        crawl_batched.init_db = lambda: None
        crawl_batched._db_count = lambda label: 0      # 預設：不計入新增
        crawl_batched.DB_PATH = os.path.join(self.tmp.name, "t.db")

    def tearDown(self):
        (crawl_batched.search_and_crawl, crawl_batched.build_driver,
         crawl_batched.init_db, crawl_batched._db_count,
         crawl_batched.DB_PATH) = self._orig
        self.tmp.cleanup()

    def _fake(self, totals):
        """totals: {(start,end): total}；未列出的區間視為 0 筆。"""
        def _search(**kw):
            self.calls.append(kw)
            key   = (kw["start_date"], kw["end_date"])
            total = totals.get(key, 10)
            return {
                "collected": 0,
                "total": total,
                "truncated": total >= crawl_batched._RESULT_LIMIT,
            }
        return _search

    def test_no_split_when_under_limit(self):
        crawl_batched.search_and_crawl = self._fake({})
        crawl_batched.batched_crawl(
            keyword="借名登記", total_target=100,
            start_date=date(2025, 1, 1), end_date=date(2025, 1, 10),
            headless=True,
        )
        self.assertEqual(len(self.calls), 1)
        self.assertEqual((self.calls[0]["start_date"], self.calls[0]["end_date"]),
                         ("2025/01/01", "2025/01/10"))

    def test_splits_and_processes_newest_first(self):
        # 整段超過上限 → 應切半，且較新的半段先查
        crawl_batched.search_and_crawl = self._fake({("2025/01/01", "2025/01/10"): 900})
        crawl_batched.batched_crawl(
            keyword="借名登記", total_target=100,
            start_date=date(2025, 1, 1), end_date=date(2025, 1, 10),
            headless=True,
        )
        ranges = [(c["start_date"], c["end_date"]) for c in self.calls]
        self.assertEqual(ranges, [
            ("2025/01/01", "2025/01/10"),   # 探測 → 超過上限
            ("2025/01/06", "2025/01/10"),   # 較新的半段先
            ("2025/01/01", "2025/01/05"),
        ])

    def test_single_day_over_limit_is_not_split_further(self):
        crawl_batched.search_and_crawl = self._fake({
            ("2025/01/01", "2025/01/02"): 900,
            ("2025/01/02", "2025/01/02"): 900,
            ("2025/01/01", "2025/01/01"): 900,
        })
        crawl_batched.batched_crawl(
            keyword="借名登記", total_target=100,
            start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
            headless=True,
        )
        ranges = [(c["start_date"], c["end_date"]) for c in self.calls]
        self.assertEqual(ranges, [
            ("2025/01/01", "2025/01/02"),
            ("2025/01/02", "2025/01/02"),
            ("2025/01/01", "2025/01/01"),
        ])
        # 多日區間先探測（truncated 就交回上層切分），單日則直接把能拿的拿走
        self.assertIs(self.calls[0]["skip_if_truncated"], True)
        self.assertIs(self.calls[1]["skip_if_truncated"], False)
        self.assertIs(self.calls[2]["skip_if_truncated"], False)

    def test_new_filters_are_passed_through(self):
        crawl_batched.search_and_crawl = self._fake({})
        crawl_batched.batched_crawl(
            keyword="", total_target=10,
            start_date=date(2025, 1, 8), end_date=date(2025, 1, 8),
            headless=True,
            court="臺灣臺北地方法院", case_types=("民事",), judgment_type="判決",
        )
        kw = self.calls[0]
        self.assertEqual(kw["court"], "臺灣臺北地方法院")
        self.assertEqual(kw["case_types"], ("民事",))
        self.assertEqual(kw["judgment_type"], "判決")
        self.assertEqual(kw["keyword"], "")
        self.assertEqual(kw["keyword_label"], "臺灣臺北地方法院-民事-判決")

    def test_case_year_still_passed_through(self):
        # 舊功能：案號年度與裁判日期是獨立維度
        crawl_batched.search_and_crawl = self._fake({})
        crawl_batched.batched_crawl(
            keyword="借名登記", total_target=10,
            start_date=date(2024, 1, 1), end_date=date(2024, 1, 2),
            headless=True, case_year_start=113, case_year_end=113,
        )
        self.assertEqual(self.calls[0]["case_year_start"], 113)
        self.assertEqual(self.calls[0]["case_year_end"], 113)

    def test_target_zero_means_unlimited(self):
        crawl_batched.search_and_crawl = self._fake({})
        crawl_batched.batched_crawl(
            keyword="借名登記", total_target=0,
            start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
            headless=True,
        )
        # -n 0 不是「不爬」，而是「不設上限」→ 該區間仍被查詢
        self.assertEqual(len(self.calls), 1)

    def test_stops_once_target_reached(self):
        crawl_batched.search_and_crawl = self._fake({})
        counter = {"n": 0}

        def _count(label):
            # 每次查詢後多 5 筆
            return counter["n"]

        def _search(**kw):
            self.calls.append(kw)
            counter["n"] += 5
            return {"collected": 5, "total": 5, "truncated": False}

        crawl_batched._db_count = _count
        crawl_batched.search_and_crawl = _search
        crawl_batched.batched_crawl(
            keyword="借名登記", total_target=8,
            start_date=date(2020, 1, 1), end_date=date(2025, 12, 31),
            headless=True,
        )
        # 6 個年度段，但累計達 8 筆後就停（第 2 段後 total_new=10 >= 8）
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
