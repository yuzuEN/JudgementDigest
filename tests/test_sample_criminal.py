import copy
import json
from pathlib import Path
import tempfile
import unittest

from retrieval.sample_criminal import exclusion, sample


def record(charge='竊盜罪', day='2025-01-01'):
    return {'fact': '被告取走物品。', 'meta': {
        'criminals': ['甲'], 'accusation': [charge], 'relevant_articles': ['刑法第320條'],
        'task_validity': dict(accusation=True, article=True, imprisonment=True),
        'sentence_kind': '有期徒刑', 'term_of_imprisonment': {'imprisonment': 6},
        'label_detail': {'term_reason': 'single_prison_sentence'}, 'judgment_date': day}}


class SampleTests(unittest.TestCase):
    def test_reject_missing_or_ambiguous_labels(self):
        self.assertIsNone(exclusion(record()))
        mutations = [
            ('criminals', ['甲', '乙']), ('criminals', []),
            ('relevant_articles', []), ('accusation', ['']),
            ('task_validity', dict(accusation=True, article=True, imprisonment=False)),
            ('label_detail', {'term_reason': 'no_safe_single_sentence'}),
            ('term_of_imprisonment', {'imprisonment': 0}),
            ('reextraction', {'defendant_status': '多被告', 'term_reason': 'single_prison_sentence'}),
            ('judgment_date', 'unknown'),
        ]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                r = record()
                r['meta'][key] = value
                self.assertIsNotNone(exclusion(r))

    def test_reextraction_overrides_old_sentence_and_special(self):
        r = record()
        r['meta']['reextraction'] = {'defendant_status': '單被告', 'term_reason': 'no_safe_single_sentence'}
        self.assertEqual(exclusion(r), 'not_single_sentence')
        r = record()
        r['meta'].update(sentence_kind='死刑或無期徒刑',
                         term_of_imprisonment={'imprisonment': 0, 'life_imprisonment': True},
                         label_detail={'term_reason': 'single_special_sentence'})
        self.assertIsNone(exclusion(r))

    def test_single_detention_is_alternative_to_imprisonment(self):
        r = record()
        r['meta'].update(sentence_kind='拘役', detention_days=30,
                         term_of_imprisonment={'imprisonment': 0},
                         label_detail={'term_reason': 'detention_not_prison'})
        r['meta']['task_validity']['imprisonment'] = False
        self.assertIsNone(exclusion(r))
        for key, value in [('detention_days', 0), ('detention_days', '30'),
                           ('sentence_kind', '有期徒刑併拘役'),
                           ('label_detail', {'term_reason': 'no_safe_single_sentence'}),
                           ('term_of_imprisonment', {'imprisonment': 3})]:
            with self.subTest(key=key):
                bad = copy.deepcopy(r)
                bad['meta'][key] = value
                self.assertIsNotNone(exclusion(bad))
        r['meta']['task_validity']['article'] = False
        self.assertEqual(exclusion(r), 'invalid_task')

    def test_latest_per_primary_charge_and_source_mapping(self):
        records = [record(day='2023-01-01'), record(day='2025-01-01'),
                   record(day='2024-01-01'), record('傷害罪')]
        records[1]['meta']['accusation'].append('傷害罪')
        bad = copy.deepcopy(records[0])
        bad['meta']['criminals'] = ['甲', '乙']
        records.append(bad)
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / 'source.jsonl', Path(d) / 'sample.jsonl'
            src.write_text(''.join(json.dumps(r) + '\n' for r in records))
            report = sample(src, out, 2)
            selected = [json.loads(x) for x in out.read_text().splitlines()]
            self.assertEqual([r['meta']['retrieval_source_line'] for r in selected], [2, 3, 4])
            self.assertEqual(report['selected_by_charge'], {'傷害罪': 1, '竊盜罪': 2})
            self.assertEqual(report['counts']['not_single_defendant'], 1)
            with self.assertRaises(FileExistsError):
                sample(src, out, 2)
            self.assertEqual(len(out.read_text().splitlines()), 3)
            with self.assertRaises(ValueError):
                sample(src, Path(d) / 'zero.jsonl', 0)


if __name__ == '__main__':
    unittest.main()
