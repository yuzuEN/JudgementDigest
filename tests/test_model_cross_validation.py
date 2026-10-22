import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import json
import tempfile
import unittest
from judgment_bert.cross_validation import assignments, grouped_rows, prepare_cv, summarize


def record(case, year, fact=None, label='常見'):
    return dict(fact=fact or case, meta=dict(year=year, case_number=case,
                source_url=f'{case}/{year}', judgment_date=f'{year}-01-15', accusation=[label], relevant_articles=['刑法第320條']))


class TestCrossValidation(unittest.TestCase):
    def test_default_five_folds_and_optional_ten(self):
        from unittest.mock import patch
        from judgment_bert.cross_validation import main
        rows = [record(f'case{i}', 2020+i%5) for i in range(20)]
        rows.append(record('holdout', 2025))
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder); source = p/'source.jsonl'
            source.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            default = prepare_cv(source, 'accusation', p/'five', min_label_freq=1)
            ten = prepare_cv(source, 'accusation', p/'ten', folds=10, min_label_freq=1)
            self.assertEqual(default['n_folds'], 5)
            self.assertEqual(ten['n_folds'], 10)
            argv = ['cv', 'prepare', '--data', str(source), '--output', str(p/'cli')]
            for extra, expected in [([], 5), (['--folds', '10'], 10)]:
                with patch('sys.argv', argv+extra), patch('judgment_bert.cross_validation.prepare_cv') as prepare_mock:
                    main()
                self.assertEqual(prepare_mock.call_args.args[4], expected)

    def test_transitive_groups_and_fixed_holdout(self):
        rows = [record('a', 2020, '相同'), record('b', 2021, '相同'),
                record('b', 2022, '不同'), record('z', 2025, '相同'),
                record('c', 2023), record('d', 2024), record('t', 2025)]
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'source.jsonl'
            p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            loaded, groups = grouped_rows(p, 'accusation', 2018, 2025)
            plans, removed = assignments(loaded, groups, 'kfold', 2, 42, 2025)
            self.assertEqual(removed, [4])
            self.assertEqual(plans, assignments(loaded, groups, 'kfold', 2, 42, 2025)[0])
            valid = []
            for _, split in plans:
                self.assertEqual(len({split[i] for i in (1, 2, 3)}), 1)
                self.assertEqual(split[7], 'test')
                self.assertNotIn(4, split)
                valid.extend(i for i, s in split.items() if s == 'valid')
            self.assertCountEqual(valid, [1, 2, 3, 5, 6])

    def test_time_never_trains_on_future_and_purges_overlap(self):
        rows = {1: record('a', 2018), 2: record('a', 2019),
                3: record('b', 2019), 4: record('c', 2020), 5: record('t', 2025)}
        plans, _ = assignments(rows, [[1, 2], [3], [4], [5]], 'time', 10, 42, 2025)
        self.assertEqual(len(plans), 2)
        self.assertNotIn(2, plans[0][1])
        for _, split in plans:
            train = [rows[i]['meta']['year'] for i, s in split.items() if s == 'train']
            valid = [rows[i]['meta']['year'] for i, s in split.items() if s == 'valid']
            self.assertLess(max(train), min(valid))

    def test_preparation_fits_classes_on_each_training_fold(self):
        rows = [record(f'case{i}', 2020+i%5) for i in range(12)]
        rows[0]['meta']['accusation'].append('只出現一次')
        rows.append(record('test', 2025))
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder); source = p/'source.jsonl'
            source.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            for task in ('accusation', 'article'):
                out = p/task
                plan = prepare_cv(source, task, out, folds=3, min_label_freq=1)
                self.assertEqual(plan['n_folds'], 3)
                for fold in plan['folds']:
                    d = out/fold['name']
                    assignment = json.loads((d/'split_assignment.json').read_text())
                    manifest = json.loads((d/'manifest.json').read_text())
                    self.assertEqual(manifest['split_policy'], 'explicit_source_lines')
                    self.assertIsNone(manifest['valid_year'])
                    if task == 'accusation':
                        self.assertEqual('只出現一次' in manifest['classes'], assignment['1'] == 'train')
                    self.assertEqual(manifest['splits']['test']['years'], {'2025': 1})
                with self.assertRaises(FileExistsError):
                    prepare_cv(source, task, out, folds=3)
                summary = summarize(out, p/'runs'/task)
                self.assertFalse(summary['complete'])
                self.assertEqual(summary['completed_folds'], 0)

    def test_summary_rejects_smoke_or_test_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder); prepared = p/'prepared'; run = p/'runs'/'fold_01'
            prepared.mkdir(); run.mkdir(parents=True)
            (prepared/'cv_manifest.json').write_text(json.dumps(dict(mode='kfold', n_folds=1,
                folds=[dict(name='fold_01')])))
            (run/'metrics.json').write_text(json.dumps(dict(tiny_random_smoke=True)))
            with self.assertRaises(ValueError): summarize(prepared, p/'runs')

    def test_training_runs_fresh_processes_and_summarizes_validation_only(self):
        from unittest.mock import patch
        from judgment_bert.cross_validation import train_cv
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder); prepared = p/'prepared'; prepared.mkdir()
            folds = [dict(name='fold_01'), dict(name='fold_02')]
            (prepared/'cv_manifest.json').write_text(json.dumps(dict(mode='kfold', n_folds=2,
                min_label_freq=1, folds=folds)))
            for fold in folds:
                d = prepared/fold['name']; d.mkdir()
                (d/'manifest.json').write_text(json.dumps(dict(task='accusation', fold=fold['name'])))
            config = p/'config.json'; config.write_text(json.dumps(dict(evaluate_test=True)))

            def fake_train(command, check):
                self.assertTrue(check)
                self.assertEqual(command[-1], '--no-evaluate-test')
                settings = json.loads(Path(command[-2]).read_text())
                self.assertFalse(settings['evaluate_test'])
                run = Path(settings['output']); source = Path(settings['data_dir'])
                (run/'data_manifest.json').write_text((source/'manifest.json').read_text())
                (run/'run_config.json').write_text(json.dumps(settings))
                score = 0.2 if run.name == 'fold_01' else 0.4
                (run/'metrics.json').write_text(json.dumps(dict(tiny_random_smoke=False,
                    test_status='not_evaluated', best_valid_macro_f1=score,
                    history=[dict(epoch=1, valid=dict(macro_f1=score, micro_f1=score)),
                             dict(epoch=2, valid=dict(macro_f1=score+0.01, micro_f1=score))])))

            with patch('judgment_bert.cross_validation.subprocess.run', side_effect=fake_train) as launch:
                summary = train_cv(prepared, p/'runs', config)
            self.assertEqual(launch.call_count, 2)
            self.assertTrue(summary['complete'])
            self.assertAlmostEqual(summary['validation']['macro_f1']['mean'], 0.3)
            self.assertEqual([r['selected_epoch'] for r in summary['folds']], [1, 1])
            changed=p/'runs/fold_02/run_config.json'
            original=changed.read_text()
            changed.write_text(json.dumps(dict(json.loads(original),head_lr=0.5)))
            with self.assertRaisesRegex(ValueError,'different settings'):
                summarize(prepared,p/'runs')
            changed.write_text(original)
            config.write_text(json.dumps(dict(evaluate_test=True,head_lr=0.5)))
            with self.assertRaisesRegex(ValueError,'different CV configuration'):
                train_cv(prepared,p/'runs',config,selected='fold_02')
            config.write_text(json.dumps(dict(evaluate_test=True)))
            with self.assertRaises(FileExistsError): train_cv(prepared, p/'runs', config)
