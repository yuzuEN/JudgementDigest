# -*- coding: utf-8 -*-
"""
facts.py 的離線測試：事實取得與遮蔽。

案例取自 1015 人工審核抽樣（人工審核抽樣_2018-2023_分層.xlsx「事實」分頁）
發現的問題：範圍太多（結尾帶到案經）、抓錯段落（附件是圖檔時誤抓理由段）、
遮太多（施用、詐欺集團、毒品名稱被遮）、遮太少（酒駕、誹謗的犯意句沒遮）。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from facts import get_fact, leaks, mask_fact, trim_case_origin  # noqa: E402


class TestTrimCaseOrigin(unittest.TestCase):
    """REGRESSION：人工審核 20 筆「範圍太多」，事實結尾帶到「二、案經…移送偵查起訴」。"""

    def test_cuts_trailing_case_origin_with_paragraph_number(self):
        fact = "甲○○於民國110年1月1日在臺北市竊取機車1輛，始悉上情。二、案經臺北市政府警察局大安分局報告偵查起訴。"
        self.assertEqual(trim_case_origin(fact), "甲○○於民國110年1月1日在臺北市竊取機車1輛，始悉上情。")

    def test_cuts_trailing_case_origin_without_number(self):
        fact = "甲○○於民國110年1月1日在臺北市竊取機車1輛，始悉上情。案經乙○○訴由臺北市政府警察局報告偵辦。"
        self.assertEqual(trim_case_origin(fact), "甲○○於民國110年1月1日在臺北市竊取機車1輛，始悉上情。")

    def test_keeps_text_without_case_origin(self):
        fact = "甲○○於民國110年1月1日在臺北市竊取機車1輛，始悉上情。"
        self.assertEqual(trim_case_origin(fact), fact)


class TestGetFact(unittest.TestCase):
    ATTACHED = (
        "主文\n甲○○犯竊盜罪，處拘役10日。\n事實及理由\n"
        "一、本件犯罪事實及證據，均引用檢察官聲請簡易判決處刑書之記載（如附件）。\n"
        "附件：\n臺灣臺北地方檢察署檢察官聲請簡易判決處刑書\n"
        "犯罪事實\n一、甲○○意圖為自己不法之所有，於民國110年1月1日在臺北市○○區竊取機車1輛，始悉上情。\n"
        "二、案經臺北市政府警察局大安分局報告偵辦。\n證據並所犯法條\n一、證據清單…"
    )

    def test_attachment_fact_stops_before_case_origin(self):
        fact, src = get_fact(facts_and_reasons="一、本件犯罪事實及證據，均引用檢察官聲請簡易判決處刑書之記載（如附件）。",
                             full_text=self.ATTACHED)
        self.assertEqual(src, "附件")
        self.assertTrue(fact.startswith("一、甲○○意圖為自己不法之所有"))
        self.assertTrue(fact.endswith("始悉上情。"))

    def test_image_attachment_is_reported_not_guessed(self):
        """REGRESSION：附件是圖檔時，舊版從理由段的「犯罪事實…案經」硬抓，人工審核 2 筆抓錯段落。"""
        full = ("事實及理由\n一、本件犯罪事實及證據，均引用檢察官起訴書之記載（如附件）。\n"
                "二、核被告所為，係犯刑法第320條第1項之竊盜罪。被告犯罪事實明確，案經檢察官起訴。\n附件：（圖片）")
        fact, src = get_fact(facts_and_reasons="一、本件犯罪事實及證據，均引用檢察官起訴書之記載（如附件）。", full_text=full)
        self.assertEqual((fact, src), ("", "附件抓不到"))

    def test_own_fact_section(self):
        fact, src = get_fact(criminal_facts="犯罪事實\n一、甲○○於民國110年1月1日在臺北市竊取機車1輛，始悉上情。\n二、案經乙○○訴由臺北市政府警察局移送偵查。")
        self.assertEqual(src, "事實段")
        self.assertTrue(fact.endswith("始悉上情。"))

    def test_first_paragraph_with_any_second_heading(self):
        """REGRESSION：第二段是「二、證據」時舊版抓不到事實（約 2,700 筆）。"""
        fr = "一、甲○○於民國110年1月1日在臺北市○○路飲用啤酒後騎乘機車上路，經警測得吐氣酒精濃度每公升0.3毫克。二、證據：被告自白。"
        fact, src = get_fact(facts_and_reasons=fr)
        self.assertEqual(src, "事實及理由第一段")
        self.assertTrue(fact.startswith("甲○○於民國110年1月1日"))

    def test_first_paragraph_starting_with_defendant_and_date(self):
        """REGRESSION：「被告翁○○於民國…」開頭的事實被當成理由排除（台北 143 筆）。"""
        fr = "一、被告甲○○於民國108年3月27日晚間6時許飲用啤酒2瓶後，駕駛機車上路，經警測得吐氣酒精濃度每公升0.3毫克。二、證據：被告自白。"
        self.assertEqual(get_fact(facts_and_reasons=fr)[1], "事實及理由第一段")

    def test_first_paragraph_defendant_reasoning_is_rejected(self):
        fr = "一、被告所為係犯刑法第185條之3第1項第1款之不能安全駕駛動力交通工具罪，應予論科。二、爰審酌被告…"
        self.assertEqual(get_fact(facts_and_reasons=fr), ("", "無"))

    def test_attachment_sentence_mentioning_facts_is_not_a_heading(self):
        """REGRESSION：「犯罪事實及證據並所犯法條分敘如下：」被當成標題，事實開頭多一句。"""
        full = ("事實及理由\n一、本件犯罪事實及證據，均引用檢察官聲請簡易判決處刑書之記載（如附件）。\n"
                "附件：\n臺灣臺北地方檢察署檢察官聲請簡易判決處刑書\n被告甲○○…\n上列被告因公共危險案件，業經偵查終結，認宜聲請以簡易判決處刑，茲將\n"
                "犯罪事實及證據並所犯法條分敘如下：\n    犯罪事實\n一、甲○○明知酒後不得駕駛動力交通工具，竟於民國106年10月11日駕車上路。\n"
                "二、案經臺北市政府警察局移送偵辦。\n    證據並所犯法條\n")
        fact, src = get_fact(facts_and_reasons="一、本件犯罪事實及證據，均引用檢察官聲請簡易判決處刑書之記載（如附件）。", full_text=full)
        self.assertEqual(src, "附件")
        self.assertTrue(fact.startswith("一、甲○○明知酒後"), fact)

    def test_first_paragraph_that_is_reasoning_is_rejected(self):
        fr = "一、按刑法第185條之3第1項第1款規定之構成要件，以吐氣所含酒精濃度達每公升0.25毫克為準。二、證據：被告自白。"
        self.assertEqual(get_fact(facts_and_reasons=fr), ("", "無"))


class TestMaskFact(unittest.TestCase):
    def test_intent_clause_is_masked(self):
        """REGRESSION：人工審核遮太少，酒駕的犯意句（改寫過的罪名）沒遮。"""
        out = mask_fact("飲用保力達藥酒1杯後，竟基於酒後駕駛動力交通工具之犯意，騎乘機車上路。", ["不能安全駕駛罪"])
        self.assertIn("基於××之犯意", out)
        self.assertNotIn("酒後駕駛動力交通工具", out)

    def test_intent_clause_with_multiple_charges(self):
        out = mask_fact("共同基於三人以上共同詐欺取財、一般洗錢及參與犯罪組織之犯意聯絡，依指示提款。", [])
        self.assertIn("共同基於××之犯意聯絡", out)

    def test_intent_clause_with_comma(self):
        out = mask_fact("劉○○基於意圖營利，供給賭博場所、聚眾賭博與賭博之犯意，提供居所作為賭博場所。", [])
        self.assertIn("劉○○基於××之犯意，提供居所", out)

    def test_intent_clause_without_zhi_and_other_openers(self):
        """REGRESSION：v1.1 有 5.1% 事實留下「竊盜犯意」「承前竊盜之犯意」這類寫法。"""
        cases = {
            "竟基於意圖為自己不法所有之竊盜犯意，徒手竊取": "竟基於意圖為自己不法所有之××犯意，徒手竊取",
            "復承前竊盜之犯意，接續竊取": "復承前××之犯意，接續竊取",
            "王○○接續前揭公然侮辱犯意，以「王八蛋」辱罵": "王○○接續前揭××犯意，以「王八蛋」辱罵",
            "竟萌生乘機性交之犯意，先褪去": "竟萌生××之犯意，先褪去",
        }
        for src, want in cases.items():
            self.assertEqual(mask_fact(src, []), want)

    def test_intent_modifiers_are_not_masked(self):
        for src in ("基於同一犯意，接續竊取", "承前揭犯意，再次進入", "基於單一犯意接續為之", "基於概括犯意"):
            self.assertEqual(mask_fact(src, []), src)

    def test_charge_name_before_intent_is_masked(self):
        out = mask_fact("另行起意，而有竊盜之故意，竊取財物", ["竊盜罪"])
        self.assertIn("××之故意", out)

    def test_charge_name_before_zhi_fanxing_is_masked(self):
        out = mask_fact("以此方式幫助該詐欺集團遂行詐欺取財及洗錢之犯行。", ["詐欺取財罪", "洗錢罪"])
        self.assertEqual(out, "以此方式幫助該詐欺集團遂行××及××之犯行。")

    def test_intent_clause_keeps_leading_description(self):
        out = mask_fact("基於縱有人以其帳戶實施犯罪亦不違背其本意之幫助詐欺取財之不確定故意，交付帳戶。", [])
        self.assertIn("亦不違背其本意之××之不確定故意", out)

    def test_descriptive_words_are_kept(self):
        """REGRESSION：人工審核遮太多，施用、詐欺集團、侵占入己被遮。"""
        fact = "於同日在住處施用第二級毒品甲基安非他命1次。另將帳戶交予詐欺集團成員，並將卡片侵占入己。"
        out = mask_fact(fact, ["施用第二級毒品罪", "詐欺取財罪", "侵占遺失物罪"])
        self.assertEqual(out, fact)

    def test_charge_name_used_as_name_is_masked(self):
        out = mask_fact("甲○○前因施用毒品案件，經法院判處有期徒刑確定；乙○○所涉詐欺取財罪嫌，另為不起訴處分。",
                        ["施用毒品罪", "詐欺取財罪"])
        self.assertIn("前因××案件", out)
        self.assertIn("所涉××罪嫌", out)

    def test_law_cite_does_not_eat_subject(self):
        """REGRESSION：舊版「任意字＋法」把主詞和毒品名稱一起遮成「××所規定」。"""
        out = mask_fact("甲○○知悉甲基安非他命係毒品危害防制條例第2條第2項第2款所規定之第二級毒品。", [])
        self.assertEqual(out, "甲○○知悉甲基安非他命係××所規定之第二級毒品。")

    def test_leaks(self):
        self.assertTrue(leaks("違反刑法第185條之3規定", []))
        self.assertTrue(leaks("前因竊盜案件入監", ["竊盜罪"]))
        self.assertFalse(leaks("竊取機車1輛", ["竊盜罪"]))
        self.assertFalse(leaks(mask_fact("前因竊盜案件，依刑法第320條第1項論處", ["竊盜罪"]), ["竊盜罪"]))


if __name__ == "__main__":
    unittest.main()
