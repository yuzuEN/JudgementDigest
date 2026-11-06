import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import json
import tempfile
import unittest
from unittest.mock import patch
from judgment_bert.balancing import balanced_bins, balance_report
from judgment_bert.nested_cv import prepare_nested, choose_inner, train_nested, summarize_nested


def row(i, year=2018):
    return dict(fact=f'事實{i}',meta=dict(year=year,judgment_date=f'{year}-{i%12+1:02d}-15',
        case_number=f'case{i}',source_url=f'url{i}',accusation=['常見',f'罪{i%3}'],
        relevant_articles=['刑法第320條']))


class TestBalancedFolds(unittest.TestCase):
    def test_balances_month_labels_and_count_deterministically(self):
        rows = {i:row(i) for i in range(600)}; groups = [[i] for i in rows]
        bins = balanced_bins(rows,groups,5,42,'accusation')
        self.assertEqual(bins,balanced_bins(rows,groups,5,42,'accusation'))
        self.assertCountEqual([i for b in bins for i in b],list(rows))
        report = balance_report(rows,bins,'accusation')
        self.assertEqual(report['row_count_range'],[120,120])
        self.assertLessEqual(report['max_month_count_gap'],2)
        self.assertLessEqual(report['max_label_count_gap'],2)

    def test_groups_not_split_and_dates_validated(self):
        rows = {i:row(i) for i in range(20)}
        groups = [[0,1,2]]+[[i] for i in range(3,20)]
        bins = balanced_bins(rows,groups,5,42,'accusation')
        self.assertEqual(sum(set([0,1,2])<=set(b) for b in bins),1)
        del rows[0]['meta']['judgment_date']
        with self.assertRaises(ValueError): balanced_bins(rows,groups,5,42,'accusation')
        rows[0]['meta']['judgment_date']='2019-01-01'
        with self.assertRaises(ValueError): balanced_bins(rows,groups,5,42,'accusation')


class TestNestedCV(unittest.TestCase):
    def prepare(self, folder, task='accusation'):
        rows = [row(i,2018+i//20) for i in range(60)]
        rows.append(row(1000,2025))
        overlap = row(2000,2019); overlap['meta']['case_number']='case0'; rows.append(overlap)
        source = folder/'source.jsonl'
        source.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        out = folder/task
        plan = prepare_nested(source,task,out,folds=5,min_label_freq=1)
        return out, plan

    def test_nested_excludes_outer_and_reserved_year_from_inner(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            for task in ('accusation','article'):
                out,plan = self.prepare(p,task)
                self.assertEqual(len(plan['outer_folds']),2)
                self.assertEqual(plan['outer_folds'][0]['purged_outer_overlap_rows'],1)
                for fold in plan['outer_folds']:
                    root=out/fold['name']; validation_year=fold['year']
                    for d in (root/'inner').glob('fold_*'):
                        self.assertEqual((d/'test.jsonl').read_text(),'')
                        for split in ('train','valid'):
                            for line in (d/f'{split}.jsonl').read_text().splitlines():
                                self.assertLess(json.loads(line)['year'],validation_year)
                    self.assertEqual((root/'refit'/'valid.jsonl').read_text(),'')
                    refit=json.loads((root/'refit'/'manifest.json').read_text())
                    self.assertEqual(refit['evaluation_role'],'outer_valid')
                    self.assertEqual(set(refit['splits']['test']['years']),{str(validation_year)})
                    self.assertNotIn('2025',str(refit['splits']))
                self.assertFalse(summarize_nested(out,p/f'{task}_runs')['complete'])

    def test_inner_choice_uses_mean_and_median_epoch_not_best_fold(self):
        def candidate(name,scores,epochs):
            return dict(name=name,config={},summary=dict(complete=True,
                validation={'macro_f1':{'mean':sum(scores)/len(scores)}},
                folds=[dict(selected_epoch=e) for e in epochs]))
        choice=choose_inner([candidate('unstable',[0.9,0.1],[1,5]),
                             candidate('stable',[0.6,0.6],[2,3])])
        self.assertEqual(choice['candidate'],'stable')
        self.assertEqual(choice['epochs'],3)
        with self.assertRaises(ValueError): choose_inner([dict(summary=dict(complete=False))])

    def test_future_records_cannot_change_inner_assignments(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder); original,_=self.prepare(p)
            bridge=row(3000,2019)
            bridge['meta']['case_number']='case0'
            bridge['fact']='事實1'
            with (p/'source.jsonl').open('a') as f:
                f.write(json.dumps(bridge)+'\n')
            changed=p/'changed'
            prepare_nested(p/'source.jsonl','accusation',changed,folds=5,min_label_freq=1)
            for index in range(1,6):
                relative=f'valid_2019/inner/fold_{index:02d}/split_assignment.json'
                self.assertEqual((original/relative).read_text(),(changed/relative).read_text())

    def test_runner_refits_fixed_epochs_then_evaluates_outer(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder); prepared,plan=self.prepare(p)
            config=p/'config.json';config.write_text(json.dumps(dict(epochs=5,evaluate_test=True)))
            summary=dict(complete=True,validation={'macro_f1':{'mean':0.4}},
                         folds=[dict(selected_epoch=e) for e in [1,2,2,3,5]])
            def inner(data,run,config_path):
                c=json.loads(Path(config_path).read_text())
                self.assertFalse(c['fixed_epochs']); self.assertFalse(c['evaluate_test'])
                return summary
            def refit(command,check):
                self.assertEqual(command[-2:],['--fixed-epochs','--evaluate-test'])
                config=json.loads(Path(command[command.index('--config')+1]).read_text())
                self.assertEqual(config['epochs'],2)
                self.assertTrue(config['fixed_epochs'])
                data=Path(config['data_dir']); run=Path(config['output'])
                self.assertEqual((data/'valid.jsonl').read_text(),'')
                (run/'data_manifest.json').write_text((data/'manifest.json').read_text())
                (run/'metrics.json').write_text(json.dumps(dict(fixed_epochs=True,tiny_random_smoke=False,
                    test_status='evaluated',history=[dict(epoch=1),dict(epoch=2)],test={'macro_f1':0.3})))
            with patch('judgment_bert.nested_cv.train_cv',side_effect=inner) as train, \
                 patch('judgment_bert.nested_cv.subprocess.run',side_effect=refit) as launch:
                result=train_nested(prepared,p/'runs',[config])
            self.assertEqual(train.call_count,2);self.assertEqual(launch.call_count,2)
            self.assertTrue(result['complete']);self.assertFalse(result['final_test_evaluated'])
            self.assertEqual(result['outer_validation']['macro_f1']['mean'],0.3)
