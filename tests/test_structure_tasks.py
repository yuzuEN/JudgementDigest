# -*- coding: utf-8 -*-
"""
structure_tasks.py 的離線測試。

之前完全沒有接入 pytest（只有手動執行 `python structure_tasks.py` 時
才會跑 self_check()），PR #4 review 兩次指出這個缺口。這裡先把
self_check() 接進 pytest，再補今天實際修過的兩個 bug 的回歸測試。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from structure_tasks import (  # noqa: E402
    chinese_number,
    extract_laws,
    extract_sentences,
    self_check,
)


class TestSelfCheck(unittest.TestCase):
    def test_self_check_passes(self):
        """把既有的 self_check() 斷言接進 CI，而不是只能手動執行才會跑到。"""
        self_check()


class TestChineseNumberCommaAmount(unittest.TestCase):
    """
    REGRESSION：處罰金金額含千分位逗號（阿拉伯數字寫法）時，SINGLE_RE／
    TOTAL_RE 原本完全比對不到，整案被誤判成「無刑期」（容嫣於 PR #4
    留言回報：extract_sentences('甲犯竊盜罪，處罰金新臺幣30,000元。')
    原本回傳 ([], '無刑期')）。
    """

    def test_comma_amount_is_recognized_as_a_sentence(self):
        terms, status = extract_sentences("甲犯竊盜罪，處罰金新臺幣30,000元。")
        self.assertEqual(terms, ["罰金新臺幣30,000元"])
        self.assertNotEqual(status, "無刑期")


class TestLawRESingleCharName(unittest.TestCase):
    """
    REGRESSION：LAW_RE 原本要求法規名稱前綴至少 2 字，「刑法」「民法」這類
    單字全名（不含「法」本身只有 1 字前綴）永遠比對不到（容嫣於 PR #4 留言
    回報：extract_laws('', '刑法第339條第1項；洗錢防制法第19條第1項')
    只回傳洗錢防制法，appendix_parser 的 _LAW_PREFIX 先前已用同樣理由修過）。
    """

    def test_two_character_law_name_is_matched(self):
        laws = extract_laws("", "刑法第339條第1項；洗錢防制法第19條第1項")
        self.assertIn("刑法第339條第1項", laws)
        self.assertIn("洗錢防制法第19條第1項", laws)


class TestChineseNumberMixedDigits(unittest.TestCase):
    """阿拉伯數字混中文單位（今天稍早修的另一個問題）不能被這次改壞。"""

    def test_arabic_digit_run_mixed_with_chinese_unit(self):
        self.assertEqual(chinese_number("10萬"), 100000)
        self.assertEqual(chinese_number("3萬6千"), 36000)


if __name__ == "__main__":
    unittest.main()
