"""Optional additional expanding-year analysis using fixed training parameters."""
import argparse
import json
from pathlib import Path
from .cross_validation import prepare_cv, train_cv, write_json


def run_time_cv(data,task,output,config,first_year=2018,test_year=2025,min_label_freq=30,seed=42,class_list=None):
    output=Path(output).resolve()
    if output.exists():raise FileExistsError(f'Refusing to overwrite Time CV: {output}')
    output.mkdir(parents=True)
    prepared=output/'prepared'
    prepare_cv(data,task,prepared,mode='time',seed=seed,first_year=first_year,
               test_year=test_year,min_label_freq=min_label_freq,class_list=class_list)
    result=train_cv(prepared,output/'runs',config)
    result.update(analysis_role='additional_time_cv',parameter_search=False,final_test_evaluated=False,
                  note='Fixed external settings; each year uses its own VALID for checkpoint selection. '
                       'This is additional validation analysis, not an untouched final TEST.')
    write_json(output/'time_cv_summary.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--task',choices=['accusation','article'],default='accusation')
    parser.add_argument('--first-year',type=int,default=2018)
    parser.add_argument('--test-year',type=int,default=2025)
    parser.add_argument('--min-label-freq',type=int,default=30)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--class-list',type=Path)
    args=parser.parse_args()
    print(json.dumps(run_time_cv(args.data,args.task,args.output,args.config,args.first_year,
        args.test_year,args.min_label_freq,args.seed,args.class_list),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
