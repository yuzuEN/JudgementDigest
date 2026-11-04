# -*- coding: utf-8 -*-
"""
backfill_structured.py 的離線測試：篩選條件、備份檔名、試跑不寫入、
--only-missing 依規則版本判斷、只寫結構化欄位。全部在暫存 DB 進行。
"""

import glob
import io
import logging
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))

import backfill_structured as B  # noqa: E402
import html_parser  # noqa: E402
from structuring import STRUCTURING_VERSION  # noqa: E402

VERDICT_WIN = "被告應給付原告新臺幣10萬元。訴訟費用由被告負擔。"
VERDICT_LOSE = "原告之訴駁回。訴訟費用由原告負擔。"
ROWS = [
    # (id, case_number, court, judgment_date, verdict)
    (1, "臺灣臺北地方法院 113 年度訴字第 1 號民事判決", "臺灣臺北地方法院", "2025-01-07", VERDICT_WIN),
    (2, "臺灣臺北地方法院 112 年度訴字第 2 號民事判決", "臺灣臺北地方法院", "2024-03-01", VERDICT_LOSE),
    (3, "臺灣高雄地方法院 113 年度訴字第 3 號民事判決", "臺灣高雄地方法院", "2025-02-01", VERDICT_LOSE),
]


class TestBuildWhere(unittest.TestCase):
    def test_no_filter(self):
        self.assertEqual(B.build_where(None, None, False), ("1=1", []))

    def test_court_year_and_missing(self):
        where, params = B.build_where("臺北", "2025", True)
        self.assertIn("court LIKE ?", where)
        self.assertIn("judgment_date LIKE ?", where)
        self.assertIn("structuring_version != ?", where)
        self.assertEqual(params, ["%臺北%", "2025%", STRUCTURING_VERSION])


class _TempDbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "judgments.db")
        self._orig = (B.DB_PATH, html_parser.DB_PATH)
        B.DB_PATH = html_parser.DB_PATH = self.db
        html_parser.init_db()
        with sqlite3.connect(self.db) as c:
            c.executemany("INSERT INTO judgments (id, crawl_id, case_number, court, judgment_date, "
                          "case_type, judgment_type, verdict) VALUES (?,?,?,?,?,'民事','判決',?)",
                          [(r[0], *r) for r in ROWS])
        logging.disable(logging.INFO)

    def tearDown(self):
        logging.disable(logging.NOTSET)
        B.DB_PATH, html_parser.DB_PATH = self._orig
        self.tmp.cleanup()

    def run_backfill(self, **kw):
        with redirect_stdout(io.StringIO()):
            return B.run(**kw)

    def column(self, name):
        with sqlite3.connect(self.db) as c:
            return dict(c.execute(f"SELECT id, {name} FROM judgments"))


class TestBackupDb(_TempDbCase):
    def test_backup_name_matches_gitignore(self):
        """備份要叫 judgments.db.bak-*，才會被 .gitignore 的 judgments.db* 排除。"""
        dst = B.backup_db(self.db)
        self.assertRegex(os.path.basename(dst), r"^judgments\.db\.bak-\d{8}_\d{6}$")
        self.assertTrue(os.path.exists(dst))


class TestRun(_TempDbCase):
    def test_dry_run_does_not_write(self):
        self.assertEqual(self.run_backfill(dry_run=True), 3)
        self.assertEqual(set(self.column("structuring_version").values()), {None})
        self.assertEqual(glob.glob(self.db + ".bak-*"), [])

    def test_backfill_writes_structured_columns_only(self):
        with sqlite3.connect(self.db) as c:
            before = c.execute("SELECT verdict, case_number FROM judgments ORDER BY id").fetchall()
        self.assertEqual(self.run_backfill(no_backup=True), 3)
        self.assertEqual(set(self.column("structuring_version").values()), {STRUCTURING_VERSION})
        self.assertEqual(self.column("outcome"), {1: "勝訴", 2: "敗訴", 3: "敗訴"})
        with sqlite3.connect(self.db) as c:
            after = c.execute("SELECT verdict, case_number FROM judgments ORDER BY id").fetchall()
        self.assertEqual(before, after, "原始欄位不能被改動")

    def test_backup_before_write(self):
        self.run_backfill()
        self.assertEqual(len(glob.glob(self.db + ".bak-*")), 1)

    def test_filters(self):
        self.assertEqual(self.run_backfill(court="臺北", no_backup=True), 2)
        self.assertEqual(self.run_backfill(court="臺北", year="2025", dry_run=True), 1)
        self.assertEqual(self.run_backfill(court="花蓮", dry_run=True), 0)

    def test_only_missing_refreshes_old_versions(self):
        self.run_backfill(no_backup=True)
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE judgments SET structuring_version='0.0.0' WHERE id=3")
        self.assertEqual(self.run_backfill(only_missing=True, no_backup=True), 1)
        self.assertEqual(self.run_backfill(only_missing=True, no_backup=True), 0)

    def test_idempotent(self):
        self.run_backfill(no_backup=True)
        first = self.column("outcome")
        self.run_backfill(no_backup=True)
        self.assertEqual(self.column("outcome"), first)


class TestMain(unittest.TestCase):
    def test_arguments_are_passed_to_run(self):
        argv = ["backfill_structured.py", "--court", "臺北", "--year", "2025",
                "--only-missing", "--dry-run", "--no-backup"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(B, "run") as run:
            B.main()
        run.assert_called_once_with("臺北", "2025", True, True, True)


if __name__ == "__main__":
    unittest.main()
