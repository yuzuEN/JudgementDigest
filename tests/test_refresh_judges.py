# -*- coding: utf-8 -*-
"""
refresh_judges.py 的離線測試：只更新法官／書記官有變的列、略過被截斷的全文、
--dry-run 不寫入、寫入前備份。全部在暫存 DB 進行。
"""

import glob
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))

import html_parser  # noqa: E402
import refresh_judges as R  # noqa: E402

SIGNED = "本件判決如主文。法　官　王小明　以上正本係照原本作成。書記官　李小華"
ROWS = [
    # (id, judges, clerk, full_text)
    (1, "王小明", "李小華", SIGNED),                      # 已經正確：不動
    (2, "", "", SIGNED),                                   # 之前沒抓到：要更新
    # 長度剛好到上限：簽名區可能被截掉，就算抓得到法官也不動
    (3, "", "", SIGNED + "截" * (R.FULL_TEXT_CAP - len(SIGNED))),
]


class _TempDbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "judgments.db")
        self._orig = html_parser.DB_PATH
        html_parser.DB_PATH = self.db
        html_parser.init_db()
        html_parser.DB_PATH = self._orig
        with closing(sqlite3.connect(self.db)) as c, c:
            c.executemany("INSERT INTO judgments (id, crawl_id, judges, clerk, full_text) "
                          "VALUES (?,?,?,?,?)", [(i, i, j, k, t) for i, j, k, t in ROWS])
        self.patches = [mock.patch.object(R, "DB_PATH", self.db),
                        mock.patch.object(R, "_extract_judges_and_clerk",
                                          side_effect=self.fake_extract)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    @staticmethod
    def fake_extract(full_text):
        return ("王小明", "李小華") if "王小明" in full_text else ("", "")

    def run_main(self, *argv):
        with mock.patch.object(sys, "argv", ["refresh_judges.py", *argv]), \
                redirect_stdout(io.StringIO()) as out:
            rc = R.main()
        return rc, out.getvalue()

    def judges(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            return dict(c.execute("SELECT id, judges FROM judgments"))

    def backups(self):
        return glob.glob(self.db + ".bak-*")


class TestRefreshJudges(_TempDbCase):
    def test_dry_run_reports_but_does_not_write(self):
        rc, out = self.run_main("--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("會更新 1 筆", out)
        self.assertIn("法官 0 位 → 1 位：1", out)
        self.assertEqual(self.judges()[2], "")
        self.assertEqual(self.backups(), [])

    def test_updates_only_changed_rows(self):
        rc, _ = self.run_main("--no-backup")
        self.assertEqual(rc, 0)
        self.assertEqual(self.judges(), {1: "王小明", 2: "王小明", 3: ""})
        self.assertEqual(self.backups(), [])

    def test_backup_before_write(self):
        self.run_main()
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].endswith("-judges"))
        with closing(sqlite3.connect(backups[0])) as c, c:      # 備份是寫入前的內容
            self.assertEqual(c.execute("SELECT judges FROM judgments WHERE id=2").fetchone()[0], "")

    def test_nothing_to_change_skips_backup(self):
        self.run_main("--no-backup")
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("會更新 0 筆", out)
        self.assertEqual(self.backups(), [])


if __name__ == "__main__":
    unittest.main()
