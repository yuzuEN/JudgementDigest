"""One encoder and one head per run; no cross-task labels or shared checkpoints."""
from __future__ import annotations
import torch
from torch import nn
from transformers import AutoModel


class AttentionPool(nn.Module):
    def __init__(self, hidden):
        super().__init__()
        self.score = nn.Linear(hidden, 1, bias=False)

    def forward(self, states, mask):
        scores = self.score(states).squeeze(-1)
        scores = scores.masked_fill(~mask.bool(), torch.finfo(scores.dtype).min)
        weights = scores.softmax(-1) * mask.to(states.dtype)
        weights = weights / weights.sum(-1, keepdim=True).clamp_min(1e-9)
        return (weights.unsqueeze(-1) * states).sum(1)


class SingleTaskBert(nn.Module):
    def __init__(self, num_labels, model_name='google-bert/bert-base-chinese', revision=None,
                 pooling='cls', head='linear', finetune='full', last_n=2,
                 chunk_pooling='mean', dropout=.1, encoder=None):
        super().__init__()
        if pooling not in ('cls','mean','attention') or head not in ('linear','mlp'):
            raise ValueError('Unknown pooling or head')
        if finetune not in ('full','last_n','frozen') or chunk_pooling not in ('mean','attention'):
            raise ValueError('Unknown finetune or chunk pooling mode')
        self.encoder = encoder if encoder is not None else AutoModel.from_pretrained(model_name, revision=revision)
        self.pooling_name = pooling; self.finetune = finetune; self.chunk_pooling_name = chunk_pooling
        hidden = self.encoder.config.hidden_size
        self.token_attention = AttentionPool(hidden) if pooling=='attention' else None
        self.chunk_attention = AttentionPool(hidden) if chunk_pooling=='attention' else None
        if head=='linear':
            self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden,num_labels))
        else:
            self.head = nn.Sequential(nn.Linear(hidden,512),nn.ReLU(),nn.Dropout(dropout),
                                      nn.Linear(512,256),nn.ReLU(),nn.Dropout(dropout),nn.Linear(256,num_labels))
        if finetune != 'full':
            for parameter in self.encoder.parameters():
                parameter.requires_grad = False
            if finetune=='last_n':
                layers = getattr(getattr(self.encoder,'encoder',None),'layer',None)
                if layers is None or not 1 <= last_n <= len(layers):
                    raise ValueError('last_n must select existing encoder layers')
                for layer in layers[-last_n:]:
                    for parameter in layer.parameters():
                        parameter.requires_grad = True

    def train(self, mode=True):
        super().train(mode)
        if self.finetune=='frozen':
            self.encoder.eval()  # frozen features must not change due to encoder dropout
        return self

    def _pool(self, states, mask):
        if self.pooling_name=='cls':
            return states[:,0]
        if self.pooling_name=='attention':
            return self.token_attention(states,mask)
        weights = mask.to(states.dtype).unsqueeze(-1)
        return (states*weights).sum(1) / weights.sum(1).clamp_min(1)

    def forward(self, input_ids, attention_mask, chunk_mask=None):
        if input_ids.shape[-1] > self.encoder.config.max_position_embeddings:
            raise ValueError('Input exceeds encoder position embeddings; chunk or truncate explicitly')
        if input_ids.ndim == 2:
            states = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
            return self.head(self._pool(states,attention_mask))
        if input_ids.ndim != 3 or chunk_mask is None:
            raise ValueError('Chunk inputs need [batch,chunks,tokens] and chunk_mask')
        batch,chunks,tokens = input_ids.shape
        valid = chunk_mask.reshape(-1).bool()
        if not chunk_mask.bool().any(1).all():
            raise ValueError('Every document needs at least one chunk')
        ids = input_ids.reshape(-1,tokens)[valid]
        masks = attention_mask.reshape(-1,tokens)[valid]
        states = self.encoder(input_ids=ids, attention_mask=masks).last_hidden_state
        pooled = self._pool(states,masks)
        documents = pooled.new_zeros((batch*chunks,pooled.shape[-1]))
        documents[valid] = pooled
        documents = documents.reshape(batch,chunks,-1)
        if self.chunk_pooling_name=='attention':
            features = self.chunk_attention(documents,chunk_mask)
        else:
            weights = chunk_mask.to(documents.dtype).unsqueeze(-1)
            features = (documents*weights).sum(1)/weights.sum(1).clamp_min(1)
        return self.head(features)
