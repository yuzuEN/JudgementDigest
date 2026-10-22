import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"model"))

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from sample_balanced import sentence_group


class SamplingTest(unittest.TestCase):
    def test_source_frequency_filter_before_sampling_preserves_original_labels(self):
        script=Path(__file__).resolve().parents[1]/'model/sample_balanced.py'
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);source=p/'source.jsonl';rows=[]
            for i in range(24):
                m=dict(criminals=['test'],year=2016,judgment_date='2016-01-01',jid=str(i),
                       accusation=['A']+(['rare'] if i<3 else []),
                       relevant_articles=['rare_law'] if i>=20 else ['L'],
                       task_validity=dict(accusation=True,article=True,imprisonment=True),
                       sentence_kind='有期徒刑',label_detail=dict(term_reason='single_prison_sentence'),
                       term_of_imprisonment=dict(imprisonment=3,death_penalty=False,life_imprisonment=False))
                rows.append(dict(fact=f'fact{i}',meta=m))
            source.write_text(''.join(json.dumps(x)+'\n' for x in rows))
            subprocess.run([sys.executable,str(script),'--source',str(source),'--output',str(p/'out'),
                            '--size','20','--proposals','100','--min-label-frequency','10'],
                           check=True,capture_output=True,text=True)
            report=json.loads((p/'out/sampling_report.json').read_text())
            classes=json.loads((p/'out/fixed_classes.json').read_text())
            self.assertEqual(classes['accusation'],['A']);self.assertEqual(classes['article'],['L'])
            self.assertEqual(report['candidate_count_before_frequency_filter'],24)
            self.assertEqual(report['candidate_count'],20)
            selected=[json.loads(line) for line in (p/'out/shared_100k.jsonl').read_text().splitlines()]
            self.assertTrue(all(x['meta']['accusation']==['A'] and x['meta']['relevant_articles']==['L'] for x in selected))
            self.assertEqual(sum('sampling_original_accusation' in x['meta'] for x in selected),3)

    def test_special_sentences_excluded_even_with_conflicting_metadata(self):
        for flag in ('death_penalty', 'life_imprisonment'):
            meta = dict(label_detail=dict(term_reason='single_prison_sentence'),
                        sentence_kind='有期徒刑', task_validity=dict(imprisonment=True),
                        term_of_imprisonment={'imprisonment': 3, flag: True})
            self.assertIsNone(sentence_group(meta, True))
            meta['label_detail']['term_reason'] = 'single_special_sentence'
            self.assertIsNone(sentence_group(meta, False))

    def test_shared_gates_exact_month_quotas_and_detention_switch(self):
        script = Path(__file__).resolve().parents[1]/'model/sample_balanced.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.jsonl'
            rows = []
            for year in range(2016, 2026):
                for month in range(1, 13):
                    for kind in ('prison', 'detention', 'unsafe', 'invalid_law'):
                        m = dict(criminals=['test'], year=year, judgment_date=f'{year}-{month:02d}-01',
                                 jid=f'{year}-{month}-{kind}', accusation=['A'], relevant_articles=['L'],
                                 task_validity=dict(accusation=True, article=kind != 'invalid_law',
                                                    imprisonment=kind == 'prison'),
                                 label_detail=dict(term_reason={'prison':'single_prison_sentence',
                                                               'detention':'detention_not_prison'}.get(kind,'no_safe_single_sentence')),
                                 sentence_kind='拘役' if kind == 'detention' else '有期徒刑',
                                 detention_days=30 if kind == 'detention' else 0,
                                 term_of_imprisonment=dict(imprisonment=3, death_penalty=False, life_imprisonment=False))
                        rows.append(dict(fact=f'fact {year} {month} {kind}', meta=m))
            # A repeated document must not become an additional independent candidate.
            rows.append(rows[0])
            for flag in ('death_penalty', 'life_imprisonment'):
                special = json.loads(json.dumps(rows[0]))
                special['meta']['jid'] = flag
                special['meta']['sentence_kind'] = '死刑或無期徒刑'
                special['meta']['label_detail']['term_reason'] = 'single_special_sentence'
                special['meta']['term_of_imprisonment'][flag] = True
                rows.append(special)
            source.write_text(''.join(json.dumps(x)+'\n' for x in rows))
            for exclude in (False, True):
                output = root / str(exclude)
                cmd = [sys.executable, str(script), '--source', str(source), '--output', str(output),
                       '--size', '120', '--proposals', '2000']
                if exclude:
                    cmd.append('--exclude-detention')
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                report = json.loads((output/'sampling_report.json').read_text())
                self.assertEqual(report['candidate_count'], 120 if exclude else 240)
                self.assertEqual(report['filters']['excluded_duplicate_jid'], 1)
                self.assertEqual(report['written'], 120)
                self.assertTrue(all(x['selected'] == 1 for x in report['months'].values()))
                selected = [json.loads(x) for x in (output/'shared_100k.jsonl').read_text().splitlines()]
                self.assertEqual(len({x['meta']['jid'] for x in selected}), 120)
                self.assertTrue(all(x['meta']['task_validity']['article'] for x in selected))
                self.assertTrue(all(not x['meta']['term_of_imprisonment'].get(flag)
                                    for x in selected for flag in ('death_penalty', 'life_imprisonment')))
                if exclude:
                    self.assertTrue(all(x['meta']['sentence_kind'] == '有期徒刑' for x in selected))


if __name__ == '__main__':
    unittest.main()
