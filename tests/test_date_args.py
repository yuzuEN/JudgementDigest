# -*- coding: utf-8 -*-
"""
日期參數的解析與防呆。

這一組全部是回歸測試：日期條件若被靜默忽略或靜默放寬，爬回來的資料範圍
就跟使用者以為的不一樣，而且不會有任何錯誤訊息 —— 是這個專案裡最貴的一種 bug。
"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler import (            # noqa: E402
    _ad_search, _parse_ad_date, _roc_parts, parse_date_arg, resolve_date_range,
)


class TestParseAdDate(unittest.TestCase):
    """REGRESSION：`_roc_parts` 原本只做 split，不存在的日期照樣送進查詢表單。"""

    def test_accepts_both_separators(self):
        self.assertEqual(_parse_ad_date("2025/01/07"), date(2025, 1, 7))
        self.assertEqual(_parse_ad_date("2025-12-31"), date(2025, 12, 31))
        self.assertEqual(_parse_ad_date(" 2025/1/7 "), date(2025, 1, 7))

    def test_rejects_impossible_dates(self):
        # 原本 _roc_parts("2024/13/45") 會回傳 (113, 13, 45)
        for bad in ("2024/13/45", "2025/02/30", "2025/00/10", "2025/01/32"):
            self.assertIsNone(_parse_ad_date(bad), msg=bad)

    def test_rejects_roc_year_typo(self):
        # 誤把民國年填進來：原本會算出 -1797 年並照樣送出
        self.assertIsNone(_parse_ad_date("114/03/01"))

    def test_rejects_unparseable(self):
        for bad in ("2024.03.01", "20240301", "2025", "", "民國114年1月7日"):
            self.assertIsNone(_parse_ad_date(bad), msg=bad)

    def test_roc_parts_still_converts(self):
        self.assertEqual(_roc_parts("2025/01/07"), (114, 1, 7))
        self.assertEqual(_roc_parts("2025-12-31"), (114, 12, 31))
        self.assertIsNone(_roc_parts("2024/13/45"))


class TestParseDateArg(unittest.TestCase):
    def test_returns_date(self):
        self.assertEqual(parse_date_arg("2025/01/07"), date(2025, 1, 7))

    def test_raises_with_usable_message(self):
        with self.assertRaises(ValueError) as ctx:
            parse_date_arg("2024.03.01")
        # 訊息會直接顯示給使用者，必須帶上原值與正確格式
        self.assertIn("2024.03.01", str(ctx.exception))
        self.assertIn("YYYY/MM/DD", str(ctx.exception))


class TestResolveDateRange(unittest.TestCase):
    TODAY = date(2026, 9, 19)

    def test_years_expand_to_whole_years(self):
        sd, ed = resolve_date_range(start_year=2018, end_year=2023, today=self.TODAY)
        self.assertEqual((sd, ed), (date(2018, 1, 1), date(2023, 12, 31)))

    def test_end_year_omitted_means_today_not_year_end(self):
        # 爬未來日期沒有意義，所以預設迄日是今天而非當年 12/31
        _, ed = resolve_date_range(start_year=2015, end_year=None, today=self.TODAY)
        self.assertEqual(ed, self.TODAY)

    def test_dates_override_years(self):
        sd, ed = resolve_date_range(
            start_date="2024/06/01", end_date="2024/06/30",
            start_year=2015, end_year=2023, today=self.TODAY)
        self.assertEqual((sd, ed), (date(2024, 6, 1), date(2024, 6, 30)))

    def test_mixed_date_and_year(self):
        sd, ed = resolve_date_range(
            start_date="2024/06/01", start_year=2015, end_year=2025, today=self.TODAY)
        self.assertEqual((sd, ed), (date(2024, 6, 1), date(2025, 12, 31)))

    def test_start_after_end_rejected(self):
        with self.assertRaises(ValueError):
            resolve_date_range(start_year=2020, end_year=2018, today=self.TODAY)

    def test_start_year_in_the_future_rejected(self):
        # 迄日預設為今天，所以未來的起始年會被同一個判斷擋下
        with self.assertRaises(ValueError):
            resolve_date_range(start_year=2030, today=self.TODAY)

    def test_mixed_params_out_of_order_rejected(self):
        with self.assertRaises(ValueError):
            resolve_date_range(
                start_date="2025/06/01", end_year=2024, today=self.TODAY)

    def test_same_day_is_allowed(self):
        sd, ed = resolve_date_range(
            start_date="2025/01/08", end_date="2025/01/08", today=self.TODAY)
        self.assertEqual(sd, ed)

    def test_malformed_date_raises_not_traceback(self):
        # REGRESSION：原本 date.fromisoformat 會直接把 ValueError 噴成 traceback
        with self.assertRaises(ValueError):
            resolve_date_range(start_date="2024/13/45", today=self.TODAY)

    def test_invalid_year_raises(self):
        with self.assertRaises(ValueError):
            resolve_date_range(start_year=0, today=self.TODAY)


class _ExplodingDriver:
    """任何屬性存取都失敗 —— 用來證明查詢在碰瀏覽器之前就中止了。"""

    def __getattr__(self, name):
        raise AssertionError(f"driver.{name} 不應該被呼叫：日期無效時應提前中止")


class TestAdSearchAbortsOnBadDate(unittest.TestCase):
    """
    REGRESSION：`_ad_search` 原本對無法解析的日期只印一行 warning 就跳過該欄位，
    查詢照送但變成「沒有日期範圍」—— 使用者以為在抓一週，實際抓了全部。
    """

    def test_unparseable_date_aborts_before_touching_driver(self):
        for kwargs in ({"start_date": "2024.03.01"},
                       {"end_date": "114/03/01"},
                       {"start_date": "2025/01/01", "end_date": "2025/02/30"}):
            with self.subTest(**kwargs):
                url, total = _ad_search(_ExplodingDriver(), "借名登記", **kwargs)
                self.assertIsNone(url)
                self.assertIsNone(total)


if __name__ == "__main__":
    unittest.main()
