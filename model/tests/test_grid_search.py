import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from judgment_bert.grid_search import combinations, tune, evaluate_locked
from judgment_bert.train import parse_args


class TestGridSearch(unittest.TestCase):
    def fixture(self,p):
        data=p/'data';data.mkdir()
        manifest=dict(task='accusation',source_sha256='source',min_label_freq=30,
                      splits=dict(train=dict(n=100,years={'2018':100}),valid=dict(n=10,years={'2018':10})))
        (data/'manifest.json').write_text(json.dumps(manifest))
        config=p/'base.json';config.write_text(json.dumps(dict(epochs=5,evaluate_test=True)))
        grid=p/'grid.json';grid.write_text(json.dumps(dict(encoder_lr=[1e-5,2e-5],dropout=[0.1,0.2])))
        return data,config,grid,manifest

    def test_cartesian_product_and_control_keys(self):
        choices=combinations(dict(encoder_lr=[1e-5,2e-5],dropout=[0.1,0.2]))
        self.assertEqual(len(choices),4)
        self.assertEqual(choices,combinations(dict(dropout=[0.1,0.2],encoder_lr=[1e-5,2e-5])))
        for grid in ({}, {'dropout':[]},{'seed':[42]},{'output':['bad']}):
            with self.assertRaises(ValueError):combinations(grid)

    def fake_train(self,command,check):
        from judgment_bert.train import parse_args
        self.assertTrue(check)
        self.assertEqual(command[-1],'--no-evaluate-test')
        args=parse_args(command[4:])
        settings={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
        self.assertFalse(settings['evaluate_test']);self.assertFalse(settings['fixed_epochs'])
        run=Path(settings['output']);source=Path(settings['data_dir'])
        (run/'run_config.json').write_text(json.dumps(settings))
        (run/'data_manifest.json').write_text((source/'manifest.json').read_text())
        score=0.8 if run.name=='candidate_02' else 0.5
        (run/'metrics.json').write_text(json.dumps(dict(tiny_random_smoke=False,fixed_epochs=False,
            test_status='not_evaluated',best_valid_macro_f1=score,
            history=[dict(epoch=1,valid=dict(macro_f1=score)),dict(epoch=2,valid=dict(macro_f1=0.4))])))

    def test_search_selects_settings_not_weights_and_preserves_epoch_rule(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);data,base,grid,manifest=self.fixture(p)
            with patch('judgment_bert.grid_search.subprocess.run',side_effect=self.fake_train) as launch:
                result=tune(data,base,grid,p/'search')
            self.assertEqual(launch.call_count,4)
            self.assertEqual(result['winner'],'candidate_02')
            best=json.loads((p/'search/best_config.json').read_text())
            self.assertEqual(best['encoder_lr'],2e-5);self.assertEqual(best['dropout'],0.1)
            self.assertEqual(best['epochs'],5)
            self.assertFalse(best['evaluate_test'])
            self.assertNotIn('checkpoint',best)
            with self.assertRaises(FileExistsError):tune(data,base,grid,p/'search')

    def test_locked_evaluation_checks_source_role_and_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);data,base,grid,manifest=self.fixture(p)
            with patch('judgment_bert.grid_search.subprocess.run',side_effect=self.fake_train):
                tune(data,base,grid,p/'search')
            prepared=p/'cv';prepared.mkdir()
            plan=dict(mode='kfold',task='accusation',source_sha256='source',min_label_freq=30,
                      n_folds=10,folds=[dict(splits=dict(valid=dict(years={'2018':10,'2024':10})))])
            (prepared/'cv_manifest.json').write_text(json.dumps(plan))
            with patch('judgment_bert.grid_search.train_cv',return_value=dict(complete=True)) as run:
                result=evaluate_locked(p/'search',prepared,p/'main')
            self.assertTrue(result['complete']);self.assertEqual(run.call_count,1)
            self.assertEqual(result['protocol']['role'],'main')
            self.assertIn('optimistic',result['protocol']['note'])
            with self.assertRaises(ValueError):evaluate_locked(p/'search',prepared,p/'time','time')
            best=p/'search/best_config.json';best.write_text(json.dumps(dict(dropout=0.9)))
            with self.assertRaises(ValueError):evaluate_locked(p/'search',prepared,p/'tampered')

    def test_search_rejects_unexpected_trial_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);data,base,grid,manifest=self.fixture(p)
            def wrong_config(command,check):
                self.fake_train(command,check)
                path=Path(command[5]).parent/'run_config.json'
                settings=json.loads(path.read_text());settings['dropout']=0.9
                path.write_text(json.dumps(settings))
            with patch('judgment_bert.grid_search.subprocess.run',side_effect=wrong_config):
                with self.assertRaises(ValueError):tune(data,base,grid,p/'search')

    def test_evaluation_hold_skips_before_reading_data_or_starting_models(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);search=p/'search';search.mkdir()
            (search/'evaluation_hold.json').write_text(json.dumps(dict(reason='Tuning only')))
            with patch('judgment_bert.grid_search.train_cv') as launch:
                for role in ('main','time'):
                    result=evaluate_locked(search,p/'no_data',p/role,role)
                    self.assertEqual(result['status'],'skipped')
                    self.assertFalse((p/role).exists())
                launch.assert_not_called()
