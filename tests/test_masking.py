# -*- coding: utf-8 -*-
"""
retrieval/masking.py 的離線測試：使用者輸入與判決顯示的遮名。
漏遮就是把個資送出去或顯示出來，所以每一種格式都用具體的例子釘住。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retrieval.masking import find_spans, mask, mask_parties, party_names  # noqa: E402


class TestPatterns(unittest.TestCase):
    def assertMasked(self, text, expected, names=()):
        self.assertEqual(mask(text, names)[0], expected)

    def test_id_number(self):
        self.assertMasked("我的身分證是A123456789。", "我的身分證是【身分證字號】。")

    def test_mobile_and_landline(self):
        self.assertMasked("手機0912-345-678，家裡(02)2345-6789", "手機【電話】，家裡【電話】")
        self.assertMasked("手機 0912345678", "手機 【電話】")

    def test_email(self):
        self.assertMasked("寄到 wang.ming@example.com 就好", "寄到 【電子郵件】 就好")

    def test_address(self):
        self.assertMasked("住在臺北市大安區和平東路二段106號3樓", "住在【地址】")
        self.assertMasked("新北市板橋區文化路1段21巷5號", "【地址】")
        self.assertMasked("寄到台中市西區民權路99號之1", "寄到【地址】")

    def test_address_without_city_is_left_for_the_user(self):
        """沒有縣市的地址不自動遮（否則會把前面的字一起吃掉），由使用者在預覽時補遮。"""
        self.assertMasked("住大安區和平東路106號", "住大安區和平東路106號")

    def test_given_names(self):
        self.assertMasked("王小明開車撞到我，王小明的太太也在車上", "【姓名】開車撞到我，【姓名】的太太也在車上",
                          names=["王小明"])

    def test_longer_name_wins(self):
        self.assertMasked("王小明和王小是不同人", "【姓名】和【姓名】是不同人", names=["王小", "王小明"])

    def test_amounts_and_dates_untouched(self):
        text = "去年3月15日車禍，請求賠償500000元，住院5天"
        self.assertMasked(text, text)

    def test_spans_report_original_positions(self):
        text = "電話0912345678"
        (span,) = find_spans(text)
        self.assertEqual((span.start, span.end, span.kind), (2, 12, "phone"))
        self.assertEqual(text[span.start:span.end], span.text)

    def test_empty(self):
        self.assertEqual(mask(None), ("", []))


class TestParties(unittest.TestCase):
    def test_party_names_skip_already_masked(self):
        self.assertEqual(party_names("王小明；李○華", "大同股份有限公司即大同商行"),
                         ["王小明", "大同股份有限公司"])

    def test_mask_parties_replaces_with_roles(self):
        text = "原告王小明主張被告陳大華駕車不慎，原告訴訟代理人林律師到庭。"
        out = mask_parties(text, "王小明", "陳大華", ["林律師"])
        self.assertEqual(out, "原告【原告】主張被告【被告】駕車不慎，原告訴訟代理人【代理人】到庭。")

    def test_mask_parties_also_masks_patterns(self):
        out = mask_parties("被告住臺中市西區民權路99號", "", "", [])
        self.assertEqual(out, "被告住【地址】")


if __name__ == "__main__":
    unittest.main()
