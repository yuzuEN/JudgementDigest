# -*- coding: utf-8 -*-
"""
retrieval/masking.py 的離線測試：使用者輸入與判決顯示的遮名。
漏遮就是把個資送出去或顯示出來，所以每一種格式都用具體的例子釘住。
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retrieval.masking import find_spans, mask, mask_parties, party_names, third_party_names  # noqa: E402


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


class TestSameRulesAsBrowser(unittest.TestCase):
    """瀏覽器（frontend/src/mask.ts）和這裡的規則要一致，兩邊跑同一份案例。"""

    def test_shared_cases(self):
        path = Path(__file__).resolve().parents[1] / "frontend" / "src" / "test" / "masking_cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertGreater(len(cases), 20)
        for case in cases:
            self.assertEqual(mask(case["text"], case["names"])[0], case["expected"], case["text"])

    def test_full_width_spans_point_at_the_original_text(self):
        text = "電話０９１２３４５６７８"
        (span,) = find_spans(text)
        self.assertEqual(span.text, "０９１２３４５６７８")


class TestParties(unittest.TestCase):
    def test_party_names_skip_already_masked(self):
        self.assertEqual(party_names("王小明；李○華", "大同股份有限公司即大同商行"),
                         ["王小明", "大同股份有限公司"])

    def test_mask_parties_replaces_with_roles(self):
        text = "原告王小明主張被告陳大華駕車不慎，原告訴訟代理人林律師到庭。"
        out = mask_parties(text, "王小明", "陳大華", ["林律師"])
        self.assertEqual(out, "原告【原告】主張被告【被告】駕車不慎，原告訴訟代理人【代理人】到庭。")

    def test_third_party_names(self):
        text = "原告與訴外人簡建祥結婚，證人洪瑞斌到庭，其配偶馮品瑄亦在場，證人林文表示不知情"
        self.assertEqual(third_party_names(text), ["林文", "洪瑞斌", "簡建祥", "馮品瑄"])

    def test_names_without_the_word_third_party(self):
        cases = {"證人【關係人】（原名李佩華，65年生）": "李佩華", "原告（原名：陳麗川）獲發股數": "陳麗川",
                 "其餘繼承人即蔡淑智到場": "蔡淑智", "前所有權人為蔡志陽所有": "蔡志陽", "第三人徐浦洲另行起訴": "徐浦洲"}
        for text, name in cases.items():
            self.assertIn(name, third_party_names(text), text)

    def test_names_in_a_list(self):
        self.assertEqual(third_party_names("由訴外人王大明、謝新潭、陳榮坤合資興建"), ["王大明", "謝新潭", "陳榮坤"])

    def test_list_stops_at_ordinary_words(self):
        self.assertEqual(third_party_names("訴外人王大明、被告到場"), ["王大明"])

    def test_common_words_after_a_list_or_title_are_not_names(self):
        for text in ("所有權人為何人", "繼承人即高雄市民", "訴外人王大明、連帶保證", "訴外人王大明、董事長", "原告曾匯款",
                     "第三人陳述意見", "保證人為連帶債務人", "訴外人王大明、施作工程"):
            self.assertNotIn(True, [n in ("何人", "高雄市", "連帶保", "董事長", "曾匯款", "陳述", "連帶債", "施作工", "施作")
                                    for n in third_party_names(text)], text)

    def test_role_words_are_not_names(self):
        for text in ("訴外人即原告", "以證人身分到庭", "法定代理人之配偶", "配偶贈與為由", "證人方面表示", "訴外人公司"):
            self.assertEqual(third_party_names(text), [], text)

    def test_third_party_masked_everywhere(self):
        """同一個人在別的段落沒有寫稱謂時也要遮掉。"""
        names = third_party_names("訴外人簡建祥借款")
        self.assertEqual(mask_parties("由簡建祥簽名", "", "", [], names), "由【關係人】簽名")

    def test_mask_parties_also_masks_patterns(self):
        out = mask_parties("被告住臺中市西區民權路99號", "", "", [])
        self.assertEqual(out, "被告住【地址】")


if __name__ == "__main__":
    unittest.main()
