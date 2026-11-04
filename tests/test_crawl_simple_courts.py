# -*- coding: utf-8 -*-
"""
crawl_simple_courts.py 的離線測試：狀態檔、待爬月份、子程序參數、Ctrl+C 收尾與重試流程。
子程序、睡眠與瀏覽器全部以 mock 取代；狀態檔與資料庫都在暫存目錄。
"""

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, nullcontext, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))

import crawl_monthly  # noqa: E402
import crawl_simple_courts as C  # noqa: E402

COURT = C.SIMPLE_ONLY_COURTS[0]


class _TempCwd(unittest.TestCase):
    """狀態檔與 judgments.db 都用相對於目前目錄的路徑，所以在暫存目錄裡執行。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self.tmp.cleanup()

    def write_state(self, year, done_months, skip_small=True):
        months = {crawl_monthly.month_key(year, m): {"status": "done"} for m in done_months}
        with open(C.state_path(COURT, year, skip_small), "w", encoding="utf-8") as f:
            json.dump({"months": months}, f)


class TestStatePath(unittest.TestCase):
    def test_skip_small_has_its_own_state_file(self):
        with_small = C.state_path(COURT, 2024, skip_small=False)
        without = C.state_path(COURT, 2024, skip_small=True)
        self.assertTrue(with_small.endswith("_2024.json"))
        self.assertTrue(without.endswith("_2024_無小額.json"))
        self.assertIn(COURT, without)


class TestPendingMonths(_TempCwd):
    def test_no_state_file_means_all_pending(self):
        self.assertEqual(C.pending_months(COURT, 2024, True), list(range(1, 13)))

    def test_done_months_are_skipped(self):
        self.write_state(2024, [1, 2, 3, 12])
        self.assertEqual(C.pending_months(COURT, 2024, True), list(range(4, 12)))

    def test_state_files_are_separate_by_small_claims(self):
        self.write_state(2024, range(1, 13), skip_small=True)
        self.assertEqual(C.pending_months(COURT, 2024, True), [])
        self.assertEqual(C.pending_months(COURT, 2024, False), list(range(1, 13)))


class TestRecordCount(_TempCwd):
    def test_counts_crawl_records(self):
        with closing(sqlite3.connect("judgments.db")) as c, c:
            c.execute("CREATE TABLE crawl_records (id INTEGER PRIMARY KEY)")
            c.executemany("INSERT INTO crawl_records VALUES (?)", [(1,), (2,), (3,)])
        self.assertEqual(C.record_count(), 3)


class TestChildArgs(unittest.TestCase):
    def test_crawl_year_runs_crawl_monthly_by_absolute_path(self):
        with mock.patch.object(C, "run_child", return_value=0) as run:
            C.crawl_year(COURT, 2023, skip_small=True)
        args = run.call_args.args[0]
        self.assertEqual(args[0], os.path.join(C.HERE, "crawl_monthly.py"))
        self.assertEqual(args[args.index("--court") + 1], COURT)
        self.assertEqual(args[args.index("--year") + 1], "2023")
        self.assertEqual(args[args.index("--state") + 1], C.state_path(COURT, 2023, True))
        self.assertIn("--skip-small-claims", args)
        self.assertIn("--no-export", args)

    def test_crawl_year_with_small_claims(self):
        with mock.patch.object(C, "run_child", return_value=0) as run:
            C.crawl_year(COURT, 2023, skip_small=False)
        self.assertNotIn("--skip-small-claims", run.call_args.args[0])

    def test_parse_new_warns_on_failure(self):
        with mock.patch.object(C, "run_child", return_value=2) as run, \
                redirect_stdout(io.StringIO()) as out:
            C.parse_new()
        self.assertEqual(run.call_args.args[0], [os.path.join(C.HERE, "html_parser.py")])
        self.assertIn("解析結束代碼 2", out.getvalue())


class TestRunChild(unittest.TestCase):
    def _popen(self, proc):
        return mock.patch.object(C.subprocess, "Popen", return_value=proc)

    def test_returns_exit_code(self):
        proc = mock.Mock(**{"wait.return_value": 0})
        with self._popen(proc) as popen:
            self.assertEqual(C.run_child(["x.py", "--a"]), 0)
        self.assertEqual(popen.call_args.args[0], [sys.executable, "x.py", "--a"])

    def test_ctrl_c_waits_for_child_then_raises(self):
        """子程序在時限內自己結束：不強制終止，但仍回報中斷讓外層停下。"""
        proc = mock.Mock()
        proc.wait.side_effect = [KeyboardInterrupt, 0]
        proc.poll.side_effect = [None, 0, 0]
        with self._popen(proc), redirect_stdout(io.StringIO()):
            with self.assertRaises(C.Interrupted):
                C.run_child(["x.py"])
        proc.kill.assert_not_called()

    def test_ctrl_c_kills_child_after_grace_period(self):
        """子程序一直不結束（每次等 1 秒都逾時）：時限一到就強制終止。"""
        proc = mock.Mock(**{"poll.return_value": None})
        proc.wait.side_effect = [KeyboardInterrupt, subprocess.TimeoutExpired("x", 1), 0]
        clock = iter([0, 0.5, C.GRACE_SEC + 1])     # 開始、等待中、超過時限
        with self._popen(proc), mock.patch.object(C.time, "time", side_effect=lambda: next(clock)), \
                redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(C.Interrupted):
                C.run_child(["x.py"])
        proc.kill.assert_called_once()
        self.assertIn("強制終止", out.getvalue())


class TestMain(_TempCwd):
    def run_main(self, *argv):
        with mock.patch.object(sys, "argv", ["crawl_simple_courts.py", *argv]), \
                redirect_stdout(io.StringIO()) as out:
            rc = C.main()
        return rc, out.getvalue()

    def test_dry_run_lists_pending_months(self):
        self.write_state(2025, range(1, 13))
        self.write_state(2024, [1, 2])
        rc, out = self.run_main("--dry-run", "--courts", COURT, "--years", "2025,2024")
        self.assertEqual(rc, 0)
        self.assertIn(f"{COURT} 2025：✓ 完成", out)
        self.assertIn(f"{COURT} 2024：待爬 {list(range(3, 13))}", out)

    def test_unknown_court_is_rejected(self):
        with mock.patch.object(sys, "argv", ["x", "--courts", "臺灣臺北地方法院"]), \
                mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                C.main()

    def _patched_loop(self, pending):
        """pending：每次呼叫 pending_months 依序回傳的待爬月份。"""
        return [mock.patch.object(C, "pending_months", side_effect=pending),
                mock.patch.object(C, "crawl_year", return_value=0),
                mock.patch.object(C, "parse_new"),
                mock.patch.object(C, "record_count", return_value=0),
                mock.patch.object(C.time, "sleep"),
                mock.patch.object(crawl_monthly, "keep_awake", return_value=nullcontext())]

    def _run_loop(self, pending):
        patches = self._patched_loop(pending)
        mocks = [p.start() for p in patches]
        try:
            rc, out = self.run_main("--courts", COURT, "--years", "2024")
        finally:
            for p in patches:
                p.stop()
        return rc, out, mocks

    def test_retry_until_complete(self):
        # 第 1 次前：待爬；第 1 次後：還有 5 月 → 等待重試；第 2 次前、後：完成；總結：完成
        rc, out, (_, crawl, parse, _, sleep, _) = self._run_loop([[1, 5], [5], [], [], []])
        self.assertEqual(rc, 0)
        self.assertEqual(crawl.call_count, 1)
        sleep.assert_called_once_with(C.RETRY_WAIT_MIN * 60)
        self.assertIn("12 個月全部完成", out)

    def test_gives_up_after_max_attempts(self):
        rc, out, (_, crawl, _, _, sleep, _) = self._run_loop(lambda *a: [7])
        self.assertEqual(rc, 1)
        self.assertEqual(crawl.call_count, C.MAX_ATTEMPTS)
        self.assertEqual(sleep.call_count, C.MAX_ATTEMPTS - 1)   # 最後一次失敗後不再等
        self.assertIn("以下月份未完成 [7]", out)


if __name__ == "__main__":
    unittest.main()
