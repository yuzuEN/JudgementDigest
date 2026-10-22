import json
from pathlib import Path
import tempfile
import unittest
import torch
from transformers import BertConfig, BertModel, BertTokenizerFast, ElectraConfig, ElectraModel
from judgment_bert.analyze import describe
from judgment_bert.data import prepare, term_class, filter_to_classes
from judgment_bert.encoding import chunk_token_ids, FactDataset, Collator
from judgment_bert.model import SingleTaskBert
from judgment_bert.train import metrics, resolve_device
from unittest.mock import patch


def record(case,year,fact,labels):
    return {'fact':fact,'meta':{'year':year,'case_number':case,'source_url':f'{case}/{year}',
                               'accusation':labels,'relevant_articles':[]}}


class TestPreparation(unittest.TestCase):
    def test_active_task_only_train_frequency_and_unseen_validation_truth(self):
        rows=[record('a',2023,'甲',['常見']),record('b',2023,'乙',['常見']),
              record('c',2023,'丙',['罕見']),record('d',2024,'丁',['未來']),
              record('e',2025,'戊',['常見']), record('f',2024,'己',['常見','未來'])]
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder); data=p/'data.jsonl'
            data.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
            manifest=prepare(data,'accusation',p/'out',min_label_freq=2)
            self.assertEqual(manifest['classes'],['常見'])
            self.assertEqual(manifest['splits']['train']['n'],2)
            valid=json.loads((p/'out/valid.jsonl').read_text())
            self.assertEqual(valid['true_labels'],['常見'])
            self.assertEqual(valid['raw_true_labels'],['常見','未來'])
            self.assertEqual(manifest['skipped']['valid_without_frequent_label'],1)
            self.assertEqual(valid['target'],['常見'])
            self.assertEqual(manifest['splits']['valid']['n'],1)
            with self.assertRaises(FileExistsError):prepare(data,'accusation',p/'out',min_label_freq=2)

    def test_case_group_and_exact_fact_leakage_removed_chronologically(self):
        rows=[record('a',2023,'甲',['罪']),record('a',2024,'乙',['罪']),
              record('c',2024,'甲',['罪']),record('d',2024,'丁',['罪']),record('e',2025,'戊',['罪'])]
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);data=p/'data.jsonl';data.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            manifest=prepare(data,'accusation',p/'out',min_label_freq=1)
            self.assertEqual(manifest['removed_cross_split_case_rows']['valid'],1)
            self.assertEqual(manifest['removed_duplicate_fact_rows']['valid'],1)
            self.assertEqual(manifest['splits']['train']['n'],1)
            self.assertEqual(manifest['splits']['valid']['n'],1)

    def test_term_mask_fractional_boundaries_and_special_terms(self):
        row={'meta':{'term_task':False,'sentence_kind':'拘役','term_of_imprisonment':{'imprisonment':0}}}
        self.assertIsNone(term_class(row))
        row['meta']['term_task']=True
        self.assertIsNone(term_class(row))
        row['meta']['sentence_kind']='有期徒刑'
        for months,expected in [(6,0),(6.5,1),(36,5),(60,6),(119.5,7),(120,8),(301,8)]:
            row['meta']['term_of_imprisonment']={'imprisonment':months}
            self.assertEqual(term_class(row),expected)
        row['meta']['term_of_imprisonment']={'life_imprisonment':True}
        self.assertEqual(term_class(row),9)
        row['meta']['term_of_imprisonment']={'death_penalty':True}
        self.assertEqual(term_class(row),10)

    def test_closed_labels_drop_empty_and_preserve_mixed_rows(self):
        rows=[dict(true_labels=['seen','unseen']),dict(true_labels=['unseen'])]
        filtered,report=filter_to_classes(rows,['seen'])
        self.assertEqual(len(filtered),1)
        self.assertEqual(filtered[0]['true_labels'],['seen'])
        self.assertEqual(filtered[0]['raw_true_labels'],['seen','unseen'])
        self.assertEqual(report['dropped_empty'],1)
        self.assertEqual(rows[0]['true_labels'],['seen','unseen'])
        result=metrics([[10.0]],[filtered[0]['true_labels']],['seen'],'multilabel')
        self.assertEqual(result['micro_f1'],1)
        self.assertEqual(result['macro_f1'],1)
        with self.assertRaises(ValueError):metrics([[10.0]],[['seen','unseen']],['seen'],'multilabel')

    def test_percentile_uses_linear_interpolation(self):
        self.assertEqual(describe([1,2,3,10])['q3'],4.75)


class TestBert(unittest.TestCase):
    @staticmethod
    def encoder():
        return BertModel(BertConfig(vocab_size=32,hidden_size=16,num_hidden_layers=2,
                                    num_attention_heads=2,intermediate_size=32,max_position_embeddings=16))

    def test_electra_last_two_layers_and_mlp_backward(self):
        encoder=ElectraModel(ElectraConfig(vocab_size=32,embedding_size=16,
            hidden_size=16,num_hidden_layers=4,num_attention_heads=2,
            intermediate_size=32,max_position_embeddings=16))
        model=SingleTaskBert(3,head='mlp',finetune='last_n',last_n=2,encoder=encoder)
        linear=[layer for layer in model.head if isinstance(layer,torch.nn.Linear)]
        self.assertEqual([(x.in_features,x.out_features) for x in linear],[(16,512),(512,256),(256,3)])
        ids=torch.tensor([[2,5,3],[2,6,3]])
        model(ids,ids.ne(0)).sum().backward()
        self.assertTrue(all(p.grad is None for p in encoder.embeddings.parameters()))
        for layer in encoder.encoder.layer[:2]:
            self.assertTrue(all(not p.requires_grad and p.grad is None for p in layer.parameters()))
        for layer in encoder.encoder.layer[-2:]:
            self.assertTrue(all(p.requires_grad and p.grad is not None for p in layer.parameters()))
        self.assertTrue(all(p.grad is not None for p in model.head.parameters()))

    def test_auto_device_prefers_mps_over_cpu(self):
        with patch('torch.cuda.is_available',return_value=False):
            with patch('torch.backends.mps.is_available',return_value=True):
                self.assertEqual(resolve_device().type,'mps')
            with patch('torch.backends.mps.is_available',return_value=False):
                self.assertEqual(resolve_device().type,'cpu')
        self.assertEqual(resolve_device('cpu').type,'cpu')

    def test_pooling_variants_forward_and_backward(self):
        for pooling in ('cls','mean','attention'):
            model=SingleTaskBert(3,pooling=pooling,encoder=self.encoder())
            ids=torch.tensor([[2,5,3,0],[2,6,7,3]]); mask=ids.ne(0)
            logits=model(ids,mask)
            self.assertEqual(tuple(logits.shape),(2,3))
            torch.nn.BCEWithLogitsLoss()(logits,torch.tensor([[1.,0,0],[0,1.,1.]])).backward()
            self.assertIsNotNone(model.encoder.embeddings.word_embeddings.weight.grad)

    def test_chunk_padding_ignored_and_encoder_gradients_preserved(self):
        for pooling in ('mean','attention'):
            model=SingleTaskBert(2,chunk_pooling=pooling,encoder=self.encoder())
            model.eval()
            ids=torch.tensor([[[2,5,3],[2,6,3],[0,0,0]]])
            chunks=torch.tensor([[True,True,False]])
            prediction=model(ids,ids.ne(0),chunks)
            changed=ids.clone();changed[0,2]=torch.tensor([8,9,10])
            self.assertTrue(torch.allclose(prediction,model(changed,changed.ne(0),chunks)))
            prediction.sum().backward()
            self.assertIsNotNone(model.encoder.embeddings.word_embeddings.weight.grad)

    def test_frozen_encoder_stays_eval_but_head_trains(self):
        model=SingleTaskBert(2,finetune='frozen',head='mlp',encoder=self.encoder())
        model.train()
        self.assertFalse(model.encoder.training)
        self.assertFalse(any(p.requires_grad for p in model.encoder.parameters()))
        self.assertTrue(any(p.requires_grad for p in model.head.parameters()))

    def test_last_layer_unfreezing_and_position_limit(self):
        model=SingleTaskBert(2,finetune='last_n',last_n=1,encoder=self.encoder())
        self.assertFalse(any(p.requires_grad for p in model.encoder.encoder.layer[0].parameters()))
        self.assertTrue(all(p.requires_grad for p in model.encoder.encoder.layer[1].parameters()))
        with self.assertRaises(ValueError):model(torch.ones((1,17),dtype=torch.long),torch.ones((1,17)))

    def test_real_tokenizer_chunking_retains_tail_and_single_document_label(self):
        with tempfile.TemporaryDirectory() as folder:
            vocab=Path(folder)/'vocab.txt'
            vocab.write_text('[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\n甲\n乙\n丙\n')
            tok=BertTokenizerFast(vocab_file=str(vocab),do_lower_case=False)
            rows=[dict(fact='甲'*15+'乙',target=['罪'])]
            ds=FactDataset(rows,tok,['罪'],'multilabel',max_length=8,long_text='chunk',overlap=2)
            sample=ds[0]
            self.assertGreater(len(sample['chunks']),1)
            self.assertIn(tok.convert_tokens_to_ids('乙'),sample['chunks'][-1])
            batch,target,_=Collator(tok.pad_token_id,chunked=True)([sample])
            self.assertEqual(tuple(target.shape),(1,1))
            self.assertLessEqual(batch['input_ids'].shape[-1],8)
            self.assertEqual(chunk_token_ids(list(range(7)),4,1),[[0,1,2,3],[3,4,5,6]])
            with self.assertRaises(ValueError):chunk_token_ids([1],4,4)



class TestNonemptyPrediction(unittest.TestCase):
    def test_empty_predictions_fall_back_to_argmax(self):
        scores=metrics([[-4.,-5.]],[['A']],['A','B'],'multilabel')
        self.assertEqual(scores['micro_f1'],1.)
        self.assertEqual(scores['prediction_policy'],'at_least_one')
        legacy=metrics([[-4.,-5.]],[['A']],['A','B'],'multilabel',require_one=False)
        self.assertEqual(legacy['micro_f1'],0.)

    def test_threshold_tie_and_existing_multilabel_predictions(self):
        tie=metrics([[0.,0.]],[['A']],['A','B'],'multilabel')
        self.assertEqual(tie['subset_accuracy'],1.)
        multiple=metrics([[3.,4.]],[['A','B']],['A','B'],'multilabel')
        self.assertEqual(multiple['subset_accuracy'],1.)

if __name__=='__main__':
    torch.set_num_threads(1)
    unittest.main()
