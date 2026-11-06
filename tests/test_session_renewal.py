# -*- coding: utf-8 -*-
"""
Phase B 每 80 筆會重建 WebDriver session。重建後舊 driver 會被 quit，
若呼叫端繼續沿用舊的參照，接下來每一段都會在失效的 session 上查詢而全部落空。

這裡用假的 driver 與假的網路層（完全離線）釘住兩件事：
  1. search_and_crawl 會把「目前有效的 driver」回傳給呼叫端
  2. crawl_batched 會採用回傳的 driver，不會沿用已被 quit 的舊物件
"""

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))

import crawl_batched  # noqa: E402
import crawler  # noqa: E402

RENEW_EVERY = 80        # 與 crawler.search_and_crawl 內的 _SESSION_RENEW_EVERY 一致


class _FakeDriver:
    _seq = 0

    def __init__(self):
        _FakeDriver._seq += 1
        self.name = f"driver-{_FakeDriver._seq}"
        self.quit_called = False

    def get(self, url):
        pass

    def quit(self):
        self.quit_called = True


class _CrawlerFakes:
    """把 crawler 對外的網路／瀏覽器互動全部換掉，只留下流程本身。"""

    def __init__(self, tmpdir, n_items):
        self.tmpdir = tmpdir
        self.n_items = n_items
        self.built = []

    def __enter__(self):
        self._orig = {n: getattr(crawler, n) for n in (
            "_ad_search", "_parse_case_rows", "_go_next_page", "crawl_detail_page",
            "build_driver", "DB_PATH", "HTML_DIR",
        )}
        self._orig_sleep = crawler.time.sleep

        items = [{
            "case_number": f"臺灣臺北地方法院 113 年度 訴 字第 {i} 號民事判決",
            "court": "臺灣臺北地方法院",
            "case_title": "清償借款",
            "judgment_date": "2025-01-08",
            "url": f"https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDV,113,x,{i},20250108,1",
        } for i in range(self.n_items)]

        def _build(headless=True):
            d = _FakeDriver()
            self.built.append(d)
            return d

        def _detail(driver, url, case_number):
            path = os.path.join(crawler.HTML_DIR, f"{abs(hash(case_number))}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x")
            return path

        crawler._ad_search       = lambda *a, **k: ("http://list", len(items))
        crawler._parse_case_rows = lambda driver: items
        crawler._go_next_page    = lambda driver: False
        crawler.crawl_detail_page = _detail
        crawler.build_driver     = _build
        crawler.time.sleep       = lambda s: None      # 略過 renew 的 15 秒等待
        crawler.DB_PATH  = os.path.join(self.tmpdir, "t.db")
        crawler.HTML_DIR = os.path.join(self.tmpdir, "html")
        os.makedirs(crawler.HTML_DIR, exist_ok=True)
        crawler.init_db()
        return self

    def __exit__(self, *exc):
        for n, v in self._orig.items():
            setattr(crawler, n, v)
        crawler.time.sleep = self._orig_sleep
        return False


class TestSearchAndCrawlReturnsDriver(unittest.TestCase):
    def test_returns_same_driver_when_no_renewal(self):
        with tempfile.TemporaryDirectory() as tmp, _CrawlerFakes(tmp, 3):
            d = _FakeDriver()
            res = crawler.search_and_crawl(keyword="x", max_results=3, driver=d)
            self.assertEqual(res["collected"], 3)
            self.assertIs(res["driver"], d)
            self.assertFalse(d.quit_called)     # 傳入的 driver 不該被關掉

    def test_returns_new_driver_after_renewal(self):
        n = RENEW_EVERY + 5
        with tempfile.TemporaryDirectory() as tmp, _CrawlerFakes(tmp, n) as fakes:
            d = _FakeDriver()
            res = crawler.search_and_crawl(keyword="x", max_results=n, driver=d)
            self.assertEqual(res["collected"], n)
            self.assertTrue(d.quit_called, "重建時舊 driver 應被 quit")
            self.assertTrue(fakes.built, "應該建立了新的 driver")
            self.assertIsNot(res["driver"], d)
            self.assertIs(res["driver"], fakes.built[-1])


class TestBatchedAdoptsRenewedDriver(unittest.TestCase):
    def test_next_segment_uses_renewed_driver(self):
        """跨區間時必須換用新 driver —— 否則第二段會在已 quit 的 session 上查詢。"""
        n = RENEW_EVERY + 5
        used = []

        with tempfile.TemporaryDirectory() as tmp, _CrawlerFakes(tmp, n) as fakes:
            orig_search = crawler.search_and_crawl

            def _spy(**kw):
                # 記下「呼叫當下」的狀態：該段結束時這個 driver 本來就可能被重建掉
                used.append((kw["driver"], kw["driver"].quit_called))
                return orig_search(**kw)

            orig = (crawl_batched.search_and_crawl, crawl_batched.build_driver,
                    crawl_batched.DB_PATH, crawl_batched.init_db)
            crawl_batched.search_and_crawl = _spy
            crawl_batched.build_driver = crawler.build_driver
            crawl_batched.DB_PATH = crawler.DB_PATH
            crawl_batched.init_db = crawler.init_db
            try:
                crawl_batched.batched_crawl(
                    keyword="x", total_target=10 ** 6,
                    start_date=date(2024, 1, 1), end_date=date(2025, 12, 31),
                    headless=True,
                )
            finally:
                (crawl_batched.search_and_crawl, crawl_batched.build_driver,
                 crawl_batched.DB_PATH, crawl_batched.init_db) = orig

        self.assertGreaterEqual(len(used), 2, "應該處理了 2 個年度段")
        self.assertIsNot(used[1][0], used[0][0], "第二段仍沿用了上一段的 driver")
        self.assertFalse(used[1][1], "第二段拿到的是已被 quit 的 driver")


if __name__ == "__main__":
    unittest.main()
