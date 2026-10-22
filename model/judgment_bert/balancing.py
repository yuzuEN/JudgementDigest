"""Deterministic grouped balancing of multilabel targets, calendar month and row count."""
from collections import Counter
from datetime import date
import math
import random
from .data import labels_for, term_class


def features(row, task):
    meta = row['meta']
    try:
        day = date.fromisoformat(meta['judgment_date'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Balancing requires an ISO judgment_date on every development record') from exc
    if day.year != meta['year']:
        raise ValueError('judgment_date year differs from meta.year')
    labels = [str(term_class(row))] if task == 'imprisonment' else labels_for(row, task)
    return Counter({**{('label', label): 1 for label in labels}, ('month', str(day.month)): 1})


def balanced_bins(rows, groups, folds, seed, task):
    if folds < 2 or len(groups) < folds:
        raise ValueError('Need at least two folds and at least one independent group per fold')
    counters = [sum((features(rows[i], task) for i in group), Counter()) for group in groups]
    totals = sum(counters, Counter())
    family_sizes = Counter(key[0] for key in totals)
    target_size = sum(map(len, groups))/folds
    capacity = math.ceil(target_size) + max(map(len, groups))-1
    order = list(range(len(groups))); rng = random.Random(seed); rng.shuffle(order)
    # Place rare labels first; groups remain indivisible even when that prevents exact balance.
    order.sort(key=lambda i: (min(totals[key] for key in counters[i] if key[0]=='label'),
                              -len(groups[i])))
    bins = [[] for _ in range(folds)]; counts = [Counter() for _ in range(folds)]
    sizes = [0]*folds
    tie_order = list(range(folds)); rng.shuffle(tie_order)
    for index in order:
        group = groups[index]; vector = counters[index]
        candidates = [f for f in tie_order if sizes[f]+len(group) <= capacity]
        if not candidates:
            candidates = [f for f in tie_order if sizes[f] == min(sizes)]

        def cost(fold):
            value = (2*sizes[fold]*len(group)+len(group)**2)/target_size**2
            for key, amount in vector.items():
                target = max(totals[key]/folds, 1)
                value += (2*counts[fold][key]*amount+amount**2)/(target**2*family_sizes[key[0]])
            return value, sizes[fold]

        chosen = min(candidates, key=cost)
        bins[chosen].extend(group); counts[chosen].update(vector); sizes[chosen] += len(group)
    if any(not bucket for bucket in bins):
        raise ValueError('Grouped balance produced an empty fold; reduce folds or inspect large groups')
    return bins


def balance_report(rows, bins, task):
    counters = [sum((features(rows[i], task) for i in bucket), Counter()) for bucket in bins]
    totals = sum(counters, Counter())
    report = dict(method='grouped greedy normalized squared imbalance; equal family weights',
                  objectives=['multilabel target counts', 'calendar month counts', 'row count'],
                  folds=[dict(n=len(bucket), months={str(m): counter[('month',str(m))] for m in range(1,13)},
                              labels={k[1]:counter[k] for k in totals if k[0]=='label'})
                         for bucket,counter in zip(bins,counters)],
                  note='Approximate balance of source labels for the listed records; groups are never split.')
    report['row_count_range'] = [min(map(len,bins)), max(map(len,bins))]
    report['max_month_count_gap'] = max(max(c[k] for c in counters)-min(c[k] for c in counters)
                                      for k in totals if k[0]=='month')
    report['max_label_count_gap'] = max(max(c[k] for c in counters)-min(c[k] for c in counters)
                                      for k in totals if k[0]=='label')
    return report
