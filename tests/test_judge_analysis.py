# -*- coding: utf-8 -*-
"""
judge_analysis 的離線測試。

分析程式的 bug 比解析程式更危險：解析錯了通常看得出來（欄位空白、格式怪異），
統計算錯卻會產出一個看起來很合理、實際上是錯的數字。因此這裡對三件事
做嚴格驗證：

  1. Benjamini–Hochberg 校正的實作是否正確（用教科書例子驗）
  2. 案件組合調整是否真的抵銷了案件分派差異（用合成資料驗）
  3. 攤平函式是否正確處理合議庭與空值
"""

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "judge_analysis"))

from src import metrics as M          # noqa: E402
from src.loader import explode_citations, explode_judges   # noqa: E402


class TestBenjaminiHochberg(unittest.TestCase):
    def test_all_null_rejects_nothing(self):
        """全都是大 p 值時不應該有任何顯著結果。"""
        self.assertEqual(M.benjamini_hochberg([0.5, 0.6, 0.9, 0.99]), [False] * 4)

    def test_textbook_example(self):
        """
        BH 的標準例子：p 排序後與 (i/n)·α 比較，取最大的通過者 k，
        排名 1..k 全部拒絕——**包含中間那些單看不通過的**。
        這一點最常被實作錯成「逐一比較」。
        """
        p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
        got = M.benjamini_hochberg(p, alpha=0.05)
        # 門檻 = 0.00625, 0.0125, 0.01875, 0.025, 0.03125, 0.0375, 0.04375, 0.05
        #   i=1: 0.001 ≤ 0.00625 ✓
        #   i=2: 0.008 ≤ 0.0125  ✓  ← 最大的通過者，k=2
        #   i=3: 0.039 > 0.01875 ✗（之後皆不通過）
        self.assertEqual(got, [True, True] + [False] * 6)

    def test_intermediate_values_are_rejected_too(self):
        p = [0.01, 0.02, 0.03, 0.04]
        # 門檻 = 0.0125, 0.025, 0.0375, 0.05；最大通過者是 i=4 → 全部拒絕
        self.assertEqual(M.benjamini_hochberg(p, alpha=0.05), [True] * 4)

    def test_is_less_conservative_than_bonferroni(self):
        p = [0.01] * 10
        bh = M.benjamini_hochberg(p, alpha=0.05)
        bonferroni = [x <= 0.05 / 10 for x in p]
        self.assertGreaterEqual(sum(bh), sum(bonferroni))

    def test_empty(self):
        self.assertEqual(M.benjamini_hochberg([]), [])


class TestNormalTail(unittest.TestCase):
    def test_known_values(self):
        self.assertAlmostEqual(M._norm_sf(1.959964), 0.05, places=5)
        self.assertAlmostEqual(M._norm_sf(2.575829), 0.01, places=5)
        self.assertAlmostEqual(M._norm_sf(0.0), 1.0, places=6)

    def test_symmetric(self):
        self.assertAlmostEqual(M._norm_sf(1.5), M._norm_sf(-1.5))


def _synthetic(judge_specs):
    """
    合成「法官×案件」資料。

    judge_specs: {judge: [(case_type_category, outcome), ...]}
    """
    rows = []
    for judge, cases in judge_specs.items():
        for i, (cat, outcome) in enumerate(cases):
            rows.append({
                "judge": judge, "role": "獨任", "seat": 0,
                "id": f"{judge}-{i}", "case_type_category": cat,
                "outcome": outcome, "is_adversarial": True,
                "plaintiff_won": 1.0 if outcome == "勝訴" else (
                    0.5 if outcome == "一部勝訴一部敗訴" else 0.0),
                "awarded_amount": np.nan, "grant_ratio": np.nan,
                "cost_share_plaintiff": np.nan, "reasoning_length": 1000,
                "is_default_judgment": 0, "defendant_is_corp": 0,
                "defendant_has_lawyer": 0, "judge_count": 1,
                "panel_key": judge, "presiding_judge": judge,
            })
    return pd.DataFrame(rows)


class TestCaseMixAdjustment(unittest.TestCase):
    """
    案件組合調整的核心驗證。

    造兩位法官：
      A 全辦「借貸／清償」（全體勝訴率高）
      B 全辦「侵權」（全體勝訴率低）
    兩人在**各自的案件類型內**都剛好等於該類型的平均。
    正確的調整應該讓兩人的「差異」都接近 0——
    原始勝訴率會相差懸殊，但那是案件分派造成的，不是心證。
    """

    def setUp(self):
        loan_win, loan_lose = 90, 10      # 借貸：90% 勝訴
        tort_win, tort_lose = 30, 70      # 侵權：30% 勝訴
        specs = {
            "A": [("借貸／清償", "勝訴")] * loan_win + [("借貸／清償", "敗訴")] * loan_lose,
            "B": [("侵權", "勝訴")] * tort_win + [("侵權", "敗訴")] * tort_lose,
        }
        self.jc = _synthetic(specs)
        self.cases = self.jc.drop(columns=["judge", "role", "seat"]).copy()
        self.cases["judges_json"] = ""
        self.prof = M.judge_profile(self.jc, self.cases)

    def test_raw_rates_differ_a_lot(self):
        self.assertAlmostEqual(self.prof.loc["A", "全部勝訴率"], 0.90)
        self.assertAlmostEqual(self.prof.loc["B", "全部勝訴率"], 0.30)

    def test_adjusted_difference_is_near_zero(self):
        """調整後兩人都應接近 0——這正是這個方法存在的理由。"""
        self.assertAlmostEqual(self.prof.loc["A", "差異"], 0.0, places=6)
        self.assertAlmostEqual(self.prof.loc["B", "差異"], 0.0, places=6)

    def test_no_false_significance(self):
        self.assertFalse(bool(self.prof.loc["A", "顯著(BH)"]))
        self.assertFalse(bool(self.prof.loc["B", "顯著(BH)"]))

    def test_genuine_deviation_is_detected(self):
        """真的偏離時必須抓得到：C 辦同樣的借貸案，但勝訴率只有 40%。"""
        specs = {
            "A": [("借貸／清償", "勝訴")] * 90 + [("借貸／清償", "敗訴")] * 10,
            "C": [("借貸／清償", "勝訴")] * 40 + [("借貸／清償", "敗訴")] * 60,
        }
        jc = _synthetic(specs)
        cases = jc.drop(columns=["judge", "role", "seat"]).copy()
        cases["judges_json"] = ""
        prof = M.judge_profile(jc, cases)
        self.assertLess(prof.loc["C", "差異"], -0.2)
        self.assertLess(prof.loc["C", "p值"], 0.01)
        self.assertTrue(bool(prof.loc["C", "顯著(BH)"]))

    def test_small_sample_is_not_testable(self):
        """案件數低於門檻的法官不得被標記為顯著。"""
        specs = {
            "A": [("借貸／清償", "勝訴")] * 90 + [("借貸／清償", "敗訴")] * 10,
            "D": [("借貸／清償", "敗訴")] * 5,     # 0% 勝訴，但只有 5 件
        }
        jc = _synthetic(specs)
        cases = jc.drop(columns=["judge", "role", "seat"]).copy()
        cases["judges_json"] = ""
        prof = M.judge_profile(jc, cases)
        self.assertFalse(bool(prof.loc["D", "可檢定"]))
        self.assertFalse(bool(prof.loc["D", "顯著(BH)"]))

    def test_sole_judge_columns_exist(self):
        for c in ("獨任比例", "獨任_對審案件數", "獨任_差異", "獨任_顯著(BH)"):
            self.assertIn(c, self.prof.columns)


class TestExplode(unittest.TestCase):
    def test_panel_expands_to_one_row_per_judge(self):
        cases = pd.DataFrame([{
            "id": 1, "case_number": "X", "case_type_category": "侵權",
            "outcome": "勝訴", "presiding_judge": "甲",
            "judges_json": json.dumps(
                [{"name": "甲", "role": "審判長", "seat": 0},
                 {"name": "乙", "role": "陪席", "seat": 1},
                 {"name": "丙", "role": "陪席", "seat": 2}], ensure_ascii=False),
            "applicable_laws_json": "",
        }])
        out = explode_judges(cases)
        self.assertEqual(len(out), 3)
        self.assertEqual(set(out["judge"]), {"甲", "乙", "丙"})
        self.assertEqual(out[out["judge"] == "甲"]["role"].iloc[0], "審判長")

    def test_missing_or_malformed_json_is_skipped_not_crashed(self):
        cases = pd.DataFrame([
            {"id": 1, "case_number": "A", "case_type_category": "", "outcome": "",
             "presiding_judge": "", "judges_json": "", "applicable_laws_json": ""},
            {"id": 2, "case_number": "B", "case_type_category": "", "outcome": "",
             "presiding_judge": "", "judges_json": "{壞掉的", "applicable_laws_json": "{壞"},
        ])
        self.assertTrue(explode_judges(cases).empty)
        self.assertTrue(explode_citations(cases).empty)

    def test_citations_explode(self):
        cases = pd.DataFrame([{
            "id": 7, "case_number": "X", "case_type_category": "侵權",
            "outcome": "勝訴", "presiding_judge": "甲", "judges_json": "",
            "applicable_laws_json": json.dumps([
                {"law": "民法", "article": 184, "sub": None, "paragraph": 1,
                 "item": None, "position": "前段", "key": "民法§184第1項前段"},
                {"law": "民法", "article": 185, "sub": None, "paragraph": None,
                 "item": None, "position": "", "key": "民法§185"},
            ], ensure_ascii=False),
        }])
        out = explode_citations(cases)
        self.assertEqual(len(out), 2)
        self.assertEqual(out["law"].tolist(), ["民法", "民法"])
        self.assertEqual(out["article"].tolist(), [184, 185])
        # pandas 會把數值欄裡的 None 轉成 NaN，這是預期行為
        paras = out["paragraph"].tolist()
        self.assertEqual(paras[0], 1)
        self.assertTrue(pd.isna(paras[1]))
        self.assertEqual(out["position"].tolist(), ["前段", ""])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestLoaderOnLegacyDatabase(unittest.TestCase):
    """REGRESSION：從未結構化的舊資料庫，應給出可操作的提示而非 traceback。

    load_cases 的 SELECT 直接列出 35 個結構化欄位，舊資料庫沒有這些欄位時
    會拋出 `no such column: case_kind`，下方「結構化欄位全為空」的友善
    SystemExit 只在「欄位存在但為空」時才摸得到。
    """

    def test_missing_columns_raise_friendly_system_exit(self):
        import sqlite3
        import tempfile
        from src.loader import load_cases
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "old.db")
            conn = sqlite3.connect(p)
            conn.execute("CREATE TABLE judgments (id INTEGER, case_number TEXT, court TEXT,"
                         " judgment_date TEXT, judgment_type TEXT)")
            conn.commit()
            conn.close()
            with self.assertRaises(SystemExit) as cm:
                load_cases(p)
            self.assertIn("backfill_structured.py", str(cm.exception))
