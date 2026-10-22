import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import unittest
from judgment_bert.data import term_class


class TestTermGroups(unittest.TestCase):
    def test_mtl_boundaries(self):
        row = {'meta': {'term_task': True, 'sentence_kind': '有期徒刑',
                        'term_of_imprisonment': {}}}
        for months, expected in [(0, 0), (6.5, 0), (7, 1), (12, 1), (13, 2),
                                 (36, 5), (37, 6), (60, 6), (61, 7),
                                 (119.9, 7), (120, 8), (301, 8)]:
            row['meta']['term_of_imprisonment']['imprisonment'] = months
            self.assertEqual(term_class(row, mtl_bins=True), expected)

    def test_safe_detention(self):
        meta = {'sentence_kind': '拘役', 'term_task': False, 'detention_days': 30,
                'reextraction': {'term_reason': 'detention_not_prison', 'defendant_status': '單被告'}}
        row = {'meta': meta}
        self.assertIsNone(term_class(row))
        self.assertEqual(term_class(row, include_detention=True), 11)
        for days in (0, -1, True, None, float('nan')):
            meta['detention_days'] = days
            self.assertIsNone(term_class(row, include_detention=True))
        meta['detention_days'] = 30
        meta['reextraction']['term_reason'] = 'no_safe_single_sentence'
        self.assertIsNone(term_class(row, include_detention=True))
