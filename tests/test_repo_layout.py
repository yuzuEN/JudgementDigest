# -*- coding: utf-8 -*-
"""
repo 結構的離線檢查：搬動檔案、改資料夾之後最容易壞、又不會被功能測試抓到的地方。

  1. data_pipeline/ 的每支程式都 import 得起來（沒有功能測試的程式也算）
  2. 用檔名啟動的子程序、以 repo 根目錄為準的資料路徑，指到的位置都對
  3. README 與 docs/ 裡的相對連結都指得到檔案
  4. .gitignore 不會把程式或文件當成資料忽略掉（data_*/ 曾經連 data_pipeline/ 一起忽略）
"""

import importlib
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "data_pipeline"
sys.path.insert(0, str(PIPELINE))
sys.path.insert(0, str(ROOT / "scripts"))

# 指到本機資料、不進版控的連結（刑事萃取報告附的 finaldata/ 輸出）
LOCAL_ONLY_LINK = re.compile(r"(^|/)finaldata/")


class TestModulesImport(unittest.TestCase):
    def test_every_pipeline_module_imports(self):
        modules = sorted(p.stem for p in PIPELINE.glob("*.py"))
        self.assertGreater(len(modules), 20, "data_pipeline/ 裡的程式不見了")
        for name in modules:
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_browse_db_imports(self):
        importlib.import_module("browse_db")


class TestPaths(unittest.TestCase):
    def test_simple_courts_children_exist(self):
        import crawl_simple_courts as C
        self.assertEqual(Path(C.HERE), PIPELINE)
        for script in ("html_parser.py", "crawl_monthly.py"):
            self.assertTrue((Path(C.HERE) / script).is_file(), script)

    def test_browse_db_paths(self):
        import browse_db
        self.assertEqual(Path(browse_db.ROOT), ROOT, "資料庫要在 repo 根目錄找")
        self.assertTrue((Path(browse_db.HERE) / "datasette_metadata.yml").is_file())

    def test_opendata_output_at_repo_root(self):
        import opendata_download
        self.assertEqual(Path(opendata_download.OUT), ROOT / "data_opendata")

    def test_hashed_code_files_live_together(self):
        """refresh_modeldata／rebuild_fallback_outputs 以檔名在自己的資料夾計算程式雜湊。"""
        import rebuild_fallback_outputs
        for name in rebuild_fallback_outputs.CODE_FILES:
            self.assertTrue((PIPELINE / name).is_file(), name)


def _markdown_files():
    yield ROOT / "README.md"
    yield from (ROOT / "docs").rglob("*.md")
    yield from ROOT.glob("*/README.md")


class TestMarkdownLinks(unittest.TestCase):
    LINK = re.compile(r"\]\(([^)\s]+)\)")

    def test_relative_links_resolve(self):
        broken = []
        for md in _markdown_files():
            text = md.read_text(encoding="utf-8")
            for target in self.LINK.findall(text):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                path = unquote(target.split("#", 1)[0])
                if not path or LOCAL_ONLY_LINK.search(path):
                    continue
                if not (md.parent / path).exists():
                    broken.append(f"{md.relative_to(ROOT)} → {target}")
        self.assertEqual(broken, [], "連結指到不存在的檔案")


class TestTextFiles(unittest.TestCase):
    def test_no_control_characters(self):
        """用程式產生文件時，跳脫字元寫錯會變成看不見的控制字元（曾把 README 的 \\activate 變成 BEL）。"""
        bad = []
        for pattern in ("*.md", "**/*.md", "**/*.py", "frontend/src/**/*.ts", "frontend/src/**/*.tsx"):
            for p in ROOT.glob(pattern):
                if "node_modules" in p.parts or not p.is_file():
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
                if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
                    bad.append(str(p.relative_to(ROOT)))
        self.assertEqual(sorted(set(bad)), [], "這些檔案有看不見的控制字元")


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "需要 git 與 repo")
class TestGitignore(unittest.TestCase):
    def test_code_and_docs_not_ignored(self):
        paths = [str(p.relative_to(ROOT)) for pattern in
                 ("data_pipeline/*.py", "scripts/*", "tests/*.py", "docs/**/*", "*/README.md")
                 for p in ROOT.glob(pattern) if p.is_file()]
        # --no-index：不管檔案有沒有被追蹤，只看規則本身會不會把它忽略
        r = subprocess.run(["git", "check-ignore", "--no-index", "--stdin"], cwd=ROOT,
                           input="\n".join(paths), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.stdout.split(), [], ".gitignore 會忽略這些程式或文件")


if __name__ == "__main__":
    unittest.main()
