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
from annotation.spot_check import COL, export, pick_version, score  # noqa: E402
from annotation.sample_criminal import CUE, PROSECUTOR, body_end  # noqa: E402
from retrieval.criminal_guides import segment  # noqa: E402

CUR_MANUAL, CUR_PROMPT = prompts_v6.MANUAL_VERSION_CRIMINAL, prompts_v6.PROMPT_VERSION_CRIMINAL

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


class TestCriminalVersion(unittest.TestCase):
    """刑事有自己的版本號（p6.1c 起；目前見 prompts_v6.PROMPT_VERSION_CRIMINAL），民事 p6.0 的 prompt 不受影響。"""

    def test_versions_are_separate(self):
        self.assertEqual((DOMAINS["civil"]["manual_version"], DOMAINS["civil"]["prompt_version"]), ("v0.6", "p6.0"))
        self.assertEqual((DOMAINS["criminal"]["manual_version"], DOMAINS["criminal"]["prompt_version"]),
                         (CUR_MANUAL, CUR_PROMPT))
        for text in ("刑事補充", "撤回告訴", "過苛", "刑罰反應力薄弱"):
            self.assertNotIn(text, prompts_v6.SYSTEM_CIVIL)      # 刑事的新規則沒有混進民事 prompt

    def test_criminal_prompt_rules(self):
        s = prompts_v6.SYSTEM_CRIMINAL
        sent = s[s.index("【SENT 量刑審酌】"):s.index("【EV 證據評價】")]
        self.assertIn("不是條文寫「得」還是「應」", sent)               # 1. 判準是有沒有裁量理由
        self.assertIn("必減、必加、應沒收", sent)
        self.assertIn("改標 SUB", sent)
        self.assertNotIn("自白減刑", sent)                              # 舊版把自白減刑一律列為 SENT
        self.assertIn("保安處分", sent)                                  # 2. 保安處分併入 SENT
        self.assertIn("無構陷", s[s.index("刑事補充"):])                # 3. 無恩怨、無構陷動機 → EV
        proc = s[s.index("【PROC 程序處理】"):s.index("【HI 歷史解釋】")]
        self.assertIn("§303", proc)                                     # 4. 撤回告訴、免訴
        self.assertIn("§302", proc)
        self.assertIn("只標 PROC", proc)

    def test_pick_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "a.sqlite"
            with closing(sqlite3.connect(db)) as con:
                con.executescript(SCHEMA)
                con.execute("INSERT INTO paragraphs (sample_id, batch, para_text) VALUES (9001, 'criminal-random', ?)",
                            (COURT,))
                self.assertEqual(pick_version(con, "criminal"), (CUR_MANUAL, CUR_PROMPT))   # 還沒標：用目前版本
                con.execute(INSERT, (9001, "m", 1, "SENT", None, "q", None, 1, None, "v0.6", "p6.0", "{}", "t"))
                self.assertEqual(pick_version(con, "criminal"), ("v0.6", "p6.0"))       # 只有舊版（v1）：用舊版
                con.execute(INSERT, (9001, "m", 1, "SUB", None, "q", None, 1, None, CUR_MANUAL, CUR_PROMPT, "{}", "t"))
                self.assertEqual(pick_version(con, "criminal"), (CUR_MANUAL, CUR_PROMPT))   # 有新版：用新版

    def test_export_reads_only_current_version(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as tmp:
            cases, db, sheet = Path(tmp) / "cases.sqlite", Path(tmp) / "a.sqlite", Path(tmp) / "check.xlsx"
            make_criminal_db(cases)
            build_criminal(cases, db, n=12, seed=2)
            with closing(sqlite3.connect(db)) as con:
                for (sid,) in con.execute("SELECT sample_id FROM paragraphs").fetchall():
                    for run in (1, 2, 3):
                        con.execute(INSERT, (sid, "m", run, "EV", "中性", "堪信為真實", "high", 1, "明示評價",
                                             "v0.6", "p6.0", "{}", "t"))
                        con.execute(INSERT, (sid, "m", run, "SUB", None, "核被告所為", "high", 1, None,
                                             CUR_MANUAL, CUR_PROMPT, "{}", "t"))
                con.commit()
            export(db, sheet, n_per_label=25, seed=1)
            wb = load_workbook(sheet)
            self.assertEqual(wb["EV"].max_row - 1, 0)                 # p6.0 的標註不混進來
            self.assertEqual(wb["SUB"].max_row - 1, 12)
            self.assertIn(CUR_PROMPT, wb["填寫說明"].cell(1, 1).value)
            wb.close()

    def test_annotate_dry_run_reports_criminal_version(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        from annotation import annotate
        with tempfile.TemporaryDirectory() as tmp:
            cases, db = Path(tmp) / "cases.sqlite", Path(tmp) / "a.sqlite"
            make_criminal_db(cases)
            build_criminal(cases, db, n=3, seed=2)
            out = io.StringIO()
            with mock.patch.object(sys, "argv", ["annotate", "--db", str(db), "--dry-run"]), redirect_stdout(out):
                annotate.main()
            self.assertIn(f"手冊 {CUR_MANUAL}、prompt {CUR_PROMPT}", out.getvalue())
            self.assertIn("【SENT 量刑審酌】", prompts_v6.SYSTEM_CRIMINAL)


# 沒有「附件」標題、直接接在署名後面的檢察官聲請簡易判決處刑書（v0.7c 抽查 SUB 9181、9247、EV 9083 的情形）
ANNEX_TEXT = """臺灣桃園地方法院刑事簡易判決
113年度桃簡字第1號
主文
被告犯竊盜罪，處拘役十日。
事實及理由
一、本件犯罪事實及證據，均引用檢察官聲請簡易判決處刑書之記載。
二、核被告所為，係犯刑法第320條第1項之竊盜罪。爰審酌被告犯後坦承犯行，兼衡其智識程度等一切情狀，量處如主文所示之刑。
中華民國113年6月27日
桃園簡易庭法官李大華
以上正本證明與原本無異。
臺灣桃園地方檢察署檢察官聲請簡易判決處刑書
犯罪事實
一、被告意圖為自己不法之所有，竊取安全帽1頂，業經被害人報警處理。
證據並所犯法條
一、詢據被告坦承不諱，核與告訴人指訴相符，並有監視器畫面在卷可稽，被告犯嫌堪以認定。
二、核被告所為，係犯刑法第320條第1項之竊盜罪嫌。至被告竊得之安全帽，已發還告訴人，不聲請宣告沒收。
三、依刑事訴訟法第451條第1項聲請逕以簡易判決處刑。此致臺灣桃園地方法院
"""


class TestAnnexCutoff(unittest.TestCase):
    """v0.8c：判決本文在署名或檢察官書類的地方結束，後面的段落都不抽。"""

    def test_annex_without_heading_is_excluded(self):
        paragraphs = segment(ANNEX_TEXT)
        self.assertTrue(any("犯嫌堪以認定" in p["text"] and not p.get("part") for p in paragraphs))  # 分段程式沒標 part
        texts = [paragraphs[i]["text"] for i in eligible(paragraphs)]
        self.assertTrue(texts)
        self.assertTrue(all("罪嫌" not in t and "犯嫌" not in t and "詢據" not in t for t in texts))
        self.assertTrue(any("係犯刑法第320條第1項之竊盜罪。" in t for t in texts))              # 法院自己的論罪留著
        self.assertLess(body_end(paragraphs), len(paragraphs))

    def test_court_text_is_not_flagged(self):
        court = [
            "公訴意旨認被告涉犯刑法第306條第1項之無故侵入他人住宅罪嫌，無非係以被告之供述為其論據。",
            "經查，被告所涉傷害罪嫌，依同法第287條前段規定，須告訴乃論。",
            "訊據被告固坦承有申請帳戶並交付提款卡之事實，惟矢口否認有何幫助詐欺犯行。",
            "本件犯罪事實、證據及應適用之法條，除證據並所犯法條欄第5行「信件3封」更正為「信件3紙」外，均引用檢察官聲請簡易判決處刑書之記載。",
            "一、本件犯罪事實、證據及應適用之法條，除被告係犯「刑法第339條第1項之詐欺取財罪嫌」應更正為係犯「刑法第339條第1項之詐欺取財罪」外，均引用之。",
            "被告之辯護人雖以被告犯後態度良好，請依刑法第59條規定酌減其刑等語。",
        ]
        for t in court:
            self.assertIsNone(PROSECUTOR.search(t), t)

    def test_prosecutor_text_is_flagged(self):
        prosecutor = [
            "二、所犯法條：(一)被告就犯罪事實（一）所為，係犯刑法第310條第1項之誹謗罪嫌。",
            "二、核被告【被告】所為，係犯刑法第164條第2項之頂替罪嫌。",
            "一、詢據被告對於上開犯罪事實坦承不諱，核與告訴人之指訴情節相符，被告犯嫌堪以認定。",
            "足認被告之自白與事實相符，其犯嫌應堪認定。",
            "上揭犯罪事實，業據告訴人於警詢時及本署偵查中指訴明確。",
            "若成立犯罪，與前揭起訴部分屬裁判上一罪，爰不另為不起訴處分，併此敘明。",
        ]
        for t in prosecutor:
            self.assertIsNotNone(PROSECUTOR.search(t), t)


class TestCueSample(unittest.TestCase):
    """v0.8c：PROC、ADM 在隨機樣本太少，另外依線索加抽，batch 分開。"""

    def test_cue_batches(self):
        text = FULL_TEXT.replace(
            "三、據上論斷",
            "三、按被告以外之人於審判外之陳述，經當事人於審判程序同意作為證據，本院審酌其作成時之情況，認為適當，有證據能力。\n"
            "四、告訴人已於本院審理時撤回告訴，此部分應諭知不受理之判決。\n五、據上論斷")
        with tempfile.TemporaryDirectory() as tmp:
            cases, db = Path(tmp) / "cases.sqlite", Path(tmp) / "a.sqlite"
            make_fulltext_db(cases, n=40)
            with closing(sqlite3.connect(cases)) as con:
                con.execute("UPDATE full_text SET text = ? WHERE text != ''", (text,))
                con.commit()
            meta = build_criminal(cases, db, n=10, seed=3, n_cue=5)
            self.assertEqual(meta["by_batch"], {"criminal-random": 10, "criminal-cue:PROC": 5, "criminal-cue:ADM": 5})
            rows = read(db, "SELECT batch, para_text, case_id FROM paragraphs")
            self.assertEqual(len({r[2] for r in rows}), 20)                     # 同一件判決只用一次
            for batch, para, _ in rows:
                if batch.startswith("criminal-cue:"):
                    self.assertRegex(para, CUE[batch.split(":")[1]])
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(detect_domain(con), "criminal")                # 加抽批也認得是刑事


class TestV08cPrompt(unittest.TestCase):
    """v0.8c 的規則寫進了刑事 prompt，民事沒有。"""

    def test_rules(self):
        s = prompts_v6.SYSTEM_CRIMINAL
        sent = s[s.index("【SENT 量刑審酌】"):s.index("【EV 證據評價】")]
        self.assertIn("已發還被害人", sent)                              # 1. 依法不能沒收 → SUB
        self.assertNotIn("無宣告沒收之必要、", sent)                      # 不再把「無宣告沒收之必要」列成觸發詞
        self.assertIn("累犯分兩步", sent)                                 # 2. 累犯
        self.assertIn("前案紀錄表附卷可憑", s[s.index("【EV 證據評價】"):s.index("【CL 判例援引】")])  # 3. EV 反例
        self.assertIn("釋字第775號", s[s.index("【CL 判例援引】"):s.index("【PROC 程序處理】")])      # 6. CL
        exp = s[s.index("刑事補充"):s.index("== 判斷順序 ==")]
        for text in ("罪數的固定公式", "只有標記詞", "否定一方的常情論證", "UNC", "本案事證明確"):  # 4、5
            self.assertIn(text, exp)
        for text in ("累犯分兩步", "罪數的固定公式", "釋字第775號"):
            self.assertNotIn(text, prompts_v6.SYSTEM_CIVIL)


if __name__ == "__main__":
    unittest.main()
