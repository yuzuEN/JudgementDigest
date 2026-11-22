# -*- coding: utf-8 -*-
"""
刑事標註的離線測試：從刑事判決導讀抽樣（sample_criminal.py）、annotate.py 自動改用刑事 prompt 與標籤、
抽查表改成刑事的標籤（SENT、ADM）。不呼叫 API。
"""

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from annotation import prompts_v6  # noqa: E402
from annotation.annotate import DOMAINS, detect_domain, parse_response, reparse  # noqa: E402
from annotation.sample import SCHEMA, build_sample  # noqa: E402
from annotation.sample_criminal import FIRST_ID, build_sample as build_criminal, eligible  # noqa: E402
from annotation.spot_check import COL, export, score  # noqa: E402

EVIDENCE = "二、訊據被告固坦承有前揭行為，惟否認犯行。經查，證人甲之證述與監視器畫面相符，堪信為真實。"
COURT = ("三、核被告所為，係犯刑法第320條第1項之竊盜罪。爰以行為人之責任為基礎，審酌被告犯後坦承犯行、"
         "已與被害人和解，兼衡其智識程度、家庭經濟狀況等一切情狀，量處如主文所示之刑。")
GUIDE = [
    {"function": "info", "label": "案件資訊", "text": "臺灣臺北地方法院刑事簡易判決", "pre": False, "part": None},
    {"function": "verdict", "label": "主文", "text": "被告犯竊盜罪，處拘役參拾日。", "pre": False, "part": None},
    {"function": "facts", "label": "犯罪事實", "text": "一、被告意圖為自己不法之所有，徒手竊取被害人之機車一輛。",
     "pre": False, "part": None},
    {"function": "evidence", "label": "證據", "text": EVIDENCE, "pre": False, "part": None},
    {"function": "court", "label": "論罪科刑", "text": COURT, "pre": False, "part": None},
    {"function": "laws", "label": "法條", "text": "據上論斷，應依刑事訴訟法第449條第1項前段，判決如主文。",
     "pre": False, "part": None},
    {"function": "table", "label": "附表", "text": "編號｜物品\n1｜機車", "pre": True, "part": None},
]
COLS = ("sample_id, annotator, run_no, label, polarity, quote, confidence, quote_valid, subtype, "
        "manual_version, prompt_version, raw_response, created_at")
INSERT = f"INSERT INTO annotations ({COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"


def make_criminal_db(path: Path, n: int = 30) -> None:
    """假的刑事 cases.sqlite：cases＋guides；最後兩件只有資料集節錄（source = dataset），不能抽。"""
    with closing(sqlite3.connect(path)) as con:
        con.execute("CREATE TABLE cases (row INTEGER PRIMARY KEY, id INTEGER UNIQUE, case_number TEXT, court TEXT, "
                    "year TEXT, charges TEXT, sentence TEXT, summary TEXT, url TEXT)")
        con.execute("CREATE TABLE guides (case_id INTEGER PRIMARY KEY, source TEXT NOT NULL, "
                    "judgment_date TEXT NOT NULL, paragraphs TEXT NOT NULL)")
        for i in range(n):
            cid = 500 + i
            con.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?)",
                        (i, cid, f"{cid}號", "臺北地院", "113", json.dumps(["竊盜罪"], ensure_ascii=False),
                         "拘役、罰金", "摘要", None))
            source = "dataset" if i >= n - 2 else "judgment"
            con.execute("INSERT INTO guides VALUES (?,?,?,?)",
                        (cid, source, "2024-01-01", json.dumps(GUIDE, ensure_ascii=False)))
        con.commit()


FULL_TEXT = """臺灣臺北地方法院刑事簡易判決
113年度簡字第1號
主文
被告犯竊盜罪，處拘役參拾日。
犯罪事實
一、被告意圖為自己不法之所有，徒手竊取被害人之機車一輛。
理由
一、上揭犯罪事實，業據被告於警詢時坦承不諱，核與證人甲之證述相符，並有監視器畫面截圖在卷可稽，足認被告之任意性自白與事實相符，堪以採信。
二、核被告所為，係犯刑法第320條第1項之竊盜罪。爰以行為人之責任為基礎，審酌被告犯後坦承犯行、已與被害人和解，兼衡其智識程度等一切情狀，量處如主文所示之刑。
三、據上論斷，應依刑事訴訟法第449條第1項前段，判決如主文。
"""


def make_fulltext_db(path: Path, n: int = 20) -> None:
    """新版刑事 cases.sqlite：cases＋full_text（遮名原文包，以 row 對應），沒有 guides 表；最後一件沒有全文。"""
    with closing(sqlite3.connect(path)) as con:
        con.execute("CREATE TABLE cases (row INTEGER PRIMARY KEY, id INTEGER UNIQUE, case_number TEXT, court TEXT, "
                    "year TEXT, charges TEXT, sentence TEXT, summary TEXT, url TEXT)")
        con.execute("CREATE TABLE full_text (row INTEGER PRIMARY KEY, text TEXT)")
        for i in range(n):
            con.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?)",
                        (i, 700 + i, f"{i}號", "臺北地院", "113", json.dumps(["竊盜罪"], ensure_ascii=False),
                         "拘役、罰金", "摘要", None))
            con.execute("INSERT INTO full_text VALUES (?, ?)", (i, "" if i == n - 1 else FULL_TEXT))
        con.commit()


def read(db: Path, sql: str) -> list:
    with closing(sqlite3.connect(db)) as con:
        return con.execute(sql).fetchall()


class TestSampleCriminal(unittest.TestCase):
    def test_eligible_only_evidence_and_court(self):
        self.assertEqual(eligible(GUIDE), [3, 4])
        # 附在判決後面的檢察官書類（聲請簡易判決處刑書）不標，即使功能是證據或論罪科刑
        attached = GUIDE + [dict(GUIDE[3], part="附件：聲請簡易判決處刑書", text="業據被告坦承不諱，被告犯嫌應堪認定。" * 2)]
        self.assertEqual(eligible(attached), [3, 4])
        short = [{"function": "court", "text": "本件判決如主文。", "pre": False}]
        self.assertEqual(eligible(short), [])     # 少於 20 字不標

    def test_build_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases, out = Path(tmp) / "cases.sqlite", Path(tmp) / "a" / "annotation.sqlite"
            make_criminal_db(cases)
            meta = build_criminal(cases, out, n=10, seed=1)
            self.assertEqual(meta["n"], 10)
            self.assertEqual(meta["n_source_cases"], 28)                 # dataset 的兩件不算
            rows = read(out, "SELECT sample_id, case_id, para_idx, batch, category, prev_text, para_text, next_text, "
                             "unit_start, unit_end, split_how, outcome FROM paragraphs ORDER BY sample_id")
            self.assertEqual(rows[0][0], FIRST_ID)
            self.assertEqual(len({r[1] for r in rows}), 10)              # 每件一段
            self.assertTrue(all(r[1] < 528 for r in rows))               # 沒抽到只有資料集節錄的
            for sid, cid, idx, batch, cat, prev, text, nxt, s, e, how, outcome in rows:
                self.assertIn(idx, (3, 4))
                self.assertEqual(text, GUIDE[idx]["text"])
                self.assertEqual((s, e), (0, len(text)))
                self.assertEqual(prev, GUIDE[idx - 1]["text"][-300:])
                self.assertEqual(nxt, GUIDE[idx + 1]["text"][:300])
                self.assertEqual((batch, cat, outcome), ("criminal-random", "竊盜罪", "拘役、罰金"))
                self.assertTrue(how.startswith("criminal-guide:"))
            self.assertTrue((out.parent / "meta.json").exists())

    def test_exclude_same_seed_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = Path(tmp) / "cases.sqlite"
            make_criminal_db(cases)
            a, b = Path(tmp) / "a.sqlite", Path(tmp) / "b.sqlite"
            build_criminal(cases, a, n=8, seed=5)
            build_criminal(cases, b, n=8, seed=5)
            self.assertEqual(read(a, "SELECT case_id, para_idx FROM paragraphs"),
                             read(b, "SELECT case_id, para_idx FROM paragraphs"))     # 同一個 seed 抽到同一批
            used = {r[0] for r in read(a, "SELECT case_id FROM paragraphs")}
            c = Path(tmp) / "c.sqlite"
            build_criminal(cases, c, n=8, seed=6, exclude=used)
            self.assertFalse(used & {r[0] for r in read(c, "SELECT case_id FROM paragraphs")})
            with self.assertRaises(SystemExit):
                build_criminal(cases, a, n=3, seed=9)              # 已經有段落的資料庫不能再寫


    def test_full_text_bundle(self):
        """新版檢索庫沒有 guides 表：從 full_text 當場分段，和後端刑事導讀頁同一種切法。"""
        with tempfile.TemporaryDirectory() as tmp:
            cases, out = Path(tmp) / "cases.sqlite", Path(tmp) / "annotation.sqlite"
            make_fulltext_db(cases)
            meta = build_criminal(cases, out, n=10, seed=3)
            self.assertEqual((meta["n"], meta["n_source_cases"]), (10, 19))      # 沒有全文的那件不算
            rows = read(out, "SELECT case_id, split_how, para_text FROM paragraphs")
            self.assertTrue(all(cid < 719 for cid, _, _ in rows))
            self.assertEqual({how for _, how, _ in rows} <= {"criminal-guide:evidence", "criminal-guide:court"}, True)
            self.assertTrue(all(t.startswith(("一、上揭犯罪事實", "二、核被告所為")) for _, _, t in rows))

    def test_full_text_skips_attached_prosecutor_document(self):
        text = FULL_TEXT.replace("三、據上論斷", "三、據上論斷") + """附件：
臺灣臺北地方檢察署檢察官聲請簡易判決處刑書
證據並所犯法條
一、上開犯罪事實，業據被告於警詢時坦承不諱，核與告訴人指訴相符，被告犯嫌應堪認定。
二、核被告所為，係犯刑法第320條第1項之竊盜罪嫌。
"""
        with tempfile.TemporaryDirectory() as tmp:
            cases, out = Path(tmp) / "cases.sqlite", Path(tmp) / "annotation.sqlite"
            make_fulltext_db(cases)
            with closing(sqlite3.connect(cases)) as con:
                con.execute("UPDATE full_text SET text = ? WHERE text != ''", (text,))
                con.commit()
            build_criminal(cases, out, n=15, seed=4)
            texts = [r[0] for r in read(out, "SELECT para_text FROM paragraphs")]
            self.assertEqual(len(texts), 15)
            self.assertFalse(any("犯嫌" in t or "罪嫌" in t for t in texts))


class TestCriminalDomain(unittest.TestCase):
    def test_detect_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "x.sqlite"
            with closing(sqlite3.connect(db)) as con:
                con.executescript(SCHEMA)
                con.execute("INSERT INTO paragraphs (sample_id, batch, para_text) VALUES (1, 'criminal-random', 'x')")
                self.assertEqual(detect_domain(con), "criminal")
                con.execute("INSERT INTO paragraphs (sample_id, batch, para_text) VALUES (2, 'random', 'x')")
                self.assertEqual(detect_domain(con), "civil")      # 混到民事的就不是刑事

    def test_domains_use_matching_prompt(self):
        self.assertIs(DOMAINS["criminal"]["system"], prompts_v6.SYSTEM_CRIMINAL)
        self.assertIn("SENT", DOMAINS["criminal"]["labels"])
        self.assertNotIn("CONCL", DOMAINS["criminal"]["labels"])
        self.assertIn("【SENT 量刑審酌】", prompts_v6.SYSTEM_CRIMINAL)
        self.assertIn("【ADM 證據能力】", prompts_v6.SYSTEM_CRIMINAL)

    def test_parse_criminal(self):
        raw = json.dumps({"labels": [
            {"code": "SUB", "quote": "核被告所為，係犯刑法第320條第1項之竊盜罪", "polarity": None},
            {"code": "SENT", "quote": "審酌被告犯後坦承犯行、已與被害人和解", "polarity": None},
            {"code": "EV", "quote": "證人甲之證述與監視器畫面相符，堪信為真實", "polarity": "不利被告", "basis": "明示評價"},
        ]}, ensure_ascii=False)
        rows = parse_response(raw, EVIDENCE + COURT, domain="criminal")
        self.assertEqual([(r[0], r[1], r[4], r[5]) for r in rows],
                         [("SUB", None, 1, None), ("SENT", None, 1, None), ("EV", "不利被告", 1, "明示評價")])
        # 民事的標籤、民事的傾向在刑事都不合法
        bad = json.dumps({"labels": [
            {"code": "CONCL", "quote": "核被告所為", "polarity": "有理由"},
            {"code": "EV", "quote": "堪信為真實", "polarity": "有利原告"},
            {"code": "SENT", "quote": "審酌被告犯後坦承犯行", "polarity": "酌減"},
        ]}, ensure_ascii=False)
        rows = parse_response(bad, EVIDENCE + COURT, domain="criminal")
        self.assertEqual(rows[0][0], "INVALID:CONCL")
        self.assertEqual(rows[1][1], "INVALID:有利原告")
        self.assertEqual(rows[2][1], "INVALID:酌減")               # 民事 DAM 的方向在刑事不合法
        # 不給 domain 照舊是民事（舊的呼叫方式不變）
        self.assertEqual(parse_response(bad, EVIDENCE + COURT)[0][0], "CONCL")

    def test_reparse_uses_criminal_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "a.sqlite"
            good = '說明。{"labels": [{"code": "SENT", "quote": "審酌被告犯後坦承犯行", "polarity": null}]}'
            with closing(sqlite3.connect(db)) as con:
                con.executescript(SCHEMA)
                con.execute("INSERT INTO paragraphs (sample_id, batch, para_text) VALUES (9001, 'criminal-random', ?)",
                            (COURT,))
                con.execute(INSERT, (9001, "m", 1, "PARSE_ERROR", None, None, None, 0, None, "v0.6", "p6.0", good, "t"))
                con.commit()
            self.assertEqual(reparse(db), (1, 1))
            self.assertEqual(read(db, "SELECT label, quote_valid FROM annotations"), [("SENT", 1)])


class TestCriminalSpotCheck(unittest.TestCase):
    def test_export_and_score(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as tmp:
            cases, db, sheet = Path(tmp) / "cases.sqlite", Path(tmp) / "a.sqlite", Path(tmp) / "check.xlsx"
            make_criminal_db(cases)
            build_criminal(cases, db, n=12, seed=2)
            v = prompts_v6.PROMPT_VERSION
            with closing(sqlite3.connect(db)) as con:
                for sid, text in con.execute("SELECT sample_id, para_text FROM paragraphs").fetchall():
                    if "量處" in text:
                        label, pol, quote, sub = "SENT", None, "審酌被告犯後坦承犯行、已與被害人和解", None
                    else:
                        label, pol, quote, sub = "EV", "不利被告", "證人甲之證述與監視器畫面相符，堪信為真實", "明示評價"
                    for run in (1, 2, 3):
                        con.execute(INSERT, (sid, "m", run, label, pol, quote, "high", 1, sub, "v0.6", v, "{}", "t"))
                con.commit()
            export(db, sheet, n_per_label=25, seed=1)
            wb = load_workbook(sheet)
            self.assertEqual(wb.sheetnames, ["填寫說明", "RULE", "SUB", "SENT", "EV", "PROC", "ADM", "EXP"])
            self.assertNotIn("CONCL", wb.sheetnames)
            n_sent, n_ev = wb["SENT"].max_row - 1, wb["EV"].max_row - 1
            self.assertEqual(n_sent + n_ev, 12)                      # 沒有 10 個的回歸上限
            self.assertIn("不利被告", wb["EV"].cell(2, COL["傾向／方向"] + 1).value)
            for name in ("SENT", "EV"):
                w = wb[name]
                for i in range(2, w.max_row + 1):
                    w.cell(i, COL["判定"] + 1, "符合")
                    w.cell(i, COL["引文判定"] + 1, "正確")
            wb.save(sheet)
            wb.close()
            score(sheet)


if __name__ == "__main__":
    unittest.main()
