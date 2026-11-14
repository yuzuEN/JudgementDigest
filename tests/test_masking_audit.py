# -*- coding: utf-8 -*-
"""遮名抽查（retrieval/masking_audit.py）與人名辨識結果檔（retrieval/ner.py）的離線測試，不需要 torch。"""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retrieval import masking_audit as audit  # noqa: E402
from retrieval.ner import read_names  # noqa: E402


def fake_cases(path: Path, n: int = 30, long_id: int = None):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE cases (id INTEGER, case_number TEXT)")
    con.execute("CREATE TABLE sections (id INTEGER PRIMARY KEY, claim TEXT, defense TEXT, court TEXT)")
    for i in range(1, n + 1):
        court = "證人李惠明於當日到庭" if i != long_id else "甲" * (audit.CELL_LIMIT + 10)
        con.execute("INSERT INTO cases VALUES (?, ?)", (i, f"第 {i} 號"))
        con.execute("INSERT INTO sections VALUES (?, ?, ?, ?)", (i, "【原告】騎乘ABC-1234號機車", "【被告】則以", court))
    con.commit()
    con.close()


class TestSample(unittest.TestCase):
    def test_sample_three_sections_per_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "cases.sqlite"
            fake_cases(db)
            rows = audit.sample_rows(db, n=5, seed=1)
        self.assertEqual(rows.id.nunique(), 5)
        self.assertEqual(len(rows), 15)
        self.assertEqual(list(rows.段落[:3]), ["原告主張", "被告答辯", "法院判斷"])

    def test_same_seed_same_cases_and_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "cases.sqlite"
            fake_cases(db)
            a = set(audit.sample_rows(db, n=10, seed=1).id)
            b = set(audit.sample_rows(db, n=10, seed=1).id)
            c = set(audit.sample_rows(db, n=10, seed=1, exclude=a).id)
        self.assertEqual(a, b)
        self.assertFalse(a & c)

    def test_long_section_split_for_excel(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "cases.sqlite"
            fake_cases(db, long_id=3)
            rows = audit.sample_rows(db, ids=[3])
        self.assertEqual(list(rows.段落), ["原告主張", "被告答辯", "法院判斷（1/2）", "法院判斷（2/2）"])
        self.assertTrue((rows.文字.str.len() <= audit.CELL_LIMIT).all())

    def test_hints(self):
        self.assertIn("ABC-1234", audit.hints("騎乘ABC-1234號機車"))
        self.assertIn("李惠明", audit.hints("當日，李惠明於現場"))
        self.assertEqual(audit.hints("車牌號碼000-0000號"), "", "法院遮過的不提示")

    def test_sheet_round_trip_and_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "cases.sqlite"
            fake_cases(db)
            rows = audit.sample_rows(db, n=4, seed=1)
            first, second = rows.id.unique()[:2]
            rows.loc[rows.id == first, "漏遮姓名"] = ["李惠明", "", "李惠明、王大明"]
            rows.loc[rows.id == second, "漏遮車牌"] = ["ABC-1234", "", ""]
            out = audit.write_sheet(rows, Path(tmp) / "a.xlsx", {"抽樣": "test"})
            back = pd.read_excel(out, sheet_name=audit.SHEET)
            self.assertEqual(audit.read_ids([out]), sorted(rows.id.unique()))
        result = audit.score(back).set_index("類別")
        self.assertEqual(result.loc["漏遮姓名", "個數"], 2, "同一件同一個名字只算一次")
        self.assertEqual(result.loc["漏遮姓名", "有問題的件數"], 1)
        self.assertEqual(result.loc["漏遮姓名", "每 100 件"], 50.0)
        self.assertEqual(result.loc["漏遮車牌", "個數"], 1)
        self.assertEqual(result.loc["漏遮身分證", "個數"], 0)


class TestNerFile(unittest.TestCase):
    def test_read_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ner.jsonl"
            p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in
                                   [{"id": 1, "names": ["李惠明"]}, {"id": 2, "names": []}]) + "\n", encoding="utf-8")
            self.assertEqual(read_names(p), {1: ["李惠明"], 2: []})


if __name__ == "__main__":
    unittest.main()
