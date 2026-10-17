# -*- coding: utf-8 -*-
"""
structure_tasks.py 及其合併、標準化後處理的離線測試。

之前完全沒有接入 pytest（只有手動執行 `python structure_tasks.py` 時
才會跑 self_check()），PR #4 review 兩次指出這個缺口。這裡先把
self_check() 接進 pytest，再補今天實際修過的兩個 bug 的回歸測試。
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from merge import merge_workbooks  # noqa: E402
from build_structured_review import HEADERS, build_row  # noqa: E402
from export_structured_db import create_views, import_main_sheet  # noqa: E402
from normalize import normalize_charge, normalize_charges, normalize_law_levels  # noqa: E402
from structure_tasks import (  # noqa: E402
    chinese_number,
    extract_charges,
    extract_execution_fines,
    extract_laws,
    extract_offense_clauses,
    extract_sentences,
    matched_laws,
    main_section,
    resolve_law_references,
    sentence_months,
    sentence_to_months,
    self_check,
    structure_row,
)


class TestParagraphLocalLawReferences(unittest.TestCase):
    """承前法名只能在同一編號大點內指向前方最近的完整法名。"""

    LAWS = {"刑法", "刑事訴訟法", "毒品危害防制條例", "槍砲彈藥刀械管制條例"}

    def test_reference_uses_nearest_compatible_law_in_same_point(self):
        """同條例取最近條例，不取更遠的刑法。"""
        text = (
            "㈠刑法第11條，毒品危害防制條例第2條第2項，"
            "同條例第10條第2項之施用第二級毒品罪。"
        )
        resolved = resolve_law_references(text, self.LAWS)
        self.assertIn("毒品危害防制條例第10條第2項", resolved)

    def test_reference_does_not_cross_numbered_point(self):
        """新大點沒有完整法名時，不沿用上一大點的法名。"""
        text = "㈠毒品危害防制條例第2條。㈡前開條例第10條第2項。"
        resolved = resolve_law_references(text, self.LAWS)
        self.assertIn("㈡前開條例第10條第2項", resolved)

    def test_narrative_ending_in_reference_is_not_a_law_name(self):
        """「再犯該條例」不能反過來被當成完整法名。"""
        text = (
            "（二）毒品危害防制條例第20條規定，若5年後再犯該條例第10條。"
        )
        resolved = resolve_law_references(text, self.LAWS)
        self.assertIn("毒品危害防制條例第10條", resolved)

    def test_elided_article_reuses_nearest_explicit_law_name(self):
        """「刑法第216條、第210條」的第二個條號應承接同一法名。"""
        text = "核被告所為，係犯刑法第216條、第210條之行使偽造私文書罪。"
        resolved = resolve_law_references(text, self.LAWS)
        self.assertIn("刑法第216條、刑法第210條", resolved)

    def test_applied_article_reuses_nearest_explicit_law_name(self):
        """「刑法第176條準用第175條」兩條都屬於後續同一正式罪名。"""
        text = "係犯刑法第176條準用第175條第3項之過失以煤氣炸燬住宅以外之物罪。"
        resolved = resolve_law_references(text, self.LAWS)
        self.assertIn("刑法第176條準用刑法第175條第3項", resolved)
        laws, _ = matched_laws(
            "過失以煤氣炸燬住宅以外之物罪", "", "", resolved, "", "",
        )
        self.assertEqual(laws, ["刑法第176條", "刑法第175條第3項"])


class TestSelfCheck(unittest.TestCase):
    def test_self_check_passes(self):
        """把既有的 self_check() 斷言接進 CI，而不是只能手動執行才會跑到。"""
        self_check()


class TestSentenceMonths(unittest.TestCase):
    """有期徒刑與拘役共用月數欄，但拘役仍保留日數換算的小數精度。"""

    def test_detention_days_are_converted_to_months(self):
        """拘役按 30 日一月換算，避免短期拘役被誤記成 0 或缺值。"""
        self.assertEqual(sentence_to_months("拘役拾日"), 0.33)
        self.assertEqual(sentence_to_months("拘役貳拾日"), 0.67)
        self.assertEqual(sentence_to_months("拘役參拾日"), 1.0)
        self.assertEqual(sentence_to_months("拘役伍拾日"), 1.67)
        self.assertEqual(sentence_months(["拘役拾日", "拘役參拾日"]), ["0.33", "1"])

    def test_other_sentence_types_stay_without_month_value(self):
        """死刑、無期徒刑與罰金仍不硬塞進有限月數。"""
        self.assertIsNone(sentence_to_months("死刑"))
        self.assertIsNone(sentence_to_months("無期徒刑"))
        self.assertIsNone(sentence_to_months("罰金新臺幣壹萬元"))


class TestChineseNumberCommaAmount(unittest.TestCase):
    """
    REGRESSION：處罰金金額含千分位逗號（阿拉伯數字寫法）時，SINGLE_RE／
    TOTAL_RE 原本完全比對不到，整案被誤判成「無刑期」（容嫣於 PR #4
    留言回報：extract_sentences('甲犯竊盜罪，處罰金新臺幣30,000元。')
    原本回傳 ([], '無刑期')）。
    """

    def test_comma_amount_is_recognized_as_a_sentence(self):
        declared, executions = extract_sentences("甲犯竊盜罪，處罰金新臺幣30,000元。")
        self.assertEqual(declared, [])
        self.assertEqual(executions, [])
        self.assertEqual(
            extract_offense_clauses("甲犯竊盜罪，處罰金新臺幣30,000元。")[0]["fine"],
            "罰金新臺幣30,000元",
        )


class TestAlignedOffenseExtraction(unittest.TestCase):
    """罪名、主刑與罰金必須保留相同的主文順序。"""

    def test_primary_and_fine_are_separate_and_aligned(self):
        """併科罰金另存罰金，易科罰金不是宣告罰金。"""
        verdict = (
            "甲犯竊盜罪，處有期徒刑參月，如易科罰金，以新臺幣壹仟元折算壹日；"
            "又犯侵占罪，處有期徒刑陸月，併科罰金新臺幣壹萬元。"
        )
        offenses = extract_offense_clauses(verdict, "甲")
        self.assertEqual([item["charge"] for item in offenses], ["竊盜罪", "侵占罪"])
        self.assertEqual([item["primary"] for item in offenses], ["有期徒刑參月", "有期徒刑陸月"])
        self.assertEqual([item["fine"] for item in offenses], ["", "罰金新臺幣壹萬元"])
        self.assertEqual(extract_execution_fines("應執行罰金新臺幣貳萬元。"), ["罰金新臺幣貳萬元"])

    def test_execution_and_compound_fine_do_not_become_charge(self):
        """應執行刑與併科罰金不能提供罪名描述起點。"""
        verdict = "應執行有期徒刑拾捌年，併科罰金新臺幣壹億元。"
        self.assertEqual(extract_offense_clauses(verdict), [])

    def test_standalone_fine_still_locates_charge_description(self):
        """獨立科罰金是單罪宣告刑，仍可用來定位罪名。"""
        offenses = extract_offense_clauses("甲竊盜，科罰金新臺幣貳仟元。", "甲")
        self.assertEqual([item["charge"] for item in offenses], ["竊盜"])
        self.assertEqual([item["fine"] for item in offenses], ["罰金新臺幣貳仟元"])

    def test_appendix_object_reference_does_not_discard_offense_clause(self):
        """罪名中引用附表物品不是「犯如附表所示之罪」，仍須保留罪刑對齊。"""
        verdict = "甲過失以煤氣炸燬如附表所示之物，致生公共危險，處拘役伍拾日。"
        offenses = extract_offense_clauses(verdict, "甲")
        self.assertEqual(len(offenses), 1)
        self.assertEqual(offenses[0]["primary"], "拘役伍拾日")

    def test_bare_appendix_charge_reference_is_still_discarded(self):
        """只有「犯如附表所示之罪」而無具體罪名時仍不可建立罪刑對齊。"""
        self.assertEqual(
            extract_offense_clauses("甲犯如附表所示之罪，處有期徒刑參月。", "甲"),
            [],
        )

    def test_law_falls_back_only_to_passage_containing_same_charge(self):
        """主文無法條時，只取理由中同時出現該罪名的定罪法條。"""
        reason = "核被告所為，係犯刑法第320條第1項之竊盜罪。另係犯刑法第335條第1項之侵占罪。"
        laws, source = matched_laws("竊盜罪", "竊盜罪", "", reason, "", "")
        self.assertEqual(laws, ["刑法第320條第1項"])
        self.assertEqual(source, "理由")

    def test_compound_supporting_charges_are_split_and_aligned(self):
        """「A罪及B法之B罪」應在原始萃取時拆開，且各自只取得相應法條。"""
        reason = (
            "被告所為，均係犯刑法第339條第1項之詐欺取財罪及"
            "洗錢防制法第14條第1項之一般洗錢罪。"
        )
        self.assertEqual(extract_charges("", reason), ["詐欺取財罪", "一般洗錢罪"])
        fraud_laws, _ = matched_laws("詐欺取財罪", "詐欺罪", "", reason, "", "", normalize_charge)
        laundering_laws, _ = matched_laws("一般洗錢罪", "洗錢罪", "", reason, "", "", normalize_charge)
        self.assertEqual(fraud_laws, ["刑法第339條第1項"])
        self.assertEqual(laundering_laws, ["洗錢防制法第14條第1項"])

    def test_separately_committed_marks_a_formal_charge_conclusion(self):
        """「分別犯」與「係犯」同為正式論罪句型，必須提供罪名與法條。"""
        reason = (
            "核被告所為，分別犯刑法第339條之4第1項第2款之三人以上共同詐欺取財罪、"
            "洗錢防制法第14條第1項之一般洗錢罪。"
        )
        self.assertEqual(
            extract_charges("", reason),
            ["三人以上共同詐欺取財罪", "一般洗錢罪"],
        )
        fraud_laws, _ = matched_laws(
            "三人以上共同詐欺取財罪", "詐欺罪", "", reason, "", "", normalize_charge,
        )
        laundering_laws, _ = matched_laws(
            "一般洗錢罪", "洗錢罪", "", reason, "", "", normalize_charge,
        )
        self.assertEqual(fraud_laws, ["刑法第339條之4第1項第2款"])
        self.assertEqual(laundering_laws, ["洗錢防制法第14條第1項"])

    def test_exact_raw_charge_precedes_standardized_charge_fallback(self):
        """同一粗分類下有不同罪名時，原始罪名精確配對不可混入另一罪的法條。"""
        reason = (
            "核被告所為，各係犯毒品危害防制條例第11條第1項之持有第一級毒品罪、"
            "毒品危害防制條例第11條第2項之持有第二級毒品罪。"
        )
        first_laws, _ = matched_laws(
            "持有第一級毒品罪", "持有毒品罪", "", reason, "", "", normalize_charge,
        )
        second_laws, _ = matched_laws(
            "持有第二級毒品罪", "持有毒品罪", "", reason, "", "", normalize_charge,
        )
        self.assertEqual(first_laws, ["毒品危害防制條例第11條第1項"])
        self.assertEqual(second_laws, ["毒品危害防制條例第11條第2項"])

    def test_multiple_laws_before_one_charge_do_not_absorb_next_charge_law(self):
        """同罪的第216、210條應成組，後續詐欺罪第339條不可混入前罪。"""
        reason = resolve_law_references(
            "核被告所為，係犯刑法第216條、第210條之行使偽造私文書罪、"
            "同法第339條第1項之詐欺取財罪。",
            {"刑法"},
        )
        forgery_laws, _ = matched_laws(
            "行使偽造私文書罪", "偽造文書罪", "", reason, "", "", normalize_charge,
        )
        fraud_laws, _ = matched_laws(
            "詐欺取財罪", "詐欺罪", "", reason, "", "", normalize_charge,
        )
        self.assertEqual(forgery_laws, ["刑法第216條", "刑法第210條"])
        self.assertEqual(fraud_laws, ["刑法第339條第1項"])

    def test_elided_article_after_another_charge_stays_with_its_own_charge(self):
        """後罪省略法名時仍應獨立配對，不併入前一個洗錢罪。"""
        reason = resolve_law_references(
            "核被告所為，係犯洗錢防制法第14條第1項之洗錢罪及"
            "刑法第339條之4第1項第2款之三人以上共同詐欺取財罪、"
            "第339條之2第1項之非法由自動付款設備取財罪。",
            {"刑法", "洗錢防制法"},
        )
        laundering_laws, _ = matched_laws(
            "洗錢罪", "洗錢罪", "", reason, "", "", normalize_charge,
        )
        fraud_laws, _ = matched_laws(
            "三人以上共同詐欺取財罪", "詐欺罪", "", reason, "", "", normalize_charge,
        )
        atm_laws, _ = matched_laws(
            "非法由自動付款設備取財罪", "自動付款設備詐欺罪", "", reason, "", "",
            normalize_charge,
        )
        self.assertEqual(laundering_laws, ["洗錢防制法第14條第1項"])
        self.assertEqual(fraud_laws, ["刑法第339條之4第1項第2款"])
        self.assertEqual(atm_laws, ["刑法第339條之2第1項"])

    def test_law_uses_case_fallback_after_charge_match_fails(self):
        """罪名配對失敗時，取案件層級定罪法條並明確標記備援來源。"""
        applicable = "毒品危害防制條例第10條第2項"
        laws, source = matched_laws("施用第二級毒品", "施用毒品罪", "", "", "", applicable)
        self.assertEqual(laws, ["毒品危害防制條例第10條第2項"])
        self.assertEqual(source, "案件法條備援")


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


class TestVerdictBoundaries(unittest.TestCase):
    """主文內文字不可被當成後續段落標題，罪數也不屬於罪名。"""

    def test_criminal_facts_column_phrase_does_not_truncate_verdict(self):
        """「犯罪事實欄」是主文內文字，不是新段落。"""
        verdict = "主文：蕭某就起訴書犯罪事實欄一犯詐欺得利罪，處罰金新臺幣參仟元。"
        self.assertIn("詐欺得利罪", main_section(verdict))
        self.assertEqual(extract_charges(verdict, ""), ["詐欺得利罪"])

    def test_criminal_facts_summary_phrase_does_not_truncate_verdict(self):
        """「犯罪事實要旨」同樣不是新段落。"""
        verdict = "法官起立朗讀判決主文、犯罪事實要旨。主文：甲犯竊盜罪，處有期徒刑參月。"
        self.assertEqual(extract_charges(verdict, ""), ["竊盜罪"])

    def test_charge_count_is_not_part_of_charge_name(self):
        """「共貳罪」只是罪數，不得併入罪名。"""
        verdict = "犯詐欺取財罪，共貳罪，各處有期徒刑參月。"
        self.assertEqual(extract_charges(verdict, ""), ["詐欺取財罪"])

    def test_recidivist_and_charge_count_suffix_is_removed(self):
        """罪數前夾有「均累犯」時，也不可併入原始罪名。"""
        verdict = "甲共同犯填製不實罪，均累犯，共參罪，各處有期徒刑參月。"
        self.assertEqual(extract_charges(verdict, ""), ["填製不實罪"])

    def test_common_two_and_recidivist_order_are_supported(self):
        """「兩」與「均累犯」不得迫使正則向後吞掉其他罪名。"""
        verdict = (
            "甲犯竊盜罪，共兩罪，均累犯，各處有期徒刑參月；"
            "又犯攜帶兇器竊盜罪，處有期徒刑伍月。"
        )
        self.assertEqual(extract_charges(verdict, ""), ["竊盜罪", "攜帶兇器竊盜罪"])

    def test_variant_financial_three_is_a_charge_count(self):
        """「叄」是參的異體大寫，不得連同「共叄罪」併入罪名。"""
        verdict = "甲犯不當性交罪，共叄罪，各處有期徒刑參月。"
        self.assertEqual(extract_charges(verdict, ""), ["不當性交罪"])

    def test_main_description_without_commit_or_charge_word(self):
        """主文未寫「犯／罪」時，仍可擷取被告名後至宣告刑前的描述。"""
        verdict = "陳某吐氣所含酒精濃度達0.25毫克以上而駕駛動力交通工具，累犯，處有期徒刑伍月。"
        self.assertEqual(
            extract_charges(verdict, "", defendants="陳某"),
            ["吐氣所含酒精濃度達0.25毫克以上而駕駛動力交通工具"],
        )

    def test_attempt_is_kept_in_main_description(self):
        """原始罪名保留未遂，標準類別與既遂合併。"""
        verdict = "甲殺人未遂，處有期徒刑伍年。"
        self.assertEqual(extract_charges(verdict, "", defendants="甲"), ["殺人未遂"])
        self.assertEqual(normalize_charges("[殺人未遂罪]"), "[殺人罪]")

    def test_hit_and_run_precedes_injury(self):
        """含「傷害」的交通事故逃逸罪名仍應優先歸入肇事逃逸類別。"""
        self.assertEqual(
            normalize_charge("駕駛動力交通工具發生交通事故，致人傷害逃逸罪"),
            "肇事逃逸罪",
        )

    def test_drug_impaired_driving_precedes_alcohol_driving(self):
        """服用毒品致不能安全駕駛不應被較廣的「不能安全駕駛」酒駕規則攔截。"""
        self.assertEqual(
            normalize_charge("服用毒品致不能安全駕駛動力交通工具罪"),
            "毒駕罪",
        )

    def test_specific_charge_rules_precede_broad_categories(self):
        """具體罪名不得被妨害名譽、妨害公務、傷害或公共危險等上位分類攔截。"""
        cases = {
            "侮辱公務員罪": "侮辱公務員罪",
            "對於公務員依法執行職務時，當場侮辱": "侮辱公務員罪",
            "公然侮辱罪": "妨害名譽罪",
            "重傷害未遂罪": "重傷罪",
            "放火燒燬他人所有物致生公共危險罪": "放火罪",
            "以不正方法利用自動付款設備詐欺取財罪": "不正利用自動設備罪",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_charge(raw), expected)


class TestMissingChargeGroups(unittest.TestCase):
    def test_fraud_property_descriptions_and_attempts(self):
        for raw in (
            "幫助意圖為自己不法之所有，以詐術使人將本人之物交付",
            "共同意圖為自己不法之所有，以詐術使人將本人之物交付未遂罪",
            "意圖為自己不法之所有，以詐術得財產上不法之利益",
            "詐術取財罪",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_charge(raw), "詐欺罪")

    def test_deception_without_property_does_not_imply_fraud(self):
        self.assertEqual(normalize_charge("以詐術使人施用毒品罪"), "施用毒品罪")
        self.assertEqual(normalize_charge("以詐術招募他人加入犯罪組織罪"), "組織犯罪罪")
        self.assertEqual(normalize_charge("詐術"), "")

    def test_securities_manipulation_and_fraud_remain_separate(self):
        for raw, expected in (
            ("證券交易法第一百七十一條第一項第一款之高買低賣證券罪", "操縱證券交易價格罪"),
            ("證券交易法第一百七十一條第二項之高買證券罪", "操縱證券交易價格罪"),
            ("幫助犯操縱證券交易價格罪", "操縱證券交易價格罪"),
            ("證券交易法第一百七十一條第一項第一款之詐偽罪", "證券詐偽罪"),
            ("非法經營證券業務罪", "非法經營證券業務罪"),
            ("非法經營期貨業務罪", "非法經營期貨業務罪"),
            ("證券交易法第一百七十一條", ""),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_charge(raw), expected)

    def test_sexual_images_do_not_absorb_child_images_or_nonsexual_recordings(self):
        for raw, expected in (
            ("無故攝錄他人性影像罪", "妨害性隱私及不實性影像罪"),
            ("無故攝錄他人性影像未遂罪", "妨害性隱私及不實性影像罪"),
            ("未經他人同意無故散布其性影像", "妨害性隱私及不實性影像罪"),
            ("製作不實性影像罪", "妨害性隱私及不實性影像罪"),
            ("拍攝少年性影像罪", "兒少性剝削罪"),
            ("以違反本人意願之方法使少年被拍攝性影像罪", "兒少性剝削罪"),
            ("持有未滿十八歲之人性影像罪", "兒少性剝削罪"),
            ("對於14歲以上未滿16歲之男子為性交罪及兒童及少年性剝削防制條例第36條第3項之以違反本人意願之方法使少年被拍攝性影像罪",
             "與未成年人性交猥褻罪"),
            ("竊錄身體隱私部位罪", "妨害秘密罪"),
            ("於投票所以攝影器材刺探選舉人圈選選舉票內容", ""),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_charge(raw), expected)

    def test_new_charge_groups_work_in_list_interface(self):
        self.assertEqual(normalize_charges(
            "[詐術取財罪,無故攝錄他人性影像罪,無故攝錄他人性影像未遂罪,高買證券罪]"
        ), "[詐欺罪,妨害性隱私及不實性影像罪,操縱證券交易價格罪]")


class TestLawFallback(unittest.TestCase):
    """理由只含程序法時，必須繼續向事實與適用法條補抓。"""

    def test_procedural_law_does_not_block_substantive_fallback(self):
        """過濾後為空才搜尋下一個來源。"""
        laws = extract_laws(
            "核其所為，係犯刑事訴訟法第299條。",
            "",
            "核其所為，係犯刑法第320條第1項之竊盜罪。",
        )
        self.assertEqual(laws, ["刑法第320條第1項"])

    def test_duplicate_appendix_laws_collapse_to_most_specific_citation(self):
        """全文標題、程序法及同條簡略引文不得污染案件法條備援。"""
        applicable = (
            "中華民國刑法第185條之3。刑法第185條之3第1項第1款。"
            "依刑事訴訟法第451條第1項。"
            "附錄本案所犯法條全文中華民國刑法第185條之3。"
        )
        self.assertEqual(extract_laws("", applicable), ["刑法第185條之3第1項第1款"])


class TestNormalizeLawName(unittest.TestCase):
    """跨法律逐條篩選，保留完整名稱並避免子字串誤命中。"""

    def test_added_articles_accept_chinese_numbers_and_subdivisions(self):
        for raw, key in (
            ("組織犯罪防制條例第三條第1項", "組織犯罪防制條例第3條"),
            ("商業會計法第七十一條第1款", "商業會計法第71條"),
            ("商標法第97條第1項", "商標法第97條"),
            ("家庭暴力防治法第61條第1款", "家庭暴力防治法第61條"),
            ("性騷擾防治法第25條第1項", "性騷擾防治法第25條"),
            ("個人資料保護法第41條", "個人資料保護法第41條"),
            ("藥事法第83條第1項", "藥事法第83條"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_law_levels(f"[{raw}]"), (f"[{key}]", f"[{key}]"))

    def test_excluded_articles_and_unselected_articles_stay_empty(self):
        for raw in (
            "道路交通管理處罰條例第86條", "組織犯罪防制條例第2條",
            "組織犯罪防制條例第12條", "商標法第999條", "藥事法第999條",
            "公司法第999條", "刑法第130條",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_law_levels(f"[{raw}]"), ("", ""))

    def test_mixed_list_deduplicates_and_skips_exclusions(self):
        self.assertEqual(
            normalize_law_levels("[刑法第132條,組織犯罪防制條例第2條,商標法第97條,商標法第九十七條]"),
            ("[刑法第132條,商標法第97條]", "[刑法第132條,商標法第97條]"),
        )

    def test_enforcement_act_is_not_criminal_code(self):
        """低頻刑法施行法不可誤命中入選的刑法第1條。"""
        self.assertEqual(normalize_law_levels("[中華民國刑法施行法第1條之1]"), ("", ""))

    def test_known_prefixes_are_removed_before_matching(self):
        """正式法名前的版本詞不影響標準化。"""
        self.assertEqual(
            normalize_law_levels("[修正前刑法第320條,前開商標法第95條]"),
            ("[刑法第320條]", "[刑法第320條]"),
        )

    def test_explicit_law_need_not_start_label(self):
        """明載的白名單法名可位於論述中，但「同條例」不自動承接。"""
        self.assertEqual(
            normalize_law_levels(
                "[㈱按甲基安非他命為毒品危害防制條例第2條第2項,同條例第10條第2項]"
            ),
            ("[毒品危害防制條例第2條]", "[毒品危害防制條例第2條]"),
        )

    def test_other_criminal_code_does_not_match_criminal_code(self):
        """陸海空軍刑法入選後不可被截成刑法。"""
        self.assertEqual(normalize_law_levels("[依陸海空軍刑法第54條]"),
                         ("[陸海空軍刑法第54條]", "[陸海空軍刑法第54條]"))


class TestMergeDeduplication(unittest.TestCase):
    """合併重疊匯出檔時，同工作表的裁判書連結只保留第一筆。"""

    def test_duplicate_judgment_link_is_skipped(self):
        """使用暫存 Excel 驗證去重，不觸碰實際資料檔。"""
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / "a.xlsx", Path(directory) / "b.xlsx"]
            for path, rows in zip(paths, ((["u1", "A"], ["u2", "B"]), (["u2", "B2"], ["u3", "C"]))):
                workbook = Workbook()
                sheet = workbook.active
                sheet.title = "裁判書資料"
                sheet.append(["裁判書連結", "案件"])
                for row in rows:
                    sheet.append(row)
                workbook.save(path)
            output = Path(directory) / "merged.xlsx"
            self.assertEqual(merge_workbooks(paths, output)["裁判書資料"], 3)
            workbook = load_workbook(output, read_only=True)
            values = list(workbook["裁判書資料"].values)
            self.assertEqual(values[1:], [("u1", "A"), ("u2", "B"), ("u3", "C")])
            workbook.close()


class TestStructuredDatabaseViews(unittest.TestCase):
    """Datasette Views 必須與 Excel 的空值定義一致。"""

    def test_empty_string_and_empty_list_are_missing(self):
        """空字串與 [] 都應進入原始缺值 View，不可被當成有值。"""
        headers = [
            "裁判書連結", "案件結果", "被告狀態", "主文",
            "罪名（原始）", "罪名（標準化）", "法條（對應原始）", "法條（對應標準鍵）",
            "宣告主刑", "宣告主刑（月）", "應執行刑", "應執行刑（月）",
            "單一刑期來源", "刑期資料狀態", "原始缺值欄位", "標準化缺值欄位",
            "刑期月數缺值欄位", "刑期原始缺值欄位",
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "structured.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "罪法刑"
            sheet.append(headers)
            sheet.append(["u1", "有罪", "單被告", "甲犯竊盜罪", "[\"竊盜罪\"]", "[\"竊盜罪\"]", "[[]]", "[[]]", "[\"\"]", "[\"\"]", "[]", "[]", "", "無刑罰", "法", "", "", "宣告刑、應執行刑"])
            sheet.append(["u2", "有罪", "單被告", "乙犯竊盜罪", "[\"竊盜罪\"]", "[\"\"]", "[[\"刑法第320條\"]]", "[[\"\"]]", "[\"拘役30日\"]", "[\"\"]", "[]", "[]", "宣告刑", "僅宣告主刑", "", "罪、法", "宣告刑", "應執行刑"])
            workbook.save(source)
            workbook.close()
            with sqlite3.connect(":memory:") as connection:
                self.assertEqual(import_main_sheet(source, connection), 2)
                create_views(connection)
                self.assertEqual(connection.execute('SELECT count(*) FROM "罪法_原始無值"').fetchone()[0], 1)
                self.assertEqual(connection.execute('SELECT count(*) FROM "罪法_有值但標準化無值"').fetchone()[0], 1)


class TestSingleSentenceDerivation(unittest.TestCase):
    """模型用單一刑期只能由已輸出的應執行刑或逐罪宣告主刑衍生。"""

    def test_aligned_single_primary_becomes_single_sentence(self):
        """一罪一宣告主刑可轉成單一刑期及月數。"""
        row, _ = build_row({
            "裁判字號": "測試", "被告／相對人": "甲", "裁判種類": "判決",
            "案件類型": "測試", "主文": "甲竊盜，處拘役伍拾日。",
            "事實及理由": "核被告所為，係犯刑法第320條第1項之竊盜罪。",
        })
        values = dict(zip(HEADERS, row))
        self.assertEqual(values["宣告主刑"], '["拘役伍拾日"]')
        self.assertEqual(values["單一刑期"], '["拘役伍拾日"]')
        self.assertEqual(values["單一刑期（月）"], '["1.67"]')

    def test_legacy_sheet_uses_the_same_aligned_laws_as_review_sheet(self):
        """舊工作表也要解析「同法」並輸出與新版審核表相同的定罪法條。"""
        source = {
            "裁判字號": "測試", "被告／相對人": "甲", "裁判種類": "判決",
            "案件類型": "測試", "主文": "甲犯幫助詐欺取財罪，處有期徒刑參月。",
            "事實及理由": "核被告所為，係犯刑法第30條第1項、同法第339條第1項之幫助詐欺取財罪。",
        }
        legacy = structure_row(source)
        review, _ = build_row(source)
        values = dict(zip(HEADERS, review))
        self.assertEqual(legacy[5], "[刑法第30條第1項,刑法第339條第1項]")
        self.assertEqual(legacy[6], "[幫助詐欺取財罪]")
        self.assertEqual(values["法條（對應原始）"], '[["刑法第30條第1項","刑法第339條第1項"]]')

    def test_single_appendix_sentence_uses_single_formal_supporting_charge(self):
        """附表罪名與理由正式罪名皆唯一時，可將主文刑期安全地補回同一罪。"""
        row, _ = build_row({
            "裁判字號": "測試", "被告／相對人": "甲", "裁判種類": "判決",
            "案件類型": "測試", "主文": "甲犯如附表所示之罪，處拘役伍拾日。",
            "事實及理由": "核被告所為，係犯刑法第320條第1項之竊盜罪。",
        })
        values = dict(zip(HEADERS, row))
        self.assertEqual(values["罪名（原始）"], '["竊盜罪"]')
        self.assertEqual(values["宣告主刑"], '["拘役伍拾日"]')
        self.assertEqual(values["單一刑期"], '["拘役伍拾日"]')
        self.assertEqual(values["單一刑期（月）"], '["1.67"]')


if __name__ == "__main__":
    unittest.main()
