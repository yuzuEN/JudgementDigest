import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
from transformers import BertConfig, BertModel, BertTokenizerFast
from judgment_bert.model import SingleTaskBert
from judgment_bert.test_evaluation import run, test_plan


class HeldoutEvaluationTest(unittest.TestCase):
    def fixture(self, root):
        prepared, runs = root/'prepared', root/'runs'
        prepared.mkdir(); runs.mkdir()
        def write(path, value): path.write_text(json.dumps(value))
        write(prepared/'cv_manifest.json', dict(test_year=2025, folds=[dict(name=f'fold_{i:02}') for i in (1,2)]))
        write(runs/'cv_summary.json', dict(complete=True, completed_folds=2))
        manifest=dict(classes=['A','B'], num_labels=2, kind='multilabel')
        config=dict(model='unused',pooling='cls',head='linear',finetune='frozen',last_n=1,
                    dropout=0.,device='cpu',max_length=16,long_text='truncate',batch_size=1,
                    threshold=.5,precision='fp32')
        for i in (1,2):
            name=f'fold_{i:02}'; p=prepared/name; r=runs/name;p.mkdir();r.mkdir()
            write(p/'manifest.json',manifest); write(r/'data_manifest.json',manifest)
            (p/'test.jsonl').write_text(json.dumps(dict(fact='test',true_labels=['A'],target=['A'],year=2025))+'\n')
            write(r/'run_config.json',config)
            write(r/'metrics.json',dict(test_status='not_evaluated',best_valid_macro_f1=.7,
                                       history=[dict(epoch=1,valid=dict(macro_f1=.7)),dict(epoch=2,valid=dict(macro_f1=.6))]))
            vocab=r/'vocab.txt';vocab.write_text('[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\ntest\n')
            BertTokenizerFast(vocab_file=str(vocab)).save_pretrained(r/'tokenizer')
            model=self.model()
            with torch.no_grad(): model.head[1].bias.copy_(torch.tensor([10.,-10.]))
            torch.save(model.state_dict(),r/'best.pt')
        return prepared,runs

    @staticmethod
    def model(*args, **kwargs):
        encoder=BertModel(BertConfig(vocab_size=6,hidden_size=8,num_hidden_layers=1,
                                     num_attention_heads=2,intermediate_size=16,max_position_embeddings=16))
        model=SingleTaskBert(2,head='linear',finetune='frozen',dropout=0.,encoder=encoder)
        with torch.no_grad():
            model.head[1].weight.zero_();model.head[1].bias.copy_(torch.tensor([-10.,10.]))
        return model

    def test_best_checkpoint_restored_and_same_test_aggregated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepared,runs=self.fixture(root)
            with patch('judgment_bert.model.SingleTaskBert',side_effect=self.model):
                result=run(prepared,runs,root/'test_results')
            self.assertEqual(result['test']['micro_f1']['mean'],1.)
            self.assertEqual(result['test']['micro_f1']['sample_std'],0.)
            self.assertTrue(all(x['selected_epoch']==1 for x in result['folds']))
            self.assertEqual(result['test_year'],2025)
            self.assertFalse((runs/'fold_01/metrics.json').read_text().find('not_evaluated')==-1)

    def test_new_protocol_reads_reserved_year_not_outer_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepared,runs=self.fixture(root)
            plan=json.loads((prepared/'cv_manifest.json').read_text());plan['mode']='kfold_test'
            (prepared/'cv_manifest.json').write_text(json.dumps(plan))
            for name in ('fold_01','fold_02'):
                folder=prepared/name
                (folder/'test.jsonl').rename(folder/'holdout.jsonl')
                row=json.loads((folder/'holdout.jsonl').read_text());row['year']=2024
                (folder/'test.jsonl').write_text(json.dumps(row)+'\n')
                path=runs/name/'metrics.json';metrics=json.loads(path.read_text())
                metrics.update(test_status='evaluated',evaluation_role='outer_test')
                path.write_text(json.dumps(metrics))
            with patch('judgment_bert.model.SingleTaskBert',side_effect=self.model):
                result=run(prepared,runs,root/'test_results')
            self.assertEqual(result['test_year'],2025)
            self.assertEqual(result['test_n'],1)
            self.assertEqual(result['test']['micro_f1']['mean'],1.)

    def test_reject_different_test_and_wrong_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared,runs=self.fixture(Path(tmp));path=prepared/'fold_02/test.jsonl'
            row=json.loads(path.read_text());row['fact']='different';path.write_text(json.dumps(row)+'\n')
            with self.assertRaisesRegex(ValueError,'match'):test_plan(prepared)
            row['year']=2024
            for folder in prepared.glob('fold_*'):(folder/'test.jsonl').write_text(json.dumps(row)+'\n')
            with self.assertRaisesRegex(ValueError,'reserved'):test_plan(prepared)


if __name__=='__main__':unittest.main()
