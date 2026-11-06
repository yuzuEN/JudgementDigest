"""Explicit truncation/chunking; document aggregation avoids duplicate labels per chunk."""
from __future__ import annotations
import math
import torch
from torch.utils.data import Dataset


def chunk_token_ids(ids, capacity, overlap=128, max_chunks=0):
    if capacity < 1 or not 0 <= overlap < capacity or max_chunks < 0:
        raise ValueError('Invalid capacity, overlap or max_chunks')
    chunks=[]; start=0
    while True:
        chunks.append(ids[start:start+capacity])
        if start+capacity >= len(ids) or (max_chunks and len(chunks)>=max_chunks):
            break
        start += capacity-overlap
    return chunks


class FactDataset(Dataset):
    def __init__(self, records, tokenizer, classes, kind, max_length=512, long_text='truncate',
                 overlap=128, max_chunks=0):
        if long_text not in ('truncate','chunk'):
            raise ValueError('long_text must be truncate or chunk')
        self.records=records; self.tokenizer=tokenizer; self.class_ids={k:i for i,k in enumerate(classes)}
        self.kind=kind; self.max_length=max_length; self.long_text=long_text
        self.overlap=overlap; self.max_chunks=max_chunks
        self.capacity=max_length-tokenizer.num_special_tokens_to_add(pair=False)
        if self.capacity < 1:
            raise ValueError('max_length leaves no content capacity')
        if long_text=='chunk':
            chunk_token_ids([], self.capacity, overlap, max_chunks)

    def __len__(self):
        return len(self.records)

    def __getitem__(self,index):
        row=self.records[index]
        if self.long_text=='truncate':
            enc=self.tokenizer(row['fact'],truncation=True,max_length=self.max_length,
                               padding=False,return_token_type_ids=False)
            chunks=[enc['input_ids']]
        else:
            # Turn off tokenizer length warnings without ever truncating before chunking.
            ids=self.tokenizer(row['fact'],truncation=False,add_special_tokens=False,
                               return_token_type_ids=False,return_attention_mask=False,verbose=False)['input_ids']
            chunks=[self.tokenizer.build_inputs_with_special_tokens(chunk) for chunk in
                    chunk_token_ids(ids,self.capacity,self.overlap,self.max_chunks)]
        if self.kind=='multilabel':
            target=torch.zeros(len(self.class_ids),dtype=torch.float32)
            for label in row['target']:
                target[self.class_ids[label]]=1
        else:
            target=torch.tensor(row['target'],dtype=torch.long)
        return dict(chunks=chunks,target=target,index=index)


class Collator:
    def __init__(self,pad_token_id,chunked=False):
        self.pad_token_id=pad_token_id; self.chunked=chunked

    def __call__(self,items):
        max_chunks=max(len(item['chunks']) for item in items)
        max_tokens=max(len(chunk) for item in items for chunk in item['chunks'])
        ids=torch.full((len(items),max_chunks,max_tokens),self.pad_token_id,dtype=torch.long)
        masks=torch.zeros_like(ids); chunk_mask=torch.zeros((len(items),max_chunks),dtype=torch.bool)
        for i,item in enumerate(items):
            for j,chunk in enumerate(item['chunks']):
                ids[i,j,:len(chunk)]=torch.tensor(chunk); masks[i,j,:len(chunk)]=1;chunk_mask[i,j]=True
        result=dict(input_ids=ids,attention_mask=masks)
        if self.chunked:
            result['chunk_mask']=chunk_mask
        else:
            result={k:v[:,0] for k,v in result.items()}
        return result,torch.stack([item['target'] for item in items]),[item['index'] for item in items]
