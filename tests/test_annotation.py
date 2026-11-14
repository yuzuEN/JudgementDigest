# -*- coding: utf-8 -*-
"""
annotation/ 的離線測試（v0.5）：論點單位抽樣、回應解析（CONCL 方向、EV basis）、多數決、
CONCL 和判決結果比對、線索、prompt 的標籤定義。不呼叫 API。
"""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from annotation import prompts_v5  # noqa: E402
from annotation.annotate import check_polarity, parse_response, reparse  # noqa: E402
from annotation.cues import CUES, INTEREST_SERVICE, cue_hits, quote_anchored  # noqa: E402
from annotation.sample import MAX_UNIT, SCHEMA, build_sample, used_case_ids  # noqa: E402
from annotation.spot_check import (COL, concl_directions, export, majority, outcome_flag,  # noqa: E402
                                   score, wilson)
from annotation.structure import units  # noqa: E402

# 填充句：不含任何線索，用來把每一項撐長，讓整篇超過 1,200 字、沿著「一、二、⋯」切開
FILLER = "兩造就此部分多所爭執，經本院詳予審閱卷內資料。" * 18
COURT = (
    "一、原告主張被告駕車過失撞傷原告，業據提出診斷證明書為證，核與證人所述相符，堪信為真實。" + FILLER +
    "二、被告故意以背於善良風俗之方法加損害於原告，即屬民法第184條第1項後段之侵權行為。" + FILLER +
    "三、本院審酌兩造之身分、地位、資力及原告所受痛苦程度，認原告請求精神慰撫金以20萬元為適當。" + FILLER +
    "四、衡諸常情，駕駛人於路口應減速慢行。從而，原告請求被告給付20萬元，為有理由，應予准許。" + FILLER +
    "五、本件事證已臻明確，兩造其餘攻擊或防禦方法，經本院斟酌後，認均不足以影響判決結果，爰不逐一論列。"
)
COLS = ("sample_id, annotator, run_no, label, polarity, quote, confidence, quote_valid, subtype, "
        "manual_version, prompt_version, raw_response, created_at")
INSERT = f"INSERT INTO annotations ({COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"


def read(db: Path, sql: str) -> list:
    """查詢後立刻關閉連線（Windows 不能刪除還開著的資料庫檔）。"""
    with closing(sqlite3.connect(db)) as con:
        return con.execute(sql).fetchall()


def make_cases_db(path: Path, n: int = 60) -> None:
    """假的 cases.sqlite：判決結果勝訴、敗訴交替。"""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE cases (row INTEGER PRIMARY KEY, id INTEGER UNIQUE, category TEXT, "
                "outcome TEXT, grant_ratio REAL)")
    con.execute("CREATE TABLE sections (id INTEGER PRIMARY KEY, claim TEXT, defense TEXT, court TEXT)")
    for i in range(n):
        outcome, ratio = ("勝訴", 1.0) if i % 2 == 0 else ("敗訴", 0.0)
        con.execute("INSERT INTO cases VALUES (?,?,?,?,?)", (i, 100 + i, "侵權行為", outcome, ratio))
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

    def test_filler_has_no_cues(self):
        self.assertEqual(cue_hits(FILLER), [])
        self.assertGreater(len(COURT), MAX_UNIT)

    def test_units_map_back_to_court(self):
        """抽出的單位文字要能用 unit_start／unit_end 對回法院判斷段原文，標註才對得回導讀頁。"""
        build_sample(self.cases, self.out, n_random=6, n_enriched=2, seed=1)
        us = units(COURT, MAX_UNIT)
        rows = read(self.out, "SELECT para_idx, n_paras, para_text, prev_text, next_text, unit_start, unit_end, "
                              "split_how, outcome FROM paragraphs")
        self.assertTrue(rows)
        self.assertEqual(len(us), 5)              # 沿著一～五切開
        for idx, n, text, prev, nxt, s, e, how, outcome in rows:
            self.assertEqual(n, len(us))
            self.assertEqual(text, COURT[s:e])
            self.assertEqual((s, e, how), us[idx])
            self.assertLessEqual(len(prev), 300)  # 前後文只取 300 字
            self.assertLessEqual(len(nxt), 300)
            if idx > 0:
                self.assertTrue(COURT[us[idx - 1][0]:us[idx - 1][1]].endswith(prev))
            self.assertIn(outcome, ("勝訴", "敗訴"))

    def test_batches_and_one_unit_per_case(self):
        counts = build_sample(self.cases, self.out, n_random=6, n_enriched=2, seed=1)
        self.assertEqual(sum(counts["random"].values()), 6)
        self.assertEqual(counts["enriched"], {"DAM": 2, "SUB": 2, "EXP": 2})
        case_ids = [r[0] for r in read(self.out, "SELECT case_id FROM paragraphs")]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        # 加抽的單位一定含有該類線索
        for batch, text in read(self.out, "SELECT batch, para_text FROM paragraphs WHERE batch LIKE 'enriched:%'"):
            self.assertRegex(text, CUES[batch.split(":")[1]])
        self.assertEqual(min(r[0] for r in read(self.out, "SELECT sample_id FROM paragraphs")), 3001)

    def test_exclude_previous_rounds(self):
        """新一輪不能再抽到先前各輪用過的判決。"""
        build_sample(self.cases, self.out, n_random=6, n_enriched=2, seed=1)
        used = used_case_ids([self.out])
        self.assertTrue(used)
        out2 = Path(self.tmp.name) / "out2" / "annotation.sqlite"
        build_sample(self.cases, out2, n_random=6, n_enriched=2, seed=1, exclude_cases=used, first_id=4001)
        new = {r[0] for r in read(out2, "SELECT case_id FROM paragraphs")}
        self.assertTrue(new)
        self.assertFalse(new & used)
        self.assertEqual(min(r[0] for r in read(out2, "SELECT sample_id FROM paragraphs")), 4001)
        self.assertEqual(used_case_ids([Path(self.tmp.name) / "不存在.sqlite"]), set())

    def test_same_seed_same_sample(self):
        build_sample(self.cases, self.out, n_random=6, n_enriched=2, seed=7)
        first = read(self.out, "SELECT case_id, para_idx FROM paragraphs")
        build_sample(self.cases, self.out, n_random=6, n_enriched=2, seed=7)
        second = read(self.out, "SELECT case_id, para_idx FROM paragraphs")
        self.assertEqual(first, second)


class TestParseResponse(unittest.TestCase):
    PARA = ("本院審酌兩造之身分、地位，認原告請求精神慰撫金以20萬元為適當。"
            "由上開函文可知被告已收受通知。從而，原告請求為有理由，應予准許。")

    def test_valid_labels_and_quote_check(self):
        raw = ('{"reasoning_present": true, "labels": ['
               '{"code": "DAM", "quote": "認原告請求精神慰撫金以20萬元為適當", "polarity": "全額准許", "basis": null, "confidence": "high"},'
               '{"code": "EV", "quote": "這句不在原文裡", "polarity": "有利原告", "basis": "明示評價", "confidence": "low"}]}')
        rows = parse_response(raw, self.PARA)
        self.assertEqual([(r[0], r[1], r[4], r[5]) for r in rows],
                         [("DAM", "全額准許", 1, None), ("EV", "有利原告", 0, "明示評價")])

    def test_concl_direction_and_ev_basis(self):
        raw = ('{"labels": ['
               '{"code": "EV", "quote": "由上開函文可知被告已收受通知", "polarity": "有利原告", "basis": "依證據推論", "confidence": "high"},'
               '{"code": "CONCL", "quote": "原告請求為有理由，應予准許", "polarity": "有理由", "basis": null, "confidence": "high"}]}')
        rows = parse_response(raw, self.PARA)
        self.assertEqual([(r[0], r[1], r[4], r[5]) for r in rows],
                         [("EV", "有利原告", 1, "依證據推論"), ("CONCL", "有理由", 1, None)])

    def test_same_label_multiple_quotes(self):
        """規則十二：同一個標籤可以有多段引文，各寫一列。"""
        raw = ('{"labels": ['
               '{"code": "CONCL", "quote": "原告請求為有理由", "polarity": "有理由", "confidence": "high"},'
               '{"code": "CONCL", "quote": "應予准許", "polarity": "有理由", "confidence": "high"}]}')
        self.assertEqual([r[0] for r in parse_response(raw, self.PARA)], ["CONCL", "CONCL"])

    def test_polarity_checks(self):
        self.assertEqual(check_polarity("CONCL", "一部有理由"), "一部有理由")
        self.assertEqual(check_polarity("CONCL", None), "INVALID:None")          # CONCL 一定要有方向
        self.assertEqual(check_polarity("CONCL", "有利原告"), "INVALID:有利原告")  # 用錯清單
        self.assertEqual(check_polarity("EV", "有理由"), "INVALID:有理由")        # CONCL 的方向給了別的標籤
        self.assertEqual(check_polarity("EV", None), None)
        self.assertEqual(check_polarity("RULE", None), None)
        raw = '{"labels": [{"code": "EV", "quote": "可知被告已收受通知", "polarity": "中性", "basis": "猜的", "confidence": "low"}]}'
        self.assertEqual(parse_response(raw, self.PARA)[0][5], "INVALID:猜的")

    def test_markdown_fence_and_none(self):
        raw = '```json\n{"reasoning_present": false, "labels": [{"code": "NONE", "quote": "", "polarity": null, "confidence": "high"}]}\n```'
        self.assertEqual(parse_response(raw, self.PARA), [("NONE", None, "", "high", 1, None)])

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
        label, pol, _, _, valid, _ = parse_response(raw, self.PARA)[0]
        self.assertEqual((label, pol, valid), ("INVALID:SENT", "INVALID:很多", 0))  # SENT 是刑事標籤
        self.assertEqual(parse_response("不是 JSON", self.PARA)[0][0], "PARSE_ERROR")


class TestReparse(unittest.TestCase):
    def test_reparse_old_db_without_subtype(self):
        """v0.4 以前的資料庫沒有 subtype 欄位：reparse 要自動補上欄位，再救回失敗列。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "annotation.sqlite"
            para = "本院審酌兩造之身分、地位，認原告請求精神慰撫金以20萬元為適當"
            good = ('說明文字。{"labels": [{"code": "DAM", "quote": "精神慰撫金以20萬元為適當", '
                    '"polarity": "全額准許", "confidence": "high"}]}')
            old_cols = COLS.replace("subtype, ", "")
            with closing(sqlite3.connect(db)) as con:
                con.executescript(SCHEMA.replace("    subtype        TEXT,      -- v0.5：EV 的子欄位（明示評價／依證據推論）\n", ""))
                self.assertNotIn("subtype", {r[1] for r in con.execute("PRAGMA table_info(annotations)")})
                con.execute("INSERT INTO paragraphs (sample_id, para_text) VALUES (1001, ?)", (para,))
                con.execute("INSERT INTO paragraphs (sample_id, para_text) VALUES (1002, ?)", (para,))
                con.executemany(f"INSERT INTO annotations ({old_cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
                    (1001, "m", 1, "PARSE_ERROR", None, None, None, 0, "v0.3", "p3.0", good, "t"),
                    (1002, "m", 1, "PARSE_ERROR", None, None, None, 0, "v0.3", "p3.0", "完全不是 JSON", "t"),
                ])
                con.commit()
            self.assertEqual(reparse(db), (2, 1))
            rows = read(db, "SELECT sample_id, label, polarity, quote_valid, subtype FROM annotations ORDER BY sample_id")
            self.assertEqual(rows, [(1001, "DAM", "全額准許", 1, None), (1002, "PARSE_ERROR", None, 0, None)])
            self.assertEqual(reparse(db), (1, 0))   # 再跑一次不會重複寫入


class TestSpotCheck(unittest.TestCase):
    def test_majority(self):
        rr = {1: {"EV": 0, "SUB": 0}, 2: {"EV": 0}, 3: {"NONE": 0}}
        self.assertEqual(majority(rr), {"EV"})
        self.assertEqual(majority({1: {"NONE": 0}, 2: {"DAM": 0}, 3: {"EV": 0}}), {"NONE"})

    def test_outcome_flag(self):
        self.assertEqual(outcome_flag("敗訴", {"有理由"}), "衝突")
        self.assertEqual(outcome_flag("敗訴", {"一部有理由"}), "衝突")
        self.assertEqual(outcome_flag("敗訴", {"無理由"}), "一致")
        self.assertEqual(outcome_flag("勝訴", {"無理由"}), "注意")
        self.assertEqual(outcome_flag("確認勝訴", {"有理由"}), "一致")
        self.assertEqual(outcome_flag("一部勝訴一部敗訴", {"有理由", "無理由"}), "一致")
        self.assertEqual(outcome_flag(None, {"有理由"}), "")
        self.assertEqual(outcome_flag("勝訴", set()), "")

    def test_concl_directions_majority(self):
        """一個單位兩筆 CONCL（本金有理由、利息無理由），三次中出現兩次以上的方向才算。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "a.sqlite"
            v = prompts_v5.PROMPT_VERSION
            with closing(sqlite3.connect(db)) as con:
                con.executescript(SCHEMA)
                for run, dirs in ((1, ["有理由", "無理由"]), (2, ["有理由", "無理由"]), (3, ["一部有理由"])):
                    for d in dirs:
                        con.execute(INSERT, (5, "m", run, "CONCL", d, "q", "high", 1, None, "v0.5", v, "{}", "t"))
                con.execute(INSERT, (6, "m", 1, "NONE", None, "", "high", 1, None, "v0.5", v, "{}", "t"))
                con.commit()
                self.assertEqual(concl_directions(con), {5: {"有理由", "無理由"}})

    def test_export_and_score(self):
        """抽查表從輸出到計分：精確度、引文正確率、CONCL 和判決結果比對。"""
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as tmp:
            cases = Path(tmp) / "cases.sqlite"
            db = Path(tmp) / "annotation.sqlite"
            sheet = Path(tmp) / "check.xlsx"
            make_cases_db(cases, n=40)
            build_sample(cases, db, n_random=12, n_enriched=2, seed=3)
            v = prompts_v5.PROMPT_VERSION
            with closing(sqlite3.connect(db)) as con:
                for sid, text in con.execute("SELECT sample_id, para_text FROM paragraphs").fetchall():
                    if "堪信" in text:
                        label, pol, quote, sub = "EV", "有利原告", "核與證人所述相符，堪信為真實", "明示評價"
                    elif "應予准許" in text:
                        label, pol, quote, sub = "CONCL", "有理由", "為有理由，應予准許", None
                    else:
                        label, pol, quote, sub = "NONE", None, "", None
                    for run in (1, 2, 3):
                        con.execute(INSERT, (sid, "m", run, label, pol, quote, "high", 1, sub, "v0.5", v, "{}", "t"))
                con.commit()
            export(db, sheet, n_per_label=5, seed=1)
            wb = load_workbook(sheet)
            self.assertIn("CONCL", wb.sheetnames)
            self.assertIn("EXP", wb.sheetnames)
            ws = wb["EV"]
            self.assertGreater(ws.max_row - 1, 0)
            self.assertEqual(ws.cell(2, COL["引文錨定（自動）"] + 1).value, "是")
            self.assertIn("明示評價", ws.cell(2, COL["傾向／方向"] + 1).value)
            # CONCL：判決敗訴卻標「有理由」→ 衝突；勝訴 → 一致
            wc = wb["CONCL"]
            flags = {wc.cell(i, COL["判決結果比對"] + 1).value for i in range(2, wc.max_row + 1)}
            self.assertTrue(flags)
            self.assertTrue(flags <= {"衝突（判決敗訴）", "一致（判決勝訴）"})
            for name in ("EV", "CONCL"):
                w = wb[name]
                for i in range(2, w.max_row + 1):
                    w.cell(i, COL["判定"] + 1, "符合")
                    w.cell(i, COL["引文判定"] + 1, "正確" if i % 2 == 0 else "錯誤")
            wb.save(sheet)
            wb.close()
            score(sheet)   # 不應拋出錯誤；檔案要能關閉，暫存資料夾才刪得掉（Windows）

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

    def test_concl_moved_out_of_sub(self):
        """v0.5：「即屬有據」「核屬有理」是請求判斷（CONCL），不再算 SUB 的定性。"""
        for t in ("原告請求為有理由，應予准許", "即屬有據", "核屬有理", "洵屬有據", "應予駁回"):
            self.assertIn("CONCL", cue_hits(t), t)
            self.assertNotIn("SUB", cue_hits(t), t)
            self.assertTrue(quote_anchored("CONCL", t), t)
            self.assertFalse(quote_anchored("SUB", t), t)
        self.assertTrue(quote_anchored("SUB", "被告無法律上原因而獲債務減免之利益，核屬給付型不當得利"))
        self.assertIn("SUB", cue_hits("即屬民法第184條第1項後段之侵權行為"))

    def test_ev_inference_terms(self):
        for t in ("由上開函文可知被告已收受", "足徵原告確已交付", "無從遽認被告有過失", "核與監視器畫面吻合",
                  "被告所辯，無足採信", "原告難證明其主張"):
            self.assertIn("EV", cue_hits(t), t)

    def test_exp_closed_list(self):
        for t in ("此類詐騙手法屢見不鮮", "依社會通念", "衡諸常情", "依經驗法則"):
            self.assertIn("EXP", cue_hits(t), t)
        self.assertNotIn("EXP", cue_hits("被告應注意並能注意而不注意"))

    def test_every_label_is_defined_in_prompt(self):
        for label in prompts_v5.LABELS_CIVIL[:-1]:
            self.assertIn(f"【{label}", prompts_v5.SYSTEM_CIVIL)
        for label in prompts_v5.LABELS_CRIMINAL[:-1]:
            self.assertIn(f"【{label}", prompts_v5.SYSTEM_CRIMINAL)
        self.assertEqual((prompts_v5.MANUAL_VERSION, prompts_v5.PROMPT_VERSION), ("v0.5", "p5.0"))
        for label in ("CONCL", "HI"):
            self.assertIn(label, prompts_v5.LABELS_CIVIL)
        for d in ("有理由", "一部有理由", "無理由"):
            self.assertIn(d, prompts_v5.POLARITY_CIVIL)
            self.assertIn(d, prompts_v5.SYSTEM_CIVIL)
        self.assertIn('"basis"', prompts_v5.SYSTEM_CIVIL)
        self.assertIn("10～100 字", prompts_v5.SYSTEM_CIVIL)

    def test_quote_anchored(self):
        """規則 10：EV 只引到列舉證據、SUB 只引到大前提，自動檢查要能抓出來（v0.3 抽查 1051、1249）。"""
        self.assertFalse(quote_anchored("EV", "業據提出與其所述相符之授信約定書、連帶保證書、借據"))
        self.assertTrue(quote_anchored("EV", "堪信原告之主張為真實"))
        self.assertTrue(quote_anchored("EV", "足見兩造確係約定以農會貸款撥放日為給付尾款之日"))
        self.assertFalse(quote_anchored("SUB", "仍須符合附表項次1各項要件，始有附表項次1各等級之適用"))
        self.assertFalse(quote_anchored("SUB", "比對其是否與法規範構成要件之連絡對象相符"))
        self.assertTrue(quote_anchored("RULE", "按損害之發生或擴大，被害人與有過失者，法院得減輕賠償金額"))
        self.assertTrue(quote_anchored("EXP", "衡諸常情，駕駛人於路口應減速慢行"))
        self.assertIsNone(quote_anchored("CL", "最高法院52年台上字第1240號判例參照"))

    def test_rule_cue(self):
        self.assertIn("RULE", cue_hits("四、另按損害之發生或擴大，被害人與有過失者"))
        self.assertIn("RULE", cue_hits("所謂即受確認判決之法律上利益，係指因法律關係之存否不明確"))
        self.assertNotIn("RULE", cue_hits("本院審酌兩造身分地位，認慰撫金以20萬元為適當"))


if __name__ == "__main__":
    unittest.main()
