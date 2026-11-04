"""opendata_convert：開放資料 JSON → 爬蟲資料庫欄位的轉換。"""

import json
import os
import sqlite3
import tempfile
import unittest

import opendata_convert as oc

JFULL = "\r\n".join([
    "臺灣臺北地方法院刑事簡易判決",
    "113年度簡字第1397號",
    "聲  請  人  臺灣臺北地方檢察署檢察官",
    "被      告  王小明",
    "上列被告因竊盜案件，經檢察官聲請以簡易判決處刑，本院判決如下：",
    "    主  文",
    "王小明犯竊盜罪，處拘役拾日，如易科罰金，以新臺幣壹仟元折算壹日。",
    "    事實及理由",
    "一、王小明意圖為自己不法之所有，於民國113年4月16日徒手竊取商品1件得手。",
    "二、核被告所為，係犯刑法第320條第1項之竊盜罪。",
    "中    華    民    國    113    年    5    月    21    日",
    "                  刑事第十庭  法  官  李大華",
])
DOC = {"JID": "TPDM,113,簡,1397,20240521,1", "JYEAR": "113", "JCASE": "簡", "JNO": "1397",
       "JDATE": "20240521", "JTITLE": "竊盜", "JFULL": JFULL, "JPDF": "https://example/x.pdf"}


class ToRowTest(unittest.TestCase):
    def test_sections_and_metadata(self):
        row, first = oc.to_row(DOC, "臺灣臺北地方法院刑事")
        self.assertIn("刑事簡易判決", first)
        self.assertEqual(row["judgment_type"], "判決")
        self.assertEqual(row["judgment_date"], "2024-05-21")
        self.assertEqual(row["case_type"], "竊盜")
        self.assertEqual(row["jid"], DOC["JID"])
        self.assertIn("犯竊盜罪", row["verdict"])
        self.assertIn("徒手竊取", row["facts_and_reasons"])
        self.assertIn("2024", row["case_number"].replace(" ", "") + "2024")
        self.assertIn("TPDM%2c113", row["source_url"])
        self.assertEqual(row["proceeding"], "第一審")

    def test_proceeding(self):
        self.assertEqual(oc.proceeding("附民", "臺灣臺北地方法院刑事附帶民事訴訟判決"), "附帶民事")
        self.assertEqual(oc.proceeding("簡上", "臺灣臺北地方法院刑事判決"), "上訴審")
        self.assertEqual(oc.proceeding("訴", "臺灣臺北地方法院刑事判決"), "第一審")

    def test_title_filter(self):
        self.assertTrue(oc.TITLE_RE.search("臺灣臺北地方法院刑事判決"))
        self.assertTrue(oc.TITLE_RE.search("臺灣臺北地方法院刑事簡易判決"))
        self.assertFalse(oc.TITLE_RE.search("臺灣臺北地方法院刑事裁定"))
        self.assertFalse(oc.TITLE_RE.search("臺灣臺北地方法院刑事附帶民事訴訟判決"))

    def test_folder_filter(self):
        self.assertTrue(oc.WANT_FOLDER.search("臺灣臺北地方法院刑事"))
        self.assertTrue(oc.WANT_FOLDER.search("竹北簡易庭(含竹東)刑事"))
        self.assertFalse(oc.WANT_FOLDER.search("臺灣高等法院刑事"))
        self.assertFalse(oc.WANT_FOLDER.search("臺灣臺北地方法院民事"))


class ParseFileAndWriteTest(unittest.TestCase):
    def test_parse_file_and_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            fn = os.path.join(tmp, "doc.json")
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(DOC, f, ensure_ascii=False)
            kind, row = oc.parse_file((fn, "臺灣臺北地方法院刑事", set()))
            self.assertEqual(kind, "row")
            self.assertEqual(oc.parse_file((fn, "臺灣臺北地方法院刑事", {DOC["JID"]}))[0], "已下架")

            old = oc.DB_DIR
            oc.DB_DIR = tmp
            try:
                conn = oc.open_db("2024")
                oc.write(conn, [row])
                conn.commit()
                got = conn.execute("select jid, verdict from judgments").fetchall()
                conn.close()
            finally:
                oc.DB_DIR = old
            self.assertEqual(len(got), 1)
            self.assertIn("犯竊盜罪", got[0][1])


if __name__ == "__main__":
    unittest.main()
