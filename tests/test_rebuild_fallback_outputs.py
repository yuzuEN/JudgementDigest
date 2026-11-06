"""Exercise the real default extractor through versioned SQLite/XLSX export."""
from contextlib import closing, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from openpyxl import load_workbook
from rebuild_fallback_outputs import rebuild
from refresh_modeldata import SOURCE_COLUMNS


class TestRebuildFallbackOutputs(unittest.TestCase):
    def test_read_only_source_and_default_fallback_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root/'raw.db'
            with closing(sqlite3.connect(database)) as db, db:
                db.execute('CREATE TABLE judgments (id INTEGER PRIMARY KEY, judgment_date TEXT, '+
                           ','.join(k+' TEXT' for k in SOURCE_COLUMNS)+')')
                values = dict.fromkeys(SOURCE_COLUMNS, '')
                values.update(case_number='臺灣臺北地方法院 111 年度簡字第 1 號刑事判決',
                              defendant='甲某', verdict='甲某犯竊盜罪，處拘役拾日。',
                              reasons='核被告所為，係犯刑法第320條第1項之罪。')
                db.execute('INSERT INTO judgments VALUES ('+','.join('?' for _ in range(len(values)+2))+')',
                           [1, '2022-01-01', *values.values()])
            original = hashlib.sha256(database.read_bytes()).hexdigest()
            with redirect_stdout(io.StringIO()):
                report = rebuild(database, root/'result')
            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), original)
            self.assertEqual(report['counts']['before_raw_empty'], 1)
            self.assertEqual(report['counts']['after_raw_empty'], 0)
            with closing(sqlite3.connect(root/'result'/'2018-2025_罪法刑.db')) as db:
                raw, source, audit = db.execute(
                    'SELECT "法條（對應原始）", "法條來源", "法條備援紀錄" FROM "有罪_單被告"').fetchone()
                self.assertEqual(json.loads(raw), [['刑法第320條第1項']])
                self.assertTrue(json.loads(source)[0].startswith('舊版備援'))
                self.assertTrue(json.loads(audit)[0]['recovered'])
            book = load_workbook(root/'result'/'2018-2025_罪法刑.xlsx', read_only=True)
            rows = list(book['罪法刑'].values)
            self.assertEqual(len(rows), 2)
            self.assertIn('法條備援紀錄', rows[0])
            book.close()
            with self.assertRaises(FileExistsError):
                rebuild(database, root/'result')
