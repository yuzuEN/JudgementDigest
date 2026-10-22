import unittest
import torch
from transformers import ElectraConfig, ElectraModel
from judgment_bert.model import SingleTaskBert, AttentionPool
from judgment_bert.train import make_grad_scaler, precision_context, parse_args, evaluate


class TestPrecision(unittest.TestCase):
    def test_fp32_is_default_and_cli_can_opt_in(self):
        argv=['--data-dir','data','--output','runs']
        self.assertEqual(parse_args(argv).precision,'fp32')
        self.assertEqual(parse_args(argv+['--precision','bf16']).precision,'bf16')
        self.assertIsNone(make_grad_scaler(torch.device('cpu'),'fp32'))

    @unittest.skipUnless(torch.backends.mps.is_available(),'Requires Apple MPS')
    def test_attention_padding_mask_uses_autocast_score_dtype(self):
        device=torch.device('mps')
        for precision in ('fp16','bf16'):
            pool=AttentionPool(8).to(device)
            states=torch.randn(2,3,8,device=device,requires_grad=True)
            mask=torch.tensor([[1,1,0],[1,0,0]],device=device)
            with precision_context(device,precision):
                result=pool(states,mask)
            self.assertTrue(torch.isfinite(result).all().item())
            result.sum().backward()

    @unittest.skipUnless(torch.backends.mps.is_available(),'Requires Apple MPS')
    def test_mps_electra_mixed_precision_backward_and_numpy_evaluation(self):
        device=torch.device('mps')
        for precision,dtype in [('fp16',torch.float16),('bf16',torch.bfloat16)]:
            with self.subTest(precision=precision):
                encoder=ElectraModel(ElectraConfig(vocab_size=32,embedding_size=16,hidden_size=16,
                    num_hidden_layers=2,num_attention_heads=2,intermediate_size=32,max_position_embeddings=16))
                model=SingleTaskBert(2,head='mlp',finetune='last_n',last_n=1,encoder=encoder).to(device)
                optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad])
                initial_head=model.head[0].weight.detach().clone()
                scaler=make_grad_scaler(device,precision)
                batch=dict(input_ids=torch.tensor([[2,5,3],[2,6,3]],device=device),
                           attention_mask=torch.ones(2,3,dtype=torch.long,device=device))
                target=torch.tensor([[1.,0.],[0.,1.]],device=device)
                for _ in range(2):
                    optimizer.zero_grad()
                    with precision_context(device,precision):
                        logits=model(**batch)
                        loss=torch.nn.functional.binary_cross_entropy_with_logits(logits,target)
                    self.assertEqual(logits.dtype,dtype);self.assertTrue(torch.isfinite(loss).item())
                    if scaler is None:loss.backward();optimizer.step()
                    else:
                        scaler.scale(loss).backward();scaler.unscale_(optimizer)
                        torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
                        scaler.step(optimizer);scaler.update()
                torch.mps.synchronize()
                self.assertTrue(all(torch.isfinite(p).all().item() for p in model.parameters()))
                self.assertFalse(torch.equal(initial_head,model.head[0].weight.detach()))
                loader=[({k:v.cpu() for k,v in batch.items()},target.cpu(),[0,1])]
                result=evaluate(model,loader,device,[dict(true_labels=['a']),dict(true_labels=['b'])],
                                dict(classes=['a','b'],kind='multilabel'),0.5,precision)
                self.assertTrue(0<=result['macro_f1']<=1)
