"""Outer expanding-year evaluation with balanced grouped inner K-fold selection."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

from .balancing import balanced_bins, balance_report
from .cross_validation import grouped_rows, write_json, train_cv
from .data import prepare


def prepare_nested(data, task, output, folds=5, seed=42, first_year=2018,
                   test_year=2025, min_label_freq=30):
    output = Path(output)
    if task not in ('accusation', 'article'):
        raise ValueError('Nested CV currently supports accusation and article')
    if first_year >= test_year or min_label_freq < 1:
        raise ValueError('Invalid years or frequency threshold')
    if output.exists():
        raise FileExistsError(f'Refusing to replace nested data: {output}')
    rows, groups = grouped_rows(data, task, first_year, test_year)
    years = sorted({r['meta']['year'] for r in rows.values() if r['meta']['year'] < test_year})
    if len(years) < 2 or not any(r['meta']['year'] == test_year for r in rows.values()):
        raise ValueError('Need at least two development years and the reserved test year')
    output.mkdir(parents=True)
    plan = dict(task=task, inner_folds=folds, seed=seed, first_year=first_year,
                reserved_test_year=test_year, min_label_freq=min_label_freq,
                source_file=Path(data).name, source_sha256=hashlib.sha256(Path(data).read_bytes()).hexdigest(),
                protocol='Inner selection only; fixed-epoch full-past refit; outer next-year evaluation once',
                outer_folds=[])
    for year in years[1:]:
        name = f'valid_{year}'; root = output/name
        # Build inner groups using past records only; future metadata cannot alter inner folds.
        rows, current_groups = grouped_rows(data, task, first_year, year)
        _, past_groups = grouped_rows(data, task, first_year, year-1)
        outer = []; purged = []
        for group in current_groups:
            past = [i for i in group if rows[i]['meta']['year'] < year]
            future_valid = [i for i in group if rows[i]['meta']['year'] == year]
            if past:
                purged.extend(future_valid)
            else:
                outer.extend(future_valid)
        if not outer:
            raise ValueError(f'No independent outer records remain for {year}')
        bins = balanced_bins(rows, past_groups, folds, seed, task)
        inner = root/'inner'; inner.mkdir(parents=True)
        inner_plan = dict(task=task, mode='balanced_inner_kfold', seed=seed, n_folds=folds,
                          min_label_freq=min_label_freq, outer_valid_year=year,
                          balance=balance_report(rows, bins, task), folds=[])
        all_past = [i for group in past_groups for i in group]
        for index, valid in enumerate(bins):
            fold_name = f'fold_{index+1:02d}'
            split = {i:'train' for i in all_past}; split.update((i,'valid') for i in valid)
            manifest = prepare(data, task, inner/fold_name, test_year=test_year,
                               min_label_freq=min_label_freq, split_by_line=split,
                               required_splits=('train','valid'))
            manifest['cross_validation'] = dict(mode='nested_inner', outer_valid_year=year,
                                                fold=fold_name, seed=seed, n_folds=folds)
            write_json(inner/fold_name/'manifest.json', manifest)
            write_json(inner/fold_name/'split_assignment.json', split)
            inner_plan['folds'].append(dict(name=fold_name, num_labels=manifest['num_labels'],
                                           splits=manifest['splits']))
        prepared_bins = [[json.loads(line)['source_line'] for line in
                          (inner/f['name']/'valid.jsonl').read_text().splitlines()]
                         for f in inner_plan['folds']]
        inner_plan['balance_after_label_filtering'] = balance_report(rows, prepared_bins, task)
        for fold in inner_plan['folds']:
            fold['validation_target_counts'] = dict(Counter(
                target for line in (inner/fold['name']/'valid.jsonl').read_text().splitlines()
                for target in json.loads(line)['target']))
        write_json(inner/'cv_manifest.json', inner_plan)
        split = {i:'train' for i in all_past}; split.update((i,'test') for i in outer)
        manifest = prepare(data, task, root/'refit', test_year=year,
                           min_label_freq=min_label_freq, split_by_line=split,
                           required_splits=('train','test'))
        manifest['evaluation_role'] = 'outer_valid'
        manifest['outer_valid_year'] = year
        write_json(root/'refit'/'manifest.json', manifest)
        write_json(root/'refit'/'split_assignment.json', split)
        plan['outer_folds'].append(dict(name=name, year=year, purged_outer_overlap_rows=len(purged),
                                        num_labels=manifest['num_labels'], splits=manifest['splits']))
        print(f'{name}: {folds} balanced inner folds; full-past train={manifest["splits"]["train"]["n"]}; '
              f'outer valid={manifest["splits"]["test"]["n"]}', flush=True)
    write_json(output/'nested_manifest.json', plan)
    return plan


def choose_inner(candidates):
    for candidate in candidates:
        if not candidate['summary']['complete']:
            raise ValueError('All inner folds must finish before selecting a configuration')
    winner = max(candidates, key=lambda c:c['summary']['validation']['macro_f1']['mean'])
    epochs = math.ceil(statistics.median(f['selected_epoch'] for f in winner['summary']['folds']))
    return dict(candidate=winner['name'], config=winner['config'], epochs=epochs,
                inner_mean_macro_f1=winner['summary']['validation']['macro_f1']['mean'],
                epoch_rule='ceil(median(inner selected epochs))',
                selection_source='inner validation only; outer validation not consulted')


def summarize_nested(prepared, output):
    prepared = Path(prepared); output = Path(output)
    plan = json.loads((prepared/'nested_manifest.json').read_text())
    results = []; missing = []
    for fold in plan['outer_folds']:
        root = output/fold['name']; metrics = root/'refit'/'metrics.json'
        if not metrics.exists():
            missing.append(fold['name']); continue
        result = json.loads(metrics.read_text())
        manifest = json.loads((root/'refit'/'data_manifest.json').read_text())
        expected = json.loads((prepared/fold['name']/'refit'/'manifest.json').read_text())
        selection = json.loads((root/'selection.json').read_text())
        if (manifest != expected or manifest.get('evaluation_role') != 'outer_valid'
                or not result.get('fixed_epochs') or result.get('tiny_random_smoke')
                or result.get('test_status') != 'evaluated' or len(result['history']) != selection['epochs']
                or any('valid' in epoch for epoch in result['history'])):
            raise ValueError(f'{fold["name"]}: invalid nested refit provenance or evaluation')
        results.append(dict(name=fold['name'], year=fold['year'], selection=selection,
                            outer_valid=result['test']))
    summary = dict(complete=not missing, expected_outer_folds=len(plan['outer_folds']),
                   completed_outer_folds=len(results), missing_folds=missing, outer_folds=results,
                   reserved_test_year=plan['reserved_test_year'], final_test_evaluated=False,
                   note='Unweighted outer-year validation mean and sample SD; fold-local label spaces.')
    if results:
        summary['outer_validation'] = {key:dict(mean=statistics.mean(r['outer_valid'][key] for r in results),
            sample_std=statistics.stdev(r['outer_valid'][key] for r in results) if len(results)>1 else None)
            for key,value in results[0]['outer_valid'].items() if isinstance(value,(float,int))}
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/'nested_summary.json', summary)
    return summary


def train_nested(prepared, output, configs, outer=None):
    prepared = Path(prepared).resolve(); output = Path(output).resolve()
    plan = json.loads((prepared/'nested_manifest.json').read_text())
    names = [f['name'] for f in plan['outer_folds']]
    if outer is not None and outer not in names:
        raise ValueError(f'Unknown outer fold: {outer}')
    settings = [json.loads(Path(config).read_text()) for config in configs]
    if not settings or any(c.get('tiny_smoke') or c.get('check_data') for c in settings):
        raise ValueError('Provide at least one formal training config, without tiny_smoke/check_data')
    for name in names:
        if outer is not None and name != outer:
            continue
        run = output/name
        if run.exists():
            raise FileExistsError(f'Refusing to overwrite nested run: {run}')
        run.mkdir(parents=True)
        candidates = []
        for index, config in enumerate(settings):
            candidate = f'candidate_{index+1:02d}'
            config = dict(config, fixed_epochs=False, evaluate_test=False)
            path = run/f'{candidate}.json'; write_json(path,config)
            summary = train_cv(prepared/name/'inner', run/candidate, path)
            candidates.append(dict(name=candidate, config=config, summary=summary))
        selection = choose_inner(candidates)
        write_json(run/'selection.json', selection)
        write_json(run/'inner_candidates.json', candidates)
        refit = run/'refit'; refit.mkdir()
        config = dict(selection['config'], data_dir=str(prepared/name/'refit'), output=str(refit),
                      epochs=selection['epochs'], fixed_epochs=True, evaluate_test=True,
                      expected_min_label_freq=plan['min_label_freq'])
        path = refit/'refit_config.json'; write_json(path,config)
        subprocess.run([sys.executable,'-m','judgment_bert.train','--config',str(path),
                        '--fixed-epochs','--evaluate-test'],check=True)
        summarize_nested(prepared,output)
    return summarize_nested(prepared,output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--data',type=Path,required=True)
    prep.add_argument('--task',choices=['accusation','article'],default='accusation')
    prep.add_argument('--output',type=Path,required=True)
    prep.add_argument('--folds',type=int,default=5)
    prep.add_argument('--seed',type=int,default=42)
    prep.add_argument('--first-year',type=int,default=2018)
    prep.add_argument('--test-year',type=int,default=2025)
    prep.add_argument('--min-label-freq',type=int,default=30)
    for command in ('train','summarize'):
        sub = commands.add_parser(command)
        sub.add_argument('--prepared',type=Path,required=True)
        sub.add_argument('--output',type=Path,required=True)
        if command=='train':
            sub.add_argument('--configs',type=Path,nargs='+',required=True)
            sub.add_argument('--outer',help='Run a single outer fold, e.g. valid_2019')
    args = parser.parse_args()
    if args.command=='prepare':
        prepare_nested(args.data,args.task,args.output,args.folds,args.seed,args.first_year,
                       args.test_year,args.min_label_freq)
    elif args.command=='train':
        print(json.dumps(train_nested(args.prepared,args.output,args.configs,args.outer),ensure_ascii=False,indent=2))
    else:
        print(json.dumps(summarize_nested(args.prepared,args.output),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
