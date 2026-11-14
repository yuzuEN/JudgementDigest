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

from retrieval.masking import (by_appearance, find_spans, listed_with, mask, mask_parties, party_names, party_roles,  # noqa: E402
                               rare_two_char_names, third_party_names,
                               usable_person_names)


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

    def test_address_without_city(self):
        """沒有縣市、但有門牌號碼的地址也遮；前面的「住」「因當時」「系爭」不能被吃進去。"""
        self.assertMasked("住大安區和平東路106號", "住【地址】")
        self.assertMasked("因當時東門街68號房屋", "因當時【地址】房屋")
        self.assertMasked("系爭中山路二段5號房屋", "系爭【地址】房屋")
        self.assertMasked("坐落永靖鄉同安村永福路1段664號建物", "坐落【地址】建物")

    def test_road_without_house_number_untouched(self):
        for text in ("沿中山路往南行駛", "民法第184條第1項", "本院卷第12號", "行經該路三段"):
            self.assertMasked(text, text)

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

    def test_several_people_in_a_role_are_numbered(self):
        """多個被告、多個關係人時要分得出誰是誰；只有一個人時不加編號。"""
        text = "被告陳大華、林小美、王建國應連帶給付，林小美並向證人簡建祥借款，簡建祥轉交洪瑞斌"
        out = mask_parties(text, "王小明", "陳大華；林小美；王建國", [], ["簡建祥", "洪瑞斌"])
        self.assertEqual(out, "被告【被告1】、【被告2】、【被告3】應連帶給付，【被告2】並向證人【關係人1】借款，"
                              "【關係人1】轉交【關係人2】")

    def test_numbers_consistent_across_sections(self):
        """同一件判決的每一段用同樣的名單，同一個人在每一段都是同一個編號。"""
        others = by_appearance(["洪瑞斌", "簡建祥"], "證人簡建祥到庭\n洪瑞斌未到")
        self.assertEqual(others, ["簡建祥", "洪瑞斌"])
        self.assertEqual(mask_parties("洪瑞斌未到", "", "", [], others), "【關係人2】未到")
        self.assertEqual(mask_parties("證人簡建祥到庭", "", "", [], others), "證人【關係人1】到庭")

    def test_role_words_in_party_fields(self):
        """
        人工抽查：代理人欄位解析成「被告兼下一人；陳晁遠」，清掉「兼…」後的「被告」被當成名字，
        全文的「被告」都被換掉，還換進已經放好的【被告】裡變成【【代理人3】】；陳晁遠也被當成代理人。
        """
        self.assertEqual(party_names("被告葉麗玉；上被告；王大明；被告兼下一人"), ["葉麗玉", "王大明"])
        p, d, a = party_roles("邱嚴樟", "陳信宇", ["林君鴻；被告兼下一人；陳晁遠"])
        self.assertEqual((p, d, a), (["邱嚴樟"], ["陳信宇", "陳晁遠"], ["林君鴻"]))
        out = mask_parties("被告陳信宇持股18萬股，被告陳晁遠為被告陳信宇之父親", "邱嚴樟", "陳信宇",
                           ["林君鴻；被告兼下一人；陳晁遠"])
        self.assertEqual(out, "被告【被告1】持股18萬股，被告【被告2】為被告【被告1】之父親")

    def test_short_names_never_replaced_inside_tags(self):
        out = mask_parties("被告陳信宇與證人林文", "", "陳信宇", [], ["林文", "被告"])
        self.assertEqual(out, "【關係人2】【被告】與證人【關係人1】")

    def test_mask_parties_masks_plates(self):
        out = mask_parties("原告騎乘971-KNM號機車，與被告駕駛之車牌號碼AUC-2222號自小客車碰撞", "", "", [])
        self.assertEqual(out, "原告騎乘【車牌】號機車，與被告駕駛之車牌號碼【車牌】號自小客車碰撞")


class TestPlates(unittest.TestCase):
    def test_plate_span_is_only_the_plate(self):
        (span,) = find_spans("車號：XY-123")
        self.assertEqual((span.kind, span.text), ("plate", "XY-123"))

    def test_item_codes_in_a_series_are_not_split(self):
        self.assertEqual(mask("依結構圖7345-ST-A03施工")[0], "依結構圖7345-ST-A03施工")


class TestPersonNames(unittest.TestCase):
    """人名辨識（CKIP）的結果要篩過才拿來全文取代，否則會把一般用語一起遮掉。"""

    def test_keeps_full_names(self):
        self.assertEqual(usable_person_names(["李惠明", "歐陽美華", "盧新璋", "曾湘云"]), ["曾湘云", "李惠明", "歐陽美華", "盧新璋"])

    def test_two_character_results_not_used(self):
        """兩個字的辨識結果多半是一般詞（人工抽查：「馬達」被遮掉），不拿來全文取代；有稱謂的仍由規則遮。"""
        self.assertEqual(usable_person_names(["林文", "建國", "馬達", "陳情", "周全", "李敖"]), [])
        self.assertIn("林文", third_party_names("證人林文到庭"))

    def test_rare_two_character_names(self):
        """兩個字的名字只在全部判決裡很少出現時才遮：「陳情」出現在很多判決，「張蕾」只有一件。"""
        texts = ["原告陳情如下"] * 20 + ["證人張蕾到庭陳情"]
        rare = rare_two_char_names(["陳情", "張蕾", "王陳", "孫鄭"], texts, max_df=10)
        self.assertEqual(rare, {"張蕾"})
        self.assertEqual(usable_person_names(["陳情", "張蕾", "馬達"], rare), ["張蕾"])
        self.assertEqual(usable_person_names(["張蕾"]), [], "沒給頻率資料時不收兩個字的")

    def test_glued_characters_removed(self):
        self.assertEqual(usable_person_names(["查張德滿", "王怡文固", "陳國輝代", "林蔡貴蘭"]),
                         ["張德滿", "林蔡貴蘭", "王怡文", "陳國輝"])
        self.assertEqual(usable_person_names(["三樓馬達", "張冠李戴"]), [])

    def test_rare_characters(self):
        """「陳奕𤋱」的「𤋱」在 Unicode 擴充 B 區（人工抽查發現漏遮）。"""
        self.assertEqual(usable_person_names(["陳奕𤋱"]), ["陳奕𤋱"])
        self.assertEqual(mask_parties("補償給陳雯菁、陳奕𤋱", "", "", [], ["陳雯菁", "陳奕𤋱"]), "補償給【關係人1】、【關係人2】")

    def test_drops_non_names(self):
        for bad in ("王", "王○明", "王〇明", "John", "王小明先生是", "陳述", "簡易", "曾經", "", None,
                    "利云云", "固可認", "卷可佐", "伊前夫", "張渠", "許北之", "霍夫曼", "張一", "蘇童", "王姓", "陳某"):
            self.assertEqual(usable_person_names([bad]), [], bad)

    def test_real_names_with_function_characters(self):
        self.assertEqual(usable_person_names(["張之瑋", "吳渭渠", "儲開軒", "陳其邁"]), ["儲開軒", "吳渭渠", "張之瑋", "陳其邁"])
        self.assertEqual(usable_person_names(["余梅之", "上開二", "孫鄭"]), [])

    def test_longer_names_replaced_first(self):
        """誤判的「孫鄭」不能比「鄭宇峰」先換掉而切斷它，露出「宇峰」。"""
        out = mask_parties("曾孫鄭宇峰、曾孫女鄭宇真", "", "", [], ["孫鄭", "鄭宇峰", "鄭宇真"])
        self.assertEqual(out, "曾孫【關係人2】、曾孫女【關係人3】")

    def test_names_listed_after_known_names(self):
        self.assertEqual(listed_with("陳大同、吳渭渠、林美美等8人", ["陳大同"]), ["吳渭渠", "林美美"])
        self.assertEqual(listed_with("陳大同、被告到場", ["陳大同"]), [])

    def test_more_titles(self):
        self.assertEqual(third_party_names("友人杜英達之帳戶，同事林小美到場"), ["杜英達", "林小美"])

    def test_replaced_everywhere_as_third_party(self):
        names = usable_person_names(["李惠明"])
        self.assertEqual(mask_parties("李惠明於當日將款項交付", "", "", [], names), "【關係人】於當日將款項交付")


if __name__ == "__main__":
    unittest.main()
