import json
import re
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path

from backend.criminal_service import CriminalService
from retrieval.criminal_guides import build, clean, cn_number, executed_or_single, sentences, dataset_guide, dataset_rows, judgment_guide, judgment_id, segment
from tests.test_criminal_service import synthetic, train_artifacts


@contextmanager
def connect(path):
    """sqlite3 的 with 只會 commit、不會關閉連線；Windows 上沒關的檔案刪不掉，暫存資料夾會清不掉。"""
    con = sqlite3.connect(path)
    try:
        with con:
            yield con
    finally:
        con.close()

# 簡易判決：主文 → 事實及理由 → 署名 → 附錄法條 → 附表 → 附件（起訴書，裡面再分犯罪事實、證據）
FULL_TEXT = """臺灣臺北地方法院刑事簡易判決
109年度審簡字第1號
公 訴 人 臺灣臺北地方檢察署檢察官
被 告 王大明
上列被告因 竊盜 案件，經檢察官提起公訴，本院判決如下：
主 文
王大明犯竊盜罪，處拘役參拾日。
事實及理由
一、本件犯罪事實及證據，均引用檢察官起訴書（如附件）之記載。
二、論罪科刑：
㈠核被告所為，係犯刑法第320條第1項之竊盜罪。
㈡爰 審酌 被告犯後坦承犯行，量處如主文所示之刑。毒品以第一、二級
毒品為限。
三、依刑事訴訟法第449條第2項，逕以簡易判決處刑如主文。
四、如不服本判決，得於20日內提出上訴。
中 華 民 國 109 年 5 月 29 日
刑事第二十庭 法 官 洪○○
附錄本案論罪科刑法條全文：
中華民國刑法第320條
意圖為自己或第三人不法之所有，而竊取他人之動產者，
處5年以下有期徒刑。
附表一：
編號 物品 1 手機
附件：
臺灣臺北地方檢察署檢察官起訴書
犯罪事實
一、王大明於民國109年1月1日竊取告訴人陳小華的手機。證人林美玉、黃志明於現場目睹。
二、案經陳小華訴請偵辦。
證據並所犯法條
一、證據清單及待證事實：被告王大明之自白、證人林美玉之證述。
二、核被告所為，係犯刑法第320條第1項之竊盜罪嫌。
三、依刑事訴訟法第251條第1項提起公訴。
中 華 民 國 109 年 3 月 23 日
"""


def stored_text(paragraphs):
    return re.sub(r"\s", "", "".join(p["text"] for p in paragraphs))


class TestSegment(unittest.TestCase):
    def setUp(self):
        self.paras = segment(FULL_TEXT)
        self.fns = [(p["function"], p["part"]) for p in self.paras]

    def test_bracketed_or_missing_attachment_heading(self):
        # 「【附件】：」標題，或沒有標題、直接接檢察官書類的標題行，都算附件
        for heading in ("【附件】：\n", ""):
            text = FULL_TEXT.replace("附件：\n", heading)
            parts = {p["part"] for p in segment(text) if "罪嫌" in p["text"] or "陳小華訴請" in p["text"]}
            self.assertEqual(parts, {"附件：起訴書"}, heading)

    def test_court_mention_of_prosecutor_document_is_not_attachment(self):
        # 法院本文提到「附件：…處刑書1份」不是書類本身的標題行
        text = FULL_TEXT.replace("附件：\n臺灣臺北地方檢察署檢察官起訴書\n", "附件：臺灣臺北地方檢察署檢察官起訴書1份\n")
        self.assertIsNone(next(p for p in segment(text) if "罪嫌" in p["text"])["part"])

    def test_sections_keep_original_order(self):
        order = []
        for fn, part in self.fns:
            if not order or order[-1] != (fn, part):
                order.append((fn, part))
        self.assertEqual(order, [
            ("info", None), ("verdict", None), ("facts", None), ("court", None), ("laws", None), ("other", None),
            ("laws", None), ("table", None), ("info", "附件：起訴書"), ("facts", "附件：起訴書"),
            ("evidence", "附件：起訴書"), ("court", "附件：起訴書"), ("laws", "附件：起訴書"), ("other", "附件：起訴書")])

    def test_no_text_is_lost_except_headings(self):
        headings = {"主文", "事實及理由", "犯罪事實", "證據並所犯法條"}
        source = "".join(line for raw in FULL_TEXT.splitlines()
                         if (line := re.sub(r"\s", "", clean(raw))) not in headings)
        source = source.replace("王大明", "被告").replace("被告被告", "被告")
        for name in ("陳小華", "林美玉", "黃志明"):
            source = source.replace(name, "【關係人】")
        self.assertEqual(stored_text(self.paras), source)

    def test_glossary_spaces_removed_and_inline_numbers_not_split(self):
        court = [p["text"] for p in self.paras if p["function"] == "court"]
        self.assertTrue(any("爰審酌被告" in t for t in court))
        self.assertTrue(any("第一、二級毒品為限" in t for t in court))

    def test_laws_and_tables_keep_line_breaks(self):
        appendix = next(p for p in self.paras if p["text"].startswith("附錄"))
        self.assertTrue(appendix["pre"])
        self.assertIn("\n中華民國刑法第320條\n", appendix["text"])
        self.assertEqual(next(p for p in self.paras if p["function"] == "table")["text"].splitlines()[0], "附表一：")

    def test_short_last_paragraph_is_kept(self):
        paras = segment("主 文\n本件公訴不受理。\n理 由\n一、告訴人撤回告訴，依刑事訴訟法第303條第3款判決如主文。")
        self.assertEqual([(p["function"], p["text"]) for p in paras[:1]], [("verdict", "本件公訴不受理。")])

    def test_system_fields_of_old_format_are_dropped(self):
        paras = segment("檔名：[D:\\x.TXT]\n主文：[王大明犯竊盜罪，\n處拘役。]\n主 文\n被告犯竊盜罪。")
        self.assertEqual([p["text"] for p in paras], ["被告犯竊盜罪。"])


# 原文每行固定寬度折行（約 26 個中文字），法條附錄要保留各項分行，但折行要接回去
WRAPPED = """臺灣雲林地方法院刑事簡易判決 104年度港簡字第156號
上列被告因公共危險等案件，經檢察官聲請以簡易判決處刑（10
4 年度撤緩偵字第242 號）本院判決如下：
主 文
被告犯妨害公眾往來安全罪，處拘役貳拾日。
事實及理由
一、犯罪事實：
緣某公司與自救會簽訂備忘錄，備忘錄三（五）規定應補償損
失。嗣颱風襲台，魚塭潰堤。
㈠被告等人共同基於壅塞陸路之犯意聯絡，停放車輛壅塞道路。
二、認定犯罪事實所憑證據及理由：
㈠被告於偵查中坦白承認，並有現場照片在卷可稽。
三、論罪科刑：核被告所為，係犯刑法第185 條第1 項之罪。
中 華 民 國 105 年 1 月 27 日
附錄本案論罪科刑法條全文：
中華民國刑法第185條
損壞或壅塞陸路、水路、橋樑或其他公眾往來之設備或以他法致
生往來之危險者，處5年以下有期徒刑，拘役或5百元以下罰金
。
第1項之未遂犯罰之。
"""


class TestHardWraps(unittest.TestCase):
    def setUp(self):
        self.paras = segment(WRAPPED)

    def test_fixed_width_wraps_are_joined_but_real_breaks_kept(self):
        info = self.paras[0]["text"]
        self.assertIn("（104年度撤緩偵字第242號）", info)
        self.assertTrue(info.startswith("臺灣雲林地方法院刑事簡易判決104年度港簡字第156號\n"))
        laws = [p["text"] for p in self.paras if p["function"] == "laws"][-1]
        self.assertIn("以他法致生往來之危險者", laws)
        self.assertIn("罰金。\n第1項之未遂犯罰之。", laws)
        self.assertIn("\n中華民國刑法第185條\n", laws)

    def test_inline_reference_numbers_are_not_headings(self):
        self.assertTrue(any("備忘錄三（五）規定" in p["text"] for p in self.paras))

    def test_sub_items_follow_their_numbered_heading(self):
        fns = [(p["function"], p["text"][:6]) for p in self.paras if p["function"] in ("facts", "evidence", "court")]
        self.assertEqual(fns, [("facts", "一、犯罪事實"), ("facts", "㈠被告等人共"), ("evidence", "二、認定犯罪"),
                               ("evidence", "㈠被告於偵查"), ("court", "三、論罪科刑")])


class TestSentences(unittest.TestCase):
    def verdict(self, text):
        return sentences([{"function": "verdict", "text": text, "part": None}])

    def test_single_offence_has_no_executed_sentence(self):
        self.assertEqual(self.verdict("被告犯恐嚇公眾罪，處有期徒刑貳月，如易科罰金，以新臺幣壹仟元折算壹日。"),
                         {"declared": ["有期徒刑 2 月"], "executed": None})

    def test_several_offences_and_executed_sentence(self):
        got = self.verdict("被告犯轉讓禁藥罪，累犯，處有期徒刑肆月；又犯轉讓禁藥罪，累犯，處有期徒刑伍月。應執行有期徒刑柒月。")
        self.assertEqual(got, {"declared": ["有期徒刑 4 月", "有期徒刑 5 月"], "executed": "有期徒刑 7 月"})

    def test_same_sentence_for_each_count(self):
        got = self.verdict("被告犯販賣第二級毒品罪，共陸罪，均累犯，各處有期徒刑拾年貳月。應執行有期徒刑拾壹年。")
        self.assertEqual(got, {"declared": ["有期徒刑 10 年 2 月（共 6 罪，各）"], "executed": "有期徒刑 11 年"})

    def test_fines_exemption_and_numerals(self):
        self.assertEqual(self.verdict("被告犯公然侮辱罪，科罰金新臺幣伍仟元，如易服勞役，以新臺幣壹仟元折算壹日。")["declared"], ["罰金 5,000 元"])
        self.assertEqual(self.verdict("被告犯毀損他人物品罪，免刑。")["declared"], ["免刑"])
        self.assertEqual(self.verdict("被告犯詐欺罪，處有期徒刑叄年拾月，併科罰金新臺幣６千元。")["declared"], ["有期徒刑 3 年 10 月，併科罰金 6,000 元"])
        self.assertEqual(cn_number("壹佰貳拾"), 120)
        self.assertEqual(cn_number("兩萬伍仟"), 25000)

    def test_messy_verdict_wording(self):
        self.assertEqual(self.verdict("被告犯誹謗罪，共貳罪，分別處拘役貳拾日、伍拾日。應執行拘役陸拾日。"),
                         {"declared": ["拘役 20 日", "拘役 50 日"], "executed": "拘役 60 日"})
        got = self.verdict("被告販賣第三級毒品，處有期徒刑參年捌月。又製造第三級毒品，處有期徒刑肆年。所處有期徒刑部分，應執行有期徒刑陸年陸月。")
        self.assertEqual(got, {"declared": ["有期徒刑 3 年 8 月", "有期徒刑 4 年"], "executed": "有期徒刑 6 年 6 月"})
        self.assertEqual(self.verdict("被告有配偶而與人通姦，處有期徒刑貳月又拾伍日。")["declared"], ["有期徒刑 2 月 15 日"])
        self.assertEqual(self.verdict("被告犯持有手槍罪，處有期徒刑1年7月，併科罰金新臺幣（下同）5萬元。")["declared"], ["有期徒刑 1 年 7 月，併科罰金 50,000 元"])
        self.assertEqual(self.verdict("被告犯詐欺罪，處有期徒刑貮年参月併科罰金新臺幣玖萬元。")["declared"], ["有期徒刑 2 年 3 月，併科罰金 90,000 元"])
        self.assertEqual(self.verdict("被告犯竊盜罪，處有期徒刑貳月扣案如附表所示之物均沒收之。")["declared"], ["有期徒刑 2 月"])

    def test_executed_or_single(self):
        """應執行刑欄：有應執行刑用它；一罪時用那一罪的宣告刑；數罪沒定應執行刑或刑在附表時留空。"""
        self.assertEqual(executed_or_single({"declared": ["有期徒刑 4 月", "有期徒刑 5 月"], "executed": "有期徒刑 7 月"}), "有期徒刑 7 月")
        self.assertEqual(executed_or_single({"declared": ["拘役 30 日"], "executed": None}), "拘役 30 日")
        self.assertIsNone(executed_or_single({"declared": ["有期徒刑 4 月", "有期徒刑 5 月"], "executed": None}))
        self.assertIsNone(executed_or_single({"declared": ["有期徒刑 1 年（共 3 罪，各）"], "executed": None}))
        self.assertIsNone(executed_or_single({"declared": ["如附表所示之刑"], "executed": None}))
        self.assertIsNone(executed_or_single({"declared": [], "executed": None}))

    def test_attachment_verdict_is_ignored(self):
        got = sentences([{"function": "verdict", "text": "被告處有期徒刑貳月。", "part": "附件：起訴書"}])
        self.assertEqual(got, {"declared": [], "executed": None})


class TestMasking(unittest.TestCase):
    def test_defendant_role_names_and_listed_names(self):
        guide = judgment_guide({"full_text": FULL_TEXT, "judgment_date": "2020-05-29", "defendant": "王大明"})
        text = json.dumps(guide, ensure_ascii=False)
        for name in ("王大明", "陳小華", "林美玉", "黃志明"):
            self.assertNotIn(name, text)
        self.assertIn("告訴人【關係人】", text)
        self.assertIn("證人【關係人】、【關係人】", text)
        self.assertNotIn("被告被告", text)
        self.assertEqual(guide["source"], "judgment")

    def test_simplified_trial_is_not_a_name(self):
        # 「簡」是姓氏：「被告簡式審判程序」的「簡式審」不是被告的名字
        text = FULL_TEXT.replace("三、依刑事訴訟法第449條第2項", "三、經告知被告簡式審判程序之旨，依刑事訴訟法第449條第2項")
        out = json.dumps(segment(text), ensure_ascii=False)
        self.assertIn("被告簡式審判程序", out)
        self.assertNotIn("被告判程序", out)

    def test_full_text_masks_officers_lists_citations_and_repeated_names(self):
        raw = """被 告 王大明
主 文
王大明處拘役十日。
事實及理由
一、會長周連福與董事長王永慶協商，更換會長為丁春樹。
共犯丁春樹（見偵卷第52頁）、林清
分（見偵卷第42頁）、徐名汯（另案處分）等人到場。
【被告】、黃萬泰、林億誠、林樹等人駕車。
證人【關係人】、周信宏、許董養於現場目睹。
二、周連福、王永慶、丁春樹、林清分、徐名汯再次到場。
三、刑法第185條規定損壞道路致生危險者，處五年以下有期徒刑。
中華民國105年1月27日
法 官 蔡鎮宇
書記官 黃嫀文
"""
        text = "\n".join(p["text"] for p in segment(raw))
        for name in ("王大明", "周連福", "王永慶", "丁春樹", "林清分", "徐名汯", "黃萬泰", "林億誠", "林樹", "周信宏", "許董養", "蔡鎮宇", "黃嫀文"):
            self.assertNotIn(name, text)
        self.assertNotIn("林清\n分", text)
        self.assertIn("刑法第185條規定損壞道路致生危險者，處五年以下有期徒刑。", text)
        self.assertIn("（見偵卷第52頁）", text)
        self.assertIn("書記官【關係人】", text)


class TestBuild(unittest.TestCase):
    def test_judgment_identity_ignores_url_encoding_not_case_id(self):
        self.assertEqual(judgment_id("https://judgment.judicial.gov.tw/FJUD/data.aspx?id=TPDM%2c113%2c簡"),
                         judgment_id("https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=TPDM,113,%E7%B0%A1&ot=in"))
        self.assertIsNone(judgment_id("https://example.com/?id=TPDM"))
        self.assertIsNone(judgment_id("https://judgment.judicial.gov.tw/?id=a&id=b"))

    def _raw_db(self, path: Path, rows):
        columns = ("full_text", "judgment_date", "defendant", "source_url", "case_number")
        with connect(path) as con:
            con.execute("CREATE TABLE judgments (" + ",".join(f"{c} TEXT" for c in columns) + ")")
            con.executemany("INSERT INTO judgments VALUES (?, ?, ?, ?, ?)", [tuple(r[c] for c in columns) for r in rows])

    def test_build_and_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train_artifacts(root)
            svc = CriminalService(root)
            self.assertIsNone(svc.guide(1)["criminal"])          # 還沒有 guides 表：只有摘要
            self.assertEqual(svc.guide(1)["labeler"], "summary-only")
            self.assertIsNone(svc.guide(9999))
            url = svc._query("SELECT url FROM cases WHERE id = 1")[0]["url"]
            row = {"full_text": FULL_TEXT, "judgment_date": "2020-05-29", "defendant": "王大明",
                   "source_url": url, "case_number": "臺灣臺北地方法院 109 年度審簡字第 1 號刑事判決"}
            raw = root / "raw.sqlite"
            self._raw_db(raw, [row])
            result = build(raw, svc.db_path)
            self.assertGreater(result["from_judgment"], 0)
            guide = svc.guide(1)
            self.assertEqual(guide["labeler"], "criminal-rule-v1")
            self.assertEqual(guide["criminal"]["source"], "judgment")
            self.assertEqual(guide["criminal"]["paragraphs"][1]["function"], "verdict")
            self.assertEqual(guide["criminal"]["paragraphs"][1]["text"], "被告犯竊盜罪，處拘役參拾日。")
            # 同一個識別碼有兩件時不知道是哪一件：不用
            self._raw_db(root / "dup.sqlite", [row, row])
            self.assertEqual(build(root / "dup.sqlite", svc.db_path)["ambiguous_urls"], 1)
            self.assertIsNone(svc.guide(1)["criminal"])

    def test_national_year_databases_and_full_coverage_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "national"
            raw_dir.mkdir()
            cases = root / "cases.db"
            urls = [f"https://judgment.judicial.gov.tw/FJUD/data.aspx?id=TPDM,{year},簡,1" for year in (2024, 2025)]
            with connect(cases) as con:
                con.execute("CREATE TABLE cases (id INTEGER PRIMARY KEY, url TEXT)")
                con.executemany("INSERT INTO cases VALUES (?, ?)", [(41, urls[0]), (92, urls[1])])
                con.execute("CREATE TABLE guides (case_id INTEGER PRIMARY KEY, source TEXT, judgment_date TEXT, paragraphs TEXT)")
                con.execute("INSERT INTO guides VALUES (41, 'judgment', '', '[]')")
            for i, year in enumerate((2024, 2025)):
                row = {"full_text": FULL_TEXT if i == 0 else "", "judgment_date": f"{year}-05-29", "defendant": "王大明",
                       "source_url": urls[i], "case_number": "臺灣臺北地方法院刑事判決"}
                self._raw_db(raw_dir / f"刑事判決_全國地院_{year}.db", [row])
            with self.assertRaisesRegex(ValueError, "原文只對上 1/2 件"):
                build(raw_dir, cases, require_full=True)
            with connect(cases) as con:
                self.assertEqual(con.execute("SELECT * FROM guides").fetchall(), [(41, "judgment", "", "[]")])
            with connect(raw_dir / "刑事判決_全國地院_2025.db") as con:
                con.execute("UPDATE judgments SET full_text = ?", (FULL_TEXT,))
            result = build(raw_dir, cases, require_full=True)
            self.assertEqual((result["from_judgment"], result["from_dataset"]), (2, 0))
            with connect(cases) as con:
                self.assertEqual(con.execute("SELECT case_id FROM guides ORDER BY case_id").fetchall(), [(41,), (92,)])
                texts = [json.loads(r[0]) for r in con.execute("SELECT paragraphs FROM guides")]
                for paragraphs in texts:
                    self.assertIn("verdict", {p["function"] for p in paragraphs})
                    self.assertIn("laws", {p["function"] for p in paragraphs})
                    self.assertTrue(any(p["part"] == "附件：起訴書" for p in paragraphs))
            with self.assertRaisesRegex(ValueError, "不能使用 CAIL fact 備援"):
                build(raw_dir, cases, root / "data.jsonl", require_full=True)

    def test_packaged_full_text_joins_index_row_and_overrides_fact_guide(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train_artifacts(root)
            svc = CriminalService(root)
            first = svc._query("SELECT id, row FROM cases ORDER BY row LIMIT 1")[0]
            self.assertNotEqual(first["id"], first["row"])
            with connect(svc.db_path) as con:
                con.execute("CREATE TABLE full_text (row INTEGER PRIMARY KEY, text TEXT)")
                con.execute("INSERT INTO full_text VALUES (?, ?)", (first["row"], FULL_TEXT.replace("王大明", "【被告】")))
                con.execute("UPDATE cases SET summary = ? WHERE id = ?", ("陳小華的手機遭竊，林美玉、黃志明到場。", first["id"]))
                con.execute("UPDATE cases SET url = ? WHERE id = ?",
                            ("https://judgment.judicial.gov.tw/FJUD/data.aspx?id=TPDM,109,簡,1,20200529,1", first["id"]))
                con.execute("CREATE TABLE guides (case_id INTEGER PRIMARY KEY, source TEXT, judgment_date TEXT, paragraphs TEXT)")
                con.execute("INSERT INTO guides VALUES (?, 'dataset', '', '[]')", (first["id"],))
            guide = svc.guide(first["id"])
            self.assertEqual(guide["case"]["summary"], "主文：【被告】犯竊盜罪，處拘役參拾日。")
            from backend.schemas import Guide
            Guide.model_validate(guide)
            detail = guide["criminal"]
            self.assertEqual((detail["source"], detail["judgment_date"]), ("judgment", "2020-05-29"))
            self.assertTrue(any(p["function"] == "verdict" for p in detail["paragraphs"]))
            self.assertTrue(any(p["part"] == "附件：起訴書" for p in detail["paragraphs"]))
            self.assertIsNone(svc.guide(999999))
            with connect(svc.db_path) as con:
                con.execute("UPDATE full_text SET text = ''")
            self.assertEqual(svc.guide(first["id"])["criminal"]["source"], "dataset")
            self.assertEqual(svc.guide(first["id"])["case"]["summary"], "未收錄主文，請查看判決原文。")

    def test_old_guides_table_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train_artifacts(root)
            svc = CriminalService(root)
            with connect(svc.db_path) as con:
                con.execute("CREATE TABLE guides (case_id INTEGER PRIMARY KEY, fields TEXT NOT NULL)")
                con.execute("INSERT INTO guides VALUES (1, '{\"verdict\": \"x\"}')")
            self.assertIsNone(svc.guide(1)["criminal"])

    def test_dataset_fallback_from_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, cases, data = root / "raw.db", root / "cases.db", root / "data.zip"
            self._raw_db(raw, [])
            row = synthetic(2)[1]
            with connect(cases) as con:
                con.execute("CREATE TABLE cases (id INTEGER PRIMARY KEY, url TEXT)")
                con.execute("INSERT INTO cases VALUES (?, ?)", (321, row["meta"]["source_url"]))
            with zipfile.ZipFile(data, "w") as archive:
                archive.writestr("data.jsonl", json.dumps(row))
            self.assertEqual(len(list(dataset_rows(data))), 1)
            self.assertEqual(build(raw, cases, data)["from_dataset"], 1)
            with connect(cases) as con:
                case_id, source, _, paragraphs = con.execute("SELECT * FROM guides").fetchone()
            self.assertEqual((case_id, source), (321, "dataset"))
            self.assertEqual({p["function"] for p in json.loads(paragraphs)}, {"facts"})

    def test_dataset_guide_masks_defendant(self):
        guide = dataset_guide(synthetic(2)[1])
        self.assertEqual(guide["source"], "dataset")
        self.assertNotIn("王大明", json.dumps(guide, ensure_ascii=False))

    def test_mock(self):
        svc = CriminalService(Path("unused"), force_mock=True)
        guide = svc.guide(-1)
        self.assertTrue(guide["mock"])
        self.assertEqual(guide["paragraphs"], [])
        self.assertEqual(guide["criminal"]["paragraphs"][1]["function"], "verdict")
        self.assertIsNone(svc.guide(9999))


if __name__ == "__main__":
    unittest.main()
