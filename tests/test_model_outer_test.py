import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'model'))

from collections import Counter
import json
import tempfile
import unittest
from unittest.mock import patch
from judgment_bert.cross_validation import prepare_cv, grouped_rows, assignments, train_cv, summarize


def row(i, year=2020, fact=None):
    return dict(fact=fact or f'fact{i}',meta=dict(year=year,judgment_date=f'{year}-{i%12+1:02d}-01',
                case_number=f'case{i}',source_url=f'url{i}',accusation=['A'],relevant_articles=['L']))


class OuterTestCV(unittest.TestCase):
    def test_grouped_outer_test_internal_valid_and_reserved_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);source=p/'source.jsonl'
            records=[row(i,2020+i%5) for i in range(120)]
            records += [row(121,2021,'fact0'),row(122,2025,'fact0'),row(123,2025)]
            source.write_text(''.join(json.dumps(x)+'\n' for x in records))
            data,groups=grouped_rows(source,'accusation',2016,2025)
            expected,removed=assignments(data,groups,'kfold_test',5,42,2025)
            self.assertEqual(removed,[122])
            self.assertEqual(expected,assignments(data,groups,'kfold_test',5,42,2025)[0])
            plan=prepare_cv(source,'accusation',p/'prepared',mode='kfold_test',first_year=2016,min_label_freq=1)
            outer=Counter()
            for fold in plan['folds']:
                folder=p/'prepared'/fold['name'];split=json.loads((folder/'split_assignment.json').read_text())
                self.assertEqual(split['123'],'holdout');self.assertNotIn('122',split)
                self.assertEqual(split['1'],split['121'])
                sets={name:{json.loads(line)['fact'] for line in (folder/(name+'.jsonl')).read_text().splitlines()}
                      for name in ('train','valid','test','holdout')}
                for name,values in sets.items():
                    for other in sets:
                        if other!=name:self.assertFalse(values & sets[other])
                outer.update(int(i) for i,role in split.items() if role=='test')
                manifest=json.loads((folder/'manifest.json').read_text())
                self.assertEqual(manifest['evaluation_role'],'outer_test')
                self.assertEqual(manifest['splits']['holdout']['years'],{'2025':1})
                self.assertNotIn('2025',manifest['splits']['test']['years'])
                self.assertLess(manifest['splits']['valid']['n'],manifest['splits']['test']['n'])
            self.assertEqual(set(outer),set(range(1,122)))
            self.assertTrue(all(n==1 for n in outer.values()))

    def test_training_enables_outer_test_and_averages_test_not_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);prepared=p/'prepared';prepared.mkdir()
            (prepared/'cv_manifest.json').write_text(json.dumps(dict(mode='kfold_test',n_folds=2,
                min_label_freq=1,folds=[dict(name=f'fold_{i:02d}') for i in (1,2)])))
            for i in (1,2):
                d=prepared/f'fold_{i:02d}';d.mkdir()
                (d/'manifest.json').write_text(json.dumps(dict(evaluation_role='outer_test')))
            config=p/'config.json';config.write_text('{}')
            def fake_train(command,check):
                self.assertTrue(check);self.assertEqual(command[-1],'--evaluate-test')
                settings=json.loads(Path(command[-2]).read_text());self.assertTrue(settings['evaluate_test'])
                d=Path(settings['output']);data=Path(settings['data_dir'])
                (d/'data_manifest.json').write_text((data/'manifest.json').read_text())
                (d/'run_config.json').write_text(json.dumps(settings))
                score=.1 if d.name=='fold_01' else .3
                (d/'metrics.json').write_text(json.dumps(dict(test_status='evaluated',evaluation_role='outer_test',
                    best_valid_macro_f1=.9,history=[dict(epoch=1,valid=dict(macro_f1=.9)),
                                                  dict(epoch=2,valid=dict(macro_f1=.8))],test=dict(macro_f1=score))))
            with patch('judgment_bert.cross_validation.subprocess.run',side_effect=fake_train) as launch:
                result=train_cv(prepared,p/'runs',config)
            self.assertEqual(launch.call_count,2)
            self.assertEqual(result['primary_metric_source'],'outer_test')
            self.assertAlmostEqual(result['test']['macro_f1']['mean'],.2)
            self.assertAlmostEqual(result['validation']['macro_f1']['mean'],.9)
            self.assertEqual([x['selected_epoch'] for x in result['folds']],[1,1])
            path=p/'runs/fold_01/metrics.json';metrics=json.loads(path.read_text())
            metrics['evaluation_role']='test';path.write_text(json.dumps(metrics))
            with self.assertRaisesRegex(ValueError,'outer TEST'):summarize(prepared,p/'runs')

    def test_too_few_independent_groups_rejected(self):
        rows={i:row(i) for i in range(8)};rows[8]=row(8,2025)
        with self.assertRaisesRegex(ValueError,'10 independent'):
            assignments(rows,[[i] for i in rows],'kfold_test',5,42,2025)

    def test_fixed_classes_bypass_fold_threshold_and_shared_task_reuses_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);source=p/'source.jsonl'
            records=[row(i,2020+i%5) for i in range(120)]+[row(121,2025)]
            records[0]['meta']['accusation'].append('rare')
            source.write_text(''.join(json.dumps(x)+'\n' for x in records))
            class_list=p/'classes.json'
            class_list.write_text(json.dumps(dict(min_source_frequency=150,accusation=['rare','A'],article=['L'])))
            accusation=prepare_cv(source,'accusation',p/'acc',mode='kfold_test',min_label_freq=150,class_list=class_list)
            article=prepare_cv(source,'article',p/'art',mode='kfold_test',min_label_freq=150,
                               class_list=class_list,split_plan=p/'acc')
            for fold in accusation['folds']:
                name=fold['name'];m=json.loads((p/'acc'/name/'manifest.json').read_text())
                self.assertEqual(m['classes'],['rare','A'])
                self.assertFalse(m['training_frequency_filter_applied'])
                self.assertLess(m['training_label_frequencies'].get('rare',0),150)
                self.assertEqual((p/'acc'/name/'split_assignment.json').read_bytes(),
                                 (p/'art'/name/'split_assignment.json').read_bytes())
            self.assertEqual(article['shared_split_plan_task'],'accusation')
            wrong=p/'wrong.json';wrong.write_text(json.dumps(dict(min_source_frequency=30,accusation=['A'])))
            with self.assertRaisesRegex(ValueError,'threshold'):
                prepare_cv(source,'accusation',p/'bad',mode='kfold_test',min_label_freq=150,class_list=wrong)


if __name__=='__main__':unittest.main()
