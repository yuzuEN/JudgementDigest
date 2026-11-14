# -*- coding: utf-8 -*-
"""
civil/insights.py 的離線測試：證據對照、常見抗辯、判准金額範圍與判決導讀的段落標示。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from civil.insights import (EVIDENCE, QUESTIONNAIRE_EVIDENCE, amount_range, defense_table,  # noqa: E402
                            defense_types, evidence_mentions, evidence_table, guide_paragraphs, user_evidence,
                            without_questions)


class TestKeywords(unittest.TestCase):
    def test_evidence_mentions(self):
        text = "原告提出診斷證明書、醫療費用收據及LINE對話紀錄為證"
        self.assertEqual(evidence_mentions(text), ["medical", "receipt", "chat"])
        self.assertEqual(evidence_mentions(""), [])

    def test_defense_types(self):
        text = "被告則以：原告亦與有過失，且請求之慰撫金過高，強制險已理賠等語"
        self.assertEqual(defense_types(text), ["contributory", "excessive", "paid"])

    def test_questionnaire_keys_are_evidence_keys(self):
        """問卷勾選的證據和結果頁的證據要用同一組 key，前端才對得起來。"""
        keys = [k for k, _, _ in EVIDENCE]
        self.assertEqual(QUESTIONNAIRE_EVIDENCE, keys[:6])


class TestUserEvidence(unittest.TestCase):
    Q = "追問：是否有車禍初步分析研判表或監視器畫面？\n回答："

    def test_checkbox_description_and_answer_all_count(self):
        text = "我有診斷證明書。\n" + self.Q + "我有拿到初步分析研判表"
        self.assertEqual(user_evidence(text, ["chat"]), ["medical", "chat", "accident"])

    def test_evidence_not_in_the_questionnaire(self):
        self.assertIn("accident", user_evidence("我已經申請到車禍鑑定報告"))
        self.assertIn("salary", user_evidence("公司有開薪資證明"))

    def test_short_yes_uses_the_question(self):
        self.assertEqual(user_evidence(self.Q + "有"), ["video", "accident"])

    def test_question_alone_is_not_evidence(self):
        self.assertEqual(user_evidence(self.Q + "還不確定"), [])

    def test_negative_answers(self):
        for answer in ("沒有", "沒有研判表", "目前沒有監視器畫面"):
            self.assertEqual(user_evidence(self.Q + answer), [], answer)

    def test_negation_in_the_description(self):
        self.assertEqual(user_evidence("我沒有收據，但是有診斷證明"), ["medical"])

    def test_nothing(self):
        self.assertEqual(user_evidence(""), [])


class TestWithoutQuestions(unittest.TestCase):
    def test_keeps_description_and_answers_only(self):
        text = "我被撞傷。\n追問：有車禍鑑定嗎？\n回答：對方不肯和解"
        self.assertEqual(without_questions(text), "我被撞傷。\n對方不肯和解")

    def test_plain_text_unchanged(self):
        self.assertEqual(without_questions("我被撞傷。\n很痛"), "我被撞傷。\n很痛")


class TestTables(unittest.TestCase):
    def test_evidence_table_shares_and_user_flags(self):
        rows = evidence_table([["medical", "chat"], ["medical"], ["medical", "receipt"], []], ["chat"])
        # 比例相同時照 EVIDENCE 的順序（收據在對話紀錄前面）
        self.assertEqual([r["key"] for r in rows], ["medical", "receipt", "chat"])
        top = rows[0]
        self.assertEqual((top["key"], top["share"], top["user_has"]), ("medical", 0.75, False))
        self.assertTrue(next(r for r in rows if r["key"] == "chat")["user_has"])

    def test_evidence_table_empty(self):
        self.assertEqual(evidence_table([], ["medical"]), [])

    def test_defense_table_top3(self):
        rows = defense_table([["contributory", "excessive"], ["contributory"], ["paid", "offset"], ["limitation"]])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["key"], "contributory")
        self.assertAlmostEqual(rows[0]["share"], 0.5)


class TestAmountRange(unittest.TestCase):
    def test_quantiles_times_claim(self):
        r = amount_range([0.2, 0.4, 0.5, 0.6, 0.8, 1.0], 500_000)
        self.assertEqual(r["n_cases"], 6)
        self.assertLess(r["amount_low"], r["amount_median"])
        self.assertLess(r["amount_median"], r["amount_high"])
        self.assertLessEqual(r["amount_high"], 500_000)
        self.assertEqual(r["amount_median"], 275_000)

    def test_buckets_count_every_case(self):
        r = amount_range([0.1, 0.2, 0.3, 0.5, 0.9, 1.0], 100)
        self.assertEqual([b["count"] for b in r["buckets"]], [2, 1, 1, 0, 2])
        self.assertEqual((r["buckets"][0]["low"], r["buckets"][-1]["high"]), (0, 1))
        self.assertEqual(sum(b["count"] for b in r["buckets"]), r["n_cases"])

    def test_too_few_cases(self):
        self.assertIsNone(amount_range([0.5, 0.6, 0.7], 100_000))

    def test_invalid_ratios_dropped(self):
        self.assertIsNone(amount_range([0, -1, 1.5, None, 0.5, 0.6, 0.7, 0.8], 100))
        self.assertEqual(amount_range([0, 0.5, 0.6, 0.7, 0.8, 0.9], 100)["n_cases"], 5)

    def test_without_claim_gives_ratio_only(self):
        r = amount_range([0.5] * 5, None)
        self.assertNotIn("amount_low", r)
        self.assertEqual(r["ratio_median"], 0.5)


class TestGuide(unittest.TestCase):
    def test_functions(self):
        paras = guide_paragraphs(
            "原告主張：被告駕車撞傷原告。",
            "被告則以：原告亦有過失等語。",
            "一、本件爭點為被告有無過失。二、原告提出診斷證明書為證，堪信為真。三、綜上，原告之請求有理由。")
        self.assertEqual([p["function"] for p in paras], ["claim", "defense", "issue", "evidence", "court"])
        self.assertEqual(paras[2]["label"], "爭點")

    def test_short_headings_are_not_paragraphs(self):
        paras = guide_paragraphs("原告主張：被告未依約付款。二、其他主張內容在這裡。四、", "",
                                 "五、依民法規定應負賠償責任。六、經查：七、原告之請求有理由，應予准許。")
        texts = [p["text"] for p in paras]
        self.assertNotIn("四、", texts)
        self.assertEqual(texts[-1], "六、經查：七、原告之請求有理由，應予准許。")

    def test_long_paragraph_split_at_period(self):
        court = ("法院審酌" + "原告之請求" * 30 + "。") * 4
        paras = guide_paragraphs("", "", court)
        self.assertGreater(len(paras), 1)
        self.assertTrue(all(len(p["text"]) <= 400 for p in paras))
        self.assertEqual("".join(p["text"] for p in paras), court)

    def test_masking_does_not_change_paragraphs(self):
        """遮名標籤比名字長（【關係人12】7 個字），切段與「爭點」「證據」的判斷要和原文一樣。"""
        sentence = "訴外人王大明於當日將款項交付林小美，林小美再轉交陳志強。"
        masked_sentence = "訴外人【關係人11】於當日將款項交付【關係人12】，【關係人12】再轉交【關係人13】。"
        raw_court = "一、" + sentence * 12 + "二、" + sentence * 2 + "兩造爭點在於借款是否成立。"
        masked_court = "一、" + masked_sentence * 12 + "二、" + masked_sentence * 2 + "兩造爭點在於借款是否成立。"
        raw = guide_paragraphs("被告陳志強則以：", "", raw_court)
        masked = guide_paragraphs("被告【被告】則以：", "", masked_court)
        self.assertEqual([p["function"] for p in masked], [p["function"] for p in raw])
        self.assertEqual(len(masked), len(raw))


if __name__ == "__main__":
    unittest.main()
