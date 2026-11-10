# -*- coding: utf-8 -*-
"""
annotation/ 的離線測試：抽樣的切段與判決導讀一致、回應解析、多數決、線索、prompt 的標籤定義。
不呼叫 API。
"""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from annotation import prompts_v3  # noqa: E402
from annotation.annotate import parse_response, reparse  # noqa: E402
from annotation.sample import SCHEMA  # noqa: E402
from annotation.cues import CUES, INTEREST_SERVICE, cue_hits  # noqa: E402
from annotation.sample import build_sample  # noqa: E402
from annotation.spot_check import majority, wilson  # noqa: E402
from civil.insights import _paragraphs  # noqa: E402

COURT = (
    "一、原告主張被告駕車過失撞傷原告，業據提出診斷證明書為證，核與證人所述相符，堪信為真實。"
    "二、被告故意以背於善良風俗之方法加損害於原告，即屬民法第184條第1項後段之侵權行為。"
    "三、本院審酌兩造之身分、地位、資力及原告所受痛苦程度，認原告請求精神慰撫金以20萬元為適當。"
    "四、原告請求自起訴狀繕本送達翌日起至清償日止，按週年利率5%計算之利息，為有理由。"
    "五、本件事證已臻明確，兩造其餘攻擊或防禦方法，經本院斟酌後，認均不足以影響判決結果，爰不逐一論列。"
)


def read(db: Path, sql: str) -> list:
    """查詢後立刻關閉連線（Windows 不能刪除還開著的資料庫檔）。"""
    with closing(sqlite3.connect(db)) as con:
        return con.execute(sql).fetchall()


def make_cases_db(path: Path, n: int = 60) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE cases (row INTEGER PRIMARY KEY, id INTEGER UNIQUE, category TEXT)")
    con.execute("CREATE TABLE sections (id INTEGER PRIMARY KEY, claim TEXT, defense TEXT, court TEXT)")
    for i in range(n):
        con.execute("INSERT INTO cases VALUES (?,?,?)", (i, 100 + i, "侵權行為"))
        con.execute("INSERT INTO sections VALUES (?,?,?,?)", (100 + i, "原告主張", "被告答辯", COURT))
    con.commit()
    con.close()


class TestSample(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cases = Path(self.tmp.name) / "cases.sqlite"
        self.out = Path(self.tmp.name) / "out" / "annotation.sqlite"
        make_cases_db(self.cases)

    def tearDown(self):
        self.tmp.cleanup()

    def test_paragraphs_match_reading_guide(self):
        """抽出的段落文字與序號要和判決導讀的 _paragraphs() 完全一致，標註才對得回導讀頁。"""
        build_sample(self.cases, self.out, n_random=6, n_enriched=2, seed=1)
        guide = _paragraphs(COURT)
        rows = read(self.out, "SELECT para_idx, n_paras, para_text, prev_text FROM paragraphs")
        self.assertTrue(rows)
        for idx, n, text, prev in rows:
            self.assertEqual(n, len(guide))
            self.assertEqual(text, guide[idx])
            self.assertEqual(prev, guide[idx - 1] if idx > 0 else "")

    def test_batches_and_one_paragraph_per_case(self):
        counts = build_sample(self.cases, self.out, n_random=6, n_enriched=2, seed=1)
        self.assertEqual(sum(counts["random"].values()), 6)
        self.assertEqual(counts["enriched"], {"DAM": 2, "SUB": 2, "SERVICE": 2})
        case_ids = [r[0] for r in read(self.out, "SELECT case_id FROM paragraphs")]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        # 加抽的段落一定含有該類線索
        for batch, text in read(self.out, "SELECT batch, para_text FROM paragraphs WHERE batch LIKE 'enriched:%'"):
            self.assertRegex(text, CUES[batch.split(":")[1]])

    def test_same_seed_same_sample(self):
        build_sample(self.cases, self.out, n_random=6, n_enriched=2, seed=7)
        first = read(self.out, "SELECT case_id, para_idx FROM paragraphs")
        build_sample(self.cases, self.out, n_random=6, n_enriched=2, seed=7)
        second = read(self.out, "SELECT case_id, para_idx FROM paragraphs")
        self.assertEqual(first, second)


class TestParseResponse(unittest.TestCase):
    PARA = "本院審酌兩造之身分、地位，認原告請求精神慰撫金以20萬元為適當"

    def test_valid_labels_and_quote_check(self):
        raw = ('{"reasoning_present": true, "labels": ['
               '{"code": "DAM", "quote": "認原告請求精神慰撫金以20萬元為適當", "polarity": "全額准許", "confidence": "high"},'
               '{"code": "EV", "quote": "這句不在原文裡", "polarity": "有利原告", "confidence": "low"}]}')
        rows = parse_response(raw, self.PARA)
        self.assertEqual([(r[0], r[1], r[4]) for r in rows], [("DAM", "全額准許", 1), ("EV", "有利原告", 0)])

    def test_markdown_fence_and_none(self):
        raw = '```json\n{"reasoning_present": false, "labels": [{"code": "NONE", "quote": "", "polarity": null, "confidence": "high"}]}\n```'
        self.assertEqual(parse_response(raw, self.PARA), [("NONE", None, "", "high", 1)])

    def test_reasoning_before_json(self):
        """v0.3 試標：模型先寫推理說明，最後才附 JSON。"""
        raw = ('這段是在核定慰撫金，法院審酌身分地位後認定金額，標 DAM。\n\n'
               '{"reasoning_present": true, "labels": [{"code": "DAM", "quote": "認原告請求精神慰撫金以20萬元為適當", '
               '"polarity": "全額准許", "confidence": "medium"}]}')
        self.assertEqual(parse_response(raw, self.PARA)[0][:2], ("DAM", "全額准許"))

    def test_self_correction_takes_last_json(self):
        """v0.3 試標：模型給了答案又自我修正，應取最後（修正後）的那個。"""
        raw = ('{"labels": [{"code": "EV", "quote": "不在原文", "polarity": "有利原告", "confidence": "low"}]}\n\n'
               'Wait — 引文出自後段，修正如下：\n\n'
               '{"labels": [{"code": "DAM", "quote": "精神慰撫金以20萬元為適當", "polarity": "不明", "confidence": "low"}]}')
        rows = parse_response(raw, self.PARA)
        self.assertEqual([(r[0], r[4]) for r in rows], [("DAM", 1)])

    def test_invalid_label_polarity_and_parse_error(self):
        raw = '{"labels": [{"code": "SENT", "quote": "精神慰撫金", "polarity": "很多", "confidence": "high"}]}'
        label, pol, _, _, valid = parse_response(raw, self.PARA)[0]
        self.assertEqual((label, pol, valid), ("INVALID:SENT", "INVALID:很多", 0))  # SENT 是刑事標籤
        self.assertEqual(parse_response("不是 JSON", self.PARA)[0][0], "PARSE_ERROR")


class TestReparse(unittest.TestCase):
    def test_reparse_recovers_old_parse_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "annotation.sqlite"
            para = "本院審酌兩造之身分、地位，認原告請求精神慰撫金以20萬元為適當"
            good = ('說明文字。{"labels": [{"code": "DAM", "quote": "精神慰撫金以20萬元為適當", '
                    '"polarity": "全額准許", "confidence": "high"}]}')
            with closing(sqlite3.connect(db)) as con:
                con.executescript(SCHEMA)
                con.execute("INSERT INTO paragraphs (sample_id, para_text) VALUES (1001, ?)", (para,))
                con.execute("INSERT INTO paragraphs (sample_id, para_text) VALUES (1002, ?)", (para,))
                cols = ("sample_id, annotator, run_no, label, polarity, quote, confidence, quote_valid, "
                        "manual_version, prompt_version, raw_response, created_at")
                con.executemany(f"INSERT INTO annotations ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
                    (1001, "m", 1, "PARSE_ERROR", None, None, None, 0, "v0.3", "p3.0", good, "t"),
                    (1002, "m", 1, "PARSE_ERROR", None, None, None, 0, "v0.3", "p3.0", "完全不是 JSON", "t"),
                ])
                con.commit()
            self.assertEqual(reparse(db), (2, 1))
            rows = read(db, "SELECT sample_id, label, polarity, quote_valid FROM annotations ORDER BY sample_id")
            self.assertEqual(rows, [(1001, "DAM", "全額准許", 1), (1002, "PARSE_ERROR", None, 0)])
            self.assertEqual(reparse(db), (1, 0))   # 再跑一次不會重複寫入


class TestSpotCheck(unittest.TestCase):
    def test_majority(self):
        rr = {1: {"EV": 0, "SUB": 0}, 2: {"EV": 0}, 3: {"NONE": 0}}
        self.assertEqual(majority(rr), {"EV"})
        self.assertEqual(majority({1: {"NONE": 0}, 2: {"DAM": 0}, 3: {"EV": 0}}), {"NONE"})

    def test_wilson(self):
        lo, hi = wilson(20, 25)
        self.assertAlmostEqual(lo, 0.6087, places=4)
        self.assertAlmostEqual(hi, 0.9114, places=4)
        lo, hi = wilson(25, 25)   # 全部符合時上界是 1，下界仍小於 1
        self.assertAlmostEqual(hi, 1.0, places=4)
        self.assertLess(lo, 0.9)


class TestCuesAndPrompts(unittest.TestCase):
    def test_cues(self):
        self.assertEqual(cue_hits("本院審酌兩造身分地位，認慰撫金以20萬元為適當"), ["DAM"])
        self.assertIn("SUB", cue_hits("核被告所為，係犯刑法第339條第1項之詐欺取財罪"))
        self.assertTrue(INTEREST_SERVICE.search("自起訴狀繕本送達翌日起至清償日止"))
        self.assertFalse(INTEREST_SERVICE.search("該訴狀繕本於114年3月12日寄存送達於被告"))

    def test_every_label_is_defined_in_prompt(self):
        for label in prompts_v3.LABELS_CIVIL[:-1]:
            self.assertIn(f"【{label}", prompts_v3.SYSTEM_CIVIL)
        for label in prompts_v3.LABELS_CRIMINAL[:-1]:
            self.assertIn(f"【{label}", prompts_v3.SYSTEM_CRIMINAL)
        self.assertEqual(prompts_v3.MANUAL_VERSION, "v0.3")


if __name__ == "__main__":
    unittest.main()
