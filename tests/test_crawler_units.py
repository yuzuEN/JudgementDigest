# -*- coding: utf-8 -*-
"""
crawler.py 的離線單元測試（不連網、不開瀏覽器）。

涵蓋查詢條件轉換（法院／案件類別／日期）、URL 欄位解析、HTML 完整性判斷，
以及 DB 寫入。凡是需要 Selenium 或司法院伺服器的部分請見 tests/live_check.py。
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))

import crawler  # noqa: E402
from crawler import (  # noqa: E402
    _CASE_SYS_CODES, _COURT_CODES, _JUDGMENT_TYPES, _case_number_year,
    _court_code, _is_html_content_complete, _judgment_date, _roc_parts,
    _sys_code, _url_case_key,
)

# data.aspx 的 id 參數為 URL-encoded 的「法院,年度,字別,案號,日期,序號」
SAMPLE_URL = (
    "https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD"
    "&id=TPDV%2c113%2c%e8%a8%b4%2c4898%2c20250108%2c1&ot=in"
)


class TestCourtCode(unittest.TestCase):
    def test_full_name(self):
        self.assertEqual(_court_code("臺灣臺北地方法院"), "TPD")

    def test_simplified_taiwan_char(self):
        # 使用者常打「台」而非「臺」
        self.assertEqual(_court_code("台灣台北地方法院"), "TPD")

    def test_code_passthrough(self):
        self.assertEqual(_court_code("TPD"), "TPD")
        self.assertEqual(_court_code("tpd"), "TPD")

    def test_abbreviation(self):
        self.assertEqual(_court_code("臺北地方法院"), "TPD")
        self.assertEqual(_court_code("台北地院"), "TPD")

    def test_unique_substring_only(self):
        # 「地方法院」會命中數十個法院 → 不猜，回傳空字串（呼叫端會退回所有法院）
        self.assertEqual(_court_code("地方法院"), "")

    def test_unknown_and_empty(self):
        self.assertEqual(_court_code("不存在的法院"), "")
        self.assertEqual(_court_code(""), "")
        self.assertEqual(_court_code("   "), "")

    def test_supreme_courts_not_confused(self):
        self.assertEqual(_court_code("最高法院"), "TPS")
        self.assertEqual(_court_code("最高行政法院"), "TPA")

    def test_every_mapped_code_round_trips(self):
        for name, code in _COURT_CODES.items():
            self.assertEqual(_court_code(name), code, msg=name)
            self.assertEqual(_court_code(code), code, msg=code)


class TestSysCode(unittest.TestCase):
    def test_names(self):
        self.assertEqual(_sys_code("民事"), "V")
        self.assertEqual(_sys_code("刑事"), "M")
        self.assertEqual(_sys_code("行政"), "A")
        self.assertEqual(_sys_code("憲法"), "C")
        self.assertEqual(_sys_code("懲戒"), "P")

    def test_code_passthrough_and_unknown(self):
        self.assertEqual(_sys_code("V"), "V")
        self.assertEqual(_sys_code("v"), "V")
        self.assertEqual(_sys_code("家事"), "")   # 家事併入民事，非獨立類別
        self.assertEqual(_sys_code(""), "")

    def test_codes_match_form_values(self):
        # 進階搜尋頁的 checkbox 值，改版時這裡會先失敗
        self.assertEqual(set(_CASE_SYS_CODES.values()), {"C", "V", "M", "A", "P"})


class TestJudgmentTypes(unittest.TestCase):
    def test_only_two_kinds(self):
        self.assertEqual(_JUDGMENT_TYPES, ("判決", "裁定"))


class TestRocParts(unittest.TestCase):
    def test_slash_format(self):
        self.assertEqual(_roc_parts("2025/01/07"), (114, 1, 7))

    def test_iso_format(self):
        self.assertEqual(_roc_parts("2025-12-31"), (114, 12, 31))

    def test_invalid(self):
        self.assertIsNone(_roc_parts("2025"))
        self.assertIsNone(_roc_parts(""))
        self.assertIsNone(_roc_parts("民國114年1月7日"))


class TestUrlParsing(unittest.TestCase):
    def test_case_number_year(self):
        # 案號年度 113，與裁判日期（2025 = 民國 114）是兩回事
        self.assertEqual(_case_number_year(SAMPLE_URL), 113)

    def test_judgment_date(self):
        self.assertEqual(_judgment_date(SAMPLE_URL), "2025-01-08")

    def test_case_key(self):
        self.assertEqual(_url_case_key(SAMPLE_URL), ("113", "訴", "4898"))

    def test_malformed_url_is_safe(self):
        self.assertIsNone(_case_number_year("https://example.com/no-id"))
        self.assertEqual(_judgment_date("https://example.com/no-id"), "")
        self.assertEqual(_url_case_key("https://example.com/no-id"), ("", "", ""))


class TestHtmlCompleteness(unittest.TestCase):
    def test_stub_too_short(self):
        self.assertFalse(_is_html_content_complete('<html>id="jud"</html>'))

    def test_long_but_no_content_marker(self):
        self.assertFalse(_is_html_content_complete("x" * 6000))

    def test_complete(self):
        self.assertTrue(_is_html_content_complete("x" * 6000 + '<div id="jud">'))
        self.assertTrue(_is_html_content_complete("x" * 6000 + '<div class="htmlcontent">'))


class TestDbWrite(unittest.TestCase):
    """upsert_record / save_html 使用暫存 DB 與暫存目錄，不碰真正的 judgments.db。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._db, self._dir = crawler.DB_PATH, crawler.HTML_DIR
        crawler.DB_PATH  = os.path.join(self.tmp.name, "test.db")
        crawler.HTML_DIR = os.path.join(self.tmp.name, "html")
        os.makedirs(crawler.HTML_DIR, exist_ok=True)
        crawler.init_db()

    def tearDown(self):
        crawler.DB_PATH, crawler.HTML_DIR = self._db, self._dir
        self.tmp.cleanup()

    def _insert(self, case_number="臺灣臺北地方法院 113 年度 訴 字第 1 號民事判決",
                keyword="臺灣臺北地方法院-民事-判決"):
        return crawler.upsert_record(
            case_number, "臺灣臺北地方法院", "清償借款", "2025-01-07",
            SAMPLE_URL, "x.html", keyword,
        )

    def test_insert_then_duplicate_is_skipped(self):
        self.assertTrue(self._insert())
        self.assertFalse(self._insert())          # case_number UNIQUE
        conn = sqlite3.connect(crawler.DB_PATH)
        n = conn.execute("SELECT COUNT(*) FROM crawl_records").fetchone()[0]
        kw = conn.execute("SELECT keyword FROM crawl_records").fetchone()[0]
        conn.close()
        self.assertEqual(n, 1)
        # 無關鍵字查詢時，keyword 欄存的是標籤 —— export_excel -k 靠它篩選
        self.assertEqual(kw, "臺灣臺北地方法院-民事-判決")

    def test_save_html_sanitizes_filename(self):
        path = crawler.save_html("<html>x</html>",
                                 "臺灣臺北地方法院 113 年度 訴 字第 1 號民事判決")
        self.assertTrue(os.path.exists(path))
        # 空白與逗號等檔名不安全字元一律換成底線
        self.assertNotIn(" ", os.path.basename(path))
        self.assertNotIn(",", os.path.basename(path))


if __name__ == "__main__":
    unittest.main()
