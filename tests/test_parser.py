# -*- coding: utf-8 -*-
"""
html_parser.py 的離線測試。

以 tests/fixtures/ 下兩份真實裁判書 HTML（取自司法院公開裁判書系統）為樣本：
  tpd_civil_judgment.html — 地方法院民事判決，標準 div 版型
  cc_ruling.html          — 憲法法庭裁定，text-pre 版型（特殊格式）
版型若被改版，這裡會先失敗。
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import html_parser  # noqa: E402
from html_parser import normalize_date, parse_html  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestNormalizeDate(unittest.TestCase):
    def test_roc_chinese(self):
        self.assertEqual(normalize_date("114年1月7日"), "2025-01-07")
        self.assertEqual(normalize_date("民國 114 年 12 月 31 日"), "2025-12-31")

    def test_roc_dotted(self):
        self.assertEqual(normalize_date("114.01.07"), "2025-01-07")
        self.assertEqual(normalize_date("114/1/7"), "2025-01-07")

    def test_ad_iso_passthrough(self):
        self.assertEqual(normalize_date("2025-01-07"), "2025-01-07")
        self.assertEqual(normalize_date("2025/01/07"), "2025-01-07")

    def test_garbage_returns_empty(self):
        # 舊版 DB 曾把「案由」誤存進日期欄，解析失敗必須回傳空字串而非拋錯
        self.assertEqual(normalize_date("清償借款"), "")
        self.assertEqual(normalize_date(""), "")


class TestParseCivilJudgment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = parse_html(
            _fixture("tpd_civil_judgment.html"), crawl_id=1,
            keyword="臺灣臺北地方法院-民事-判決",
            source_url="https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id=x",
        )

    def test_metadata(self):
        self.assertEqual(self.data["case_number"],
                         "臺灣臺北地方法院 113 年度訴字第 6910 號民事判決")
        self.assertEqual(self.data["court"], "臺灣臺北地方法院")
        self.assertEqual(self.data["judgment_date"], "2025-01-07")   # 西元 ISO
        self.assertEqual(self.data["case_type"], "清償借款")
        self.assertEqual(self.data["judgment_type"], "判決")

    def test_parties(self):
        self.assertEqual(self.data["plaintiff"], "台新國際商業銀行股份有限公司")
        self.assertEqual(self.data["defendant"], "張沛晴")
        self.assertIn("原告：", self.data["party_roles"])
        self.assertIn("被告：", self.data["party_roles"])

    def test_judges_and_clerk(self):
        self.assertEqual(self.data["judges"], "匡偉")
        self.assertEqual(self.data["clerk"], "林鈞婷")

    def test_sections(self):
        self.assertTrue(self.data["verdict"].startswith("被告"))
        self.assertIn("給付原告", self.data["verdict"])
        self.assertGreater(len(self.data["full_text"]), 500)

    def test_keyword_label_carried(self):
        self.assertEqual(self.data["keyword"], "臺灣臺北地方法院-民事-判決")

    def test_reasons_heading_not_merged_into_verdict(self):
        # 「事實及理由」單獨成行（非 notEdit 標題）時，曾被併進主文、事實及理由欄變空
        verdict = self.data["verdict"]
        self.assertLess(len(verdict), 300)
        self.assertNotIn("為有理由", verdict)
        self.assertNotIn("爰判決如主文", verdict)
        self.assertGreater(len(self.data["facts_and_reasons"]), 300)
        self.assertIn("爰判決如主文", self.data["facts_and_reasons"])


class TestParseConstitutionalCourtRuling(unittest.TestCase):
    """憲法法庭是 text-pre 版型，欄位切法與一般法院不同。"""

    @classmethod
    def setUpClass(cls):
        cls.data = parse_html(_fixture("cc_ruling.html"), crawl_id=2)

    def test_metadata(self):
        self.assertEqual(self.data["court"], "憲法法庭")
        self.assertEqual(self.data["judgment_date"], "2025-04-30")
        self.assertEqual(self.data["judgment_type"], "裁定")

    def test_sections(self):
        self.assertEqual(self.data["verdict"], "本件不受理。")
        self.assertGreater(len(self.data["reasons"]), 200)

    def test_petitioners_go_to_plaintiff_field(self):
        self.assertIn("林薛彩雲", self.data["plaintiff"])
        self.assertIn("聲請人：", self.data["party_roles"])


class TestParseDegradesGracefully(unittest.TestCase):
    def test_stub_html_does_not_raise(self):
        data = parse_html("<html><head><title>x</title></head><body></body></html>",
                          crawl_id=3, case_number_hint="臺灣臺北地方法院 113 年度 訴 字第 1 號民事判決")
        # 取不到內容時以 hint 保底，且仍能判定法院與裁判種類
        self.assertEqual(data["court"], "臺灣臺北地方法院")
        self.assertEqual(data["judgment_type"], "判決")
        self.assertEqual(data["verdict"], "")

    def test_empty_html_does_not_raise(self):
        data = parse_html("", crawl_id=4)
        self.assertEqual(data["case_number"], "")
        self.assertEqual(data["judgment_type"], "")


class TestSaveJudgment(unittest.TestCase):
    """寫入暫存 DB，不碰真正的 judgments.db。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._db = html_parser.DB_PATH
        html_parser.DB_PATH = os.path.join(self.tmp.name, "t.db")
        html_parser.init_db()

    def tearDown(self):
        html_parser.DB_PATH = self._db
        self.tmp.cleanup()

    def test_insert_and_replace(self):
        data = parse_html(_fixture("tpd_civil_judgment.html"), crawl_id=1,
                          keyword="測試標籤")
        self.assertTrue(html_parser.save_judgment(data))
        self.assertTrue(html_parser.save_judgment(data))   # INSERT OR REPLACE
        conn = sqlite3.connect(html_parser.DB_PATH)
        rows = conn.execute(
            "SELECT case_number, judgment_type, keyword FROM judgments").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "判決")
        self.assertEqual(rows[0][2], "測試標籤")


if __name__ == "__main__":
    unittest.main()


class TestSectionHeadingFallback(unittest.TestCase):
    """
    段落標題辨識的後備判準。

    兩個缺陷都會造成**靜默的資料缺漏**：標題沒被認出來，其後的內容全部
    留在 preamble，verdict 欄位變空，而且不會有任何錯誤訊息。實測 12,416
    筆裡有 17 筆中招，其中 14 筆落在臺北地院 2025 民事判決。
    """

    # _find_content_container 要求 .htmlcontent 的文字超過 100 字元才認定為正文容器，
    # 所以理由段要有足夠長度，否則整份文件會被當成未載入完成而降級處理。
    _REASONS = (
        "一、被告經合法通知，未於言詞辯論期日到場，爰依原告之聲請，由其一造辯論而為判決。"
        "二、原告主張兩造間就系爭房地有借名登記關係，惟未能舉證以實其說，其請求為無理由。"
    )

    @staticmethod
    def _page(heading_html: str) -> str:
        return (
            '<div id="jud"><div class="htmlcontent">'
            '<div class="he-h1">臺灣臺北地方法院民事判決</div>'
            '<div>114年度重訴字第486號</div>'
            '<div>原　告　黃○○</div>'
            '<div>上列當事人間請求事件，本院判決如下︰</div>'
            f'{heading_html}'
            '<div>原告之訴及假執行之聲請均駁回。</div>'
            '<div>訴訟費用由原告負擔。</div>'
            '<div class="notEdit">理　由</div>'
            f'<div>{TestSectionHeadingFallback._REASONS}</div>'
            '</div></div>'
        )

    def test_heading_with_notedit_class_still_works(self):
        """原本就支援的格式不能被改壞。"""
        d = parse_html(self._page('<div class="notEdit">主　文</div>'), crawl_id=-1)
        self.assertIn("原告之訴", d["verdict"])

    def test_heading_without_any_class(self):
        """REGRESSION：標題 div 沒有 notEdit class 時，舊規則整段漏抓。"""
        d = parse_html(self._page('<div>主　文</div>'), crawl_id=-1)
        self.assertIn("原告之訴", d["verdict"],
                      "沒有 class 的「主　文」也必須被認成段落標題")

    def test_heading_with_zero_width_characters(self):
        """REGRESSION：司法院頁面的標題偶爾夾帶 U+200B，空白正規化清不掉。"""
        d = parse_html(self._page('<div>主 文 \u200b\u200b\u200b\u200b</div>'), crawl_id=-1)
        self.assertIn("原告之訴", d["verdict"])

    def test_body_text_is_not_mistaken_for_heading(self):
        """後備判準比對完整字串，不能把提到「主文」的內文當成標題。"""
        page = (
            '<div id="jud"><div class="htmlcontent">'
            '<div class="he-h1">臺灣臺北地方法院民事判決</div>'
            '<div class="notEdit">主　文</div>'
            '<div>被告應給付原告新臺幣100萬元。</div>'
            '<div class="notEdit">理　由</div>'
            '<div>本件原判決主文第一項應予維持，爰判決如主文所示。</div>'
            f'<div>{TestSectionHeadingFallback._REASONS}</div>'
            '</div></div>'
        )
        d = parse_html(page, crawl_id=-1)
        self.assertIn("被告應給付", d["verdict"])
        self.assertNotIn("爰判決如主文所示", d["verdict"],
                         "內文提到「主文」不得被當成新的段落標題")

    def test_normalize_section_title(self):
        self.assertEqual(html_parser._normalize_section_title("主　文"), "主文")
        self.assertEqual(html_parser._normalize_section_title("主 文 \u200b\u200b"), "主文")
        self.assertEqual(html_parser._normalize_section_title("事　實　及　理　由"), "事實及理由")


class TestExtractLaws(unittest.TestCase):
    """
    _extract_laws / _YIJU_RE 的回歸測試。

    容嫣於 PR #4 留言用她本機 12,417 份民事判決做全量比對回報：
    - 案例一（filler 吞掉法條）：23 筆從有值退步成空白（其中 5 筆完全空白）。
    - 案例二（敘述文字混入）：101 筆把原告主張／答辯的法條也一併抓進來。
    第三個案例是修第一、二點時，自己在本庫實測發現的退步：只取「最後一個依」
    的簡單做法，會被括號附注裡另一個不相干的「依」（例如引用辦案應行注意事項）
    誤切，反而把前面真正的法條引用切掉。
    """

    def _laws(self, reasons: str) -> str:
        return html_parser._extract_laws(None, {"理由": reasons}, "")

    def test_filler_does_not_swallow_the_real_citation(self):
        """案例一：逗號後的 filler 不能貪走緊接在後的法條引用。"""
        text = (
            "本院依調查證據之結果，認定兩造間之借款關係屬實，"
            "原告之訴為有理由，依民事訴訟法第78條，判決如主文。"
        )
        self.assertEqual(self._laws(text), "民事訴訟法第78條")

    def test_narrative_law_mentions_are_excluded(self):
        """案例二：只取最後一個起法條引用的「依」之後的文字，不把原告主張的法條也抓進來。"""
        text = (
            "原告主張，原告援引民法第179條請求返還，並依民法第244條第1項規定聲明撤銷。"
            "被告則以罹於時效置辯。本院審酌全案卷證，認原告之訴為無理由，"
            "依民事訴訟法第78條，判決如主文。"
        )
        laws = self._laws(text)
        self.assertEqual(laws, "民事訴訟法第78條")
        self.assertNotIn("民法第179條", laws)
        self.assertNotIn("民法第244條", laws)

    def test_unrelated_yi_inside_parenthetical_note_is_not_the_anchor(self):
        """REGRESSION：括號附注裡的另一個「依」不能切掉前面真正的法條引用。"""
        text = (
            "依刑事訴訟法第449條第2項、第3項、第454條第2項"
            "（依法院辦理刑事訴訟案件應行注意事項第159點，"
            "判決書據上論結部分，得僅引用應適用之程序法條），判決如主文。"
        )
        self.assertIn("刑事訴訟法第449條", self._laws(text))

    def test_simplified_judgment_wording_still_works(self):
        """今天稍早的修正（逕以簡易判決處刑如主文）不能被這次收緊的 filler 擋掉。"""
        text = "依刑事訴訟法第449條第1項前段、第3項，逕以簡易判決處刑如主文。"
        self.assertIn("刑事訴訟法第449條", self._laws(text))


class TestPartyNameCleanup(unittest.TestCase):
    """當事人姓名擷取的殘留字元清理。"""

    def test_jian_gongtong_residue_is_dropped(self):
        """
        REGRESSION：「兼　共　同」這種獨立成行、後面沒接名字的殘留片段，
        不能被當成一個假的當事人姓名存進去（容嫣於 PR #4 留言回報，
        113 年度簡上字第 394 號的 appellant 存成「A男；A男之母；兼 共 同」）。
        """
        result = html_parser._extract_parties(["被告 甲○○", "　兼　共　同"])
        self.assertEqual(result["defendant"], "甲○○")

    def test_jian_role_prefix_still_stripped(self):
        """既有行為不能被這次的連接詞過濾改壞：「兼輔助人」前綴仍要剝除。"""
        result = html_parser._extract_parties(["被告 王哲西", "兼 輔助 人　才仁多杰"])
        self.assertEqual(result["defendant"], "王哲西；才仁多杰")
