"""Local, reproducible shared accusation/article sample; does not train models."""
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import time

import numpy as np


def sentence_group(meta, include_detention):
    reason = meta.get('label_detail', {}).get('term_reason')
    term = meta.get('term_of_imprisonment', {})
    if (term.get('death_penalty') or term.get('life_imprisonment')
            or reason == 'single_special_sentence'
            or meta.get('sentence_kind') == '死刑或無期徒刑'):
        return None
    if reason == 'detention_not_prison' and include_detention:
        days = meta.get('detention_days')
        if meta.get('sentence_kind') == '拘役' and isinstance(days, (int, float)) and days > 0:
            return '拘役（日數保留）'
    if not meta.get('task_validity', {}).get('imprisonment'):
        return None
    if reason == 'single_prison_sentence' and meta.get('sentence_kind') == '有期徒刑':
        months = term.get('imprisonment')
        if isinstance(months, (int, float)) and months > 0:
            for ceiling, name in [(6, '01–06月'), (12, '07–12月'), (18, '13–18月'),
                                  (24, '19–24月'), (30, '25–30月'), (36, '31–36月'),
                                  (60, '37–60月'), (119, '61–119月')]:
                if months <= ceiling:
                    return name
            return '120月以上'
    return None


def waterfill(capacities, total):
    """Equal targets, capped by availability; redistribute unavailable capacity."""
    caps = np.asarray(capacities, dtype=float)
    if not 0 <= total <= caps.sum() + 1e-6:
        raise ValueError('Requested target exceeds available capacity')
    lo, hi = 0., float(caps.max(initial=0))
    for _ in range(70):
        mid = (lo + hi) / 2
        if np.minimum(caps, mid).sum() < total:
            lo = mid
        else:
            hi = mid
    return np.minimum(caps, (lo + hi) / 2)


def integer_quotas(capacities, total, rng):
    targets = waterfill(capacities, total)
    quotas = np.floor(targets).astype(int)
    order = rng.permutation(len(quotas))
    order = sorted(order, key=lambda i: targets[i] - quotas[i], reverse=True)
    for i in order[:total - int(quotas.sum())]:
        quotas[i] += 1
    assert quotas.sum() == total and np.all(quotas <= capacities)
    return quotas


def self_check():
    assert np.allclose(waterfill([2, 100, 100], 12), [2, 5, 5])
    q = integer_quotas([2, 100, 100], 13, np.random.default_rng(42))
    assert q.sum() == 13 and q[0] == 2 and max(q[1:]) - min(q[1:]) <= 1
    assert sentence_group({'label_detail': {'term_reason': 'no_safe_single_sentence'}}, True) is None
    detention = {'label_detail': {'term_reason': 'detention_not_prison'},
                 'sentence_kind': '拘役', 'detention_days': 30}
    assert sentence_group(detention, True) == '拘役（日數保留）'
    assert sentence_group(detention, False) is None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--size', type=int, default=100000)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--exclude-detention', action='store_true')
    parser.add_argument('--proposals', type=int, default=2000000)
    parser.add_argument('--min-label-frequency', type=int, default=1)
    parser.add_argument('--frequency-through-year', type=int, choices=range(2016,2026), default=2025)
    args = parser.parse_args()
    self_check()
    if args.min_label_frequency < 1:
        raise ValueError('min-label-frequency must be positive')
    if args.output.exists():
        raise FileExistsError(args.output)
    started = time.time()
    rng = np.random.default_rng(args.seed)
    labels, label_ids, records, seen = [], {}, [], set()
    filters = Counter()
    source_hash = hashlib.sha256()

    def encode(family, name):
        key = (family, name)
        if key not in label_ids:
            label_ids[key] = len(labels)
            labels.append(key)
        return label_ids[key]

    with args.source.open('rb') as f:
        for line_no, raw in enumerate(f, 1):
            source_hash.update(raw)
            row = json.loads(raw)
            m = row['meta']
            filters['source_rows'] += 1
            if not isinstance(row.get('fact'), str) or not row['fact'].strip():
                filters['excluded_fact'] += 1
                continue
            if not isinstance(m.get('criminals'), list) or len(m['criminals']) != 1:
                filters['excluded_defendants'] += 1
                continue
            validity = m.get('task_validity', {})
            charge, law = m.get('accusation'), m.get('relevant_articles')
            if not (validity.get('accusation') is True and validity.get('article') is True
                    and isinstance(charge, list) and charge and isinstance(law, list) and law
                    and all(isinstance(x, str) and x.strip() for x in charge + law)):
                filters['excluded_shared_labels'] += 1
                continue
            group = sentence_group(m, not args.exclude_detention)
            if group is None:
                filters['excluded_sentence'] += 1
                continue
            try:
                day = date.fromisoformat(m['judgment_date'])
                if day.year != m['year'] or not 2016 <= day.year <= 2025:
                    raise ValueError('year mismatch or outside range')
            except (ValueError, TypeError, KeyError):
                filters['excluded_date'] += 1
                continue
            jid = m.get('jid')
            if not isinstance(jid, str) or not jid:
                filters['excluded_missing_jid'] += 1
                continue
            if jid in seen:
                filters['excluded_duplicate_jid'] += 1
                continue
            seen.add(jid)
            features = tuple(sorted({encode('accusation', x) for x in charge}
                                    | {encode('article', x) for x in law}
                                    | {encode('sentence', group)}))
            records.append((line_no, (day.year - 2016) * 12 + day.month - 1, features))
            if len(records) % 200000 == 0:
                print('eligible', len(records), flush=True)
    del seen
    original_candidate_count = len(records)
    frequency_counts = Counter(j for record in records if 2016+record[1]//12 <= args.frequency_through_year for j in record[2])
    fixed_labels = {family: sorted(key[1] for i,key in enumerate(labels)
                                  if key[0]==family and frequency_counts[i]>=args.min_label_frequency)
                    for family in ('accusation','article')}
    if any(not values for values in fixed_labels.values()):
        raise ValueError('No classes remain in a shared task')
    allowed_ids = {i for i,key in enumerate(labels) if key[0]=='sentence' or key[1] in fixed_labels[key[0]]}
    original_labels = list(labels)
    filtered = []
    for line, month, features in records:
        features = tuple(i for i in features if i in allowed_ids)
        families = {labels[i][0] for i in features}
        if not {'accusation','article'} <= families:
            filters['excluded_after_label_frequency'] += 1
            continue
        filtered.append((line, month, features))
    positive_ids = sorted({i for _,_,features in filtered for i in features})
    remap = {old:new for new,old in enumerate(positive_ids)}
    labels = [labels[i] for i in positive_ids]
    records = [(line,month,tuple(remap[i] for i in features)) for line,month,features in filtered]
    del filtered
    assert all(set(fixed_labels[family]) == {name for f,name in labels if f==family} for family in fixed_labels)
    n = len(records)
    if args.size <= 0 or n < args.size:
        raise ValueError(f'Need {args.size} eligible rows; available {n}')
    month_ids = np.array([r[1] for r in records], dtype=np.int16)
    by_month = [np.flatnonzero(month_ids == i) for i in range(120)]
    available = np.bincount([j for r in records for j in r[2]], minlength=len(labels))
    quotas = integer_quotas(np.array(list(map(len, by_month))), args.size, rng)
    targets = np.zeros(len(labels))
    weights = np.zeros(len(labels))
    # Equal family weight: co-occurring labels and month constraints prevent exact equality.
    for family in ('accusation', 'article', 'sentence'):
        ids = [i for i, key in enumerate(labels) if key[0] == family]
        incidence = args.size * available[ids].sum() / n
        targets[ids] = waterfill(available[ids], incidence)
        weights[ids] = 1 / (len(ids) * np.maximum(targets[ids], 1) ** 2)
    # Seed with inverse-availability priorities, then optimize through month-preserving swaps.
    priorities = np.array([sum(1 / max(available[j], 1) for j in r[2]) for r in records])
    keys = np.log(np.maximum(rng.random(n), 1e-300)) / priorities
    slots, slot_month = [], []
    for month, pool in enumerate(by_month):
        k = int(quotas[month])
        chosen = pool[np.argpartition(keys[pool], len(pool) - k)[-k:]] if k else []
        slots.extend(chosen)
        slot_month.extend([month] * k)
    slots = np.array(slots, dtype=np.int32)
    selected = np.zeros(n, dtype=bool)
    selected[slots] = True
    counts = np.bincount([j for i in slots for j in records[i][2]], minlength=len(labels)).astype(float)
    initial_loss = float(np.sum(weights * (counts - targets) ** 2))
    month_slots = [np.flatnonzero(np.asarray(slot_month) == m) for m in range(120)]
    accepted = 0
    print('pool', n, 'month quota range', min(quotas), max(quotas), 'initial loss', initial_loss, flush=True)
    for iteration in range(args.proposals):
        slot = int(rng.integers(args.size))
        old = int(slots[slot])
        month = records[old][1]
        new = int(rng.choice(by_month[month]))
        if selected[new]:
            continue
        old_features, new_features = records[old][2], records[new][2]
        changes = Counter(new_features)
        changes.subtract(old_features)
        delta = sum(weights[j] * (2 * (counts[j] - targets[j]) * amount + amount * amount)
                    for j, amount in changes.items() if amount)
        if delta < -1e-14:
            selected[old] = False
            selected[new] = True
            slots[slot] = new
            for j, amount in changes.items():
                counts[j] += amount
            accepted += 1
        if (iteration + 1) % 500000 == 0:
            print('proposals', iteration + 1, 'accepted', accepted,
                  'loss', float(np.sum(weights * (counts - targets) ** 2)), flush=True)
    chosen_lines = {records[i][0] for i in slots}
    assert len(chosen_lines) == args.size
    assert np.array_equal(np.bincount(month_ids[slots], minlength=120), quotas)
    actual = np.bincount([j for i in slots for j in records[i][2]], minlength=len(labels))
    assert np.array_equal(actual, counts)
    args.output.mkdir(parents=True)
    outpath = args.output / 'shared_100k.jsonl'
    output_hash = hashlib.sha256()
    verified_months, verified_labels, verified_ids = Counter(), Counter(), set()
    fact_hashes = Counter()
    written = 0
    modified_labels = Counter()
    with args.source.open('rb') as source, outpath.open('xb') as dest:
        for line_no, raw in enumerate(source, 1):
            if line_no not in chosen_lines:
                continue
            row = json.loads(raw); m = row['meta']
            if args.min_label_frequency > 1:
                for family,field in [('accusation','accusation'),('article','relevant_articles')]:
                    original = m[field]
                    kept = [label for label in original if label in fixed_labels[family]]
                    assert kept
                    if kept != original:
                        m['sampling_original_'+field] = original
                        modified_labels[family+'_rows'] += 1
                        modified_labels[family+'_occurrences'] += len(original)-len(kept)
                    m[field] = kept
                m['sampling_label_filter'] = dict(min_source_frequency=args.min_label_frequency,
                                                frequency_years=[2016,args.frequency_through_year])
                raw = (json.dumps(row,ensure_ascii=False)+'\n').encode('utf-8')
            assert len(m['criminals']) == 1
            assert m['task_validity']['accusation'] and m['task_validity']['article']
            group = sentence_group(m, not args.exclude_detention)
            assert group is not None and m['jid'] not in verified_ids
            verified_ids.add(m['jid'])
            verified_months[m['judgment_date'][:7]] += 1
            verified_labels.update({('accusation', x) for x in m['accusation']})
            verified_labels.update({('article', x) for x in m['relevant_articles']})
            verified_labels[('sentence', group)] += 1
            fact_hashes[hashlib.sha256(row['fact'].strip().encode()).digest()] += 1
            dest.write(raw); output_hash.update(raw); written += 1
    assert written == args.size
    assert all(verified_labels[key] == actual[i] for i, key in enumerate(labels))
    assert all(verified_months[f'{2016+m//12:04d}-{m%12+1:02d}'] == quotas[m] for m in range(120))
    report = dict(source=str(args.source.resolve()), source_sha256=source_hash.hexdigest(),
                  output=str(outpath.resolve()), output_sha256=output_hash.hexdigest(),
                  seed=args.seed, requested=args.size, written=written, include_detention=not args.exclude_detention,
                  filters=dict(filters), candidate_count=n, candidate_count_before_frequency_filter=original_candidate_count,
                  min_source_label_frequency=args.min_label_frequency, frequency_years=[2016,args.frequency_through_year],
                  fixed_classes=fixed_labels, modified_active_labels=dict(modified_labels),
                  method='Exact equal year-month quotas (availability capped); inverse-frequency random initialization; greedy same-month swaps minimizing equal-family mean squared relative label deviation',
                  exclude_life_and_death=True,
                  sentence_bins='9 fixed-term MTL bins plus separate detention; life/death excluded; no conversion of detention days to prison months',
                  target_definition='Within each family, equal label incidence targets capped at candidate availability; total target incidence uses candidate mean labels per record * sample size',
                  initial_objective=initial_loss, final_objective=float(np.sum(weights * (counts-targets)**2)),
                  proposals=args.proposals, accepted_swaps=accepted,
                  months={f'{2016+m//12:04d}-{m%12+1:02d}': dict(available=len(by_month[m]),target=int(quotas[m]),selected=int(quotas[m])) for m in range(120)},
                  labels={family:{key[1]:dict(available=int(available[i]),target=round(float(targets[i]),3),selected=int(actual[i])) for i,key in enumerate(labels) if key[0]==family} for family in ('accusation','article','sentence')},
                  duplicate_fact_groups=sum(v>1 for v in fact_hashes.values()),
                  duplicate_fact_extra_rows=sum(v-1 for v in fact_hashes.values() if v>1),
                  selected_source_lines=sorted(chosen_lines),
                  limitations=['Single-sentence eligibility follows existing label_detail.term_reason; no sentence_source field exists to re-audit execution-versus-declared priority.',
                               'Joint balance is approximate, without replacement; linked/rare labels prevent exact equality. Optimization is heuristic, not a proven global optimum.',
                               'All years 2016–2025 included; no folds assigned. Existing meta.fold is inherited and must be regenerated by the model split pipeline.',
                               'Sampling intentionally changes prevalence; a natural-distribution held-out test is needed to measure population performance.',
                               'Exact duplicate facts retained across distinct judgments; group these together during subsequent data splitting.',
                               'Source task_validity is preserved: detention remains invalid for the current imprisonment task even though it is eligible for shared accusation/article sampling.'],
                  elapsed_seconds=round(time.time()-started,2))
    class_list = dict(min_source_frequency=args.min_label_frequency,
                      frequency_years=[2016,args.frequency_through_year],
                      source=str(args.source.resolve()), source_sha256=source_hash.hexdigest(),
                      source_candidate_count=original_candidate_count,
                      **fixed_labels,
                      source_frequencies={family:{name:frequency_counts[i] for i,(f,name) in enumerate(original_labels) if f==family}
                                          for family in ('accusation','article')})
    (args.output/'fixed_classes.json').write_text(json.dumps(class_list,ensure_ascii=False,indent=2)+'\n')
    (args.output/'sampling_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    import csv
    with (args.output/'label_distribution.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f); writer.writerow(['family','label','available','target','selected'])
        for family, values in report['labels'].items():
            for label, values in sorted(values.items()):
                writer.writerow([family,label,values['available'],values['target'],values['selected']])
    with (args.output/'month_distribution.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f); writer.writerow(['year_month','available','target','selected'])
        for month, values in report['months'].items():
            writer.writerow([month,values['available'],values['target'],values['selected']])
    print(json.dumps({k:report[k] for k in ['candidate_count','written','initial_objective','final_objective','elapsed_seconds']},indent=2),flush=True)


if __name__ == '__main__':
    main()
