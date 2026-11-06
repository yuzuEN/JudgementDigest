"""Task-independent preparation; fit labels on training years only."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from .analyze import iter_records

TASKS = ('accusation', 'article', 'imprisonment')
TERM_CLASSES = ['0-6', '6-12', '12-18', '18-24', '24-30', '30-36', '36-60',
                '60-120', '120+', 'life', 'death']


def labels_for(row, task):
    meta = row['meta']
    key = 'accusation' if task == 'accusation' else 'relevant_articles'
    values = meta.get(key, [])
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        raise ValueError(f'{key} must be a list of strings (law names must be retained)')
    return sorted({v.strip() for v in values if v.strip()})


def term_class(row, include_detention=False, mtl_bins=False):
    meta = row['meta']
    if include_detention and meta.get('sentence_kind') == '拘役':
        days = meta.get('detention_days')
        extraction = meta.get('reextraction', {})
        if (extraction.get('term_reason') == 'detention_not_prison'
                and extraction.get('defendant_status') == '單被告'
                and not isinstance(days, bool) and isinstance(days, (int, float))
                and math.isfinite(days) and days > 0):
            return 11
        return None
    if meta.get('term_task') is not True:
        return None
    term = meta.get('term_of_imprisonment', {})
    death, life = term.get('death_penalty') is True, term.get('life_imprisonment') is True
    if death and life:
        raise ValueError('Death and life cannot both be true')
    if death:
        return 10
    if life:
        return 9
    if meta.get('sentence_kind') != '有期徒刑':
        return None  # detention/mixed terms must not become a 0-month prison sentence
    months = term.get('imprisonment')
    if isinstance(months, bool) or not isinstance(months, (float, int)) or not math.isfinite(months) or months < 0:
        raise ValueError(f'Invalid prison months: {months!r}')
    if mtl_bins:
        months = int(months)  # Reproduce the original MTL encoder, including fractional months.
    for index, upper in enumerate((6, 12, 18, 24, 30, 36, 60)):
        if months <= upper:
            return index
    return 7 if months < 120 else 8


def filter_to_classes(records, classes, kind='multilabel'):
    """Use the training label space for every split, including legacy prepared data."""
    if kind != 'multilabel':
        return records, dict(before=len(records), after=len(records), dropped_empty=0,
                             mixed_rows=0, removed_label_occurrences=0)
    allowed=set(classes); kept=[]; removed=0; mixed=0
    for record in records:
        truth=record['true_labels']
        target=[label for label in truth if label in allowed]
        removed += sum(label not in allowed for label in truth)
        if not target:
            continue
        mixed += len(target)!=len(truth)
        kept.append(dict(record, raw_true_labels=record.get('raw_true_labels',truth),
                         true_labels=target, target=target))
    return kept, dict(before=len(records),after=len(kept),dropped_empty=len(records)-len(kept),
                      mixed_rows=mixed,removed_label_occurrences=removed)


def prepare(path, task, output, train_through=2023, valid_year=2024, test_year=2025,
            min_label_freq=30, deduplicate_facts=True, include_detention=False, mtl_bins=False, split_by_line=None,
            required_splits=('train', 'valid', 'test'), fixed_classes=None):
    if task not in TASKS:
        raise ValueError(f'Unknown task: {task}')
    if split_by_line is None and not train_through < valid_year < test_year:
        raise ValueError('Require train-through < valid-year < test-year')
    if min_label_freq < 1:
        raise ValueError('min_label_freq must be positive')
    output = Path(output)
    if any((output/f'{split}.jsonl').exists() for split in ('train','valid','test','holdout')):
        raise FileExistsError(f'Refusing to replace prepared splits: {output}')
    split_names = ('train','valid','test','holdout') if split_by_line is not None and 'holdout' in split_by_line.values() else ('train','valid','test')
    frames = defaultdict(list); skipped = Counter(); seen_documents = set()
    for line, row in iter_records(path):
        fact = row['fact'].strip()
        if not fact:
            skipped['empty_fact'] += 1; continue
        meta = row['meta']; year = meta.get('year')
        if not isinstance(year, int):
            skipped['missing_year'] += 1; continue
        split = 'train' if year <= train_through else 'valid' if year == valid_year else 'test' if year == test_year else None
        if split_by_line is not None:
            split = split_by_line.get(line)
            if split not in (None, *split_names):
                raise ValueError(f'Invalid split at source line {line}: {split}')
        if split is None:
            skipped['outside_requested_years'] += 1; continue
        case = str(meta.get('case_number') or meta.get('source_url') or f'line:{line}')
        document = str(meta.get('source_url') or f'{case}:{meta.get("judgment_date", line)}')
        if document in seen_documents:
            skipped['duplicate_document'] += 1; continue
        seen_documents.add(document)
        if task == 'imprisonment':
            target = term_class(row, include_detention=include_detention, mtl_bins=mtl_bins)
            if target is None:
                skipped['not_eligible_for_term'] += 1; continue
        else:
            target = labels_for(row, task)
            if not target:
                skipped['empty_active_task_labels'] += 1; continue
        frames[split].append(dict(id=document, case_group=case, fact=fact, true_labels=target, year=year,
                                  source_line=line, fact_source=meta.get('fact_source')))
    # Exact fact equality only; process chronologically, so future records never remove training records.
    seen_facts = set(); seen_case_groups = set(); cross_split_overlap = {}; removed = Counter(); case_removed = Counter()
    for split in split_names:
        local_facts = {hashlib.sha256(r['fact'].encode()).hexdigest() for r in frames[split]}
        cross_split_overlap[split] = len(local_facts & seen_facts)
        kept = []
        for record in frames[split]:
            digest = hashlib.sha256(record['fact'].encode()).hexdigest()
            if record['case_group'] in seen_case_groups:
                case_removed[split] += 1
            elif deduplicate_facts and digest in seen_facts:
                removed[split] += 1
            else:
                kept.append(record)
        frames[split] = kept
        seen_facts.update(local_facts)
        seen_case_groups.update(r['case_group'] for r in kept)
    frequency = Counter()
    if task == 'imprisonment':
        classes = (['0-6', '7-12', '13-18', '19-24', '25-30', '31-36',
                    '37-60', '61-119', '120+', 'life', 'death'] if mtl_bins else list(TERM_CLASSES))
        if include_detention:
            classes.append('detention')
    else:
        frequency.update(label for row in frames['train'] for label in row['true_labels'])
        if fixed_classes is not None:
            if (not isinstance(fixed_classes,list) or not fixed_classes
                    or any(not isinstance(x,str) or not x.strip() for x in fixed_classes)
                    or len(set(fixed_classes)) != len(fixed_classes)):
                raise ValueError('fixed_classes must be a nonempty unique list of labels')
            classes = list(fixed_classes)
        else:
            classes = sorted(k for k,v in frequency.items() if v >= min_label_freq)
        if not classes:
            raise ValueError('No training labels meet the frequency threshold')
    class_set = set(classes); split_info = {}
    output.mkdir(parents=True, exist_ok=True)
    for split in split_names:
        records = []; unknown_labels = Counter()
        for record in frames[split]:
            if task == 'imprisonment':
                record['target'] = record['true_labels']
            else:
                record['target'] = [x for x in record['true_labels'] if x in class_set]
                unknown_labels.update(x for x in record['true_labels'] if x not in class_set)
                if not record['target']:
                    skipped[f'{split}_without_frequent_label'] += 1; continue
                record['raw_true_labels'] = record['true_labels']
                record['true_labels'] = list(record['target'])
            records.append(record)
        frames[split] = records
        with (output/f'{split}.jsonl').open('w', encoding='utf-8') as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False)+'\n')
        split_info[split] = dict(n=len(records), years=dict(Counter(r['year'] for r in records)),
                                removed_label_occurrences=dict(unknown_labels))
    if any(not frames[k] for k in required_splits):
        raise ValueError('A split is empty; inspect requested years and task eligibility')
    manifest = dict(include_detention=include_detention, mtl_bins=mtl_bins, label_filter_policy='train_classes_all_splits_drop_empty', task=task, classes=classes, num_labels=len(classes),
                    kind='multiclass' if task=='imprisonment' else 'multilabel',
                    class_policy='fixed_source_class_list' if fixed_classes is not None else 'per_fold_train_frequency',
                    training_frequency_filter_applied=fixed_classes is None,
                    source_file=Path(path).name, source_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                    split_policy='explicit_source_lines' if split_by_line is not None else 'calendar_years',
                    train_through=None if split_by_line is not None else train_through,
                    valid_year=None if split_by_line is not None else valid_year, test_year=test_year,
                    min_label_freq=min_label_freq, training_label_frequencies=dict(frequency),
                    exact_fact_deduplication=deduplicate_facts, cross_split_exact_fact_overlap=cross_split_overlap,
                    removed_duplicate_fact_rows=dict(removed), removed_cross_split_case_rows=dict(case_removed),
                    skipped=dict(skipped), splits=split_info,
                    term_bin_note=('Original MTL: int(months); 0-6, 7-12, ..., 61-119, >=120; life/death separate' if mtl_bins else '(0,6], (6,12], ..., (36,60], (60,120), [120,infinity); zero allowed; life/death separate'))
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--task', choices=TASKS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--train-through', type=int, default=2023)
    parser.add_argument('--valid-year', type=int, default=2024)
    parser.add_argument('--test-year', type=int, default=2025)
    parser.add_argument('--min-label-freq', type=int, default=30)
    parser.add_argument('--keep-cross-split-duplicate-facts', action='store_true')
    parser.add_argument('--include-detention', action='store_true', help='Add safely extracted single-defendant detention as class 11')
    parser.add_argument('--mtl-bins', action='store_true', help='Reproduce original MTL integer-month bins')
    args = parser.parse_args()
    result = prepare(args.data, args.task, args.output, args.train_through, args.valid_year,
                     args.test_year, args.min_label_freq, not args.keep_cross_split_duplicate_facts,
                     args.include_detention, args.mtl_bins)
    print(json.dumps({k:result[k] for k in ('task','num_labels','splits','skipped','removed_duplicate_fact_rows')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
