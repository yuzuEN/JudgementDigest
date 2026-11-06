# -*- coding: utf-8 -*-
"""
兩個與「只收判決時的完整性」有關的行為：

1. 全文檢索粗篩：指定裁判種類且沒有關鍵字時，以該詞做伺服器端全文檢索，
   把單日 976 筆（多為本票類裁定）縮到 55 筆，結果集才不會撞到 500 上限。
   資料標籤不能因此改變，否則會和先前批次的資料分家。

2. 分群桶截斷偵測：單日改用案號年度分群後，若某個桶本身仍 >= 500 列就會被截斷。
   原本的檢查看「過濾後收到幾筆」—— 只收判決時一個 940 列的桶可能只收到 3 筆，
   永遠不會觸發警告。必須改看翻到的原始列數。
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))

import crawl_batched  # noqa: E402
import crawl_monthly  # noqa: E402
import crawler  # noqa: E402
from crawler import Pacer, _RESULT_LIMIT  # noqa: E402

LIST_URL = "https://judgment.judicial.gov.tw/FJUD/qryresultlst.aspx?ty=JUDBOOK&q=abc"


class _FakeDriver:
    page_source = "<html>ok</html>"

    def get(self, url):
        pass

    def quit(self):
        pass


def _row(i, kind="裁定"):
    return {
        "case_number": f"臺灣臺北地方法院 114 年度 司票 字第 {i} 號民事{kind}",
        "court": "臺灣臺北地方法院", "case_title": "本票", "judgment_date": "2025-03-03",
        "url": f"https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDV,114,x,{i},20250303,1",
    }


class _CrawlerFakes:
    def __init__(self, tmp, total, pages, year_links=None):
        self.tmp, self.total, self.pages = tmp, total, list(pages)
        self.year_links = year_links or []
        self.searched = []

    def __enter__(self):
        names = ("_ad_search", "_parse_case_rows", "_go_next_page", "crawl_detail_page",
                 "_collect_year_links", "_collect_court_links", "_list_page_error",
                 "DB_PATH", "HTML_DIR")
        self._orig = {n: getattr(crawler, n) for n in names}
        self._sleep = crawler.time.sleep
        pages = self.pages
        state = {"page": 0}

        def _search(driver, keyword, *a, **k):
            self.searched.append(keyword)
            return LIST_URL, self.total

        def _rows(driver):
            return pages[state["page"]] if state["page"] < len(pages) else []

        def _next(driver):
            state["page"] += 1
            return state["page"] < len(pages)

        def _detail(driver, url, cn):
            path = os.path.join(crawler.HTML_DIR, f"{abs(hash(cn))}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x")
            return path

        crawler._ad_search = _search
        crawler._parse_case_rows = _rows
        crawler._go_next_page = _next
        crawler.crawl_detail_page = _detail
        crawler._collect_year_links = lambda d: self.year_links
        crawler._collect_court_links = lambda d: []
        crawler._list_page_error = lambda d: ""
        crawler.time.sleep = lambda s: None
        crawler.DB_PATH = os.path.join(self.tmp, "t.db")
        crawler.HTML_DIR = os.path.join(self.tmp, "html")
        os.makedirs(crawler.HTML_DIR, exist_ok=True)
        crawler.init_db()
        return self

    def __exit__(self, *exc):
        for n, v in self._orig.items():
            setattr(crawler, n, v)
        crawler.time.sleep = self._sleep
        return False


class TestFullTextPrefilter(unittest.TestCase):
    def _run(self, **kw):
        with tempfile.TemporaryDirectory() as tmp, \
                _CrawlerFakes(tmp, total=10, pages=[[_row(1, "判決")]]) as fakes:
            res = crawler.search_and_crawl(max_results=5, driver=_FakeDriver(),
                                           pacer=Pacer(delay=0), **kw)
            import sqlite3
            conn = sqlite3.connect(crawler.DB_PATH)
            labels = [r[0] for r in conn.execute("SELECT keyword FROM crawl_records")]
            conn.close()
        return fakes.searched, res, labels

    def test_judgment_type_becomes_full_text_query_when_no_keyword(self):
        searched, _, _ = self._run(keyword="", judgment_type="判決",
                                   court="臺灣臺北地方法院", case_types=("民事",),
                                   keyword_label="臺灣臺北地方法院-民事-判決")
        self.assertEqual(searched, ["判決"])

    def test_user_keyword_is_not_overridden(self):
        searched, _, _ = self._run(keyword="借名登記", judgment_type="判決")
        self.assertEqual(searched, ["借名登記"])

    def test_no_prefilter_without_judgment_type(self):
        searched, _, _ = self._run(keyword="", court="臺灣臺北地方法院")
        self.assertEqual(searched, [""])

    def test_label_is_unchanged_by_prefilter(self):
        # 標籤必須維持「臺灣臺北地方法院-民事-判決」，不能變成「判決」，否則與 1、2 月資料分家
        _, res, labels = self._run(keyword="", judgment_type="判決",
                                   court="臺灣臺北地方法院", case_types=("民事",),
                                   keyword_label="臺灣臺北地方法院-民事-判決")
        self.assertEqual(res["collected"], 1)
        self.assertEqual(labels, ["臺灣臺北地方法院-民事-判決"])


class TestBucketTruncationDetection(unittest.TestCase):
    def test_full_bucket_is_reported_even_if_few_judgments_collected(self):
        """940 列的桶只翻得到 500 列、其中只有 1 筆判決 → 仍必須回報截斷。"""
        pages = [[_row(p * 20 + i) for i in range(20)] for p in range(25)]  # 500 列裁定
        pages[3][0] = _row(9999, "判決")                                     # 其中 1 筆判決
        with tempfile.TemporaryDirectory() as tmp, _CrawlerFakes(
                tmp, total=976, pages=pages,
                year_links=[(LIST_URL + "&gy=jyear&gc=114", 114, False)]):
            res = crawler.search_and_crawl(
                keyword="", judgment_type="判決", max_results=_RESULT_LIMIT,
                start_date="2025/03/03", end_date="2025/03/03",
                court="臺灣臺北地方法院", case_types=("民事",),
                driver=_FakeDriver(), pacer=Pacer(delay=0), skip_if_truncated=False)
        self.assertEqual(res["collected"], 1)
        self.assertEqual(len(res["truncated_buckets"]), 1)
        self.assertIn("ROC114", res["truncated_buckets"][0])

    def test_small_bucket_is_not_reported(self):
        pages = [[_row(i) for i in range(20)] for _ in range(3)]              # 60 列
        with tempfile.TemporaryDirectory() as tmp, _CrawlerFakes(
                tmp, total=600, pages=pages,
                year_links=[(LIST_URL + "&gy=jyear&gc=114", 114, False)]):
            res = crawler.search_and_crawl(
                keyword="", judgment_type="判決", max_results=_RESULT_LIMIT,
                court="臺灣臺北地方法院", driver=_FakeDriver(),
                pacer=Pacer(delay=0), skip_if_truncated=False)
        self.assertEqual(res["truncated_buckets"], [])


class TestTruncatedBucketsPropagate(unittest.TestCase):
    def test_batched_collects_into_stats(self):
        def _fake(**kw):
            return {"collected": 0, "total": 10, "truncated": False, "page_errors": 0,
                    "truncated_buckets": ["2025/03/03~2025/03/03 ROC114"],
                    "driver": kw.get("driver")}

        orig = (crawl_batched.search_and_crawl, crawl_batched.build_driver,
                crawl_batched.init_db, crawl_batched._db_count)
        crawl_batched.search_and_crawl = _fake
        crawl_batched.build_driver = lambda headless: _FakeDriver()
        crawl_batched.init_db = lambda: None
        crawl_batched._db_count = lambda label: 0
        stats = {}
        try:
            crawl_batched.batched_crawl(
                keyword="", total_target=0, start_date=date(2025, 3, 3),
                end_date=date(2025, 3, 3), headless=True, judgment_type="判決",
                pacer=Pacer(delay=0), stats=stats)
        finally:
            (crawl_batched.search_and_crawl, crawl_batched.build_driver,
             crawl_batched.init_db, crawl_batched._db_count) = orig
        self.assertEqual(stats["truncated_buckets"], ["2025/03/03~2025/03/03 ROC114"])

    def test_monthly_records_in_state(self):
        def _fake(**kw):
            kw["stats"].update(processed=1, failed_segments=[], truncated_days=[],
                               truncated_buckets=["2025/03/03~2025/03/03 ROC114"], pacer="")
            return 0

        orig = crawl_monthly.batched_crawl
        crawl_monthly.batched_crawl = _fake
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "s.json")
                with redirect_stdout(io.StringIO()) as out:
                    st = crawl_monthly.crawl_months(2025, [3], "臺灣臺北地方法院", ("民事",),
                                                    "判決", 0, path)
        finally:
            crawl_monthly.batched_crawl = orig
        rec = st["months"]["2025-03"]
        self.assertEqual(rec["truncated_buckets"], ["2025/03/03~2025/03/03 ROC114"])
        # 重跑救不回，所以不列為 incomplete（避免每次都白白重跑），但要明確顯示
        self.assertEqual(rec["status"], "done")
        self.assertIn("分群桶達 500 上限", out.getvalue())


if __name__ == "__main__":
    unittest.main()
