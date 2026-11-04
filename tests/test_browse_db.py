# -*- coding: utf-8 -*-
"""
scripts/browse_db.py 的離線測試：補建索引、找資料庫的位置、轉交給 datasette 的指令。
datasette 本身不會啟動（subprocess.call 以 mock 取代）。
"""

import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import browse_db as B  # noqa: E402


class _TempRoot(unittest.TestCase):
    """把 browse_db.ROOT 換成暫存目錄，當成 repo 根目錄。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "judgments.db")
        with sqlite3.connect(self.db) as c:
            c.execute("CREATE TABLE judgments (id INTEGER, court TEXT, judgment_date TEXT)")
        self.root = mock.patch.object(B, "ROOT", self.tmp.name)
        self.root.start()

    def tearDown(self):
        self.root.stop()
        self.tmp.cleanup()

    def indexes(self):
        with sqlite3.connect(self.db) as c:
            return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}

    def run_main(self, *argv, call=None):
        with mock.patch.object(sys, "argv", ["browse_db.py", *argv]), \
                mock.patch.object(B.subprocess, "call", call or mock.Mock(return_value=0)) as c, \
                redirect_stdout(io.StringIO()) as out:
            rc = B.main()
        return rc, out.getvalue(), c


class TestEnsureIndexes(_TempRoot):
    def test_indexes_only_existing_columns(self):
        B.ensure_indexes(self.db)
        self.assertEqual(self.indexes(), {"idx_judgments_court", "idx_judgments_judgment_date"})

    def test_idempotent(self):
        B.ensure_indexes(self.db)
        B.ensure_indexes(self.db)
        self.assertEqual(len(self.indexes()), 2)


class TestMain(_TempRoot):
    def test_missing_database(self):
        rc, out, call = self.run_main("--db", "nope.db")
        self.assertEqual(rc, 1)
        self.assertIn("找不到資料庫", out)
        call.assert_not_called()

    def test_default_database_is_at_repo_root(self):
        rc, _, call = self.run_main()
        self.assertEqual(rc, 0)
        cmd = call.call_args.args[0]
        self.assertEqual(cmd[1:5], ["-m", "datasette", "serve", self.db])
        self.assertIn("idx_judgments_court", self.indexes())

    def test_command_and_environment(self):
        _, _, call = self.run_main("-p", "8002")
        cmd, env = call.call_args.args[0], call.call_args.kwargs["env"]
        metadata = cmd[cmd.index("--metadata") + 1]
        self.assertEqual(metadata, os.path.join(B.HERE, "datasette_metadata.yml"))
        self.assertTrue(os.path.isfile(metadata))
        settings = {cmd[i + 1]: cmd[i + 2] for i, a in enumerate(cmd) if a == "--setting"}
        self.assertEqual(settings, B.SETTINGS)
        self.assertEqual(cmd[-2:], ["-p", "8002"])          # 其餘參數原樣轉交
        self.assertEqual(env["PYTHONUTF8"], "1")

    def test_ctrl_c_exits_cleanly(self):
        rc, _, _ = self.run_main(call=mock.Mock(side_effect=KeyboardInterrupt))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
