# -*- coding: utf-8 -*-
"""
判決導讀「法院怎麼認定」（D3）：annotation/guide_batch.py（整篇標註、匯出）與 backend/reasoning.py（對到導讀段落）。
不呼叫 API。
"""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from annotation import guide_batch  # noqa: E402
from annotation.prompts_v6 import PROMPT_VERSION  # noqa: E402
from backend import reasoning  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.settings import Settings  # noqa: E402
from civil.insights import guide_paragraphs  # noqa: E402
from retrieval import build as retrieval_build  # noqa: E402
from tests.test_backend import build_artifacts  # noqa: E402

COLS = ("sample_id, annotator, run_no, label, polarity, quote, confidence, quote_valid, subtype, "
        "manual_version, prompt_version, raw_response, created_at")


def annotate(db: Path, rows: list) -> None:
    """模擬 annotate.py 寫入的標註：rows = [(sample_id, run_no, label, polarity, quote), ...]。"""
    with closing(sqlite3.connect(db)) as con:
        con.executemany(f"INSERT INTO annotations ({COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(s, "m", r, lab, pol, q, "high", 1, None, "v0.6", PROMPT_VERSION, "{}", "t")
                         for s, r, lab, pol, q in rows])
        con.commit()


class TestParseIds(unittest.TestCase):
    def test_parse_ids(self):
        self.assertEqual(guide_batch.parse_ids("101,205 318\n205，7"), [101, 205, 318, 7])
        self.assertEqual(guide_batch.parse_ids("abc"), [])


class TestForCase(unittest.TestCase):
    """reasoning.for_case：引文對到導讀段落、段落內位置、重疊去重、文字變動時重新定位。"""
    CLAIM = "原告主張被告駕車撞傷原告"
    DEFENSE = "被告則以：原告亦與有過失等語"
    COURT = ("一、本件爭點為被告有無過失。二、原告提出診斷證明書為證，在卷可稽，堪信為真實。"
             "三、綜上，原告之請求有理由，應予准許。")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "guide.sqlite"
        self.paras = guide_paragraphs(self.CLAIM, self.DEFENSE, self.COURT)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows):
        with closing(sqlite3.connect(self.db)) as g:
            g.executescript(guide_batch.GUIDE_SCHEMA)
            g.executemany("INSERT INTO reasoning (case_id, unit_idx, label, polarity, basis, quote, span_start, span_end) "
                          "VALUES (?,?,?,?,?,?,?,?)", rows)
            g.executemany("INSERT INTO meta VALUES (?, ?)", [("prompt_version", "p6.0"), ("manual_version", "v0.6")])
            g.commit()

    def row(self, label, quote, pol=None, basis=None, court=None):
        s = (court or self.COURT).index(quote)
        return (1, 0, label, pol, basis, quote, s, s + len(quote))

    def test_maps_to_paragraph(self):
        self.write([self.row("EV", "診斷證明書為證，在卷可稽，堪信為真實", "有利原告", "明示評價"),
                    self.row("CONCL", "原告之請求有理由，應予准許", "有理由")])
        r = reasoning.for_case(self.db, 1, self.COURT, self.paras)
        self.assertEqual((r["labeler"], r["manual_version"]), ("llm-p6.0", "v0.6"))
        self.assertEqual([i["label"] for i in r["items"]], ["EV", "CONCL"])
        for it in r["items"]:
            text = self.paras[it["paragraph"]]["text"]
            self.assertIn(self.paras[it["paragraph"]]["function"], reasoning.COURT_FUNCTIONS)
            self.assertEqual(text[it["start"]:it["end"]], it["quote"])
        self.assertEqual(r["items"][0]["basis"], "明示評價")

    def test_relocates_when_text_changed(self):
        """資料更新後位置不同（例如遮名改了）：用引文重新找；找不到的項目略過。"""
        self.write([self.row("CONCL", "原告之請求有理由，應予准許", "有理由"),
                    (1, 0, "EV", None, None, "這句不在新的判決文字裡", 0, 10)])
        court = "（前言）" + self.COURT
        r = reasoning.for_case(self.db, 1, court, guide_paragraphs(self.CLAIM, self.DEFENSE, court))
        self.assertEqual([i["label"] for i in r["items"]], ["CONCL"])

    def test_dedupe_overlapping_same_label(self):
        """同一標籤、範圍重疊（例如重複的結論）只留較長的一筆；不同標籤可以重疊。"""
        self.write([self.row("CONCL", "原告之請求有理由，應予准許", "有理由"),
                    self.row("CONCL", "原告之請求有理由", "有理由"),
                    self.row("SUB", "原告之請求有理由")])
        r = reasoning.for_case(self.db, 1, self.COURT, self.paras)
        self.assertEqual(sorted((i["label"], i["quote"]) for i in r["items"]),
                         [("CONCL", "原告之請求有理由，應予准許"), ("SUB", "原告之請求有理由")])

    def test_quote_with_mark(self):
        q = "二、原告提出診斷證明書〔略〕堪信為真實"
        s = self.COURT.index("二、原告"); e = self.COURT.index("堪信為真實") + len("堪信為真實")
        self.write([(1, 0, "EV", "有利原告", None, q, s, e)])
        it = reasoning.for_case(self.db, 1, self.COURT, self.paras)["items"][0]
        self.assertTrue(self.paras[it["paragraph"]]["text"][it["start"]:it["end"]].endswith("堪信為真實"))

    def test_no_data(self):
        self.assertIsNone(reasoning.for_case(Path(self.tmp.name) / "沒有.sqlite", 1, self.COURT, self.paras))
        self.assertIsNone(reasoning.for_case(None, 1, self.COURT, self.paras))
        self.write([self.row("CONCL", "原告之請求有理由，應予准許", "有理由")])
        self.assertIsNone(reasoning.for_case(self.db, 999, self.COURT, self.paras))   # 這件沒有標註


class TestExportAnchor(unittest.TestCase):
    def test_ev_requires_evaluation_words(self):
        """匯出時 EV 的引文要有評價用語（規則十）：列舉證據的句子篩掉，堪信⋯⋯保留；其他標籤不篩。"""
        from annotation.sample import SCHEMA
        with tempfile.TemporaryDirectory() as tmp:
            db, out = Path(tmp) / "a.sqlite", Path(tmp) / "guide.sqlite"
            text = "二、原告提出診斷證明書為證，在卷可稽，堪信為真實。三、被告應負賠償責任。"
            with closing(sqlite3.connect(db)) as con:
                con.executescript(SCHEMA)
                con.execute("INSERT INTO paragraphs (sample_id, case_id, para_idx, unit_start, para_text) "
                            "VALUES (1, 7, 0, 100, ?)", (text,))
                con.commit()
            annotate(db, [(1, 1, "EV", "有利原告", "在卷可稽，堪信為真實"),
                          (1, 1, "EV", "有利原告", "原告提出診斷證明書為證"),
                          (1, 1, "SUB", None, "被告應負賠償責任")])
            r = guide_batch.export(db, out)
            self.assertEqual(r["labels"], {"EV": 1, "SUB": 1})
            with closing(sqlite3.connect(out)) as g:
                quote, s, e = g.execute("SELECT quote, span_start, span_end FROM reasoning WHERE label = 'EV'").fetchone()
            self.assertEqual(quote, "在卷可稽，堪信為真實")
            self.assertEqual((s, e), (100 + text.index(quote), 100 + text.index(quote) + len(quote)))


class TestEndToEnd(unittest.TestCase):
    """建檢索資料 → guide_batch build → 三輪標註 → export → 後端導讀 API 回傳 reasoning。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        build_artifacts(base)
        cases = retrieval_build.artifact_dir(base) / "cases.sqlite"
        with closing(sqlite3.connect(cases)) as con:
            cls.case_id, cls.court = con.execute(
                "SELECT s.id, s.court FROM sections s JOIN cases c ON c.id = s.id WHERE c.y = 1 LIMIT 1").fetchone()
        cls.db = base / guide_batch.GUIDE_DIR / "annotation.sqlite"
        cls.built = guide_batch.build(cases, cls.db, [cls.case_id, 99999999])
        with closing(sqlite3.connect(cls.db)) as con:
            sid = con.execute("SELECT sample_id FROM paragraphs WHERE case_id = ?", (cls.case_id,)).fetchone()[0]
        concl, ev = "綜上，原告之請求有理由", "原告提出診斷證明書為證，在卷可稽"
        annotate(cls.db, [(sid, r, "CONCL", "有理由", concl) for r in (1, 2, 3)]
                 + [(sid, r, "EV", "有利原告", ev) for r in (1, 2)]
                 + [(sid, 3, "SUB", None, "本件爭點為被告有無過失")])        # 只有一輪 → 不匯出
        cls.exported = guide_batch.export(cls.db, base / guide_batch.GUIDE_DIR / guide_batch.GUIDE_DB)
        cls.client = TestClient(create_app(Settings(artifacts_dir=base)))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_build(self):
        self.assertEqual(self.built["added"], [self.case_id])
        self.assertEqual(self.built["missing"], [99999999])
        again = guide_batch.build(retrieval_build.artifact_dir(Path(self.tmp.name)) / "cases.sqlite", self.db,
                                  [self.case_id])
        self.assertEqual((again["added"], again["skipped"]), ([], [self.case_id]))   # 已有的判決不重複加入

    def test_export_majority(self):
        # SUB 只有一輪 → 不匯出；EV 的引文只列舉證據、沒有評價用語（規則十）→ 不匯出
        self.assertEqual(self.exported["labels"], {"CONCL": 1})
        self.assertEqual(self.exported["runs"], 3)

    def test_guide_api_returns_reasoning(self):
        r = self.client.get(f"/api/judgments/civil/{self.case_id}/guide").json()
        self.assertEqual(r["labeler"], "rule-v0")                      # 段落標色照舊
        self.assertEqual(r["reasoning"]["labeler"], f"llm-{PROMPT_VERSION}")
        items = {i["label"]: i for i in r["reasoning"]["items"]}
        self.assertEqual(set(items), {"CONCL"})
        for it in items.values():
            text = r["paragraphs"][it["paragraph"]]["text"]
            self.assertEqual(text[it["start"]:it["end"]], it["quote"])
        self.assertEqual(items["CONCL"]["polarity"], "有理由")

    def test_other_case_has_no_reasoning(self):
        with closing(sqlite3.connect(retrieval_build.artifact_dir(Path(self.tmp.name)) / "cases.sqlite")) as con:
            other = con.execute("SELECT id FROM cases WHERE id != ? LIMIT 1", (self.case_id,)).fetchone()[0]
        self.assertIsNone(self.client.get(f"/api/judgments/civil/{other}/guide").json()["reasoning"])

    def test_mock_guide_has_sample_reasoning(self):
        client = TestClient(create_app(Settings(artifacts_dir=Path(self.tmp.name), mode="mock")))
        case_id = client.post("/api/civil/report", json={"text": "被告駕車撞傷我，我想請求賠償醫藥費。" * 3}).json()["similar"][0]["case_id"]
        r = client.get(f"/api/judgments/civil/{case_id}/guide").json()
        self.assertTrue(r["mock"])
        for it in r["reasoning"]["items"]:
            self.assertEqual(r["paragraphs"][it["paragraph"]]["text"][it["start"]:it["end"]], it["quote"])


if __name__ == "__main__":
    unittest.main()
