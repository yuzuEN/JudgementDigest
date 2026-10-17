"""原始引用頻率排名的案件去重、排除、截斷與名稱辨識。"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from law_frequency import analyze_database, describe, extract_law_keys, rank_articles


class TestLawFrequency(unittest.TestCase):
    def test_names_aliases_and_longest_match(self):
        self.assertEqual(extract_law_keys(
            "依陸海空軍刑法第54條、刑法施行法第1條之1、按個資法第四十一條第1項"
        ), ["陸海空軍刑法第54條", "刑法施行法第1條", "個人資料保護法第41條"])
        self.assertEqual(extract_law_keys("同條例第2條、新法第14條、行法第1條"), [])
        self.assertEqual(extract_law_keys("槍砲彈藥刀械管制條例第8條、毒品危害防制條例第10條"),
                         ["槍砲彈藥刀械管制條例第8條", "毒品危害防制條例第10條"])

    def test_exclude_before_limit_and_deterministic_numeric_tie(self):
        ranked, _ = rank_articles({
            "a": ["刑法第10條", "刑法第2條", "刑法第2條", "組織犯罪防制條例第2條"],
            "b": ["組織犯罪防制條例第2條"],
        }, top=2, min_cases=1)
        self.assertEqual(ranked, [("刑法第2條", 1), ("刑法第10條", 1)])

    def test_database_nested_json_and_duplicate_case_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            with sqlite3.connect(path) as c:
                c.execute('CREATE TABLE 罪法刑 (裁判字號 TEXT, "法條（對應原始）" TEXT)')
                rows = [
                    ("a", [["刑法第320條第1項", "刑法第三百二十條"], ["商標法第97條"]]),
                    ("a", [["刑法第320條"]]),
                    ("b", [["刑法第320條", "商標法第97條"]]),
                    ("c", []),
                    ("d", [["同法第97條"]]),
                ]
                c.executemany('INSERT INTO 罪法刑 VALUES (?, ?)',
                              [(case, json.dumps(raw)) for case, raw in rows])
            report = analyze_database(path, top=1, min_cases=1)
            self.assertEqual(report['all_cases'], 4)
            self.assertEqual(report['raw_law_cases'], 3)
            self.assertEqual(report['recognized_case_article_pairs'], 4)
            self.assertEqual(report['covered_cases'], 2)
            self.assertEqual(report['ranking'], [{'rank': 1, 'key': '刑法第320條', 'cases': 2}])
            self.assertEqual(report['boundary_ties'], ['商標法第97條'])

    def test_descriptive_statistics_interpolation(self):
        stats = describe([1, 2, 3, 10])
        self.assertEqual(stats['q1'], 1.75)
        self.assertEqual(stats['median'], 2.5)
        self.assertEqual(stats['q3'], 4.75)
        self.assertEqual(stats['mean'], 4)

    def test_thirty_case_threshold_keeps_boundary_without_filling_to_limit(self):
        cases = {str(i): {"刑法第320條", "組織犯罪防制條例第2條"}
                 | ({"商標法第97條"} if i < 29 else set()) for i in range(30)}
        ranked, frequency = rank_articles(cases)
        self.assertEqual(ranked, [("刑法第320條", 30)])
        self.assertEqual(frequency['商標法第97條'], 29)


if __name__ == '__main__':
    unittest.main()
