# -*- coding: utf-8 -*-
"""config.build_info / warn_if_other_sklearn：模型的 meta.json 記錄程式版本與 scikit-learn 版本，讀模型時比對。"""

import logging
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import sklearn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402


def fake_git(head="abc1234", dirty="", code=0):
    def run(args, **kwargs):
        out = head if "rev-parse" in args else dirty
        return subprocess.CompletedProcess(args, code, stdout=out + "\n", stderr="")
    return run


class TestBuildInfo(unittest.TestCase):
    def test_records_commit_and_versions(self):
        with mock.patch.object(config.subprocess, "run", fake_git()):
            info = config.build_info()
        self.assertEqual(info["git_commit"], "abc1234")
        self.assertEqual(info["sklearn"], sklearn.__version__)
        self.assertRegex(info["python"], r"^\d+\.\d+")

    def test_uncommitted_changes_are_marked_dirty(self):
        with mock.patch.object(config.subprocess, "run", fake_git(dirty=" M civil/models/service.py")):
            self.assertEqual(config.git_commit(), "abc1234-dirty")

    def test_no_git_gives_empty_commit(self):
        with mock.patch.object(config.subprocess, "run", side_effect=FileNotFoundError("git")):
            self.assertEqual(config.git_commit(), "")
        with mock.patch.object(config.subprocess, "run", fake_git(head="", code=128)):
            self.assertEqual(config.git_commit(), "")

    def test_real_repo_gives_a_commit(self):
        self.assertRegex(config.git_commit(), r"^[0-9a-f]{7,}(-dirty)?$")


class TestWarnIfOtherSklearn(unittest.TestCase):
    def test_warns_when_versions_differ(self):
        with self.assertLogs("config", "WARNING") as logs:
            config.warn_if_other_sklearn({"sklearn": "0.0.1"}, "civil_winloss_v1")
        self.assertIn("0.0.1", logs.output[0])
        self.assertIn(sklearn.__version__, logs.output[0])

    def test_silent_when_same_or_not_recorded(self):
        # assertNoLogs 要 Python 3.10；CI 是 3.9，改成看 logger 有沒有被呼叫
        with mock.patch.object(logging.getLogger("config"), "warning") as warning:
            config.warn_if_other_sklearn({"sklearn": sklearn.__version__}, "x")
            config.warn_if_other_sklearn({}, "舊的 meta 沒有記錄版本")
        warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
