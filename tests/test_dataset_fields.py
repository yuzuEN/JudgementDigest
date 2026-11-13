"""civil.dataset.fields：v6 起從分析用資料庫算樣本母體與結構化變數。"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from civil.dataset import fields as F  # noqa: E402

config.use_data_pipeline()
from structuring import STRUCTURING_VERSION  # noqa: E402

COLS = ["id", "case_number", "court", "judgment_date", "case_kind", "case_kind_category", "case_type_category",
        "case_type_mid", "claim_basis_group", "claim_basis_primary", "outcome", "is_default_judgment",
        "plaintiff_has_lawyer", "defendant_has_lawyer", "defendant_is_corp", "has_counterclaim",
        "structuring_version"]


def row(i, **kw):
    r = {"id": i, "case_number": f"臺灣臺北地方法院 113 年度訴字第 {i} 號民事判決", "court": "臺灣臺北地方法院",
         "judgment_date": "2024-05-01", "case_kind": "訴", "case_kind_category": "給付確認",
         "case_type_category": "侵權", "case_type_mid": "侵權：交通事故", "claim_basis_group": "侵權行為",
         "claim_basis_primary": "民法第184條", "outcome": "勝訴", "is_default_judgment": 0,
         "plaintiff_has_lawyer": 1, "defendant_has_lawyer": 0, "defendant_is_corp": 0, "has_counterclaim": 0,
         "structuring_version": STRUCTURING_VERSION}
    r.update(kw)
    return r


ROWS = [
    row(1),                                                        # 保留：一般
    row(2, case_kind="重訴"),                                       # 保留：重訴
    row(3, case_kind="簡上附民移簡"),                                # 保留：附民移送
    row(4, case_kind="訴更一"),                                     # 保留：更一不影響程序別
    row(5, is_default_judgment=1),                                 # 保留：母體含一造辯論，建資料集時才排除
    row(6, case_kind="簡"),                                         # 排除：簡易
    row(7, case_kind="再"),                                         # 排除：再審
    row(8, case_kind="家訴"),                                       # 排除：家事
    row(9, outcome="分割類"),                                       # 排除：不是四類結果
    row(10, judgment_date="2026-03-02"),                           # 排除：2026 年
    row(11, case_kind_category="上訴抗告"),                         # 排除：不是給付確認
    row(12, defendant_is_corp=None),                               # 排除：沒有「被告」
    row(13, court="臺北簡易庭", case_number="臺北簡易庭 113 年度北簡字第 1 號民事判決"),  # 排除：不是地院
    row(14, case_number="臺灣臺北地方法院 113 年度訴字第 14 號民事裁定"),             # 排除：裁定
]
KEEP = [1, 2, 3, 4, 5]


def make_db(path: Path, rows=ROWS):
    with sqlite3.connect(path) as con:
        con.execute(f"CREATE TABLE judgments ({', '.join(COLS)})")
        con.executemany(f"INSERT INTO judgments VALUES ({', '.join('?' * len(COLS))})",
                        [[r[c] for c in COLS] for r in rows])


class TestProcType(unittest.TestCase):
    def test_kinds(self):
        cases = {"訴": "一般", "勞訴": "一般", "訴更一": "一般", "重訴": "重訴", "重勞訴更一": "重訴",
                 "簡上附民移簡": "附民移送", "附民移": "附民移送", "簡": "簡易小額", "北小": "簡易小額",
                 "再": None, "聲": None, "全": None, "": None, None: None}
        for kind, want in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(F.proc_type(kind), want)


class TestPopulation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "work.db"
        make_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_filters_like_analysis_fields(self):
        d = F.population(self.db)
        self.assertEqual(list(d.id), KEEP)
        self.assertEqual(dict(zip(d.id, d.proc)), {1: "一般", 2: "重訴", 3: "附民移送", 4: "一般", 5: "一般"})
        self.assertEqual(set(d.court_s), {"臺北"})
        self.assertNotIn("plaintiff", d.columns)            # 不輸出當事人姓名
        self.assertTrue((d[F.FLAGS].dtypes == "int64").all())

    def test_build_writes_csv_and_meta(self):
        with mock.patch.object(config, "DATASET_DIR", self.dir):
            F.build("v6", self.db)
            d = F.load_fields("v6")
        self.assertEqual(list(d.id), KEEP)
        meta = json.loads((self.dir / "fields_v6_meta.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["n_cases"], meta["n_contested"], meta["rule_version"], meta["source_db"]),
                         (5, 4, STRUCTURING_VERSION, "work.db"))
        self.assertIn("git_commit", meta)

    def test_build_refuses_db_on_other_rule_version(self):
        db = self.dir / "old.db"
        make_db(db, ROWS + [row(99, structuring_version="2.4.0")])
        with mock.patch.object(config, "DATASET_DIR", self.dir):
            with self.assertRaises(AssertionError):
                F.build("v6", db)
        self.assertFalse((self.dir / "fields_v6.csv").exists())

    def test_build_only_for_db_versions(self):
        with self.assertRaises(AssertionError):
            F.build("v5", self.db)


class TestLoadFields(unittest.TestCase):
    def test_v5_reads_pkl_and_v6_reads_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pd.DataFrame({"id": [1], "src": ["pkl"]}).to_pickle(tmp / "fields.pkl")
            pd.DataFrame({"id": [2], "src": ["csv"]}).to_csv(tmp / "fields_v6.csv", index=False)
            with mock.patch.object(config, "FIELDS_PKL", tmp / "fields.pkl"), \
                    mock.patch.object(config, "DATASET_DIR", tmp):
                self.assertEqual(F.load_fields("v5").src.tolist(), ["pkl"])
                self.assertEqual(F.load_fields("vt").src.tolist(), ["pkl"])     # 測試用的版本名稱照舊讀 pkl
                self.assertEqual(F.load_fields("v6").src.tolist(), ["csv"])


if __name__ == "__main__":
    unittest.main()
