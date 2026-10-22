"""Evaluate VALID-selected CV checkpoints on the same held-out year, without training."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import statistics


def read_json(path):
    return json.loads(Path(path).read_text())


def test_plan(prepared):
    prepared = Path(prepared)
    plan = read_json(prepared / 'cv_manifest.json')
    filename = 'holdout.jsonl' if plan.get('mode') == 'kfold_test' else 'test.jsonl'
    reference = None
    result = []
    for fold in plan['folds']:
        name = fold['name']
        manifest = read_json(prepared / name / 'manifest.json')
        raw = (prepared / name / filename).read_bytes()
        signature = (manifest['classes'], hashlib.sha256(raw).hexdigest())
        if reference is not None and signature != reference:
            raise ValueError('TEST records and label spaces must match across all folds')
        reference = signature
        rows = [json.loads(line) for line in raw.splitlines()]
        if not rows or any(row['year'] != plan['test_year'] for row in rows):
            raise ValueError('TEST must contain only the reserved test year')
        result.append(dict(name=name, filename=filename, manifest=manifest, test_sha256=signature[1], n=len(rows)))
    if len(result) < 2:
        raise ValueError('Need at least two folds')
    return plan, result


def run(prepared, runs, output):
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoTokenizer
    from .cross_validation import write_json
    from .data import filter_to_classes
    from .encoding import FactDataset, Collator
    from .model import SingleTaskBert
    from .train import evaluate, format_metrics, resolve_device

    prepared, runs, output = map(Path, (prepared, runs, output))
    if output.exists():
        raise FileExistsError(output)
    summary = read_json(runs / 'cv_summary.json')
    plan, folds = test_plan(prepared)
    if not summary['complete'] or summary['completed_folds'] != len(folds):
        raise ValueError('All CV training and validation must finish before TEST evaluation')
    # Preflight every checkpoint before evaluating any model.
    for fold in folds:
        folder = runs / fold['name']
        metrics = read_json(folder / 'metrics.json')
        if metrics.get('tiny_random_smoke') or metrics.get('fixed_epochs'):
            raise ValueError('Formal VALID-selected checkpoints required')
        if metrics.get('test_status') != ('evaluated' if plan.get('mode')=='kfold_test' else 'not_evaluated'):
            raise ValueError('Expected checkpoints selected without TEST evaluation')
        if plan.get('mode')=='kfold_test' and metrics.get('evaluation_role')!='outer_test':
            raise ValueError('Expected outer TEST evaluation before reserved-year scoring')
        if read_json(folder / 'data_manifest.json') != fold['manifest']:
            raise ValueError('Training manifest differs from prepared data')
        if not (folder / 'best.pt').is_file():
            raise FileNotFoundError(folder / 'best.pt')
    output.mkdir(parents=True)
    results = []
    for fold in folds:
        name = fold['name']; folder = runs / name; manifest = fold['manifest']
        config = read_json(folder / 'run_config.json')
        training = read_json(folder / 'metrics.json')
        selected_epoch = next(item['epoch'] for item in training['history']
                              if item['valid']['macro_f1'] == training['best_valid_macro_f1'])
        rows = [json.loads(line) for line in (prepared / name / fold['filename']).read_text().splitlines()]
        rows, filtering = filter_to_classes(rows, manifest['classes'], manifest['kind'])
        if len(rows) != fold['n']:
            raise ValueError('Prepared TEST unexpectedly changed during label filtering')
        tokenizer = AutoTokenizer.from_pretrained(str(folder / 'tokenizer'), local_files_only=True)
        model = SingleTaskBert(manifest['num_labels'], config['model'], config.get('revision'),
                              config['pooling'], config['head'], config['finetune'], config['last_n'],
                              config.get('chunk_pooling', 'mean'), dropout=config['dropout'])
        model.load_state_dict(torch.load(folder / 'best.pt', map_location='cpu', weights_only=True))
        device = resolve_device(config['device']); model.to(device)
        dataset = FactDataset(rows, tokenizer, manifest['classes'], manifest['kind'],
                              config['max_length'], config['long_text'],
                              config.get('overlap', 128), config.get('max_chunks', 0))
        loader = DataLoader(dataset, batch_size=config['batch_size'], shuffle=False,
                            collate_fn=Collator(tokenizer.pad_token_id, config['long_text'] == 'chunk'))
        scores = evaluate(model, loader, device, rows, manifest, config['threshold'], config['precision'], require_one=True)
        result = dict(fold=name, selected_epoch=selected_epoch, selection_source='VALID Macro-F1 only',
                      checkpoint=str((folder / 'best.pt').resolve()), test_year=plan['test_year'],
                      test_n=len(rows), test_sha256=fold['test_sha256'],
                      threshold=config['threshold'], prediction_policy='at_least_one', label_filtering=filtering, test=scores)
        write_json(output / (name + '.json'), result); results.append(result)
        print(name + ' ' + format_metrics('TEST', scores), flush=True)
        del model, loader, dataset
        gc.collect()
        if device.type == 'mps': torch.mps.empty_cache()
    aggregate = {key: dict(mean=statistics.mean(item['test'][key] for item in results),
                           sample_std=statistics.stdev(item['test'][key] for item in results))
                 for key, value in results[0]['test'].items() if isinstance(value, (float, int))}
    result = dict(complete=True, evaluated_folds=len(results), test_year=plan['test_year'],
                  test_n=folds[0]['n'], num_labels=len(folds[0]['manifest']['classes']),
                  test=aggregate, folds=results,
                  note=f'Mean and sample SD across {len(results)} trained models on the same held-out TEST; these are not independent test sets. No selection by TEST and no ensemble evaluation.')
    write_json(output / 'test_summary.json', result)
    lines = [f'# {plan["test_year"]} TEST results', '',
             'Each checkpoint was selected by its own VALID Macro-F1. Final scores below use the same held-out TEST.', '',
             '| Metric | Mean | Sample SD |', '|---|---:|---:|']
    for key, value in aggregate.items():
        if key != 'unseen_true_label_occurrences':
            lines.append(f'| {key} | {value["mean"]:.2%} | {value["sample_std"]:.2%} |')
    lines += ['', result['note'], '']
    (output / 'TEST_RESULTS.md').write_text('\n'.join(lines))
    print(json.dumps(result['test'], indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('prepared', 'runs', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    run(args.prepared, args.runs, args.output)
