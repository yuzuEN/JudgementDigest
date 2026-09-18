# -*- coding: utf-8 -*-
"""
README 與實際程式行為的一致性檢查。

文件與程式最容易飄掉的地方是 CLI 參數與預設值，所以這裡直接從原始碼抓
argparse 的定義來比對，而不是靠人工核對：
  1. 每支腳本的每個長參數都要在 README 出現（沒寫到 = 文件缺漏）
  2. README 提到的每個長參數都要真的存在（寫錯 = 使用者照抄會失敗）
  3. README 白紙黑字寫出的預設值要與程式一致
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")

SCRIPTS = [
    "pipeline.py", "crawl_batched.py", "crawl_monthly.py", "crawler.py",
    "html_parser.py", "export_excel.py", "tests/live_check.py",
    "backfill_structured.py", "judge_analysis/run_analysis.py",
]

# 只看 argparse 的參數；`opts.add_argument("--headless=new")` 那些是 Chrome 啟動旗標
_ARG_RE = re.compile(
    r'\b(?:ap|\w*grp|parser)\.add_argument\(\s*((?:"[^"]+"\s*,\s*)*"[^"]+")')


def _options_of(path: Path):
    """回傳 [(該參數的所有寫法), ...]，例如 [("-n", "--num"), ("--court",)]。"""
    src = path.read_text(encoding="utf-8")
    out = []
    for m in _ARG_RE.finditer(src):
        names = tuple(t for t in re.findall(r'"([^"]+)"', m.group(1))
                      if t.startswith("-"))
        if names:
            out.append(names)
    return out


def _long_flags_of(path: Path):
    return {n for names in _options_of(path) for n in names if n.startswith("--")}


class TestReadmeDocumentsEveryFlag(unittest.TestCase):
    def test_every_cli_flag_is_documented(self):
        # 短寫法（-n）與長寫法（--num）擇一出現在 README 即算有說明
        missing = {}
        for script in SCRIPTS:
            for names in _options_of(ROOT / script):
                if not any(n in README for n in names):
                    missing.setdefault(script, []).append(names)
        self.assertEqual(missing, {}, f"README 未說明的參數：{missing}")

    def test_every_readme_flag_exists(self):
        documented = set(re.findall(r"--[a-z][a-z0-9-]+", README))
        actual = set()
        for script in SCRIPTS:
            actual |= _long_flags_of(ROOT / script)
        # 安裝說明裡的 pip 參數等外部指令不在比對範圍
        external = {"--upgrade"}
        bogus = documented - actual - external
        self.assertEqual(bogus, set(), f"README 提到但程式沒有的參數：{bogus}")


class TestDocumentedDefaults(unittest.TestCase):
    """README 明寫的預設值必須與 argparse 的 default 相符。"""

    def _default_of(self, script: str, flag: str) -> str:
        src = (ROOT / script).read_text(encoding="utf-8")
        m = re.search(
            r'add_argument\([^)]*"' + re.escape(flag) + r'"[^)]*?default\s*=\s*([^,)\s]+)',
            src, re.DOTALL)
        self.assertIsNotNone(m, f"{script} 找不到 {flag} 的 default")
        return m.group(1)

    def test_start_year_default_2015(self):
        # README：「搜尋起始年（西元），預設 2015」
        self.assertIn("預設 2015", README)
        self.assertEqual(self._default_of("pipeline.py", "--start-year"), "2015")
        self.assertEqual(self._default_of("crawl_batched.py", "--start-year"), "2015")

    def test_pipeline_num_default_100(self):
        self.assertEqual(self._default_of("pipeline.py", "--num"), "100")
        self.assertIn("預設: 100", (ROOT / "pipeline.py").read_text(encoding="utf-8"))

    def test_crawler_num_default_10(self):
        # README：「爬取筆數，預設 10」
        self.assertIn("爬取筆數，預設 10", README)
        self.assertEqual(self._default_of("crawler.py", "--num"), "10")

    def test_export_num_default_100(self):
        # README：「匯出筆數，`0` 表示全部，預設 100」
        self.assertIn("預設 100", README)
        self.assertEqual(self._default_of("export_excel.py", "--num"), "100")


class TestDocumentedBehaviour(unittest.TestCase):
    """README 描述的關鍵行為，用程式常數／實作直接驗證。"""

    def test_result_limit_is_500(self):
        from crawler import _RESULT_LIMIT
        self.assertEqual(_RESULT_LIMIT, 500)
        self.assertIn("500 筆上限", README)

    def test_case_type_names_match_code(self):
        from crawler import _CASE_SYS_CODES
        for name in _CASE_SYS_CODES:
            self.assertIn(name, README, msg=f"README 未列出案件類別「{name}」")

    def test_example_court_names_are_resolvable(self):
        # README 範例用到的法院寫法必須真的解析得出代碼
        from crawler import _court_code
        for name in ("臺灣臺北地方法院", "台北地院", "TPD"):
            self.assertEqual(_court_code(name), "TPD", msg=name)
            self.assertIn(name, README)

    def test_judgment_types_match_code(self):
        from crawler import _JUDGMENT_TYPES
        for t in _JUDGMENT_TYPES:
            self.assertIn(t, README)

    def test_export_columns_documented(self):
        # README「支援的解析欄位」那段必須涵蓋 Excel 實際輸出的欄位
        from export_excel import BASE_COLUMNS
        section = README.split("### 支援的解析欄位", 1)[1]
        for _db_col, label in BASE_COLUMNS:
            if label in ("原告代理人", "被告代理人", "上訴人代理人", "被上訴人代理人"):
                continue      # README 以「（及各方代理人）」一併帶過
            self.assertIn(label, section, msg=f"README 未列出欄位「{label}」")


if __name__ == "__main__":
    unittest.main()
