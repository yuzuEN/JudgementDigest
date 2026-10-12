# -*- coding: utf-8 -*-
"""
清單頁錯誤（「查詢設定錯誤，請重新設定查詢條件後查詢」）的偵測與復原。

這是最危險的一類失敗：錯誤頁上沒有任何案件連結，若把它當成「已翻完」，
該區段就會靜靜地少收一批資料，而且回報成功。這裡釘住三件事：
  1. 錯誤頁能被辨識，而正常清單頁不會被誤判
  2. 翻頁途中遇到錯誤頁會重載／重送查詢，復原後從同一頁續翻
  3. 真的無法復原時會計入 page_errors 回報給呼叫端，不會假裝成功
"""

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import crawl_batched  # noqa: E402
import crawler  # noqa: E402
from crawler import _carry_group_params, _list_page_error, _page_url  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ERROR_HTML = (FIXTURES / "list_error_page.html").read_text(encoding="utf-8")
NORMAL_HTML = (FIXTURES / "tpd_civil_judgment.html").read_text(encoding="utf-8")

LIST_URL = "https://judgment.judicial.gov.tw/FJUD/qryresultlst.aspx?ty=JUDBOOK&q=abc123"
BUCKET_URL = LIST_URL + "&gy=jyear&gc=114"


class _FakeDriver:
    """
    模擬清單頁：error_gets 指定「第幾次 get 之後會看到錯誤頁」，
    always_error 則是怎麼重載都失敗。其餘情況載入正常頁。
    """

    def __init__(self, error_gets=(), always_error=False):
        self.error_gets = set(error_gets)
        self.always_error = always_error
        self.page_source = ERROR_HTML if always_error else NORMAL_HTML
        self.visited = []

    def get(self, url):
        self.visited.append(url)
        n = len(self.visited)
        self.page_source = (ERROR_HTML
                            if self.always_error or n in self.error_gets
                            else NORMAL_HTML)

    def quit(self):
        pass


class TestErrorPageDetection(unittest.TestCase):
    def test_detects_real_error_page(self):
        self.assertEqual(_list_page_error(_FakeDriver(always_error=True)), "查詢設定錯誤")

    def test_normal_page_is_not_flagged(self):
        self.assertEqual(_list_page_error(_FakeDriver()), "")

    def test_bot_defense_page(self):
        d = _FakeDriver()
        d.page_source = "<html><body>The requested URL was rejected. Request Rejected</body></html>"
        self.assertEqual(_list_page_error(d), "Request Rejected")


class TestPageUrl(unittest.TestCase):
    def test_builds_page_url(self):
        self.assertEqual(
            _page_url(LIST_URL, 7),
            LIST_URL + "&sort=DS&page=7&ot=in")

    def test_replaces_existing_paging_params(self):
        u = _page_url(LIST_URL + "&sort=DS&page=3&ot=in", 9)
        self.assertEqual(u.count("page="), 1)
        self.assertTrue(u.endswith("page=9&ot=in"))

    def test_keeps_group_params(self):
        # 分群桶（gy/gc）也要能定址到指定頁
        u = _page_url(BUCKET_URL, 2)
        self.assertIn("gy=jyear", u)
        self.assertIn("gc=114", u)
        self.assertIn("page=2", u)

    def test_carry_group_params_to_new_hash(self):
        new = "https://judgment.judicial.gov.tw/FJUD/qryresultlst.aspx?ty=JUDBOOK&q=NEWHASH"
        carried = _carry_group_params(BUCKET_URL, new)
        self.assertIn("q=NEWHASH", carried)
        self.assertIn("gy=jyear", carried)
        self.assertIn("gc=114", carried)
        # 一般清單（無分群）不應被加上多餘參數
        self.assertEqual(_carry_group_params(LIST_URL, new), new)


class _Fakes:
    """把 search_and_crawl 依賴的網路互動換掉，只留翻頁流程。"""

    def __init__(self, tmpdir, pages, driver, search_result=(LIST_URL, 10)):
        self.tmpdir, self.pages, self.driver = tmpdir, pages, driver
        self.search_result = search_result     # _ad_search 的回傳值，或要拋出的例外
        self.searches = 0

    def __enter__(self):
        self._orig = {n: getattr(crawler, n) for n in (
            "_ad_search", "_parse_case_rows", "_go_next_page", "crawl_detail_page",
            "build_driver", "DB_PATH", "HTML_DIR",
        )}
        self._sleep = crawler.time.sleep
        pages = list(self.pages)

        def _search(*a, **k):
            self.searches += 1
            if isinstance(self.search_result, Exception):
                raise self.search_result
            return self.search_result

        def _rows(driver):
            # 錯誤頁一律沒有案件連結
            if _list_page_error(driver):
                return []
            return pages.pop(0) if pages else []

        def _detail(driver, url, case_number):
            path = os.path.join(crawler.HTML_DIR, f"{abs(hash(case_number))}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x")
            return path

        crawler._ad_search        = _search
        crawler._parse_case_rows  = _rows
        crawler._go_next_page     = lambda driver: False
        crawler.crawl_detail_page = _detail
        crawler.build_driver      = lambda headless=True: self.driver
        crawler.time.sleep        = lambda s: None      # 略過退避等待
        crawler.DB_PATH  = os.path.join(self.tmpdir, "t.db")
        crawler.HTML_DIR = os.path.join(self.tmpdir, "html")
        os.makedirs(crawler.HTML_DIR, exist_ok=True)
        crawler.init_db()
        return self

    def __exit__(self, *exc):
        for n, v in self._orig.items():
            setattr(crawler, n, v)
        crawler.time.sleep = self._sleep
        return False


def _item(i):
    return {
        "case_number": f"臺灣臺北地方法院 113 年度 訴 字第 {i} 號民事判決",
        "court": "臺灣臺北地方法院", "case_title": "清償借款",
        "judgment_date": "2025-01-08",
        "url": f"https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDV,113,x,{i},20250108,1",
    }


class TestRecoveryDuringPagination(unittest.TestCase):
    def test_recovers_and_keeps_collecting(self):
        """第一次解析踩到錯誤頁 → 重載後應該繼續收，而不是當成翻完。"""
        # 第 1 次 get（導向清單頁）就落在錯誤頁，之後重載才正常
        driver = _FakeDriver(error_gets={1})
        with tempfile.TemporaryDirectory() as tmp, _Fakes(tmp, [[_item(1), _item(2)]], driver):
            res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 2)
        self.assertEqual(res["page_errors"], 0)
        # 復原時是用頁碼網址跳回中斷的那一頁
        self.assertTrue(any("page=1" in u for u in driver.visited), driver.visited)

    def test_unrecoverable_error_is_reported_not_silent(self):
        """錯誤頁一直無法復原 → 必須計入 page_errors，而不是回報成功。"""
        driver = _FakeDriver(always_error=True)
        with tempfile.TemporaryDirectory() as tmp, _Fakes(tmp, [[_item(1)]], driver) as fakes:
            res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 0)
        self.assertEqual(res["page_errors"], 1)
        # 重載三次仍失敗後，會重新送出查詢換新的 q hash（第 1 次是原本的查詢）
        self.assertGreaterEqual(fakes.searches, 2)

    def test_empty_result_is_not_treated_as_error(self):
        """真的查無資料時不該觸發復原，也不該記錯誤。
        網站查無資料時摘要頁沒有清單連結，_ad_search 回傳 (None, 0)。"""
        driver = _FakeDriver()
        with tempfile.TemporaryDirectory() as tmp, \
                _Fakes(tmp, [[]], driver, search_result=(None, 0)) as fakes:
            res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 0)
        self.assertEqual(res["page_errors"], 0)
        self.assertEqual(fakes.searches, 1)


class TestSilentEmptySegments(unittest.TestCase):
    """
    查詢沒有完整跑完、卻回報 collected=0 而且沒有錯誤 —— 批次層會把該段當成完成，
    月份標成 done，資料整段遺漏且不會重試。實際發生過：
      - 宜蘭 2023-11：查詢回報 133 筆，清單頁沒有任何案件連結（也不是已知錯誤頁）
      - 高雄 2024/02/01~14：查詢頁沒載入（找不到 jud_kw），WebDriver 例外被吞掉
    """

    def test_empty_list_despite_reported_total_is_error(self):
        """查詢回報有資料、清單頁一直空白 → 重試一次後記為錯誤，不能當成翻完。"""
        driver = _FakeDriver()
        with tempfile.TemporaryDirectory() as tmp, _Fakes(tmp, [[], []], driver):
            res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 0)
        self.assertEqual(res["page_errors"], 1)
        # 有嘗試以頁碼網址重載第 1 頁，而且沒有無限重試
        self.assertTrue(any("page=1" in u for u in driver.visited), driver.visited)

    def test_empty_list_recovers_after_reload(self):
        """清單頁第一次空白、重載後正常 → 照常收集，不記錯誤。"""
        driver = _FakeDriver()
        with tempfile.TemporaryDirectory() as tmp, \
                _Fakes(tmp, [[], [_item(1), _item(2)]], driver):
            res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 2)
        self.assertEqual(res["page_errors"], 0)

    def test_missing_results_url_is_error_unless_total_is_zero(self):
        """取不到結果清單網址：查無資料（total=0）是正常，其餘都要記為錯誤。"""
        for total, expected in ((None, 1), (25, 1), (0, 0)):
            with self.subTest(total=total):
                driver = _FakeDriver()
                with tempfile.TemporaryDirectory() as tmp, \
                        _Fakes(tmp, [], driver, search_result=(None, total)):
                    res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
                self.assertEqual(res["collected"], 0)
                self.assertEqual(res["page_errors"], expected)

    def test_webdriver_exception_during_search_is_error(self):
        """查詢頁沒載入（WebDriver 例外）→ 記為錯誤，不是回報成功的空區段。"""
        driver = _FakeDriver()
        exc = crawler.NoSuchElementException("no such element: [id=\"jud_kw\"]")
        with tempfile.TemporaryDirectory() as tmp, \
                _Fakes(tmp, [], driver, search_result=exc):
            with self.assertLogs("crawler", level="ERROR"):
                res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 0)
        self.assertIsNone(res["total"])
        self.assertEqual(res["page_errors"], 1)

    def test_unknown_total_with_empty_list_is_error(self):
        """讀不到總筆數但有清單網址 → 查詢有結果，清單空白一樣要記為錯誤。"""
        driver = _FakeDriver()
        with tempfile.TemporaryDirectory() as tmp, \
                _Fakes(tmp, [[], []], driver, search_result=(LIST_URL, None)):
            res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["page_errors"], 1)

    def test_empty_bucket_is_error(self):
        """單日超過上限改走分群時，分群清單空白也是沒載到（分群連結只出現在有結果的分群）。"""
        driver = _FakeDriver()
        orig = crawler._collect_year_links
        crawler._collect_year_links = lambda d: [(BUCKET_URL, 114, False)]
        try:
            with tempfile.TemporaryDirectory() as tmp, \
                    _Fakes(tmp, [[], []], driver, search_result=(LIST_URL, 600)):
                res = crawler.search_and_crawl(
                    keyword="x", max_results=5, driver=driver,
                    court="臺灣臺北地方法院", skip_if_truncated=False)
        finally:
            crawler._collect_year_links = orig
        self.assertTrue(res["truncated"])
        self.assertEqual(res["page_errors"], 1)


class TestDetailDownloadFailures(unittest.TestCase):
    """
    清單有收到、裁判書頁卻沒存下來（逾時後頁面停在上一筆、標題與案號不符、連線被重設）
    舊版直接略過，該段照樣回報完成 —— 基隆、臺南、宜蘭等 8 院因此遺漏 40 筆。
    """

    @staticmethod
    def _detail(fail_times):
        """前 fail_times[案號] 次回傳 None（下載失敗），之後成功。"""
        calls = {}

        def _detail(driver, url, case_number):
            calls[case_number] = calls.get(case_number, 0) + 1
            if calls[case_number] <= fail_times.get(case_number, 0):
                return None
            path = os.path.join(crawler.HTML_DIR, f"{abs(hash(case_number))}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x")
            return path
        return _detail, calls

    def test_failed_download_is_retried_with_new_session(self):
        driver = _FakeDriver()
        target = _item(2)["case_number"]
        with tempfile.TemporaryDirectory() as tmp, \
                _Fakes(tmp, [[_item(1), _item(2), _item(3)]], driver):
            crawler.crawl_detail_page, calls = self._detail({target: 1})
            res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 3)
        self.assertEqual(res["page_errors"], 0)
        self.assertEqual(calls[target], 2)        # 第一輪失敗，重試成功

    def test_download_failing_twice_is_reported(self):
        driver = _FakeDriver()
        target = _item(2)["case_number"]
        with tempfile.TemporaryDirectory() as tmp, \
                _Fakes(tmp, [[_item(1), _item(2)]], driver):
            crawler.crawl_detail_page, calls = self._detail({target: 99})
            with self.assertLogs("crawler", level="ERROR") as log:
                res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 1)
        self.assertEqual(res["page_errors"], 1)
        self.assertEqual(calls[target], 2)        # 只重試一次，不會無限重試
        self.assertIn(target, "\n".join(log.output))   # 錯誤訊息列出是哪一筆


class TestNextPageTimeout(unittest.TestCase):
    """
    「下一頁」載入逾時不等於翻完。舊版把兩者都回傳 False，2022/05/16~23 翻到
    第 13 頁逾時就結束（應有 23 頁），5/16~18 的判決整批遺漏，月份仍標成 done。
    """

    @staticmethod
    def _next_raising_once():
        calls = []

        def _next(driver):
            calls.append(1)
            if len(calls) == 1:
                raise crawler.NextPageLoadError("page load timed out twice")
            return False
        return _next

    def test_timeout_jumps_to_next_page_and_keeps_collecting(self):
        driver = _FakeDriver()
        with tempfile.TemporaryDirectory() as tmp, \
                _Fakes(tmp, [[_item(1)], [_item(2)]], driver):
            crawler._go_next_page = self._next_raising_once()
            res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 2)
        self.assertEqual(res["page_errors"], 0)
        # 以頁碼網址直接跳到第 2 頁，而不是重新從第 1 頁翻
        self.assertTrue(any("page=2" in u for u in driver.visited), driver.visited)

    def test_timeout_that_cannot_recover_is_reported(self):
        # get #1 = 導向清單頁；#2~#4 = 三次重載；#5 = 重送查詢後跳頁 —— 全部失敗
        driver = _FakeDriver(error_gets={2, 3, 4, 5})
        with tempfile.TemporaryDirectory() as tmp, \
                _Fakes(tmp, [[_item(1)], [_item(2)]], driver):
            crawler._go_next_page = self._next_raising_once()
            res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 1)
        self.assertEqual(res["page_errors"], 1)

    def test_empty_page_after_jump_is_reported_not_treated_as_end(self):
        """上一頁有「下一頁」，跳過去卻是空的 → 是沒載到，不是翻完。"""
        driver = _FakeDriver()
        with tempfile.TemporaryDirectory() as tmp, _Fakes(tmp, [[_item(1)]], driver):
            crawler._go_next_page = self._next_raising_once()
            res = crawler.search_and_crawl(keyword="x", max_results=5, driver=driver)
        self.assertEqual(res["collected"], 1)
        self.assertEqual(res["page_errors"], 1)


class TestBatchReportsIncompleteSegments(unittest.TestCase):
    def test_segment_with_page_errors_is_logged(self):
        """區段有未復原的錯誤時，批次層要留下可重跑的紀錄（不是靜靜跳過）。"""
        calls = []

        def _fake_search(**kw):
            calls.append(kw)
            return {"collected": 0, "total": 10, "truncated": False,
                    "page_errors": 2, "driver": kw.get("driver")}

        orig = (crawl_batched.search_and_crawl, crawl_batched.build_driver,
                crawl_batched.init_db, crawl_batched._db_count)
        crawl_batched.search_and_crawl = _fake_search
        crawl_batched.build_driver = lambda headless: _FakeDriver()
        crawl_batched.init_db = lambda: None
        crawl_batched._db_count = lambda label: 0
        try:
            with self.assertLogs("crawl_batched", level="ERROR") as log:
                crawl_batched.batched_crawl(
                    keyword="x", total_target=100,
                    start_date=date(2025, 1, 8), end_date=date(2025, 1, 8),
                    headless=True,
                )
        finally:
            (crawl_batched.search_and_crawl, crawl_batched.build_driver,
             crawl_batched.init_db, crawl_batched._db_count) = orig

        text = "\n".join(log.output)
        self.assertIn("2025/01/08", text)
        self.assertIn("不完整", text)
        self.assertIn("--start-date", text)      # 直接給出可重跑的指令片段


if __name__ == "__main__":
    unittest.main()
