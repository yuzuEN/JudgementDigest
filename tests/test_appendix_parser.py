# -*- coding: utf-8 -*-
"""
appendix_parser.py 的離線測試。

跟 structure_tasks.py 一樣先前完全沒有 pytest 覆蓋（PR #4 review 指出過），
這裡先補今天實際修過的問題，其餘規則（rowspan 被告欄、逗號分隔多被告等）
之後可以再擴充。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from appendix_parser import parse_sentence_cell  # noqa: E402


class TestCommaAmount(unittest.TestCase):
    """
    REGRESSION：主刑罰金含千分位逗號（阿拉伯數字寫法）時，SINGLE_RE 比對不到，
    整列直接漏掉（容嫣於 PR #4 留言回報：
    parse_sentence_cell('甲○○犯詐欺取財罪，處罰金新臺幣30,000元。') 原本
    回傳 []）。
    """

    def test_comma_amount_yields_a_row_with_correct_fine(self):
        rows = parse_sentence_cell("甲○○犯詐欺取財罪，處罰金新臺幣30,000元。")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["defendant"], "甲○○")
        self.assertEqual(rows[0]["fine"], 30000)
        self.assertEqual(rows[0]["fine_type"], "主刑")


class TestSingleCharLawName(unittest.TestCase):
    """_LAW_PREFIX 支援「刑法」「民法」這類單字全名（今天稍早修的問題，回歸測試）。"""

    def test_two_character_law_name_splits_from_charge(self):
        rows = parse_sentence_cell("甲○○犯刑法第339條第1項之詐欺取財罪，處有期徒刑陸月。")
        self.assertEqual(rows[0]["law"], "刑法第339條第1項")
        self.assertEqual(rows[0]["charge"], "詐欺取財罪")


if __name__ == "__main__":
    unittest.main()
