"""Grouped K-fold inside development years, or expanding calendar-year validation."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys

from .balancing import balanced_bins, balance_report
from .analyze import iter_records
from .data import TASKS, labels_for, prepare, term_class


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def grouped_rows(path, task, first_year, test_year):
    rows = {}; parents = {}; keys = {}

    def find(line):
        while parents[line] != line:
            parents[line] = parents[parents[line]]
            line = parents[line]
        return line

    for line, row in iter_records(path):
        meta = row['meta']; year = meta.get('year'); fact = row['fact'].strip()
        if not isinstance(year, int) or not first_year <= year <= test_year or not fact:
            continue
        eligible = term_class(row) is not None if task == 'imprisonment' else bool(labels_for(row, task))
        if not eligible:
            continue
        rows[line] = row; parents[line] = line
        case = str(meta.get('case_number') or meta.get('source_url') or f'line:{line}')
        document = str(meta.get('source_url') or f'{case}:{meta.get("judgment_date", line)}')
        for key in [('case', case), ('document', document),
                    ('fact', hashlib.sha256(fact.encode()).hexdigest())]:
            if key in keys:
                parents[find(line)] = find(keys[key])
            else:
                keys[key] = line
    groups = defaultdict(list)
    for line in rows:
        groups[find(line)].append(line)
    return rows, list(groups.values())


def assignments(rows, groups, mode, folds, seed, test_year, task='accusation'):
    # Keep earlier development data; remove later holdout duplicates once, independently of fold.
    pool = []; holdout = []; removed = []
    for group in groups:
        development = [i for i in group if rows[i]['meta']['year'] < test_year]
        test = [i for i in group if rows[i]['meta']['year'] == test_year]
        if development:
            pool.append(development); removed.extend(test)
        else:
            holdout.extend(test)
    if not holdout:
        raise ValueError('No independent holdout records remain')
    base = {line: 'test' for line in holdout}
    plans = []
    if mode in ('kfold', 'kfold_test'):
        bins = balanced_bins(rows, pool, folds, seed, task)
        for index, held_out in enumerate(bins):
            split = dict(base)
            split.update((line, 'train') for group in pool for line in group)
            if mode == 'kfold_test':
                outer = set(held_out)
                remaining = [group for group in pool if group[0] not in outer]
                if len(remaining) < 10:
                    raise ValueError('Internal VALID needs at least 10 independent training groups')
                # Select one balanced tenth for VALID; train only ONE model per outer fold.
                internal_valid = balanced_bins(rows, remaining, 10, seed+1000+index, task)[0]
                split.update((line, 'holdout') for line in holdout)
                split.update((line, 'valid') for line in internal_valid)
                split.update((line, 'test') for line in held_out)
            else:
                split.update((line, 'valid') for line in held_out)
            plans.append((f'fold_{index+1:02d}', split))
    else:
        years = sorted({rows[i]['meta']['year'] for group in pool for i in group})
        for year in years[1:]:
            split = dict(base)
            for group in pool:
                train = [i for i in group if rows[i]['meta']['year'] < year]
                valid = [i for i in group if rows[i]['meta']['year'] == year]
                split.update((i, 'train') for i in train)
                # Purge validation records connected to earlier training records.
                if not train:
                    split.update((i, 'valid') for i in valid)
            if 'train' in split.values() and 'valid' in split.values():
                plans.append((f'valid_{year}', split))
        if not plans:
            raise ValueError('Need at least two development years for time validation')
    return plans, removed


def prepare_cv(data, task, output, mode='kfold', folds=5, seed=42, first_year=2018,
               test_year=2025, min_label_freq=30, class_list=None, split_plan=None):
    if task not in TASKS or mode not in ('kfold', 'kfold_test', 'time'):
        raise ValueError('Unknown task or cross-validation mode')
    if min_label_freq < 1:
        raise ValueError('min-label-freq must be positive')
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'Refusing to replace CV directory: {output}')
    if first_year >= test_year:
        raise ValueError('first-year must precede test-year')
    fixed_classes = None
    class_metadata = None
    if class_list is not None:
        class_metadata = json.loads(Path(class_list).read_text())
        fixed_classes = class_metadata.get(task)
        if not isinstance(fixed_classes,list) or not fixed_classes:
            raise ValueError('Class list is missing this task')
        if class_metadata.get('min_source_frequency') != min_label_freq:
            raise ValueError('Class list source threshold differs from min_label_freq')
    rows, groups = grouped_rows(data, task, first_year, test_year)
    if split_plan is None:
        plans, removed = assignments(rows, groups, mode, folds, seed, test_year, task)
    else:
        source_plan = json.loads((Path(split_plan)/'cv_manifest.json').read_text())
        expected = dict(mode=mode,n_folds=folds,seed=seed,first_year=first_year,test_year=test_year,
                        source_sha256=hashlib.sha256(Path(data).read_bytes()).hexdigest())
        if mode!='kfold_test' or any(source_plan.get(k)!=v for k,v in expected.items()):
            raise ValueError('Shared split plan differs in data or split configuration')
        plans=[]
        for fold in source_plan['folds']:
            name=fold['name']
            if Path(name).name!=name:
                raise ValueError('Invalid fold name')
            split={int(k):v for k,v in json.loads((Path(split_plan)/name/'split_assignment.json').read_text()).items()}
            if not set(split)<=set(rows) or set(split.values())!={'train','valid','test','holdout'}:
                raise ValueError('Shared plan has unknown records or split roles')
            for group in groups:
                if len({split[i] for i in group if i in split})>1:
                    raise ValueError('Shared plan splits a case or identical fact across roles')
            if any((rows[i]['meta']['year']==test_year)!=(role=='holdout') for i,role in split.items()):
                raise ValueError('Shared plan violates reserved-year isolation')
            plans.append((name,split))
        development={i for i,row in rows.items() if row['meta']['year']<test_year}
        if len(plans)!=folds or len({name for name,_ in plans})!=folds:
            raise ValueError('Shared plan has an inconsistent fold count')
        if any(not development<=set(split) for _,split in plans):
            raise ValueError('Shared plan omits development records')
        test_counts=Counter(i for _,split in plans for i,role in split.items() if role=='test')
        if set(test_counts)!=development or any(n!=1 for n in test_counts.values()):
            raise ValueError('Shared plan must test each development record exactly once')
        removed=[i for i,row in rows.items() if row['meta']['year']==test_year and all(i not in split for _,split in plans)]
    output.mkdir(parents=True)
    info = dict(task=task, mode=mode, seed=seed, first_year=first_year, test_year=test_year,
                n_folds=len(plans), min_label_freq=min_label_freq,
                source_file=Path(data).name,
                source_sha256=hashlib.sha256(Path(data).read_bytes()).hexdigest(),
                grouping=['case_number', 'source_url/document', 'exact stripped fact SHA256; transitive union'],
                stratified=mode in ('kfold', 'kfold_test'), removed_holdout_overlap_rows=len(removed), folds=[])
    if split_plan is not None:
        info['shared_split_plan_task']=source_plan['task']
        info['shared_split_plan_manifest_sha256']=hashlib.sha256((Path(split_plan)/'cv_manifest.json').read_bytes()).hexdigest()
    if class_metadata is not None:
        info['fixed_class_list'] = class_metadata
        info['fixed_class_list_sha256'] = hashlib.sha256(Path(class_list).read_bytes()).hexdigest()
    if mode in ('kfold', 'kfold_test'):
        score_split = 'test' if mode == 'kfold_test' else 'valid'
        info['primary_metric_source'] = 'outer_test' if mode == 'kfold_test' else 'valid'
        if mode == 'kfold_test':
            info['internal_valid_fraction_target'] = 0.1
            info['reserved_year_split'] = 'holdout'
        info['balance'] = balance_report(rows, [[i for i,s in split.items() if s==score_split]
                                               for _,split in plans], task)
    for name, split in plans:
        manifest = prepare(data, task, output/name, test_year=test_year,
                           min_label_freq=min_label_freq, split_by_line=split, fixed_classes=fixed_classes)
        if mode == 'kfold_test':
            manifest.update(evaluation_role='outer_test', test_year=None, holdout_year=test_year,
                            checkpoint_selection='internal VALID Macro-F1 only')
        manifest['cross_validation'] = dict(mode=mode, fold=name, seed=seed,
                                            holdout_year=test_year, n_folds=len(plans))
        write_json(output/name/'manifest.json', manifest)
        write_json(output/name/'split_assignment.json', split)
        info['folds'].append(dict(name=name, num_labels=manifest['num_labels'],
                                 splits=manifest['splits']))
        print(f'{name}: labels={manifest["num_labels"]}, '+
              ', '.join(f'{s}={manifest["splits"][s]["n"]}' for s in ('train','valid','test')), flush=True)
    if mode in ('kfold', 'kfold_test'):
        prepared_bins = [[json.loads(line)['source_line'] for line in
                          (output/f['name']/(score_split+'.jsonl')).read_text().splitlines()]
                         for f in info['folds']]
        info['balance_after_label_filtering'] = balance_report(rows, prepared_bins, task)
    write_json(output/'cv_manifest.json', info)
    return info


def summarize(prepared, output):
    plan = json.loads((Path(prepared)/'cv_manifest.json').read_text())
    outer_test = plan['mode'] == 'kfold_test'
    results = []; missing = []; common_settings = None
    for fold in plan['folds']:
        name = fold['name']; path = Path(output)/name/'metrics.json'
        if not path.exists():
            missing.append(name); continue
        result = json.loads(path.read_text())
        if result.get('tiny_random_smoke') or result.get('fixed_epochs') or result.get('test_status') != ('evaluated' if outer_test else 'not_evaluated'):
            raise ValueError(f'{name}: smoke results or test evaluation cannot enter CV summary')
        if outer_test and (result.get('evaluation_role') != 'outer_test' or 'test' not in result):
            raise ValueError(f'{name}: missing independently evaluated outer TEST')
        trained_manifest = json.loads((Path(output)/name/'data_manifest.json').read_text())
        expected = json.loads((Path(prepared)/name/'manifest.json').read_text())
        if trained_manifest != expected:
            raise ValueError(f'{name}: training manifest does not match prepared fold')
        settings = json.loads((Path(output)/name/'run_config.json').read_text())
        comparable = {k:v for k,v in settings.items() if k not in ('data_dir','output','config')}
        if common_settings is not None and comparable != common_settings:
            raise ValueError('Cannot combine folds trained with different settings')
        common_settings = comparable
        best = next(epoch for epoch in result['history']
                    if epoch['valid']['macro_f1'] == result['best_valid_macro_f1'])
        entry=dict(fold=name, selected_epoch=best['epoch'], valid=best['valid'])
        if outer_test: entry['test']=result['test']
        results.append(entry)
    summary = dict(mode=plan['mode'], expected_folds=plan['n_folds'], completed_folds=len(results),
                   complete=not missing, missing_folds=missing, folds=results,
                   note='Unweighted mean and sample SD of selected validation scores; no TEST scores. '
                        'Fold label spaces are fitted independently; these are not pooled OOF metrics.')
    summary['primary_metric_source']='outer_test' if outer_test else 'valid'
    if outer_test:
        summary['note']='Unweighted mean and sample SD of untouched outer-fold TEST scores after internal VALID checkpoint selection; reserved year is not included. Fold label spaces still fit TRAIN independently.'
    if results:
        if outer_test:
            summary['test'] = {metric: dict(mean=statistics.mean(r['test'][metric] for r in results),
                sample_std=statistics.stdev(r['test'][metric] for r in results) if len(results)>1 else None)
                for metric in results[0]['test'] if isinstance(results[0]['test'][metric], (float, int))}
        summary['validation'] = {metric: dict(mean=statistics.mean(r['valid'][metric] for r in results),
            sample_std=statistics.stdev(r['valid'][metric] for r in results) if len(results)>1 else None)
            for metric in results[0]['valid'] if isinstance(results[0]['valid'][metric], (float, int))}
    Path(output).mkdir(parents=True, exist_ok=True)
    write_json(Path(output)/'cv_summary.json', summary)
    return summary


def train_cv(prepared, output, config, selected=None):
    prepared = Path(prepared).resolve(); output = Path(output).resolve()
    plan = json.loads((prepared/'cv_manifest.json').read_text())
    names = [f['name'] for f in plan['folds']]
    if selected is not None and selected not in names:
        raise ValueError(f'Unknown fold: {selected}')
    settings = json.loads(Path(config).read_text())
    if any(settings.get(key) for key in ('fixed_epochs','tiny_smoke','check_data')):
        raise ValueError('CV requires formal validation-based training, without fixed_epochs/tiny_smoke/check_data')
    settings['evaluate_test'] = plan['mode'] == 'kfold_test'
    settings['expected_min_label_freq'] = plan['min_label_freq']
    run_plan = dict(settings={k:v for k,v in settings.items() if k not in ('data_dir','output')},
                    prepared_manifest=plan)
    output.mkdir(parents=True, exist_ok=True)
    provenance = output/'cv_run_manifest.json'
    if provenance.exists() and json.loads(provenance.read_text()) != run_plan:
        raise ValueError('Output already belongs to a different CV configuration or data plan')
    if not provenance.exists():
        write_json(provenance,run_plan)
    for name in names:
        if selected is not None and name != selected:
            continue
        run = output/name
        if run.exists():
            raise FileExistsError(f'Refusing to overwrite fold run: {run}')
        run.mkdir(parents=True)
        settings.update(data_dir=str(prepared/name), output=str(run))
        write_json(run/'cv_config.json', settings)
        subprocess.run([sys.executable, '-m', 'judgment_bert.train',
                        '--config', str(run/'cv_config.json'),
                        '--evaluate-test' if settings['evaluate_test'] else '--no-evaluate-test'], check=True)
    return summarize(prepared, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--data', type=Path, required=True)
    prep.add_argument('--task', choices=TASKS, default='accusation')
    prep.add_argument('--output', type=Path, required=True)
    prep.add_argument('--mode', choices=['kfold_test', 'kfold', 'time'], default='kfold_test')
    prep.add_argument('--folds', type=int, default=5, help='K-fold count (default: 5; use 10 for ten-fold CV)')
    prep.add_argument('--seed', type=int, default=42)
    prep.add_argument('--first-year', type=int, default=2018)
    prep.add_argument('--test-year', type=int, default=2025)
    prep.add_argument('--min-label-freq', type=int, default=30)
    prep.add_argument('--split-plan', type=Path, help='Reuse another task exact source-line assignments')
    prep.add_argument('--class-list', type=Path, help='Fixed source-frequency class list; disable per-fold filtering')
    for command in ('train', 'summarize'):
        child = commands.add_parser(command)
        child.add_argument('--prepared', type=Path, required=True)
        child.add_argument('--output', type=Path, required=True)
        if command == 'train':
            child.add_argument('--config', type=Path, required=True)
            child.add_argument('--fold', help='Run one fold; omit to run all folds sequentially')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare_cv(args.data, args.task, args.output, args.mode, args.folds, args.seed,
                   args.first_year, args.test_year, args.min_label_freq, args.class_list, args.split_plan)
    elif args.command == 'train':
        print(json.dumps(train_cv(args.prepared, args.output, args.config, args.fold), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summarize(args.prepared, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
