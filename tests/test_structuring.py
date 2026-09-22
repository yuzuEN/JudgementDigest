# -*- coding: utf-8 -*-
"""
structuring.py 的離線測試。

測試策略
────────
本檔的測試分成兩類：

1. **規格測試**——針對每個函式的預期行為（中文數字、案由代碼、法條拆解…）。
2. **回歸測試**——標記為 `REGRESSION` 的案例，每一則都對應一個實際發生過的
   缺陷。這些字串全部取自臺北地院 2025 年民事判決的真實主文（去識別化處理
   僅限於原判決書本身已遮蔽的部分）。規則一旦改壞，這裡會先失敗。

之所以要把每個 bug 都寫成測試，是因為這批規則是靠「跑全量→抽樣核對→修規則」
迭代出來的；沒有回歸測試的話，修 A 打破 B 不會有人發現，而資料缺漏是靜默的。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structuring as S  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
class TestCnNumeral(unittest.TestCase):
    """中文數字轉換。"""

    def test_uppercase(self):
        self.assertEqual(S.cn_numeral_to_int("壹佰貳拾參萬肆仟伍佰陸拾柒"), 1234567)

    def test_lowercase(self):
        self.assertEqual(S.cn_numeral_to_int("一百二十三萬四千五百六十七"), 1234567)

    def test_arabic_with_separators(self):
        self.assertEqual(S.cn_numeral_to_int("1,234,567"), 1234567)

    def test_mixed_arabic_and_cn_unit(self):
        # REGRESSION：舊規則不支援「21萬6201」這種混合寫法
        self.assertEqual(S.cn_numeral_to_int("21萬6201"), 216201)
        self.assertEqual(S.cn_numeral_to_int("貳拾壹萬陸仟貳佰零壹"), 216201)
        self.assertEqual(S.cn_numeral_to_int("2,000萬"), 20000000)

    def test_elided_leading_one(self):
        self.assertEqual(S.cn_numeral_to_int("十五"), 15)
        self.assertEqual(S.cn_numeral_to_int("三十"), 30)

    def test_yi(self):
        self.assertEqual(S.cn_numeral_to_int("一億二千三百萬"), 123000000)

    def test_sub_dollar_units_truncated(self):
        # REGRESSION：先去「元」再切「角」會把「貳佰捌拾伍元柒角」接成 337
        self.assertEqual(S.cn_numeral_to_int("貳佰捌拾伍元柒角"), 285)

    def test_unparseable_returns_none(self):
        # REGRESSION：只剩「萬」的殘缺片段必須回 None，
        # 不可默默當成 10000 而憑空捏造金額
        self.assertIsNone(S.cn_numeral_to_int("萬"))
        self.assertIsNone(S.cn_numeral_to_int(""))
        self.assertIsNone(S.cn_numeral_to_int(None))
        self.assertIsNone(S.cn_numeral_to_int("abc"))

    def test_decimal_amounts(self):
        """REGRESSION：小數金額。

        `_AMOUNT_TOKEN` 的字元類原本不含小數點，「2,000,000.5元」的 token
        只能從小數點後起算 →「5元」，金額少 40 萬倍且完全無聲。
        實測全庫 13 筆主文含小數金額，最嚴重一筆 43,009,039.5 元 → 5 元。
        """
        # 純阿拉伯小數：元以下捨去
        self.assertEqual(S.cn_numeral_to_int("2,000,000.5"), 2000000)
        self.assertEqual(S.cn_numeral_to_int("10,000.00"), 10000)
        self.assertEqual(S.cn_numeral_to_int("43,009,039.5"), 43009039)
        # 小數 + 單位：位值解析處理不了小數點，需單獨換算
        self.assertEqual(S.cn_numeral_to_int("1.5億"), 150000000)
        self.assertEqual(S.cn_numeral_to_int("2.5萬"), 25000)
        # 混合寫法的角分（實測 113 年度金字第 74 號：舊版得到 19）
        self.assertEqual(S.cn_numeral_to_int("92萬0084.19"), 920084)

    def test_three_decimals_after_cn_unit_is_a_separator(self):
        """REGRESSION：「856萬7.760元」的點是千分位逗號打成點。

        萬／億之後的餘數必然小於該單位，不可能再有小數；而元以下只有
        角分（2 位）。實測 8 例（55萬3.784、63萬9.534、1億4,991萬7.584…）。
        限定「有國字單位」且「小數恰為 3 位」，才不會誤傷匯率「1:4.415元」
        或每股淨值「14.587元」這類真小數。
        """
        self.assertEqual(S.cn_numeral_to_int("856萬7.760"), 8567760)
        self.assertEqual(S.cn_numeral_to_int("1億4,991萬7.584"), 149917584)
        self.assertEqual(S.cn_numeral_to_int("55萬3.784"), 553784)
        # 沒有國字單位 -> 仍視為小數，元以下捨去
        self.assertEqual(S.cn_numeral_to_int("4.415"), 4)
        self.assertEqual(S.cn_numeral_to_int("2,419.584"), 2419)
        self.assertEqual(S.cn_numeral_to_int("14.587"), 14)

    def test_zero_fragment_is_not_an_amount(self):
        """REGRESSION：「000萬」換算是 0，不可回傳 0 元。

        支援小數 + 單位之後，`000萬` 會match 到該規則並算出 0。
        0 不是金額，必須與「萬」一樣回 None，否則等於憑空捏造一筆 0 元給付。
        """
        self.assertIsNone(S.cn_numeral_to_int("000萬"))
        self.assertIsNone(S.cn_numeral_to_int("0萬"))


# ═══════════════════════════════════════════════════════════════════════════
class TestCaseKind(unittest.TestCase):
    """案由代碼與案件層級。"""

    def test_extract(self):
        self.assertEqual(
            S.extract_case_kind("臺灣臺北地方法院 113 年度訴字第 1234 號民事判決"), "訴")
        self.assertEqual(
            S.extract_case_kind("臺灣臺北地方法院 113 年度重訴字第 5 號民事判決"), "重訴")
        self.assertEqual(
            S.extract_case_kind("臺灣臺北地方法院 113 年度司消債核字第 1 號"), "司消債核")

    def test_categories(self):
        self.assertEqual(S.case_kind_category("訴"), "給付確認")
        self.assertEqual(S.case_kind_category("勞訴"), "給付確認")
        self.assertEqual(S.case_kind_category("除"), "非對審")
        self.assertEqual(S.case_kind_category("簡上"), "上訴抗告")
        self.assertEqual(S.case_kind_category("婚"), "家事形成")

    def test_unknown_kind_falls_back_by_suffix(self):
        # 沒列舉過的新字別要靠字尾推定，不能靜默掉進「未知」
        self.assertEqual(S.case_kind_category("勞小上"), "上訴抗告")
        self.assertEqual(S.case_kind_category("司消債更"), "非對審")

    def test_appended_first_instance_kind_is_not_appeal(self):
        # 「簡上附民移簡」是附帶民事訴訟移送簡易庭後的第一審，不是上訴審
        self.assertEqual(S.case_kind_category("簡上附民移簡"), "給付確認")

    def test_retrial_suffix_inherits_parent_kind(self):
        # 發回更審不改變案件性質。漏掉正規化時「除更一」會從「非對審」
        # 掉進「給付確認」，被算進勝訴率分母（實測全庫 6 筆錯置）。
        self.assertEqual(S.case_kind_category("除更一"), "非對審")
        self.assertEqual(S.case_kind_category("簡上更一"), "上訴抗告")
        self.assertEqual(S.case_kind_category("婚更一"), "家事形成")
        self.assertEqual(S.case_kind_category("再更一"), "上訴抗告")

    def test_retrial_suffix_keeps_ordinary_kinds_unchanged(self):
        # 正規化不能反過來把本來就正確的字別搬走
        self.assertEqual(S.case_kind_category("訴更一"), "給付確認")
        self.assertEqual(S.case_kind_category("重訴更二"), "給付確認")
        self.assertEqual(S.case_kind_category("勞訴更一"), "給付確認")


# ═══════════════════════════════════════════════════════════════════════════
class TestOutcome(unittest.TestCase):
    """訴訟結果分類。"""

    def test_full_win(self):
        v = "被告應給付原告新臺幣100萬元。訴訟費用由被告負擔。"
        self.assertEqual(S.classify_outcome(v)["outcome"], S.WIN)

    def test_full_loss(self):
        self.assertEqual(
            S.classify_outcome("原告之訴駁回。訴訟費用由原告負擔。")["outcome"], S.LOSE)

    def test_partial(self):
        v = "一、被告應給付原告新臺幣26,000元。二、原告其餘之訴駁回。三、訴訟費用由被告負擔5/100，餘由原告負擔。"
        self.assertEqual(S.classify_outcome(v)["outcome"], S.PARTIAL)

    # ── 以下為回歸測試 ────────────────────────────────────────────────

    def test_dismissal_with_provisional_execution_is_still_a_loss(self):
        """REGRESSION：主文被程序性過濾清空導致結果變空值（實測 795 筆）。

        「原告之訴及假執行之聲請均駁回」含有「假執行之聲請」，早期版本用
        抽金額的嚴格過濾規則去判輸贏，整句被丟掉，主文變成空的。
        """
        v = "原告之訴及假執行之聲請均駁回。訴訟費用由原告負擔。"
        self.assertEqual(S.classify_outcome(v)["outcome"], S.LOSE)
        self.assertTrue(S.outcome_clauses(v), "程序性過濾不得把主文清空")

    def test_grant_detection_is_clause_local(self):
        """REGRESSION：把子句接起來再比對，會讓否定環視看見別的判項的「駁回」。

        「被告應給付原告26,000元」＋「原告其餘之訴駁回」黏成一句後，
        准許判項整個消失，一部勝訴被誤判成敗訴（實測 92 筆）。
        """
        v = "一、被告應給付原告新臺幣26,000元。二、原告其餘之訴駁回。"
        self.assertEqual(S.classify_outcome(v)["outcome"], S.PARTIAL)

    def test_counterclaim_dismissal_does_not_taint_main_claim(self):
        """REGRESSION：「反訴原告」裡的「原告」被誤認為本訴原告（實測 24 筆）。"""
        v = ("一、被告應給付原告新臺幣697,088元。二、訴訟費用由被告負擔。"
             "四、反訴原告之訴及假執行之聲請均駁回。")
        r = S.classify_outcome(v)
        self.assertEqual(r["main_outcome"], S.WIN)
        self.assertEqual(r["counter_outcome"], S.LOSE)
        self.assertEqual(r["has_counterclaim"], 1)

    def test_main_loss_with_counter_win_is_separated(self):
        """本訴敗訴、反訴勝訴必須分開記錄，不可壓成單一結果。"""
        v = ("原告之訴及假執行之聲請均駁回。訴訟費用由原告負擔。"
             "反訴被告應給付反訴原告新臺幣10,000,000元。反訴訴訟費用由反訴被告負擔。")
        r = S.classify_outcome(v)
        self.assertEqual(r["main_outcome"], S.LOSE)
        self.assertEqual(r["counter_outcome"], S.WIN)

    def test_provisional_execution_only_dismissal_is_not_partial_loss(self):
        """REGRESSION：只駁回假執行聲請不是實體敗訴。"""
        v = "被告應給付原告新臺幣563,175元。訴訟費用由被告負擔。原告假執行之聲請駁回。"
        self.assertEqual(S.classify_outcome(v)["outcome"], S.WIN)

    def test_long_object_between_ying_and_verb(self):
        """REGRESSION：不動產主文的受詞長達 120 字，窗口太小會整段漏掉。"""
        v = ("被告應將臺北市○○區○○段000000000地號土地（權利範圍：10000分之435）"
             "及其上臺北市○○區○○段○○段00號建物（門牌號碼臺北市○○區○○路○段"
             "00巷0弄00號4樓，權利範圍：全部）移轉登記為劉淺井之全體繼承人公同共有。"
             "訴訟費用由被告負擔。")
        self.assertEqual(S.classify_outcome(v)["outcome"], S.WIN)

    def test_preliminary_and_alternative_claims_dismissed(self):
        """REGRESSION：「先位之訴及備位之訴均駁回」是敗訴，不是「其他/不明確」。"""
        for v in ("原告先位之訴及備位之訴均駁回。訴訟費用由原告負擔。",
                  "原告先、備位之訴均駁回。訴訟費用由原告負擔。"):
            self.assertEqual(S.classify_outcome(v)["outcome"], S.LOSE, v)

    def test_partition_variants(self):
        """REGRESSION：分割共有物的主文寫法分歧，只認「准予分割」會大量漏判。"""
        for v in (
            "兩造共有如附表所示之不動產，應予變賣，所得價金由兩造按應有部分比例分配。",
            "一、兩造就附表一所示被繼承人之遺產，應按附表一「本院認定分割方式」欄所示分割。",
            "如附表一所示兩造土地准予合併分割如附圖三所示。",
            "兩造共有如附表所示之不動產分割由原告單獨取得，原告應補償被告新臺幣532萬9,800元。",
        ):
            self.assertEqual(S.classify_outcome(v)["outcome"], S.PARTITION, v)

    def test_divorce_is_a_grant(self):
        """REGRESSION：形成判決「准原告與被告離婚」不是「其他/不明確」。"""
        self.assertEqual(
            S.classify_outcome("准原告與被告離婚。訴訟費用由被告負擔。")["outcome"], S.WIN)

    def test_confirm_without_the_word_exist(self):
        """REGRESSION：「確認甲對被告有…債權」沒寫「存在」二字，仍是確認判項。"""
        v = "確認雷隆程對被告有新台幣381,192元之債權。原告其餘之訴駁回。"
        self.assertEqual(S.classify_outcome(v)["outcome"], S.PARTIAL)

    def test_reason_bleed_is_truncated(self):
        """REGRESSION：少數判決的主文欄位混入理由段落，會汙染分類。"""
        v = ("原告楊逸建之訴及其假執行之聲請均駁回。"
             "理由一、按原告之訴，有下列各款情形之一者，法院得不經言詞辯論，"
             "逕以判決駁回之。被告應給付原告新臺幣100萬元。")
        self.assertEqual(S.classify_outcome(v)["outcome"], S.LOSE)

    def test_non_final_ruling(self):
        v = "本件應由林宜鈞為原告之承受訴訟人，續行訴訟。"
        self.assertEqual(S.classify_outcome(v)["outcome"], S.NON_FINAL)

    def test_outcome_only_for_adversarial_category(self):
        """非對審／上訴審不輸出 outcome，避免下游誤用。"""
        v = "被告應給付原告新臺幣100萬元。"
        self.assertEqual(S.classify_outcome(v, "非對審")["outcome"], "")
        self.assertEqual(S.classify_outcome(v, "非對審")["main_outcome"], S.WIN)


class TestAppealOutcome(unittest.TestCase):
    def test_dismissed_appeal(self):
        self.assertEqual(S.classify_appeal_outcome("上訴駁回。第二審訴訟費用由上訴人負擔。"), "上訴駁回")

    def test_reversed(self):
        self.assertEqual(
            S.classify_appeal_outcome("原判決廢棄。被上訴人應給付上訴人新臺幣10萬元。"), "原判決廢棄")

    def test_partially_reversed(self):
        self.assertEqual(
            S.classify_appeal_outcome(
                "原判決關於命上訴人給付部分廢棄。上訴人其餘上訴駁回。"), "一部廢棄")

    def test_partially_reversed_with_long_enumeration(self):
        # 主文會逐項列出被廢棄的範圍（金額、利息起算日、假執行、訴訟費用），
        # 「原判決」到「廢棄」實測可隔 168 字。舊的 .{0,40} 視窗讓 549 筆
        # 上訴抗告中的 51 筆被誤判為「上訴駁回」，「一部廢棄」少算 54%。
        self.assertEqual(
            S.classify_appeal_outcome(
                "原判決命上訴人、視同上訴人連帶給付逾新臺幣壹拾陸萬捌仟貳佰零參元"
                "及自民國一百一十三年十二月三十一日起至清償日止，按週年利率"
                "百分之五計算之利息部分，及該部分假執行宣告，暨訴訟費用之裁判均廢棄。"
                "上開廢棄部分，被上訴人在第一審之訴駁回。其餘上訴駁回。"), "一部廢棄")

    def test_reverse_detection_does_not_cross_sentences(self):
        # 放寬視窗不能放寬到跨句：上一句的「原判決」不該和下一句的「廢棄」配對，
        # 否則單純維持原判的案件會被誤標成一部廢棄。
        self.assertEqual(
            S.classify_appeal_outcome(
                "上訴駁回。原判決所命給付部分，上訴人應於確定後履行。"
                "假執行之聲請廢棄。"), "上訴駁回")


# ═══════════════════════════════════════════════════════════════════════════
class TestAmounts(unittest.TestCase):
    """判准金額抽取。"""

    def test_simple(self):
        v = "被告應給付原告新臺幣1,000,000元，及自民國113年1月1日起至清償日止，按年息5%計算之利息。"
        self.assertEqual(S.extract_awarded_amounts(v)["awarded_total"], 1000000)

    def test_security_deposit_is_excluded(self):
        """假執行擔保金不是判准金額。"""
        v = ("被告應給付原告新臺幣100萬元。訴訟費用由被告負擔。"
             "本判決第一項於原告以新臺幣35萬元為被告供擔保後，得假執行。")
        self.assertEqual(S.extract_awarded_amounts(v)["awarded_total"], 1000000)

    def test_multiple_items_are_summed(self):
        """REGRESSION：多筆給付只抓第一筆會系統性低估（實測 14.2% 案件受影響）。"""
        v = ("一、被告應給付原告甲新臺幣100,000元。"
             "二、被告應給付原告乙新臺幣200,000元。三、訴訟費用由被告負擔。")
        r = S.extract_awarded_amounts(v)
        self.assertEqual(r["awarded_total"], 300000)
        self.assertEqual(r["awarded_n_items"], 2)

    def test_no_double_counting_across_windows(self):
        """REGRESSION：同一子句內兩筆給付，視窗重疊會把第二筆算兩次。"""
        v = "被告甲應給付原告新臺幣100,000元、被告乙應給付原告新臺幣200,000元。"
        self.assertEqual(S.extract_awarded_amounts(v)["awarded_total"], 300000)

    def test_breakdown_after_qizhong_is_not_added(self):
        """REGRESSION：「及其中…元」是本金拆解，加總會憑空多算一半。"""
        v = ("被告應給付原告新臺幣708,932元，及其中新臺幣513,935元自民國113年8月10日起"
             "至清償日止，按週年利率7.63%計算之利息。訴訟費用由被告負擔。")
        self.assertEqual(S.extract_awarded_amounts(v)["awarded_total"], 708932)

    def test_currency_is_recorded(self):
        v = "被告應給付原告美金26,663元。訴訟費用由被告負擔。"
        r = S.extract_awarded_amounts(v)
        self.assertEqual(r["awarded_currency"], "USD")
        self.assertEqual(r["awarded_total"], 26663)

    def test_decimal_amount_is_not_truncated(self):
        """REGRESSION：小數金額被截斷成小數點後的尾數。

        實測 114 年度重訴字第 82 號：美金 225,739.99 元被抽成 99 元。
        """
        r = S.extract_awarded_amounts("被告應給付原告美金2,000,000.5元。")
        self.assertEqual(r["awarded_total"], 2000000)
        self.assertEqual(r["awarded_currency"], "USD")
        self.assertEqual(
            S.extract_awarded_amounts("被告應給付原告新臺幣1.5億元。")["awarded_total"],
            150000000)
        # 國字單位 + 阿拉伯小數（實測 113 年度金字第 74 號：舊版得到 19）
        self.assertEqual(
            S.extract_awarded_amounts("被告應給付原告美金92萬0084.19元。")["awarded_total"],
            920084)

    def test_counterclaim_amount_is_not_summed_into_main(self):
        """REGRESSION：反訴金額被併入本訴加總。

        classify_outcome 早就依「反訴」字樣分邊，金額卻一視同仁加總：
        本訴 60 萬 + 反訴 30 萬 -> awarded_total = 90 萬。若請求 100 萬，
        grant_ratio 會算成 0.9（真值 0.6），而且比值仍 < 1，不觸發任何旗標。
        """
        v = ("本訴部分：被告應給付原告新臺幣60萬元。"
             "反訴部分：反訴被告應給付反訴原告新臺幣30萬元。訴訟費用由被告負擔。")
        r = S.extract_awarded_amounts(v)
        self.assertEqual(r["awarded_total"], 600000)      # 只計本訴
        self.assertEqual(r["awarded_n_items"], 1)
        self.assertEqual(r["awarded_has_counter_items"], 1)
        # 反訴金額不丟棄，仍記在 items 裡並標上 side
        self.assertEqual([(i["amount"], i["side"]) for i in r["awarded_items"]],
                         [(600000, "本訴"), (300000, "反訴")])

    def test_counterclaim_only_award_is_not_main_award(self):
        """REGRESSION：主文只有反訴的給付判項時，本訴判准金額是「沒有」。

        實測 33 筆（如 114 年度重訴字第 280 號）本訴被駁回、只有反訴獲准，
        舊版把反訴的 202 萬當成本訴判准，grant_ratio 因此完全是假的。
        """
        v = "一、原告之訴駁回。三、反訴被告應給付反訴原告新臺幣202萬0265元。"
        r = S.extract_awarded_amounts(v)
        self.assertIsNone(r["awarded_total"])
        self.assertEqual(r["awarded_n_items"], 0)
        self.assertEqual(r["awarded_has_counter_items"], 1)

    def test_table_reference_is_flagged(self):
        v = "被告應連帶給付原告如附表「應給付金額」欄所示金額。訴訟費用由被告負擔。"
        self.assertEqual(S.extract_awarded_amounts(v)["awarded_in_table"], 1)

    def test_cn_amount(self):
        v = "被告應給付原告新臺幣陸仟參佰玖拾壹元。"
        self.assertEqual(S.extract_awarded_amounts(v)["awarded_total"], 6391)


class TestJointReleaseClause(unittest.TestCase):
    """
    不真正連帶：主文分列各判項、再以一句話說明重複給付免責。
    兩筆金額其實是同一筆債務，加總會憑空多一倍。
    """

    VERDICT = (
        "被告娜里諾有限公司應給付原告新臺幣肆拾肆萬零捌佰玖拾柒元。"
        "被告曾得華應給付原告新臺幣肆拾肆萬零捌佰玖拾柒元。"
        "前二項給付，如任一被告為給付，其餘被告於給付範圍內，免除給付責任。"
    )

    def test_total_is_withheld_not_summed(self):
        r = S.extract_awarded_amounts(self.VERDICT)
        self.assertIsNone(r["awarded_total"])       # 不是 881794
        self.assertEqual(r["awarded_joint_release"], 1)

    def test_items_are_still_recorded(self):
        # 明細是事實記錄，不因總額作廢而消失——下游要能自行判斷
        r = S.extract_awarded_amounts(self.VERDICT)
        self.assertEqual([i["amount"] for i in r["awarded_items"]], [440897, 440897])
        self.assertEqual(r["awarded_n_items"], 2)

    def test_flagged_as_release_not_extraction_failure(self):
        row = {"verdict": self.VERDICT,
               "case_number": "臺灣臺北地方法院 111 年度訴字第 4265 號民事判決"}
        flags = S.derive_structured_fields(row)["quality_flags"]
        self.assertIn("重複給付免責", flags)
        self.assertNotIn("金額抽取失敗", flags)

    def test_true_joint_liability_is_unaffected(self):
        # 真正連帶（民法 §272）只有一個給付動詞、一筆金額，總額照算
        r = S.extract_awarded_amounts("被告甲、乙應連帶給付原告新臺幣壹拾萬元。")
        self.assertEqual(r["awarded_total"], 100000)
        self.assertEqual(r["awarded_joint_release"], 0)

    def test_single_item_keeps_its_total(self):
        # 只抽到一筆時沒有東西可加，作廢反而丟掉好資料
        r = S.extract_awarded_amounts(
            "被告甲應給付原告新臺幣壹拾萬元。"
            "被告乙於前項給付範圍內負給付責任，如任一被告為給付，"
            "其餘被告於給付範圍內免除給付責任。")
        self.assertEqual(r["awarded_total"], 100000)
        self.assertEqual(r["awarded_joint_release"], 0)

    def test_multi_plaintiff_without_release_still_sums(self):
        # 多原告各自判項沒有免責條款，總額仍應加總（海商字第 2 號的情形）
        r = S.extract_awarded_amounts(
            "被告應給付原告甲新臺幣伍仟伍佰捌拾貳元。"
            "被告應給付原告乙新臺幣壹仟柒佰肆拾肆元。")
        self.assertEqual(r["awarded_total"], 7326)
        self.assertEqual(r["awarded_joint_release"], 0)


# ═══════════════════════════════════════════════════════════════════════════
class TestReliefType(unittest.TestCase):
    def test_money(self):
        self.assertIn("金錢給付", S.extract_relief_type("被告應給付原告新臺幣100萬元。"))

    def test_return_of_non_money_asset_is_not_money(self):
        """REGRESSION：「應返還如附表所示之虛擬資產」不是金錢給付，
        誤列會讓它變成假的「金額抽取失敗」。"""
        r = S.extract_relief_type("被告應返還原告如附表所示之虛擬資產。訴訟費用由被告負擔。")
        self.assertNotIn("金錢給付", r)

    def test_partition(self):
        self.assertIn("形成（分割）",
                      S.extract_relief_type("兩造共有如附表所示之不動產，應予變賣。"))


class TestCostShare(unittest.TestCase):
    """訴訟費用分擔比例（一部勝訴程度的連續代理變數）。"""

    def test_all_on_plaintiff(self):
        self.assertAlmostEqual(S._cost_share_plaintiff("訴訟費用由原告負擔。"), 1.0)

    def test_all_on_defendant(self):
        self.assertAlmostEqual(S._cost_share_plaintiff("訴訟費用由被告負擔。"), 0.0)

    def test_percentage(self):
        self.assertAlmostEqual(
            S._cost_share_plaintiff("訴訟費用由被告負擔百分之二十，餘由原告負擔。"), 0.8)

    def test_fraction_cn(self):
        self.assertAlmostEqual(
            S._cost_share_plaintiff("訴訟費用由被告連帶負擔三分之二，餘由原告負擔。"), 1 / 3, 3)

    def test_slash_fraction(self):
        """REGRESSION：「負擔5/100」分子在前，與國字「X分之Y」相反。"""
        self.assertAlmostEqual(
            S._cost_share_plaintiff("訴訟費用由被告負擔5/100，餘由原告負擔。"), 0.95)

    def test_fullwidth_percent(self):
        """REGRESSION：判決書混用全形％與半形%。"""
        self.assertAlmostEqual(
            S._cost_share_plaintiff("訴訟費用由被告負擔50％，餘由原告負擔。"), 0.5)

    def test_amount_between_keyword_and_verb(self):
        """REGRESSION：「訴訟費用新臺幣14,721元由被告負擔」中間夾了金額。"""
        self.assertAlmostEqual(
            S._cost_share_plaintiff("訴訟費用新臺幣14,721元由被告負擔。"), 0.0)


# ═══════════════════════════════════════════════════════════════════════════
class TestLawCitations(unittest.TestCase):
    """法條引用結構化。"""

    def test_basic(self):
        c = S.extract_law_citations("依民事訴訟法第78條規定。")
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["law"], "民事訴訟法")
        self.assertEqual(c[0]["article"], 78)

    def test_connective_prefix_is_stripped(self):
        """REGRESSION：舊規則貪婪往左吃字，法規名變成「原告依民法」「爰依民事訴訟法」。"""
        for text in ("原告依民法第184條", "爰依民事訴訟法第78條",
                     "訴訟費用負擔之依據：民事訴訟法第78條",
                     "本件上訴為無理由。依民事訴訟法第449條"):
            c = S.extract_law_citations(text)
            self.assertTrue(c, text)
            self.assertIn(c[0]["law"], ("民法", "民事訴訟法"), f"{text} → {c[0]['law']}")

    def test_cn_article_number_is_normalised(self):
        """REGRESSION：中文條號不正規化，第385條與第三百八十五條會被算成兩個法條。"""
        c = S.extract_law_citations("依民事訴訟法第三百八十五條第一項")
        self.assertEqual(c[0]["article"], 385)
        self.assertEqual(c[0]["paragraph"], 1)

    def test_paragraph_and_item_and_position(self):
        """項／款／前後段是不同的請求權基礎，壓成條號會抹平關鍵資訊。"""
        c = S.extract_law_citations("民法第184條第1項前段、第185條第1項")
        self.assertEqual(c[0]["key"], "民法§184第1項前段")
        self.assertEqual(c[1]["law"], "民法")   # 串接引用沿用前一個法規
        self.assertEqual(c[1]["article"], 185)

    def test_article_sub_number(self):
        c = S.extract_law_citations("民事訴訟法第436條之24第2項")
        self.assertEqual(c[0]["article"], 436)
        self.assertEqual(c[0]["sub"], 24)
        self.assertEqual(c[0]["paragraph"], 2)
        self.assertEqual(c[0]["key"], "民事訴訟法§436之24第2項")

    def test_anaphora_same_law(self):
        """REGRESSION：「同法」未回指會變成無意義的法規名。"""
        c = S.extract_law_citations("依民事訴訟法第78條、同法第85條第1項")
        self.assertEqual([x["law"] for x in c], ["民事訴訟法", "民事訴訟法"])

    def test_alias_normalised(self):
        """REGRESSION：「勞基法」與「勞動基準法」不合併會把統計拆散。"""
        c = S.extract_law_citations("依勞基法第22條第2項")
        self.assertEqual(c[0]["law"], "勞動基準法")

    def test_contract_clause_is_excluded(self):
        """契約條款、會員規則不是法規，不得混入法條統計。"""
        self.assertEqual(S.extract_law_citations("系爭契約第3條第1項約定"), [])
        self.assertEqual(S.extract_law_citations("違反會員條款第7條第2項"), [])

    def test_dedup(self):
        c = S.extract_law_citations("民法第184條第1項前段…民法第184條第1項前段")
        self.assertEqual(len(c), 1)

    def test_unknown_law_name_is_dropped_not_guessed(self):
        """白名單之外的名稱寧可丟棄，也不要產生髒值。"""
        self.assertEqual(S.extract_law_citations("依某某不存在法第1條"), [])


# ═══════════════════════════════════════════════════════════════════════════
class TestJudges(unittest.TestCase):
    """法官拆分與角色。"""

    def test_single_judge(self):
        j = S.split_judges("林芳華")
        self.assertEqual(j, [{"name": "林芳華", "role": "獨任", "seat": 0}])

    def test_panel_split_by_fullwidth_semicolon(self):
        """REGRESSION：judges 欄位以全形分號分隔，用頓號切會完全失效。"""
        j = S.split_judges("蔡政哲；鄧晴馨；李桂英")
        self.assertEqual([x["name"] for x in j], ["蔡政哲", "鄧晴馨", "李桂英"])

    def test_presiding_from_signature(self):
        ft = "民事第七庭 審判長法 官 姜悌文\n法 官 賴錦華\n法 官 朱漢寶\n以上正本係照原本作成。"
        j = S.split_judges("姜悌文；賴錦華；朱漢寶", ft)
        self.assertEqual(j[0]["role"], "審判長")
        self.assertEqual(j[1]["role"], "陪席")

    def test_name_regex_must_not_cross_lines(self):
        """REGRESSION：姓名比對用 \\s* 會跨行吃到下一位法官，審判長永遠對不上。"""
        ft = "審判長法 官 姜悌文\n法 官 賴錦華"
        j = S.split_judges("姜悌文；賴錦華", ft)
        self.assertEqual(j[0]["role"], "審判長",
                         "跨行貪婪匹配會抓到「姜悌文法官賴錦」這種不存在的姓名")

    def test_panel_always_has_a_presiding_judge(self):
        """簽名欄沒抓到明示標記時，仍須依慣例指定首位，不能整庭都是陪席。"""
        j = S.split_judges("甲一；乙二；丙三", full_text="（簽名欄缺漏）")
        self.assertEqual(sum(1 for x in j if x["role"] == "審判長"), 1)

    def test_panel_key_is_order_independent(self):
        self.assertEqual(S.panel_key("甲；乙；丙"), S.panel_key("丙；甲；乙"))

    def test_panel_key_agrees_with_split_judges(self):
        """REGRESSION：panel_key 沒有套用姓名過濾，與 judge_count 互相矛盾。"""
        j = "王小明；今日筆錄記載；李大同"
        self.assertEqual(len(S.split_judges(j)), 2)
        self.assertEqual(S.panel_key(j), "李大同|王小明")
        # 整欄都是雜訊時兩者都應為空
        self.assertEqual(S.panel_key("提示原證；當庭可否提供"), "")

    def test_empty(self):
        self.assertEqual(S.split_judges(""), [])


# ═══════════════════════════════════════════════════════════════════════════
class TestCaseTypeNormalisation(unittest.TestCase):
    def test_merges_variants(self):
        """717 種案由不合併，法官×案由的交叉表會稀釋到每格個位數。"""
        for raw in ("損害賠償", "損害賠償等", "侵權行為損害賠償"):
            self.assertEqual(S.normalize_case_type(raw)[1], "侵權", raw)

    def test_strips_parenthetical(self):
        self.assertEqual(S.normalize_case_type("除權判決（股票）")[0], "除權判決")

    def test_categories(self):
        # 借貸案再依原告是否為金融機構細分，見 TestCaseTypeSplit
        self.assertEqual(S.normalize_case_type("清償借款")[1], "民間借貸")
        self.assertEqual(
            S.normalize_case_type("清償借款", "玉山商業銀行股份有限公司")[1], "金融借貸")
        self.assertEqual(S.normalize_case_type("離婚")[1], "身分／家事")
        self.assertEqual(S.normalize_case_type("給付工程款")[1], "契約")


# ═══════════════════════════════════════════════════════════════════════════
class TestClaimedAmountProvenance(unittest.TestCase):
    """請求金額的來源標記——這是全部欄位裡最容易被誤用的一個。"""

    def test_window_stops_at_opposing_pleading(self):
        """REGRESSION：聲明後固定取 1500 字，會把被告答辯的金額算進請求。

        實測抽樣 1,192 筆 claimed_source=直接抽取 的案件，620 筆（52%）的
        視窗內出現對造答辯或反訴聲明字樣。
        """
        far = ("原告起訴主張：聲明：被告應給付原告新臺幣100萬元。"
               + "事實理由略。" * 20
               + "被告則以：原告尚積欠伊新臺幣300萬元等語置辯。"
               + "反訴聲明：反訴被告應給付反訴原告新臺幣300萬元。")
        r = S.extract_claimed_amount(far, "", 600000, "原告部分勝訴")
        self.assertEqual(r["claimed_total"], 1000000)
        self.assertEqual(r["claimed_source"], "直接抽取")

    def test_window_stops_at_counterclaim_statement(self):
        """反訴聲明的金額不是原告的請求。"""
        far = ("聲明：被告應給付原告新臺幣50萬元。"
               "反訴之聲明：反訴被告應給付反訴原告新臺幣80萬元。")
        self.assertEqual(
            S.extract_claimed_amount(far, "", None, "原告勝訴")["claimed_total"], 500000)

    def test_fallback_window_also_stops(self):
        """沒有聲明錨點而退回開頭 1500 字時，同樣要在對造答辯處截斷。

        實測 112 年度訴字第 768 號：主文是「原告之訴駁回」、請求是返還登記
        （非金錢），舊版卻從被告答辯段落湊出 812 萬的「請求金額」。
        """
        far = ("一、原告主張：被告應給付原告新臺幣20萬元。"
               "二、被告則以：原告應給付伊新臺幣500萬元等語置辯。")
        r = S.extract_claimed_amount(far, "", None, "原告勝訴")
        self.assertEqual(r["claimed_total"], 200000)

    def test_direct_extraction(self):
        fr = "原告起訴主張：…並聲明：㈠被告應給付原告新臺幣500,000元。"
        r = S.extract_claimed_amount(fr, "", 300000, S.PARTIAL)
        self.assertEqual(r["claimed_total"], 500000)
        self.assertEqual(r["claimed_source"], "直接抽取")

    def test_inferred_from_verdict_is_labelled(self):
        """REGRESSION：回推值若不標記來源，獲償比例會變成循環論證。"""
        fr = "原告起訴主張：…並聲明：如主文所示。"
        r = S.extract_claimed_amount(fr, "", 800000, S.WIN)
        self.assertEqual(r["claimed_total"], 800000)
        self.assertEqual(r["claimed_source"], "主文回推")

    def test_no_inference_when_not_full_win(self):
        """一部勝訴時不得用判准金額回推請求金額。"""
        fr = "原告起訴主張：…並聲明：如主文所示。"
        r = S.extract_claimed_amount(fr, "", 800000, S.PARTIAL)
        self.assertEqual(r["claimed_source"], "未取得")

    def test_procedural_paragraph_is_not_mistaken_for_claim(self):
        """REGRESSION：程序段落引用民訴 §255 時也含「聲明」二字，
        誤命中會抓到舊聲明或管轄權論述裡的數字。"""
        fr = ("壹、程序部分：按訴狀送達後，原告不得將原訴變更或追加他訴，"
              "但擴張或減縮應受判決事項之聲明者，不在此限，民事訴訟法第255條"
              "第1項第3款定有明文。"
              "貳、實體部分：原告主張…並聲明：被告應給付原告新臺幣900,000元。")
        r = S.extract_claimed_amount(fr, "", None, S.PARTIAL)
        self.assertEqual(r["claimed_total"], 900000)


# ═══════════════════════════════════════════════════════════════════════════
class TestDeriveStructuredFields(unittest.TestCase):
    """單一入口的整合測試。"""

    BASE = {
        "case_number": "臺灣臺北地方法院 113 年度訴字第 1234 號民事判決",
        "case_type": "侵權行為損害賠償",
        "judgment_type": "判決",
        "verdict": ("一、被告應給付原告新臺幣500,000元，及自民國113年1月1日起至清償日止，"
                    "按年息5%計算之利息。二、原告其餘之訴駁回。"
                    "三、訴訟費用由被告負擔百分之五十，餘由原告負擔。"),
        "facts_and_reasons": "原告主張…並聲明：被告應給付原告新臺幣1,000,000元。",
        "facts": "",
        "reasons": "按民法第184條第1項前段規定，並依民事訴訟法第79條。",
        "conclusion": "",
        "applicable_laws": "",
        "judges": "林芳華",
        "full_text": "原 告 甲公司 訴訟代理人 王大明 律師 被 告 某某股份有限公司 法 官 林芳華",
        "defendant": "某某股份有限公司",
        "plaintiff_agent": "王大明",
        "defendant_agent": "",
    }

    def setUp(self):
        self.r = S.derive_structured_fields(dict(self.BASE))

    def test_all_declared_columns_present(self):
        """STRUCTURED_COLUMNS 與實際輸出必須一致，否則寫入 DB 時會少欄位。"""
        for col, _ in S.STRUCTURED_COLUMNS:
            self.assertIn(col, self.r, f"缺少欄位 {col}")
        self.assertEqual(set(self.r), {c for c, _ in S.STRUCTURED_COLUMNS})

    def test_core_values(self):
        self.assertEqual(self.r["case_kind"], "訴")
        self.assertEqual(self.r["case_kind_category"], "給付確認")
        self.assertEqual(self.r["outcome"], S.PARTIAL)
        self.assertEqual(self.r["awarded_amount"], 500000)
        self.assertEqual(self.r["claimed_amount"], 1000000)
        self.assertEqual(self.r["claimed_source"], "直接抽取")
        self.assertAlmostEqual(self.r["grant_ratio"], 0.5)
        self.assertAlmostEqual(self.r["cost_share_plaintiff"], 0.5)
        self.assertEqual(self.r["case_type_category"], "侵權")
        self.assertEqual(self.r["defendant_is_corp"], 1)
        self.assertEqual(self.r["plaintiff_has_lawyer"], 1)
        self.assertEqual(self.r["defendant_has_lawyer"], 0)
        self.assertEqual(self.r["presiding_judge"], "林芳華")
        self.assertEqual(self.r["law_primary"], "民法")

    def test_grant_ratio_requires_direct_claim(self):
        """回推的請求金額不得拿來算獲償比例。"""
        row = dict(self.BASE, facts_and_reasons="原告聲明：如主文所示。",
                   verdict="被告應給付原告新臺幣500,000元。訴訟費用由被告負擔。")
        r = S.derive_structured_fields(row)
        self.assertEqual(r["claimed_source"], "主文回推")
        self.assertIsNone(r["grant_ratio"])

    def test_impossible_ratio_is_voided_not_just_flagged(self):
        """REGRESSION：判准大於請求的比值必須作廢；只標記旗標，下游仍會誤用。"""
        row = dict(self.BASE,
                   verdict="被告應給付原告新臺幣900,000元。訴訟費用由被告負擔。",
                   facts_and_reasons="原告主張…並聲明：被告應給付原告新臺幣100,000元。")
        r = S.derive_structured_fields(row)
        self.assertIsNone(r["grant_ratio"])
        self.assertIn("判准大於請求", r["quality_flags"])

    def test_deterministic(self):
        """同一輸入必須永遠得到同一輸出——這是可重現性的基本要求。"""
        self.assertEqual(S.derive_structured_fields(dict(self.BASE)),
                         S.derive_structured_fields(dict(self.BASE)))

    def test_empty_row_does_not_crash(self):
        r = S.derive_structured_fields({})
        self.assertEqual(r["case_kind"], "")
        self.assertEqual(r["structuring_version"], S.STRUCTURING_VERSION)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ═══════════════════════════════════════════════════════════════════════════
class TestPrimaryLaw(unittest.TestCase):
    """主要法規的挑選。"""

    def test_procedural_law_does_not_win(self):
        """REGRESSION：幾乎每份判決結尾都引用民訴 §78/§79（訴訟費用），
        純比次數的話九成案件的「主要法規」都會變成民事訴訟法，欄位失去資訊量。"""
        c = S.extract_law_citations(
            "按民法第184條第1項前段規定…依民事訴訟法第78條、第79條、第85條判決如主文。")
        self.assertEqual(S._pick_primary_law(c), "民法")

    def test_most_cited_substantive_law_wins(self):
        c = S.extract_law_citations(
            "依勞動基準法第22條、第24條、第39條，及民法第229條，依民事訴訟法第78條。")
        self.assertEqual(S._pick_primary_law(c), "勞動基準法")

    def test_falls_back_to_procedural_when_only_procedural(self):
        c = S.extract_law_citations("依民事訴訟法第436條之32第2項。")
        self.assertEqual(S._pick_primary_law(c), "民事訴訟法")

    def test_empty(self):
        self.assertEqual(S._pick_primary_law([]), "")


class TestSecurityClauseNotOverDropped(unittest.TestCase):
    """REGRESSION：含「供擔保」但同時是實體判項的子句，不得被程序性過濾丟掉。"""

    def test_stay_of_execution_granted(self):
        v = ("聲請人以新臺幣壹拾參萬貳仟元為相對人供擔保後，本院113年度司執字第236910號"
             "清償給付票款強制執行事件，於本院114年度訴字第667號債務人異議之訴事件"
             "判決確定前，准予停止執行。")
        self.assertTrue(S.outcome_clauses(v), "整句都是實體判項，不得被清空")
        self.assertEqual(S.classify_outcome(v)["outcome"], S.WIN)

    def test_pure_security_clause_is_still_dropped(self):
        """純擔保子句仍要被丟掉，否則金額與結果都會被汙染。"""
        v = "被告應給付原告新臺幣100萬元。本判決於原告以新臺幣35萬元為被告供擔保後，得假執行。"
        clauses = S.outcome_clauses(v)
        self.assertTrue(any("應給付" in c for c in clauses))
        self.assertFalse(any("為被告供擔保後" in c for c in clauses))
        self.assertEqual(S.extract_awarded_amounts(v)["awarded_total"], 1000000)


class TestAgentHasLawyer(unittest.TestCase):
    """REGRESSION：代理人欄位只留姓名，「律師」職稱已被解析器剝掉。

    早期版本直接在代理人欄位裡找「律師」二字，結果 10,561 筆的
    plaintiff_has_lawyer / defendant_has_lawyer **全部都是 0**——
    欄位看起來有值，實際上毫無資訊，而且不會有任何錯誤。
    """

    FT = ("臺灣臺北地方法院民事判決 原 告 黃淑音 訴訟 代理人 王仁炫 律師 "
          "被 告 林昀憬 黃語梵 上一人 法定代理人 黃黎兼 訴訟代理人 林瑞陽律師")

    def test_detects_lawyer_via_full_text(self):
        self.assertEqual(S._agent_has_lawyer("王仁炫", self.FT), 1)

    def test_handles_name_adjacent_to_title(self):
        """「林瑞陽律師」中間沒有空格也要認得出來。"""
        self.assertEqual(S._agent_has_lawyer("林瑞陽", self.FT), 1)

    def test_statutory_agent_is_not_a_lawyer(self):
        """法定代理人不是律師，不能誤判。"""
        self.assertEqual(S._agent_has_lawyer("黃黎兼", self.FT), 0)

    def test_multiple_agents_any_lawyer(self):
        self.assertEqual(S._agent_has_lawyer("黃黎兼；林瑞陽", self.FT), 1)

    def test_empty_inputs(self):
        self.assertEqual(S._agent_has_lawyer("", self.FT), 0)
        self.assertEqual(S._agent_has_lawyer("王仁炫", ""), 0)

    def test_agent_field_alone_is_not_enough(self):
        """代理人欄位本身含「律師」二字時也要能運作（防禦性）。"""
        self.assertEqual(S._agent_has_lawyer("王仁炫", "訴訟代理人 王仁炫 律師"), 1)


class TestClaimedSourceDowngrade(unittest.TestCase):
    """REGRESSION：判准大於請求時，來源標記必須一併降級。

    只把 grant_ratio 作廢是不夠的——請求金額欄位仍有值、來源仍寫著
    「直接抽取」，任何照 claimed_source 篩選的分析都會把這批明知不完整的
    資料當成可信資料使用（實測 169 筆）。
    """

    BASE = dict(TestDeriveStructuredFields.BASE)

    def test_source_is_downgraded(self):
        row = dict(self.BASE,
                   verdict="被告應給付原告新臺幣900,000元。訴訟費用由被告負擔。",
                   facts_and_reasons="原告主張…並聲明：被告應給付原告新臺幣100,000元。")
        r = S.derive_structured_fields(row)
        self.assertEqual(r["claimed_source"], "直接抽取（不完整）")
        self.assertIsNone(r["grant_ratio"])
        self.assertIn("判准大於請求", r["quality_flags"])
        self.assertEqual(r["claimed_amount"], 100000, "值要保留，它是請求金額的下界")

    def test_normal_case_keeps_direct_source(self):
        r = S.derive_structured_fields(dict(self.BASE))
        self.assertEqual(r["claimed_source"], "直接抽取")
        self.assertIsNotNone(r["grant_ratio"])

    def test_marginal_excess_is_caught_despite_rounding(self):
        """REGRESSION：round(1.0000295, 4) == 1.0，用四捨五入後的值比較
        會讓「判准比請求多幾十元」的矛盾靜靜溜過去（實測 2 筆）。"""
        row = dict(self.BASE,
                   verdict="被告應給付原告新臺幣1,829,482元。訴訟費用由被告負擔。",
                   facts_and_reasons="原告主張…並聲明：被告應給付原告新臺幣1,829,428元。")
        r = S.derive_structured_fields(row)
        self.assertEqual(r["claimed_source"], "直接抽取（不完整）")
        self.assertIsNone(r["grant_ratio"])

    def test_currency_mismatch_is_flagged(self):
        """幣別不同時兩個金額無從比較，必須標記。"""
        row = dict(self.BASE,
                   verdict="被告應給付原告新臺幣39,000元。訴訟費用由被告負擔。",
                   facts_and_reasons="原告主張…並聲明：被告應給付原告美金87元。")
        r = S.derive_structured_fields(row)
        self.assertIn("判准與請求幣別不同", r["quality_flags"])
        self.assertIsNone(r["grant_ratio"], "跨幣別不得計算比例")


class TestCaseTypeSplit(unittest.TestCase):
    """REGRESSION：「借貸／清償」原本佔 38.2%，一個佔近四成的類別
    在案件組合調整裡等於沒有控制力。"""

    def test_bank_loan_vs_private_loan(self):
        self.assertEqual(
            S.normalize_case_type("清償借款", "中國信託商業銀行股份有限公司")[1], "金融借貸")
        self.assertEqual(S.normalize_case_type("清償借款", "王大明")[1], "民間借貸")

    def test_credit_card_is_its_own_category(self):
        self.assertEqual(S.normalize_case_type("給付簽帳卡消費款等", "台新")[1], "信用卡／消費金融")

    def test_debtor_objection_is_not_a_loan_case(self):
        """債務人異議之訴是強制執行救濟，不是借貸案件。"""
        self.assertEqual(S.normalize_case_type("債務人異議之訴", "王大明")[1], "強制執行救濟")

    def test_plaintiff_is_optional(self):
        """不給原告時仍要能運作（歸為民間借貸）。"""
        self.assertEqual(S.normalize_case_type("清償借款")[1], "民間借貸")

    def test_other_categories_unaffected(self):
        self.assertEqual(S.normalize_case_type("侵權行為損害賠償", "甲")[1], "侵權")
        self.assertEqual(S.normalize_case_type("離婚", "甲")[1], "身分／家事")


class TestJudgeNameGuard(unittest.TestCase):
    """REGRESSION：判決書後附的筆錄／譯文會讓上游解析器把對話當成法官姓名。"""

    def test_transcript_noise_is_rejected(self):
        for junk in ("今日筆錄記載", "政治傾向為你", "准一造辯論判",
                     "本判決不得上", "宣示本件辯論", "對於原告"):
            self.assertFalse(S._is_plausible_judge_name(junk), junk)

    def test_real_names_are_kept(self):
        for name in ("林芳華", "匡偉", "歐陽志豪", "王二"):
            self.assertTrue(S._is_plausible_judge_name(name), name)

    def test_split_judges_filters_noise(self):
        j = S.split_judges("對於原告；今日筆錄記載；林芳華")
        self.assertEqual([x["name"] for x in j], ["林芳華"])
        self.assertEqual(j[0]["role"], "獨任", "濾掉雜訊後只剩一人，應為獨任")

    def test_all_noise_yields_empty(self):
        self.assertEqual(S.split_judges("今日筆錄記載；准一造辯論判"), [])


class TestLawCitationIncludesFacts(unittest.TestCase):
    """REGRESSION：部分判決只有「事　實」一段，論理與法條全寫在裡面。
    法條抽取漏掉 facts 的話這些案件的引用數會是 0（實測 37 筆）。"""

    def test_facts_section_is_scanned(self):
        row = {
            "case_number": "臺灣臺北地方法院 113 年度訴字第 1 號民事判決",
            "case_type": "清償借款", "judgment_type": "判決",
            "verdict": "被告應給付原告新臺幣100,000元。訴訟費用由被告負擔。",
            "facts": "原告主張依民法第478條及第233條規定請求被告返還借款。",
            "reasons": "", "facts_and_reasons": "", "conclusion": "",
            "applicable_laws": "", "judges": "林芳華", "full_text": "法 官 林芳華",
            "defendant": "", "plaintiff": "王大明",
            "plaintiff_agent": "", "defendant_agent": "",
        }
        r = S.derive_structured_fields(row)
        self.assertGreater(r["law_n_citations"], 0, "facts 段的法條必須被抽到")
        self.assertEqual(r["law_primary"], "民法")
        self.assertGreater(r["reasoning_length"], 0, "論理字數必須包含 facts")


# ═══════════════════════════════════════════════════════════════════════════
class TestPartyPosture(unittest.TestCase):
    """上訴審與非訟的當事人不能用 plaintiff/defendant 的語義解讀。"""

    def _row(self, **kw):
        base = {"case_number": "臺灣臺北地方法院 114 年度簡上字第 278 號民事判決",
                "verdict": "上訴駁回。", "judges": "林某", "case_type": "損害賠償",
                "full_text": "", "party_roles": ""}
        base.update(kw)
        return base

    def test_posture_labels(self):
        P = S.party_posture
        self.assertEqual(P({"party_roles": "原告：甲；被告：乙"}), "第一審對審")
        self.assertEqual(P({"party_roles": "上訴人：甲；被上訴人：乙"}), "上訴抗告")
        # 複合稱謂寫出了原審地位，歸第一審對審
        self.assertEqual(P({"party_roles": "上訴人即被告：甲"}), "第一審對審")
        self.assertEqual(P({"party_roles": "抗告人：甲；相對人：乙"}), "上訴抗告")
        self.assertEqual(P({"party_roles": "聲請人：甲"}), "非訟")
        self.assertEqual(P({"party_roles": "公訴人：檢察官；被告：乙"}), "刑事")
        # 「告訴人」不是「被告」
        self.assertEqual(P({"party_roles": "聲請人即告訴人：甲"}), "非訟")
        self.assertEqual(P({"party_roles": ""}), "")

    def test_appeal_lawyer_read_from_appellant_columns(self):
        """REGRESSION：上訴審的 *_has_lawyer 原本一律是 0。

        derive_structured_fields 只讀 plaintiff_agent/defendant_agent，
        上訴審的代理人存在 appellant_agent/appellee_agent，於是 0 是
        「沒資料可算」而不是「沒有律師」。實測 582 + 481 筆被修正為 1。
        """
        d = S.derive_structured_fields(self._row(
            appellant="甲股份有限公司", appellee="乙",
            appellant_agent="王大明", appellee_agent="李小華",
            party_roles="上訴人：甲股份有限公司；被上訴人：乙",
            full_text="上訴人甲股份有限公司訴訟代理人王大明律師被上訴人乙訴訟代理人李小華律師"))
        self.assertEqual(d["party_posture"], "上訴抗告")
        self.assertEqual(d["plaintiff_has_lawyer"], 1)
        self.assertEqual(d["defendant_has_lawyer"], 1)

    def test_appeal_defendant_is_corp_is_not_applicable(self):
        """上訴審沒有「被告」這一造，defendant_is_corp 為 None 而非 0。"""
        d = S.derive_structured_fields(self._row(
            appellant="甲", appellee="乙股份有限公司",
            party_roles="上訴人：甲；被上訴人：乙股份有限公司"))
        self.assertIsNone(d["defendant_is_corp"])

    def test_first_instance_unchanged(self):
        d = S.derive_structured_fields(self._row(
            plaintiff="甲", defendant="乙股份有限公司", plaintiff_agent="張三",
            party_roles="原告：甲；被告：乙股份有限公司",
            full_text="原告甲訴訟代理人張三律師被告乙股份有限公司"))
        self.assertEqual(d["party_posture"], "第一審對審")
        self.assertEqual(d["defendant_is_corp"], 1)
        self.assertEqual(d["plaintiff_has_lawyer"], 1)
        self.assertEqual(d["defendant_has_lawyer"], 0)
