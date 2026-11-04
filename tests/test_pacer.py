# -*- coding: utf-8 -*-
"""
速率控制（Pacer）的離線測試。

重點不只是「有沒有等待」，而是回饋迴路：出錯要降速、連續出錯要長暫停、
恢復正常後要慢慢加速回來，而且降速狀態必須跨區段延續。
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
from crawler import (  # noqa: E402
    _BRAKE_PAUSE, _BRAKE_THRESHOLD, _DEFAULT_DELAY, _JITTER, _LIST_DELAY_RATIO,
    _MAX_SLOWDOWN, _RECOVER_STREAK, Pacer,
)


class _SleepRecorder:
    """攔截 time.sleep，記錄每次等待的秒數。"""

    def __init__(self):
        self.waits = []

    def __enter__(self):
        self._orig = crawler.time.sleep
        crawler.time.sleep = self.waits.append
        return self

    def __exit__(self, *exc):
        crawler.time.sleep = self._orig
        return False


class TestWaitTiming(unittest.TestCase):
    def test_detail_wait_within_jitter_band(self):
        p = Pacer(delay=1.0)
        with _SleepRecorder() as rec:
            for _ in range(50):
                p.wait("detail")
        self.assertEqual(len(rec.waits), 50)
        for w in rec.waits:
            self.assertGreaterEqual(w, 1.0 * (1 - _JITTER) - 1e-9)
            self.assertLessEqual(w, 1.0 * (1 + _JITTER) + 1e-9)
        # 有抖動 → 不會每次都一樣
        self.assertGreater(len(set(rec.waits)), 1)

    def test_list_wait_is_lighter_than_detail(self):
        p = Pacer(delay=2.0, jitter=0.0)
        with _SleepRecorder() as rec:
            p.wait("detail")
            p.wait("list")
        self.assertAlmostEqual(rec.waits[0], 2.0)
        self.assertAlmostEqual(rec.waits[1], 2.0 * _LIST_DELAY_RATIO)

    def test_zero_delay_does_not_sleep(self):
        p = Pacer(delay=0.0)
        with _SleepRecorder() as rec:
            p.wait("detail")
            p.wait("list")
        self.assertEqual(rec.waits, [])
        self.assertEqual(p.requests, 2)      # 仍然要計數

    def test_request_counter(self):
        p = Pacer(delay=0.0)
        for _ in range(5):
            p.wait("list")
        self.assertEqual(p.requests, 5)


class TestFeedbackLoop(unittest.TestCase):
    def test_failure_doubles_the_interval(self):
        p = Pacer(delay=1.0, jitter=0.0)
        with _SleepRecorder() as rec:
            p.on_failure("查詢設定錯誤")
            self.assertEqual(p.multiplier, 2.0)
            p.wait("detail")
            p.on_failure("查詢設定錯誤")
            self.assertEqual(p.multiplier, 4.0)
            p.wait("detail")
        self.assertAlmostEqual(rec.waits[0], 2.0)
        self.assertAlmostEqual(rec.waits[1], 4.0)

    def test_multiplier_is_capped(self):
        p = Pacer(delay=1.0, brake_threshold=10 ** 6)   # 不要觸發長暫停
        with _SleepRecorder():
            for _ in range(20):
                p.on_failure("x")
        self.assertEqual(p.multiplier, _MAX_SLOWDOWN)

    def test_recovers_after_sustained_success(self):
        p = Pacer(delay=1.0)
        with _SleepRecorder():
            p.on_failure("x")
            p.on_failure("x")
        self.assertEqual(p.multiplier, 4.0)
        for _ in range(_RECOVER_STREAK):
            p.on_success()
        self.assertEqual(p.multiplier, 2.0)          # 減半，不是一次跳回全速
        for _ in range(_RECOVER_STREAK):
            p.on_success()
        self.assertEqual(p.multiplier, 1.0)
        for _ in range(_RECOVER_STREAK * 2):
            p.on_success()
        self.assertEqual(p.multiplier, 1.0)          # 不會低於 1.0

    def test_success_resets_failure_streak(self):
        """中間成功過就不該累積成連續失敗，避免無謂的長暫停。"""
        p = Pacer(delay=0.0)
        with _SleepRecorder() as rec:
            for _ in range(_BRAKE_THRESHOLD - 1):
                p.on_failure("x")
            p.on_success()
            p.on_failure("x")
        self.assertEqual(p.brakes, 0)
        self.assertNotIn(_BRAKE_PAUSE, rec.waits)

    def test_consecutive_failures_trigger_long_pause(self):
        p = Pacer(delay=0.0)
        with _SleepRecorder() as rec:
            for _ in range(_BRAKE_THRESHOLD):
                p.on_failure("查詢設定錯誤")
        self.assertEqual(p.brakes, 1)
        self.assertIn(_BRAKE_PAUSE, rec.waits)

    def test_summary_mentions_rate(self):
        p = Pacer(delay=0.0)
        for _ in range(3):
            p.wait("list")
        s = p.summary()
        self.assertIn("請求 3 次", s)
        self.assertIn("次/分", s)


class _FakeDriver:
    def get(self, url):
        pass

    def quit(self):
        pass


class TestPacerSharedAcrossSegments(unittest.TestCase):
    """降速狀態必須跨區段延續，否則被擋之後每段都重新全速衝、反覆踩坑。"""

    def test_batch_passes_one_pacer_to_every_segment(self):
        seen = []

        def _fake_search(**kw):
            pacer = kw["pacer"]
            seen.append(pacer)
            pacer.on_failure("模擬伺服器拒絕")     # 第一段就被擋
            return {"collected": 0, "total": 10, "truncated": False,
                    "page_errors": 0, "driver": kw.get("driver")}

        orig = (crawl_batched.search_and_crawl, crawl_batched.build_driver,
                crawl_batched.init_db, crawl_batched._db_count, crawler.time.sleep)
        crawl_batched.search_and_crawl = _fake_search
        crawl_batched.build_driver = lambda headless: _FakeDriver()
        crawl_batched.init_db = lambda: None
        crawl_batched._db_count = lambda label: 0
        crawler.time.sleep = lambda s: None
        try:
            crawl_batched.batched_crawl(
                keyword="x", total_target=10 ** 6,
                start_date=date(2023, 1, 1), end_date=date(2025, 12, 31),
                headless=True, delay=1.5,
            )
        finally:
            (crawl_batched.search_and_crawl, crawl_batched.build_driver,
             crawl_batched.init_db, crawl_batched._db_count,
             crawler.time.sleep) = orig

        self.assertGreaterEqual(len(seen), 3, "應該處理了 3 個年度段")
        self.assertEqual(len({id(p) for p in seen}), 1, "每段都該拿到同一個 Pacer")
        self.assertEqual(seen[0].delay, 1.5, "--delay 應該傳到 Pacer")
        self.assertGreater(seen[0].multiplier, 1.0, "降速狀態應延續到後續區段")


class TestSearchUsesPacer(unittest.TestCase):
    """search_and_crawl 沒收到 pacer 時要自己建一個，行為與舊版等價。"""

    def test_default_pacer_created(self):
        self.assertEqual(Pacer().delay, _DEFAULT_DELAY)

    def test_detail_downloads_are_paced(self):
        items = [{
            "case_number": f"臺灣臺北地方法院 113 年度 訴 字第 {i} 號民事判決",
            "court": "臺灣臺北地方法院", "case_title": "x", "judgment_date": "2025-01-08",
            "url": f"https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDV,113,x,{i},20250108,1",
        } for i in range(3)]

        orig = {n: getattr(crawler, n) for n in (
            "_ad_search", "_parse_case_rows", "_go_next_page", "crawl_detail_page",
            "DB_PATH", "HTML_DIR")}
        with tempfile.TemporaryDirectory() as tmp:
            crawler._ad_search = lambda *a, **k: ("http://list", 3)
            crawler._parse_case_rows = lambda d: items
            crawler._go_next_page = lambda d: False
            crawler.crawl_detail_page = lambda d, url, cn: os.path.join(tmp, "x.html")
            crawler.DB_PATH = os.path.join(tmp, "t.db")
            crawler.HTML_DIR = tmp
            with open(os.path.join(tmp, "x.html"), "w", encoding="utf-8") as f:
                f.write("x")
            crawler.init_db()
            pacer = Pacer(delay=0.0)
            try:
                with _SleepRecorder():
                    res = crawler.search_and_crawl(
                        keyword="x", max_results=3, driver=_FakeDriver(), pacer=pacer)
            finally:
                for n, v in orig.items():
                    setattr(crawler, n, v)

        self.assertEqual(res["collected"], 3)
        # 1 次查詢 + 3 筆詳細頁
        self.assertGreaterEqual(pacer.requests, 4)


if __name__ == "__main__":
    unittest.main()
