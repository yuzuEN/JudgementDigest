"""Main model entry: fixed best parameters -> outer-fold TEST with internal VALID -> optional Time CV."""
import argparse
import json
from pathlib import Path

from judgment_bert.cross_validation import prepare_cv, train_cv, write_json


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('configs/accusation_experiment.json'))
    parser.add_argument('--data',type=Path)
    parser.add_argument('--class-list',type=Path)
    parser.add_argument('--split-plan',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--folds',type=int)
    parser.add_argument('--epochs',type=int)
    parser.add_argument('--device')
    parser.add_argument('--precision',choices=['fp32','fp16','bf16'])
    parser.add_argument('--time-cv',action=argparse.BooleanOptionalAction,default=None)
    parser.add_argument('--print-config',action='store_true')
    args=parser.parse_args(argv)
    try:
        settings=json.loads(args.config.read_text())
    except (OSError,ValueError) as exc:
        parser.error(f'Cannot read experiment config: {exc}')
    if not isinstance(settings,dict):parser.error('Experiment config must be a JSON object')
    allowed={'data','output','training_config','task','folds','epochs','precision','time_cv',
             'first_year','test_year','min_label_freq','seed','device','class_list','split_plan'}
    if set(settings)-allowed:
        parser.error(f'Unknown experiment keys: {sorted(set(settings)-allowed)}')
    missing=allowed-{'time_cv','precision','device','class_list','split_plan'}-set(settings)
    if missing:parser.error(f'Missing experiment keys: {sorted(missing)}')
    for key in ('data','output','folds','epochs','precision','time_cv','device','class_list','split_plan'):
        value=getattr(args,key)
        if value is not None:settings[key]=str(value) if isinstance(value,Path) else value
    settings.setdefault('time_cv',False)
    settings.setdefault('precision','fp32')
    settings.setdefault('device','auto')
    if not isinstance(settings['time_cv'],bool):parser.error('time_cv must be a boolean')
    for key in ('folds','epochs','first_year','test_year','min_label_freq','seed'):
        if isinstance(settings[key],bool) or not isinstance(settings[key],int):
            parser.error(f'{key} must be an integer')
    if settings['first_year']>=settings['test_year'] or settings['min_label_freq']<1:
        parser.error('Invalid year range or label frequency')
    if settings['folds']<2 or settings['epochs']<1:parser.error('folds >=2 and epochs >=1 required')
    if settings['precision'] not in ('fp32','fp16','bf16'):parser.error('Invalid precision')
    return settings,args.print_config


def run_experiment(settings):
    output=Path(settings['output']).resolve();data=Path(settings['data']).resolve()
    training=json.loads(Path(settings['training_config']).read_text())
    if any(training.get(key) for key in ('tiny_smoke','fixed_epochs','check_data','print_config')):
        raise ValueError('Main experiment requires formal validation-based training')
    if not data.is_file():raise FileNotFoundError(f'Source data not found: {data}')
    if output.exists():raise FileExistsError(f'Refusing to overwrite experiment: {output}')
    output.mkdir(parents=True)
    training.update(epochs=settings['epochs'],precision=settings['precision'],device=settings.get('device','auto'),seed=settings['seed'],expected_min_label_freq=settings['min_label_freq'],evaluate_test=False)
    config=output/'training_config.json';write_json(config,training)
    write_json(output/'experiment_config.json',settings)

    # Grid search completed on 2018 fold 01: encoder_lr=2e-5, dropout=0.1.
    # Disabled by default; rerun manually only when a new tuning experiment is intended:
    # from judgment_bert.grid_search import tune
    # tune(tuning_fold, settings['training_config'], 'configs/accusation_grid.json', search_output)

    prepared=output/'prepared_main'
    prepare_cv(data,settings['task'],prepared,mode='kfold_test',folds=settings['folds'],seed=settings['seed'],
               first_year=settings['first_year'],test_year=settings['test_year'],
               min_label_freq=settings['min_label_freq'], class_list=settings.get('class_list'), split_plan=settings.get('split_plan'))
    primary=train_cv(prepared,output/'main',config)
    if not primary['complete']:
        raise RuntimeError('Main outer TEST evaluation is incomplete; Time CV will not run')
    result=dict(main_test=primary,time_cv_enabled=settings['time_cv'],final_test_evaluated=False)
    write_json(output/'experiment_summary.json',result)

    # Additional analysis is called only AFTER all primary outer TEST results have been saved.
    if settings['time_cv']:
        from judgment_bert.time_cv import run_time_cv
        result['time_cv']=run_time_cv(data,settings['task'],output/'time_cv',config,
            first_year=settings['first_year'],test_year=settings['test_year'],
            min_label_freq=settings['min_label_freq'],seed=settings['seed'],class_list=settings.get('class_list'))
        write_json(output/'experiment_summary.json',result)
    return result


def main():
    settings,print_only=parse_args()
    if print_only:
        print(json.dumps(settings,ensure_ascii=False,indent=2));return
    print(json.dumps(run_experiment(settings),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
