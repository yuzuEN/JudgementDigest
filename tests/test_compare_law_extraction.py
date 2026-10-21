"""比較工具必須對各版本使用同一母體，且不得改寫原始資料。"""
from contextlib import redirect_stdout
import hashlib
import io
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from build_structured_review import build_row, HEADERS
from compare_law_extraction import compare
from refresh_modeldata import SOURCE_COLUMNS


class TestComparisonCohort(unittest.TestCase):
    def test_shared_cohort_and_read_only_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / 'source.db'
            with sqlite3.connect(database) as connection:
                connection.execute('CREATE TABLE judgments (id INTEGER, judgment_date TEXT, ' +
                                   ','.join(name + ' TEXT' for name in SOURCE_COLUMNS) + ')')
                cases = [
                    ('臺灣測試地方法院 107 年度簡字第 1 號刑事判決', '2018-01-01', '甲某', '甲某犯竊盜罪，處拘役參日。'),
                    ('臺灣測試地方法院 107 年度上訴字第 2 號刑事判決', '2018-01-01', '甲某', '甲某犯竊盜罪，處拘役參日。'),
                    ('臺灣測試地方法院 107 年度簡字第 3 號刑事判決', '2017-12-31', '甲某', '甲某犯竊盜罪，處拘役參日。'),
                    ('臺灣測試地方法院 107 年度簡字第 4 號刑事判決', '2018-01-01', '甲某', '甲某無罪。'),
                    ('臺灣測試地方法院 107 年度簡字第 5 號刑事判決', '2018-01-01', '甲某；乙某', '甲某、乙某均犯竊盜罪，各處拘役參日。'),
                ]
                for identifier, (case, date, defendant, verdict) in enumerate(cases, 1):
                    values = dict(case_number=case, defendant=defendant, verdict=verdict,
                                  reasons='核被告所為，係犯刑法第320條第1項之竊盜罪。')
                    connection.execute('INSERT INTO judgments VALUES (' +
                        ','.join('?' for _ in range(len(SOURCE_COLUMNS) + 2)) + ')',
                        [identifier, date, *(values.get(key, '') for key in SOURCE_COLUMNS)])
            connection.close()
            original = hashlib.sha256(database.read_bytes()).hexdigest()
            # 歷史版本本身由整批實跑驗證；此測試隔離母體選擇與唯讀保護。
            with patch('compare_law_extraction.load_extractor', return_value=(build_row, HEADERS)), redirect_stdout(io.StringIO()):
                report = compare(database, root / 'output')
            self.assertEqual(report['counts']['eligible'], 1)
            for version in ('current', 'c733d65', 'f3adff7'):
                self.assertEqual(report['counts'][version + '_raw_empty'], 0)
            self.assertEqual(original, hashlib.sha256(database.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                compare(database, root / 'output')
