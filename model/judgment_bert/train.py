"""Train ONE of accusation/article/imprisonment per process and output directory."""
from __future__ import annotations
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import random
import math
import sys
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.preprocessing import MultiLabelBinarizer
from transformers import AutoTokenizer, BertConfig, BertModel, get_linear_schedule_with_warmup
from .encoding import FactDataset, Collator
from .model import SingleTaskBert
from .data import filter_to_classes
from evaluate import at_least_one, multilabel_scores


def resolve_device(name='auto'):
    if name != 'auto':
        return torch.device(name)
    if torch.cuda.is_available():
        return torch.device('cuda')
    if torch.backends.mps.is_available():
        return torch.device('mps')
    return torch.device('cpu')


def precision_context(device, precision):
    if precision == 'fp32':
        return nullcontext()
    dtype = torch.float16 if precision == 'fp16' else torch.bfloat16
    return torch.autocast(device_type=device.type, dtype=dtype)


def make_grad_scaler(device, precision):
    if precision != 'fp16':
        return None
    if not hasattr(torch.amp, 'GradScaler'):
        raise ValueError('FP16 AMP requires a newer PyTorch with torch.amp.GradScaler; tested on 2.8')
    return torch.amp.GradScaler(device.type)


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def metrics(logits, truth, classes, kind, threshold=.5, require_one=True):
    if kind=='multiclass':
        pred=np.argmax(logits,axis=1)
        return dict(accuracy=float(accuracy_score(truth,pred)),
                    macro_f1=float(f1_score(truth,pred,labels=list(range(len(classes))),average='macro',zero_division=0)))
    scores=torch.sigmoid(torch.as_tensor(logits)).numpy()
    predicted=at_least_one(scores,threshold) if require_one else (scores>=threshold).astype(int)
    predictions=[{classes[i] for i,value in enumerate(row) if value} for row in predicted]
    truth=[set(row) for row in truth]
    if any(row-set(classes) for row in truth):
        raise ValueError('Evaluation truth contains labels outside the trained classes; filter records first')
    universe=list(classes)
    encoder=MultiLabelBinarizer(classes=universe); encoder.fit([[]])
    y=encoder.transform(truth); p=encoder.transform(predictions)
    shared=multilabel_scores(y,p)
    return dict(micro_f1=shared['micro'],
                macro_f1=shared['macro'],
                prediction_policy='at_least_one' if require_one else 'allow_empty',
                micro_precision=float(precision_score(y,p,average='micro',zero_division=0)),
                micro_recall=float(recall_score(y,p,average='micro',zero_division=0)),
                subset_accuracy=float(accuracy_score(y,p)),
                unseen_true_label_occurrences=sum(len(row-set(classes)) for row in truth),
                metric_label_space='fixed training classes; out-of-scope labels removed and empty rows dropped')


METRIC_SOURCES = {
    'train_loss': 'TRAIN: mean training-batch loss',
    'valid': 'VALID: held-out validation data; used for selection and early stopping',
    'test': 'TEST: held-out test data; evaluated only with --evaluate-test',
    'best_valid_macro_f1': 'VALID: best validation macro-F1',
}


def format_metrics(split, values):
    names={'micro_f1':'Micro-F1', 'macro_f1':'Macro-F1',
           'micro_precision':'Micro-Precision', 'micro_recall':'Micro-Recall',
           'subset_accuracy':'Subset Accuracy', 'accuracy':'Accuracy'}
    parts=[f'{label}={values[key]:.2%}' for key,label in names.items() if key in values]
    if 'unseen_true_label_occurrences' in values:
        parts.append(f"Unseen true-label occurrences={values['unseen_true_label_occurrences']}")
    return f"[{split.upper()}] " + ' | '.join(parts)


def format_epoch(info):
    return (f"Epoch {info['epoch']}\n"
            f"[TRAIN] Loss={info['train_loss']:.6f}\n"
            + format_metrics('VALID',info['valid']))


def format_training_summary(result):
    sections=[format_epoch(info) if 'valid' in info else
              f"Epoch {info['epoch']}\n[TRAIN] Loss={info['train_loss']:.6f}" for info in result['history']]
    if result['best_valid_macro_f1'] is not None:
        sections.append(f"[VALID] Best Macro-F1={result['best_valid_macro_f1']:.2%}")
    else:
        sections.append('[VALID] Not used; fixed-epoch refit.')
    sections.append(format_metrics(result.get('evaluation_role','test'),result['test']) if 'test' in result else
                    '[TEST] Not evaluated (held out; --evaluate-test disabled).')
    return '\n\n'.join(sections)+'\n'


def evaluate(model,loader,device,records,manifest,threshold,precision='fp32',require_one=True):
    model.eval(); logits=[]; indexes=[]
    with torch.no_grad():
        for batch,_,idx in loader:
            with precision_context(device,precision):
                prediction=model(**{k:v.to(device) for k,v in batch.items()})
            logits.append(prediction.float().cpu().numpy())
            indexes.extend(idx)
    truth=[records[i]['true_labels'] for i in indexes]
    return metrics(np.concatenate(logits),truth,manifest['classes'],manifest['kind'],threshold,require_one)


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,help='JSON settings; explicit CLI arguments take precedence')
    parser.add_argument('--print-config',action='store_true',help='Show resolved settings without downloading models')
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',default='google-bert/bert-base-chinese')
    parser.add_argument('--tokenizer')
    parser.add_argument('--revision')
    parser.add_argument('--pooling',choices=['cls','mean','attention'],default='cls')
    parser.add_argument('--head',choices=['linear','mlp'],default='linear')
    parser.add_argument('--finetune',choices=['full','last_n','frozen'],default='full')
    parser.add_argument('--last-n',type=int,default=2)
    parser.add_argument('--long-text',choices=['truncate','chunk'],default='truncate')
    parser.add_argument('--chunk-pooling',choices=['mean','attention'],default='mean')
    parser.add_argument('--max-length',type=int,default=512)
    parser.add_argument('--overlap',type=int,default=128)
    parser.add_argument('--max-chunks',type=int,default=0,help='0 = keep all chunks; positive values explicitly cap the document')
    parser.add_argument('--batch-size',type=int,default=4)
    parser.add_argument('--grad-accum',type=int,default=4)
    parser.add_argument('--epochs',type=int,default=3)
    parser.add_argument('--patience',type=int,default=2)
    parser.add_argument('--encoder-lr',type=float,default=2e-5)
    parser.add_argument('--head-lr',type=float,default=1e-3)
    parser.add_argument('--dropout',type=float,default=.1,help='Classifier and pooling-head dropout; encoder keeps checkpoint settings')
    parser.add_argument('--weight-decay',type=float,default=.01)
    parser.add_argument('--warmup-ratio',type=float,default=0.,help='Linear warmup then decay; 0 preserves constant learning rate')
    parser.add_argument('--max-grad-norm',type=float,default=1.)
    parser.add_argument('--early-stop-min-delta',type=float,default=0.)
    parser.add_argument('--expected-min-label-freq',type=int,help='Assert prepared-data threshold, without rebuilding labels')
    parser.add_argument('--pos-weight',action=argparse.BooleanOptionalAction,default=False)
    parser.add_argument('--pos-weight-cap',type=float,default=10.,help='Cap per-class negative/positive ratio; only used with pos-weight')
    parser.add_argument('--threshold',type=float,default=.5)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--precision',choices=['fp32','fp16','bf16'],default='fp32',help='Opt-in autocast; fp16 uses gradient scaling, fp32 preserves baseline')
    parser.add_argument('--device',default='auto',help='auto chooses CUDA, then Apple MPS, then CPU')
    parser.add_argument('--evaluate-test',action=argparse.BooleanOptionalAction,default=False)
    parser.add_argument('--check-data',action='store_true',help='Inspect prepared data, without tokenizer/model downloads')
    parser.add_argument('--fixed-epochs',action='store_true',help='Refit for exactly epochs; no validation selection or early stopping')
    parser.add_argument('--tiny-smoke',action='store_true',help='Random tiny BERT, 1 epoch, tiny subsets; NOT an experiment result')
    argv=list(sys.argv[1:] if argv is None else argv)
    probe=argparse.ArgumentParser(add_help=False)
    probe.add_argument('--config',type=Path)
    config_path=probe.parse_known_args(argv)[0].config
    config_argv=[]
    if config_path:
        try:
            settings=json.loads(config_path.read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc:
            parser.error(f'Cannot read config: {exc}')
        if not isinstance(settings,dict):
            parser.error('Config must be a JSON object')
        actions={a.dest:a for a in parser._actions}
        for key,value in settings.items():
            if key not in actions or key in ('help','config','print_config'):
                parser.error(f'Unknown or reserved config key: {key}')
            if value is None:
                continue
            action=actions[key]; option='--'+key.replace('_','-')
            if isinstance(action,argparse.BooleanOptionalAction):
                if not isinstance(value,bool):
                    parser.error(f'{key} must be a boolean')
                config_argv.append(option if value else '--no-'+key.replace('_','-'))
            elif isinstance(action,argparse._StoreTrueAction):
                if not isinstance(value,bool):
                    parser.error(f'{key} must be a boolean')
                if value: config_argv.append(option)
            else:
                config_argv.extend([option,str(value)])
    args=parser.parse_args(config_argv+argv)
    if min(args.batch_size,args.grad_accum,args.epochs,args.patience)<1 or not 0 < args.threshold < 1:
        parser.error('Positive batch/accumulation/epochs/patience and 0<threshold<1 required')
    if not 0 <= args.dropout < 1 or not 0 <= args.warmup_ratio < 1:
        parser.error('dropout and warmup-ratio must be in [0,1)')
    if min(args.encoder_lr,args.head_lr,args.max_grad_norm,args.pos_weight_cap)<=0 or min(args.weight_decay,args.early_stop_min_delta)<0:
        parser.error('Invalid optimizer, weighting or early-stop settings')
    if args.expected_min_label_freq is not None and args.expected_min_label_freq<1:
        parser.error('expected-min-label-freq must be positive')
    return args


def main():
    args=parse_args()
    if args.print_config:
        print(json.dumps({k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},ensure_ascii=False,indent=2))
        return
    manifest=json.loads((args.data_dir/'manifest.json').read_text())
    if args.expected_min_label_freq is not None and manifest.get('min_label_freq') != args.expected_min_label_freq:
        raise ValueError('Prepared-data min_label_freq differs from config; rebuild data before training')
    if args.check_data:
        print(json.dumps(manifest,ensure_ascii=False,indent=2)); return
    if (args.output/'best.pt').exists():
        raise ValueError('Output already contains a checkpoint; select a new output directory')
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    active_splits=['train'] + ([] if args.fixed_epochs else ['valid']) + (['test'] if args.evaluate_test else [])
    records={split:read_jsonl(args.data_dir/f'{split}.jsonl') for split in active_splits}
    filtering={}
    for split in records:
        records[split],filtering[split]=filter_to_classes(records[split],manifest['classes'],manifest['kind'])
        if not records[split]:
            raise ValueError(f'{split} is empty after label filtering')
        print(f'[{split.upper()}] Label filtering: {filtering[split]}',flush=True)
    if args.tiny_smoke:
        args.epochs=1
        records={k:v[:(8 if k=='train' else 4)] for k,v in records.items()}
    tokenizer=AutoTokenizer.from_pretrained(args.tokenizer or args.model,revision=args.revision,use_fast=True)
    encoder=None
    if args.tiny_smoke:
        encoder=BertModel(BertConfig(vocab_size=len(tokenizer),hidden_size=32,num_hidden_layers=max(1,args.last_n) if args.finetune=='last_n' else 1,
                                    num_attention_heads=2,intermediate_size=64,max_position_embeddings=512))
    model=SingleTaskBert(manifest['num_labels'],args.model,args.revision,args.pooling,args.head,
                         args.finetune,args.last_n,args.chunk_pooling,dropout=args.dropout,encoder=encoder)
    if not 2 < args.max_length <= model.encoder.config.max_position_embeddings:
        raise ValueError('max-length exceeds the encoder position limit or leaves no content')
    device=resolve_device(args.device)
    model.to(device)
    scaler=make_grad_scaler(device,args.precision)
    datasets={split:FactDataset(rows,tokenizer,manifest['classes'],manifest['kind'],args.max_length,
                                args.long_text,args.overlap,args.max_chunks) for split,rows in records.items()}
    collator=Collator(tokenizer.pad_token_id,args.long_text=='chunk')
    loaders={split:DataLoader(ds,batch_size=args.batch_size,shuffle=split=='train',collate_fn=collator)
             for split,ds in datasets.items()}
    criterion=nn.CrossEntropyLoss()
    if manifest['kind']=='multilabel':
        pos_weight=None
        if args.pos_weight:
            counts=np.zeros(manifest['num_labels']); ids={k:i for i,k in enumerate(manifest['classes'])}
            for row in records['train']:
                for label in row['target']:counts[ids[label]]+=1
            pos_weight=torch.tensor(np.minimum((len(records['train'])-counts)/np.maximum(counts,1),args.pos_weight_cap),dtype=torch.float32,device=device)
        criterion=nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    encoder_ids={id(p) for p in model.encoder.parameters()}
    groups=[{'params':[p for p in model.encoder.parameters() if p.requires_grad],'lr':args.encoder_lr},
            {'params':[p for p in model.parameters() if id(p) not in encoder_ids and p.requires_grad],'lr':args.head_lr}]
    optimizer=torch.optim.AdamW([g for g in groups if g['params']],weight_decay=args.weight_decay)
    total_steps=math.ceil(len(loaders['train'])/args.grad_accum)*args.epochs
    scheduler=(get_linear_schedule_with_warmup(optimizer,math.ceil(total_steps*args.warmup_ratio),total_steps)
               if args.warmup_ratio>0 else None)
    args.output.mkdir(parents=True,exist_ok=True)
    tokenizer.save_pretrained(args.output/'tokenizer')
    model.encoder.config.save_pretrained(args.output/'encoder_config')
    config={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    (args.output/'run_config.json').write_text(json.dumps(config,indent=2)+'\n')
    (args.output/'label_filtering.json').write_text(json.dumps(filtering,indent=2)+'\n')
    (args.output/'data_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    best=-math.inf; stale=0; history=[]
    for epoch in range(args.epochs):
        model.train(); optimizer.zero_grad(); total_loss=0
        for step,(batch,target,_) in enumerate(loaders['train']):
            batch={k:v.to(device) for k,v in batch.items()};target=target.to(device)
            with precision_context(device,args.precision):
                raw_loss=criterion(model(**batch),target)
            group_start=step-step%args.grad_accum
            divisor=min(args.grad_accum,len(loaders['train'])-group_start)
            loss=raw_loss/divisor
            if scaler is None: loss.backward()
            else: scaler.scale(loss).backward()
            total_loss+=raw_loss.item()
            if (step+1)%args.grad_accum==0 or step+1==len(loaders['train']):
                if scaler is not None: scaler.unscale_(optimizer)
                nn.utils.clip_grad_norm_(model.parameters(),args.max_grad_norm)
                stepped=True
                if scaler is None:
                    optimizer.step()
                else:
                    old_scale=scaler.get_scale()
                    scaler.step(optimizer);scaler.update()
                    stepped=scaler.get_scale()>=old_scale
                if scheduler is not None and stepped: scheduler.step()
                optimizer.zero_grad()
        if args.fixed_epochs:
            info=dict(epoch=epoch+1,train_loss=total_loss/len(loaders['train']))
            history.append(info)
            print(f"Epoch {epoch+1} [TRAIN] Loss={info['train_loss']:.6f} [VALID] Not used (fixed epochs)",flush=True)
            torch.save(model.state_dict(),args.output/'best.pt')
            continue
        validation=evaluate(model,loaders['valid'],device,records['valid'],manifest,args.threshold,args.precision)
        info=dict(epoch=epoch+1,train_loss=total_loss/len(loaders['train']),valid=validation)
        history.append(info); print(format_epoch(info),flush=True)
        if validation['macro_f1']>best+args.early_stop_min_delta:
            best=validation['macro_f1'];stale=0
            torch.save(model.state_dict(),args.output/'best.pt')
        else:
            stale+=1
        if stale>=args.patience:
            break
    result=dict(tiny_random_smoke=args.tiny_smoke,history=history,best_valid_macro_f1=None if args.fixed_epochs else best,
                fixed_epochs=args.fixed_epochs, evaluation_role=manifest.get('evaluation_role','test'),
                metric_sources=METRIC_SOURCES, label_filtering=filtering,
                test_status='evaluated' if args.evaluate_test else 'not_evaluated')
    if args.evaluate_test:
        model.load_state_dict(torch.load(args.output/'best.pt',map_location=device,weights_only=True))
        result['test']=evaluate(model,loaders['test'],device,records['test'],manifest,args.threshold,args.precision)
        if result['evaluation_role']=='outer_valid':
            result['metric_sources']=dict(METRIC_SOURCES, test='OUTER_VALID: next year; evaluated once after fixed-epoch refit')
    print(format_metrics(result.get('evaluation_role','test'),result['test']) if 'test' in result else
          '[TEST] Not evaluated (held out; --evaluate-test disabled).',flush=True)
    (args.output/'training_summary.txt').write_text(format_training_summary(result),encoding='utf-8')
    (args.output/'metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
