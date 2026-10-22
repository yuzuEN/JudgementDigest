"""Tune once on one fixed fold, then evaluate locked settings with flat CV."""
import argparse
import itertools
import json
import math
from pathlib import Path
import subprocess
import sys

from .cross_validation import write_json, train_cv

CONTROL_KEYS = {'config','data_dir','output','evaluate_test','fixed_epochs','tiny_smoke',
                'check_data','print_config','seed','device'}


def combinations(grid):
    if not isinstance(grid,dict) or not grid:
        raise ValueError('Grid must be a nonempty JSON object of parameter lists')
    if set(grid) & CONTROL_KEYS:
        raise ValueError('Grid cannot change data, seed, device or training/evaluation control flags')
    if any(not isinstance(values,list) or not values for values in grid.values()):
        raise ValueError('Each grid parameter must have a nonempty list of values')
    keys=sorted(grid)
    return [dict(zip(keys,values)) for values in itertools.product(*(grid[k] for k in keys))]


def tune(data_dir, config, grid, output):
    from .train import parse_args
    data_dir=Path(data_dir).resolve(); output=Path(output).resolve()
    manifest=json.loads((data_dir/'manifest.json').read_text())
    if manifest.get('evaluation_role')=='outer_valid':
        raise ValueError('Tune on a training/validation fold, not an outer refit dataset')
    if not manifest['splits']['train']['n'] or not manifest['splits']['valid']['n']:
        raise ValueError('Tuning needs nonempty TRAIN and VALID')
    base=json.loads(Path(config).read_text()); grid=json.loads(Path(grid).read_text())
    choices=combinations(grid)
    if any(base.get(key) for key in ('fixed_epochs','tiny_smoke','check_data','print_config')):
        raise ValueError('Grid search requires formal validation-based training')
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite search: {output}')
    output.mkdir(parents=True)
    resolved=[]
    # Validate every candidate before starting any long training.
    for index,parameters in enumerate(choices,1):
        run=output/f'candidate_{index:02d}';run.mkdir()
        settings=dict(base,**parameters)
        settings.update(data_dir=str(data_dir),output=str(run),evaluate_test=False,
                        fixed_epochs=False,expected_min_label_freq=manifest['min_label_freq'])
        path=run/'candidate_config.json';write_json(path,settings)
        args=parse_args(['--config',str(path),'--no-evaluate-test'])
        expected={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
        resolved.append((parameters,run,path,expected))
    plan=dict(status='running',candidate_count=len(resolved),grid=grid,
              tuning_manifest=manifest,trials=[])
    write_json(output/'search_summary.json',plan)
    for parameters,run,path,expected in resolved:
        subprocess.run([sys.executable,'-u','-m','judgment_bert.train','--config',str(path),
                        '--no-evaluate-test'],check=True)
        metrics=json.loads((run/'metrics.json').read_text())
        actual=json.loads((run/'run_config.json').read_text())
        trained=json.loads((run/'data_manifest.json').read_text())
        if (trained!=manifest or actual!=expected or metrics.get('tiny_random_smoke')
                or metrics.get('fixed_epochs') or metrics.get('test_status')!='not_evaluated'):
            raise ValueError(f'{run.name}: unexpected training provenance')
        score=metrics['best_valid_macro_f1']
        if not isinstance(score,(int,float)) or not math.isfinite(score):
            raise ValueError(f'{run.name}: invalid validation score')
        epoch=next(e['epoch'] for e in metrics['history'] if e['valid']['macro_f1']==score)
        effective={k:v for k,v in actual.items() if k not in ('config','print_config','check_data','tiny_smoke')}
        plan['trials'].append(dict(candidate=run.name,parameters=parameters,macro_f1=score,
                                   selected_epoch=epoch,config=effective))
        write_json(output/'search_summary.json',plan)
    winner=max(plan['trials'],key=lambda trial:trial['macro_f1'])
    plan.update(status='completed',winner=winner['candidate'],best_valid_macro_f1=winner['macro_f1'],
                note='Selection uses one fixed VALID fold. Best checkpoint weights are not reused for CV. '
                     'Each CV fold retains the same maximum epochs and early-stopping rule.')
    write_json(output/'best_config.json',winner['config'])
    write_json(output/'search_summary.json',plan)
    return plan


def evaluate_locked(search, prepared, output, role='main'):
    if role not in ('main','time'):
        raise ValueError('Unknown evaluation role')
    search=Path(search).resolve();prepared=Path(prepared).resolve();output=Path(output).resolve()
    hold=search/'evaluation_hold.json'
    if hold.exists():
        return dict(status='skipped',role=role,reason=json.loads(hold.read_text())['reason'])
    selection=json.loads((search/'search_summary.json').read_text())
    plan=json.loads((prepared/'cv_manifest.json').read_text())
    if selection.get('status')!='completed':
        raise ValueError('Finish all grid candidates before evaluating locked settings')
    tuning=selection['tuning_manifest']
    if plan['source_sha256']!=tuning['source_sha256'] or plan['task']!=tuning['task'] or plan['min_label_freq']!=tuning['min_label_freq']:
        raise ValueError('Evaluation source/task differs from the tuning source/task')
    if (role=='main' and plan['mode']!='kfold') or (role=='time' and plan['mode']!='time'):
        raise ValueError('Main evaluation requires K-fold; time analysis requires time mode')
    winner=next(t for t in selection['trials'] if t['candidate']==selection['winner'])
    locked=json.loads((search/'best_config.json').read_text())
    if locked!=winner['config']:
        raise ValueError('best_config differs from the selected grid configuration')
    output.mkdir(parents=True,exist_ok=True)
    tuning_max=max(int(y) for split in ('train','valid') for y in tuning['splits'][split]['years'])
    valid_years=[int(y) for f in plan['folds'] for y in f['splits']['valid']['years']]
    provenance=dict(role=role,search=str(search),winner=selection['winner'],locked_config=locked,
                    evaluation_manifest=plan,tuning_latest_year=tuning_max,
                    time_uses_future_tuning=role=='time' and tuning_max>=min(valid_years),
                    note='Non-nested evaluation. Tuning records can recur in CV; scores may be optimistic. '
                         'Final held-out TEST is never evaluated by this command.')
    path=output/'flat_protocol.json'
    if path.exists() and json.loads(path.read_text())!=provenance:
        raise ValueError('Output already belongs to a different flat evaluation protocol')
    write_json(path,provenance)
    result=train_cv(prepared,output,search/'best_config.json')
    result['protocol']=provenance
    write_json(output/'cv_summary.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    search=commands.add_parser('tune')
    search.add_argument('--data-dir',type=Path,required=True)
    search.add_argument('--config',type=Path,required=True)
    search.add_argument('--grid',type=Path,required=True)
    search.add_argument('--output',type=Path,required=True)
    evaluation=commands.add_parser('evaluate')
    evaluation.add_argument('--search',type=Path,required=True)
    evaluation.add_argument('--prepared',type=Path,required=True)
    evaluation.add_argument('--output',type=Path,required=True)
    evaluation.add_argument('--role',choices=['main','time'],default='main')
    args=parser.parse_args()
    if args.command=='tune':
        result=tune(args.data_dir,args.config,args.grid,args.output)
    else:
        result=evaluate_locked(args.search,args.prepared,args.output,args.role)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
