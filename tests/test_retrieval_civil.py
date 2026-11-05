# -*- coding: utf-8 -*-
"""
retrieval/civil.py 的離線測試：哪些判決可以放進檢索、一造辯論與統計層怎麼分，
以及從資料庫讀取時不會改到資料庫。
"""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from retrieval.civil import expanded_row, load_expanded  # noqa: E402

config.use_data_pipeline()
import structuring as S  # noqa: E402

CLAIM = "原告主張被告於民國一一二年三月駕駛自用小客車，在臺北市某路口未注意車前狀況撞傷原告，致原告受有骨折之傷害，支出醫療費用。"
DEFENSE = "被告則以：原告亦與有過失，請求之慰撫金過高，應予酌減等語，資為抗辯。"


def source(**kw):
    return {"id": 1, "case_number": "臺灣臺北地方法院 113 年度訴字第 1 號民事判決", "court": "臺灣臺北地方法院",
            "judgment_date": "2024-05-01", "full_text": "臺灣臺北地方法院民事判決\n本件經言詞辯論終結", "plaintiff": "王小明",
            "defendant": "陳大華", "plaintiff_agent": "", "defendant_agent": "", **kw}


def derived(**kw):
    return {"outcome": "勝訴", "case_kind": "訴", "case_kind_category": "給付確認", "case_type_category": "侵權",
            "case_type_mid": "侵權：交通事故", "section_split_status": "成功", "plaintiff_claim_text": CLAIM,
            "defendant_defense_text": DEFENSE, "court_reasoning_text": "原告之請求有理由。", "is_default_judgment": 0,
            "claimed_amount": 100, "awarded_amount": 100, "grant_ratio": 1.0, **kw}


class TestExpandedRow(unittest.TestCase):
    def test_contested_case_goes_into_statistics(self):
        case, section = expanded_row(source(), derived())
        self.assertEqual((case["default_judgment"], case["in_stats"], case["y"]), (0, 1, 1))
        self.assertEqual(case["year"], "2024")
        self.assertEqual(section["defendant_defense_text"], DEFENSE)
        self.assertEqual(section["plaintiff"], "王小明")

    def test_lost_case_has_y_zero(self):
        self.assertEqual(expanded_row(source(), derived(outcome="敗訴"))[0]["y"], 0)

    def test_small_claims_court_is_kept(self):
        self.assertIsNotNone(expanded_row(source(), derived(case_kind="北小")))
        self.assertIsNotNone(expanded_row(source(), derived(case_kind="北簡")))

    def test_default_judgment_listed_but_not_in_statistics(self):
        for row, d in ((source(), derived(is_default_judgment=1)),
                       (source(full_text="被告未到場，爰依原告之聲請，由其\n一造\n辯論而為判決。"), derived())):
            case, _ = expanded_row(row, d)
            self.assertEqual((case["default_judgment"], case["in_stats"]), (1, 0))

    def test_without_real_defense_not_in_statistics(self):
        absent = "被告經合法通知，未於言詞辯論期日到場，亦未提出任何書狀作何聲明或陳述，本院無從審酌其答辯內容。"
        self.assertGreaterEqual(len(absent), 30, "要比字數門檻長，才測得到「未到場」的判斷")
        for defense in ("", absent, "被告答辯。"):
            case, _ = expanded_row(source(), derived(defendant_defense_text=defense))
            self.assertEqual((case["default_judgment"], case["in_stats"]), (0, 0), defense)

    def test_excluded(self):
        for kw in ({"outcome": "駁回聲請"}, {"outcome": ""}, {"case_kind_category": "上訴抗告"},
                   {"case_type_category": "身分／家事"}, {"case_type_category": "非訟／除權"},
                   {"case_kind": "簡上附民移簡"}, {"case_kind": "家上易"}, {"section_split_status": "失敗"},
                   {"plaintiff_claim_text": "原告主張被告應給付。"}):
            self.assertIsNone(expanded_row(source(), derived(**kw)), kw)

    def test_merged_judgment_excluded(self):
        head = "臺灣臺北地方法院民事判決\n113年度訴字第1號\n113年度訴字第2號\n原告 王小明"
        self.assertIsNone(expanded_row(source(full_text=head), derived()))


class TestLoadExpanded(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "judgments.db"
        cols = ["id INTEGER PRIMARY KEY", "party_posture TEXT", "case_kind_category TEXT"] + \
               [f"{c} TEXT" for c in S.SOURCE_COLUMNS]
        with closing(sqlite3.connect(self.db)) as con:
            con.execute(f"CREATE TABLE judgments ({', '.join(cols)})")
            rows = [(1, "第一審對審", "給付確認", "A"), (2, "第一審對審", "給付確認", "B"),
                    (3, "上訴抗告", "給付確認", "A"), (4, "第一審對審", "非訟", "A"), (5, "第一審對審", "給付確認", "A")]
            con.executemany("INSERT INTO judgments (id, party_posture, case_kind_category, case_number) VALUES (?,?,?,?)", rows)
            con.commit()

    def test_reads_first_instance_across_chunks(self):
        def derive(row):
            return derived(outcome="勝訴" if row["case_number"] == "A" else "駁回聲請")

        with mock.patch.object(S, "derive_structured_fields", derive), mock.patch("builtins.print"):
            corpus, sections = load_expanded(self.db, chunk=2)
        self.assertEqual(list(corpus.id), [1, 5])
        self.assertEqual(list(sections.id), [1, 5])

    def test_database_is_read_only(self):
        before = self.db.read_bytes()
        with mock.patch.object(S, "derive_structured_fields", lambda row: derived()), mock.patch("builtins.print"):
            load_expanded(self.db)
        self.assertEqual(self.db.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
