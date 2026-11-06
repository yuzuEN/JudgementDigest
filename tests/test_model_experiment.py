import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))

import json
import tempfile
import unittest
from unittest.mock import patch
import train_model
from judgment_bert.time_cv import run_time_cv


class TestExperiment(unittest.TestCase):
    def settings(self,p,time_cv=False):
        data=p/'source.jsonl';data.write_text('source')
        config=p/'training.json';config.write_text(json.dumps(dict(encoder_lr=2e-5,dropout=0.1,epochs=5)))
        return dict(data=str(data),output=str(p/'experiment'),training_config=str(config),task='accusation',
                    folds=5,epochs=5,precision='fp32',time_cv=time_cv,first_year=2018,test_year=2025,
                    min_label_freq=30,seed=42)

    def test_time_cv_default_off_and_cli_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);settings=self.settings(p);settings.pop('time_cv')
            config=p/'experiment.json';config.write_text(json.dumps(settings))
            resolved,_=train_model.parse_args(['--config',str(config)])
            self.assertFalse(resolved['time_cv'])
            resolved,_=train_model.parse_args(['--config',str(config),'--time-cv','--folds','10','--epochs','3'])
            self.assertTrue(resolved['time_cv']);self.assertEqual(resolved['folds'],10);self.assertEqual(resolved['epochs'],3)
            settings['time_cv']=True;config.write_text(json.dumps(settings))
            resolved,_=train_model.parse_args(['--config',str(config),'--no-time-cv'])
            self.assertFalse(resolved['time_cv'])

    def test_invalid_experiment_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);settings=self.settings(p);config=p/'experiment.json'
            for changed in (dict(settings,time_cv='false'),dict(settings,folds='five'),
                            dict(settings,first_year=2026),dict(settings,unknown=True)):
                config.write_text(json.dumps(changed))
                with self.assertRaises(SystemExit):train_model.parse_args(['--config',str(config)])

    def test_main_validation_then_optional_time_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);settings=self.settings(p,True);events=[]
            def main_valid(*args):events.append('main_validation');return dict(complete=True)
            def time_analysis(*args,**kwargs):
                self.assertTrue((p/'experiment/experiment_summary.json').exists())
                events.append('time_cv');return dict(complete=True)
            with patch('train_model.prepare_cv'),patch('train_model.train_cv',side_effect=main_valid), \
                 patch('judgment_bert.time_cv.run_time_cv',side_effect=time_analysis), \
                 patch('judgment_bert.grid_search.tune',side_effect=AssertionError('Grid must not run')):
                result=train_model.run_experiment(settings)
            self.assertEqual(events,['main_validation','time_cv'])
            self.assertTrue(result['time_cv_enabled'])
            self.assertFalse(result['final_test_evaluated'])
            effective=json.loads((p/'experiment/training_config.json').read_text())
            self.assertEqual(effective['encoder_lr'],2e-5);self.assertEqual(effective['dropout'],0.1)
            self.assertFalse(effective['evaluate_test'])

    def test_default_and_incomplete_main_never_start_time_cv(self):
        for enabled,complete in [(False,True),(True,False)]:
            with self.subTest(enabled=enabled),tempfile.TemporaryDirectory() as folder:
                settings=self.settings(Path(folder),enabled)
                with patch('train_model.prepare_cv'),patch('train_model.train_cv',return_value=dict(complete=complete)), \
                     patch('judgment_bert.time_cv.run_time_cv') as time_run:
                    if complete:train_model.run_experiment(settings)
                    else:
                        with self.assertRaises(RuntimeError):train_model.run_experiment(settings)
                    time_run.assert_not_called()

    def test_time_module_has_no_grid_search_and_uses_fixed_config(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);config=p/'config.json';config.write_text('{}')
            with patch('judgment_bert.time_cv.prepare_cv') as prepare, \
                 patch('judgment_bert.time_cv.train_cv',return_value=dict(complete=True)) as train:
                result=run_time_cv(p/'data.jsonl','article',p/'time',config)
            self.assertEqual(prepare.call_args.kwargs['mode'],'time')
            self.assertEqual(train.call_args.args[2],config)
            self.assertFalse(result['parameter_search']);self.assertFalse(result['final_test_evaluated'])
