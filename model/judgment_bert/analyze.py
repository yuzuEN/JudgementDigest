"""Measure complete, untruncated fact tokens; no model weights are loaded."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import zipfile


def extract_archive(archive, destination):
    """Extract only the JSONL and accompanying Markdown, with no archive paths."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    outputs = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if not info.filename.endswith(('.jsonl', '.md')):
                continue
            target = destination / Path(info.filename).name
            if target.exists():
                if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(z.read(info)).digest():
                    raise FileExistsError(f'Refusing to replace different file: {target}')
            else:
                target.write_bytes(z.read(info))
            outputs.append(target)
    return outputs


def iter_records(path):
    with Path(path).open(encoding='utf-8-sig') as f:
        for line_number, line in enumerate(f, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row.get('fact'), str) or not isinstance(row.get('meta'), dict):
                raise ValueError(f'Invalid fact/meta at line {line_number}')
            yield line_number, row


def describe(values):
    data = sorted(values)
    if not data:
        return {'n': 0}
    def quantile(p):
        pos = (len(data) - 1) * p
        low = math.floor(pos)
        high = math.ceil(pos)
        return data[low] + (data[high] - data[low]) * (pos - low)
    return dict(n=len(data), mean=statistics.mean(data), std_population=statistics.pstdev(data),
                min=data[0], q1=quantile(.25), median=quantile(.5), q3=quantile(.75),
                p90=quantile(.90), p95=quantile(.95), p99=quantile(.99), max=data[-1])


def length_summary(values, special_tokens=2):
    info = describe(values)
    if not values:
        return info
    info['within_limits'] = {
        str(limit): {'n': sum(n <= limit for n in values),
                     'percent': sum(n <= limit for n in values) / len(values) * 100}
        for limit in (128, 256, 512, 1024, 2048, 4096, 8192)
    }
    lost = [max(0, n - 512) for n in values]
    info['bert512'] = dict(
        over_n=sum(n > 512 for n in values),
        over_percent=sum(n > 512 for n in values) / len(values) * 100,
        dropped_content_tokens=sum(lost),
        dropped_content_percent=sum(lost) / max(1, sum(n-special_tokens for n in values)) * 100,
        mean_dropped_per_overlength=statistics.mean([n for n in lost if n]) if any(lost) else 0,
    )
    return info


def analyze(path, tokenizer, out_dir, model_id, revision=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    special = tokenizer.num_special_tokens_to_add(pair=False)
    tokenizer.model_max_length = 10**9  # measurement only: disable the 512 warning, NOT truncation
    lengths, characters, term_lengths = [], [], []
    by_year, by_source = defaultdict(list), defaultdict(list)
    cases, facts = Counter(), Counter()
    acc, art, kinds, folds = Counter(), Counter(), Counter(), Counter()
    unknown_tokens = total_content = empty_facts = term_count = 0
    group, rows = [], []
    def consume(batch):
        nonlocal unknown_tokens, total_content, empty_facts, term_count
        enc = tokenizer([row['fact'] for _, row in batch], add_special_tokens=False,
                        truncation=False, padding=False, return_attention_mask=False,
                        return_token_type_ids=False)
        for (line, row), ids in zip(batch, enc['input_ids']):
            meta = row['meta']; n = len(ids) + special
            lengths.append(n); characters.append(len(row['fact']))
            by_year[str(meta.get('year', 'missing'))].append(n)
            by_source[str(meta.get('fact_source', 'missing'))].append(n)
            if meta.get('term_task') is True:
                term_lengths.append(n); term_count += 1
            empty_facts += not bool(row['fact'].strip())
            cases[str(meta.get('case_number', ''))] += 1
            facts[hashlib.sha256(row['fact'].encode()).hexdigest()] += 1
            acc.update(set(meta.get('accusation', [])))
            art.update(set(meta.get('relevant_articles', [])))
            kinds[str(meta.get('sentence_kind', 'missing'))] += 1
            folds[str(meta.get('fold', 'missing'))] += 1
            unknown_tokens += ids.count(tokenizer.unk_token_id)
            total_content += len(ids)
            rows.append([line, meta.get('year'), meta.get('fact_source'), len(row['fact']),
                         len(ids), n, meta.get('term_task'), meta.get('fold')])
    for item in iter_records(path):
        group.append(item)
        if len(group) == 128:
            consume(group); group = []
    if group:
        consume(group)
    result = dict(
        source_file=Path(path).name, source_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        tokenizer=model_id, tokenizer_revision=revision, special_tokens=special,
        add_special_tokens=True, truncation=False, padding=False,
        character_statistics=describe(characters), token_statistics=length_summary(lengths, special),
        term_task_token_statistics=length_summary(term_lengths, special),
        by_year={k: length_summary(v, special) for k, v in sorted(by_year.items())},
        by_fact_source={k: length_summary(v, special) for k, v in sorted(by_source.items())},
        unique_cases=len(cases), duplicate_case_rows=sum(v-1 for v in cases.values()),
        unique_fact_texts=len(facts), duplicate_fact_rows=sum(v-1 for v in facts.values()),
        empty_facts=empty_facts, term_task_count=term_count,
        accusation_classes=len(acc), article_classes=len(art),
        sentence_kinds=dict(kinds), folds=dict(folds),
        unk_token_count=unknown_tokens, content_token_count=total_content,
        unk_token_percent=unknown_tokens / max(total_content, 1) * 100,
    )
    (out_dir/'fact_token_statistics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    with (out_dir/'fact_token_lengths.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['jsonl_line','year','fact_source','characters','content_tokens',
                         'tokens_including_special','term_task','fold'])
        writer.writerows(rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--data', type=Path)
    source.add_argument('--archive', type=Path)
    parser.add_argument('--extract-dir', type=Path, default=Path('data/extracted'))
    parser.add_argument('--tokenizer', default='google-bert/bert-base-chinese')
    parser.add_argument('--revision')
    parser.add_argument('--model-id', default='google-bert/bert-base-chinese')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.archive:
        files = extract_archive(args.archive, args.extract_dir)
        jsonls = [p for p in files if p.suffix == '.jsonl']
        if len(jsonls) != 1:
            parser.error('Archive must contain exactly one JSONL')
        args.data = jsonls[0]
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, revision=args.revision, use_fast=True)
    result = analyze(args.data, tokenizer, args.output, args.model_id, args.revision)
    print(json.dumps(result['token_statistics'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
