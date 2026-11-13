# -*- coding: utf-8 -*-
"""
civil/dataset/text.py 的離線測試：建資料集與後端處理使用者輸入共用的清理規則。
這些規則改了，訓練資料與上線時看到的文字就不一致，所以每一條都用具體的句子釘住。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from civil.dataset.text import (leak_re, n_case_numbers, normalize_text, prepare_input,  # noqa: E402
                                strip_for_version, strip_prayer, strip_prayer_v5)


class TestNormalizeText(unittest.TestCase):
    def test_v4_converts_everything(self):
        self.assertEqual(normalize_text("原告，㈠Ａ１", "v4"), "原告,(一)A1")

    def test_v4b_keeps_chinese_punctuation(self):
        self.assertEqual(normalize_text("原告，㈠Ａ１：", "v4b"), "原告，(一)A1：")

    def test_v5_circled_numbers_keep_brackets(self):
        """㊀ 在 NFKC 後是沒有括號的「一」（v4），v4b 不轉它，v5 先轉成 ㈠ 再正規化才保留括號。"""
        self.assertEqual(normalize_text("㊀", "v4"), "一")
        self.assertEqual(normalize_text("㊀", "v4b"), "㊀")
        self.assertEqual(normalize_text("㊀", "v5"), "(一)")

    def test_prepare_input_matches_dataset_text(self):
        """使用者輸入：去掉所有空白（同段落切分），再做 v5 正規化。"""
        self.assertEqual(prepare_input("我在  路口\n被撞，Ａ車 ㈠"), "我在路口被撞，A車(一)")
        self.assertEqual(prepare_input(None), "")

    def test_prepare_input_is_idempotent(self):
        once = prepare_input("原告主張：被告應給付１０萬元。㈡")
        self.assertEqual(prepare_input(once), once)


class TestStripPrayer(unittest.TestCase):
    def test_v3_keeps_argument_before_prayer(self):
        text = "被告辯稱借款已清償等語，資為抗辯，並聲明：原告之訴駁回。"
        self.assertEqual(strip_prayer(text), "被告辯稱借款已清償等語，資為抗辯")

    def test_v3_drops_clause_mentioning_main_text(self):
        self.assertEqual(strip_prayer("原告請求如主文所示，理由如下。"), "理由如下。")

    def test_v4_drops_provisional_execution_remnant(self):
        text = "被告未清償借款。㈡願供擔保請准宣告假執行。"
        self.assertEqual(strip_prayer(text, drop_provisional=True), "被告未清償借款。")

    def test_v5_drops_whole_prayer_block(self):
        text = ("被告向原告借款50萬元未還。爰依消費借貸之法律關係，並聲明：㈠被告應給付原告50萬元。"
                "㈡願供擔保，請准宣告假執行。")
        self.assertEqual(strip_prayer_v5(text), "被告向原告借款50萬元未還。爰依消費借貸之法律關係")

    def test_v5_prayer_stops_at_next_party(self):
        """多位被告各寫一段時，第二位被告的答辯不能被當成聲明的第 ㈡ 項刪掉。"""
        text = "被告甲則以：已清償等語，並聲明：原告之訴駁回。㈡被告乙則以：未曾借款等語。"
        # 聲明從「並聲明」起刪到句尾（句號一起刪）；下一句是另一位被告的陳述，聲明就此結束
        self.assertEqual(strip_prayer_v5(text), "被告甲則以：已清償等語㈡被告乙則以：未曾借款等語。")

    def test_v5_keeps_procedural_declarations(self):
        """「聲明異議」是程序行為，不是訴之聲明。"""
        text = "原告前已聲明異議，被告仍未給付。"
        self.assertEqual(strip_prayer_v5(text), text)

    def test_v5_removes_trailing_headings(self):
        self.assertEqual(strip_prayer_v5("被告未到場等語。(三)二、"), "被告未到場等語。")

    def test_strip_for_version_dispatch(self):
        text = "被告未清償。㈡願供擔保請准宣告假執行。"
        self.assertEqual(strip_for_version(text, "v3"), text)
        self.assertEqual(strip_for_version(text, "v4b"), "被告未清償。")


class TestLeakAndCaseNumbers(unittest.TestCase):
    def test_v5_does_not_treat_verification_as_court_finding(self):
        self.assertTrue(leak_re("v4").search("經查證屬實"))
        self.assertFalse(leak_re("v5").search("經查證屬實"))
        self.assertTrue(leak_re("v5").search("經查，原告主張為真"))

    def test_counts_merged_case_numbers(self):
        head = "臺灣臺北地方法院民事判決\n112年度訴字第1號\n112年度訴字第2號\n原告 甲"
        self.assertEqual(n_case_numbers(head), 2)
        self.assertEqual(n_case_numbers("標題\n112年度訴字第1號\n原告 甲\n113年度訴字第3號"), 1)



class TestV6SameTextRulesAsV5(unittest.TestCase):
    """v6 只換樣本母體與結構化變數的來源，文字的處理要和 v5 一模一樣。"""
    SAMPLES = ["原告主張：㊀被告於民國112年間借款Ａ１萬元。並聲明：被告應給付原告新臺幣10萬元。願供擔保請准宣告假執行。",
               "經查證屬實，被告未清償。", "本院認原告之請求為有理由。", "  原告 ，主張 ㈠ 車禍\n受傷  "]

    def test_same_as_v5(self):
        for t in self.SAMPLES:
            with self.subTest(t=t):
                self.assertEqual(normalize_text(t, "v6"), normalize_text(t, "v5"))
                self.assertEqual(strip_for_version(t, "v6"), strip_for_version(t, "v5"))
                self.assertEqual(bool(leak_re("v6").search(t)), bool(leak_re("v5").search(t)))
                self.assertEqual(prepare_input(t, "v6"), prepare_input(t, "v5"))


if __name__ == "__main__":
    unittest.main()
