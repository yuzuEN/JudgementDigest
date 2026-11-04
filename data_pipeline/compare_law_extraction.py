"""唯讀比較同一判決母體的歷史與本機法條萃取；不更新模型資料。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import types

from build_structured_review import HEADERS, build_row, classify_defendants
from refresh_modeldata import SOURCE_COLUMNS
from structure_tasks import case_result, compact

ROOT = Path(__file__).resolve().parent
MODULES = ('structure_tasks', 'law_frequency', 'normalize', 'build_structured_review')


def load_extractor(revision=None, snapshot=None):
    """各版保有自己的模組全域，不修改工作目錄或 checkout。"""
    saved = {name: sys.modules.get(name) for name in MODULES}
    try:
        for name in MODULES:
            module = types.ModuleType(name)
            module.__file__ = str(ROOT / (name + '.py'))
            sys.modules[name] = module
            if revision:
                code = subprocess.check_output(
                    ['git', 'show', f'{revision}:{name}.py'], cwd=ROOT, text=True, encoding='utf-8')
            else:
                path = snapshot / (name + '.py')
                code = (path if path.exists() else ROOT / (name + '.py')).read_text(encoding='utf-8')
            exec(compile(code, module.__file__, 'exec'), module.__dict__)
        module = sys.modules['build_structured_review']
        return module.build_row, module.HEADERS
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def compare(raw_db, output_dir, snapshot=None):
    output_dir.mkdir(parents=True, exist_ok=False)
    code_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                  for name in [*(n + '.py' for n in MODULES), 'driving_charge.py',
                               'refresh_modeldata.py', 'compare_law_extraction.py']}
    versions = {'current': (build_row, HEADERS)}
    versions.update({rev: load_extractor(revision=rev) for rev in ('c733d65', 'f3adff7')})
    if snapshot:
        versions['handoff'] = load_extractor(snapshot=snapshot)
    counts, transitions = Counter(), Counter()
    cohort_hash, source_hash = hashlib.sha256(), hashlib.sha256()
    started = time.monotonic()
    connection = sqlite3.connect(raw_db.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        with (output_dir / 'comparison.jsonl').open('w', encoding='utf-8') as output:
            query = ('SELECT id,' + ','.join(SOURCE_COLUMNS) + " FROM judgments WHERE "
                     "case_number LIKE '%刑事判決' AND judgment_date BETWEEN '2018-01-01' "
                     "AND '2025-12-31' ORDER BY id")
            for raw in connection.execute(query):
                verdict = compact(raw['verdict'])
                if (case_result(verdict) != '有罪'
                        or classify_defendants(raw['defendant'], verdict) != '單被告'
                        or '上字' in raw['case_number'] or '上訴字' in raw['case_number']):
                    continue
                counts['eligible'] += 1
                source = {target: raw[key] for key, target in SOURCE_COLUMNS.items()}
                cohort_hash.update(f'{raw["id"]}\n'.encode())
                source_hash.update((json.dumps([raw['id'], source], ensure_ascii=False) + '\n').encode())
                results, states = {}, {}
                for version, (extract, headers) in versions.items():
                    values, _ = extract(source)
                    row = dict(zip(headers, values))
                    laws = json.loads(row['法條（對應原始）'])
                    standard = json.loads(row['法條（對應標準鍵）'])
                    states[version] = any(laws)
                    counts[version + '_raw_empty'] += not any(laws)
                    counts[version + '_standard_empty'] += not any(x for group in standard for x in group)
                    counts[version + '_partial_raw'] += bool(any(laws)) and not all(laws)
                    results[version] = dict(raw=laws, standard=standard,
                        charges=json.loads(row['罪名（原始）']), sources=json.loads(row['法條來源']))
                transitions[str(tuple(states[v] for v in ('c733d65', 'f3adff7', 'current')))] += 1
                tags = []
                if states['c733d65'] and not states['f3adff7']:
                    tags.append('prior_regression_fixed' if states['current'] else 'prior_regression_unfixed')
                if states['f3adff7'] and not states['current']:
                    tags.append('new_empty')
                if not states['f3adff7'] and states['current']:
                    tags.append('recovered')
                if 'handoff' in states:
                    if not states['handoff'] and states['current']:
                        tags.append('handoff_recovered')
                    if states['handoff'] and not states['current']:
                        tags.append('handoff_new_empty')
                for version in versions:
                    if version == 'current':
                        continue
                    if results[version]['raw'] != results['current']['raw']:
                        tags.append(version + '_raw_changed')
                    if results[version]['charges'] != results['current']['charges']:
                        tags.append(version + '_charges_changed')
                counts.update(tags)
                if tags:
                    output.write(json.dumps(dict(id=raw['id'], case=raw['case_number'],
                        tags=tags, results=results), ensure_ascii=False) + '\n')
                if counts['eligible'] % 10000 == 0:
                    print('processed', counts['eligible'], round(time.monotonic() - started, 1), flush=True)
    finally:
        connection.close()
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest
           for name, digest in code_hashes.items()):
        raise RuntimeError('Source code changed during comparison; rerun before reporting results')
    report = dict(counts=dict(counts), transitions=dict(transitions),
        cohort='2018–2025 有罪、單被告刑事判決；排除案號含上字／上訴字',
        database=str(raw_db.resolve()), database_mode='read_only',
        cohort_id_sha256=cohort_hash.hexdigest(), source_rows_sha256=source_hash.hexdigest(),
        code_sha256=code_hashes,
        snapshot=str(snapshot) if snapshot else None,
        seconds=round(time.monotonic() - started, 2))
    (output_dir / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-db', type=Path, default=ROOT / 'judgments.db')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, help='交接前模組快照；未提供的模組使用工作目錄版本')
    args = parser.parse_args()
    compare(args.raw_db, args.output_dir, args.snapshot)
