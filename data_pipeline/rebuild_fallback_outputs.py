"""Versioned structured outputs and same-cohort new-only vs fallback comparison.

Raw judgments are opened read-only. Existing output directories are never replaced.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from openpyxl import Workbook
from build_structured_review import HEADERS, SHEETS, add_sheet, build_row
from export_structured_db import create_views, quote
from refresh_modeldata import SOURCE_COLUMNS, apply_review

CODE_FILES = ('structure_tasks.py', 'law_fallback.py', 'law_label_validation.py',
              'build_structured_review.py', 'normalize.py', 'law_frequency.py',
              'driving_charge.py', 'refresh_modeldata.py', 'rebuild_fallback_outputs.py')


def dump(value):
    return json.dumps(value, ensure_ascii=False)


def rebuild(raw_db, output_dir):
    output_dir.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parent
    hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in CODE_FILES}
    counts, attempts, sources = Counter(), Counter(), Counter()
    id_hash, source_hash = hashlib.sha256(), hashlib.sha256()
    workbook = Workbook(write_only=True)
    sheets = {name: add_sheet(workbook, name) for name in SHEETS}
    routing = dict(denominator='有罪_單被告', single_execution='單一應執行刑',
                   single_declared='單一宣告刑', non_single='非單一刑期',
                   standard_gap='罪法_有值但標準化無值', raw_gap='罪法_原始無值',
                   month_gap='刑期_有值但月數無值', sentence_gap='刑期_原始無值')
    started = time.monotonic()
    with closing(sqlite3.connect(raw_db.resolve().as_uri()+'?mode=ro', uri=True)) as raw, \
            closing(sqlite3.connect(output_dir/'2018-2025_罪法刑.db')) as structured, structured, \
            (output_dir/'comparison.jsonl').open('w', encoding='utf-8') as comparisons, \
            (output_dir/'recovered_evidence.jsonl').open('w', encoding='utf-8') as evidence:
        raw.row_factory = sqlite3.Row
        structured.execute('CREATE TABLE "罪法刑" (id INTEGER PRIMARY KEY, '+
                           ','.join(quote(h)+' TEXT' for h in HEADERS)+')')
        insert = 'INSERT INTO "罪法刑" VALUES ('+','.join('?' for _ in range(len(HEADERS)+1))+')'
        query = ('SELECT id,'+','.join(SOURCE_COLUMNS)+" FROM judgments WHERE "
                 "judgment_date BETWEEN '2018-01-01' AND '2025-12-31' ORDER BY id")
        for row in raw.execute(query):
            source = {v: row[k] for k, v in SOURCE_COLUMNS.items()}
            values, flags = build_row(source)
            after = dict(zip(HEADERS, values))
            structured.execute(insert, [row['id'], *values])
            sheets['罪法刑'].append(values)
            for flag, sheet in routing.items():
                if flags[flag]:
                    sheets[sheet].append(values)
            counts['structured_rows'] += 1
            case = row['case_number']
            cohort = (flags['denominator'] and case.endswith('刑事判決')
                      and '上字' not in case and '上訴字' not in case)
            if cohort:
                counts['eligible'] += 1
                before = dict(zip(HEADERS, build_row(source, use_fallback=False)[0]))
                a = json.loads(before['法條（對應原始）'])
                b = json.loads(after['法條（對應原始）'])
                assert before['罪名（原始）'] == after['罪名（原始）']
                assert len(a) == len(b)
                assert all(not old or old == new for old, new in zip(a, b))
                id_hash.update(f'{row["id"]}\n'.encode())
                source_hash.update((dump([row['id'], source])+'\n').encode())
                gates = {}
                for name, review, groups in [('before', before, a), ('after', after, b)]:
                    counts[name+'_raw_empty'] += not any(groups)
                    counts[name+'_raw_partial'] += bool(any(groups)) and not all(groups)
                    counts[name+'_empty_slots'] += sum(not slot for slot in groups)
                    gates[name] = apply_review({'fact': '', 'meta': {}}, review, 'reextracted', 'id')['meta']['reextraction']['task_validity']
                    for task, valid in gates[name].items():
                        counts[name+'_'+task+'_gate'] += valid
                assert gates['before']['accusation'] == gates['after']['accusation']
                assert gates['before']['imprisonment'] == gates['after']['imprisonment']
                audits = json.loads(after['法條備援紀錄'])
                for audit in filter(None, audits):
                    attempts.update(audit['reasons'] or ['recovered'])
                    if audit['recovered']:
                        sources[audit['legacy_source']] += 1
                changed = a != b
                counts['recovered_cases'] += changed
                counts['recovered_slots'] += sum(not old and bool(new) for old, new in zip(a, b))
                counts['all_empty_to_nonempty'] += not any(a) and bool(any(b))
                counts['all_empty_to_complete'] += not any(a) and bool(b) and all(b)
                counts['all_empty_to_partial'] += not any(a) and bool(any(b)) and not all(b)
                counts['partial_to_complete'] += bool(any(a)) and not all(a) and all(b)
                record = dict(id=row['id'], case=case, charges=json.loads(after['罪名（原始）']),
                              before=a, after=b, sources=json.loads(after['法條來源']),
                              audits=audits, task_validity=gates)
                comparisons.write(dump(record)+'\n')
                if changed:
                    evidence.write(dump(dict(record, source=source))+'\n')
            if counts['structured_rows'] % 10000 == 0:
                print(dict(counts), round(time.monotonic()-started, 1), flush=True)
        create_views(structured)
    workbook.save(output_dir/'2018-2025_罪法刑.xlsx')
    assert all(hashlib.sha256((root/name).read_bytes()).hexdigest() == h for name, h in hashes.items())
    report = dict(counts=counts, attempt_reasons=attempts, recovered_sources=sources,
                  cohort_id_sha256=id_hash.hexdigest(), source_rows_sha256=source_hash.hexdigest(),
                  code_sha256=hashes, seconds=round(time.monotonic()-started, 2),
                  raw_database_mode='read_only', structured_id='judgments.id',
                  fallback_enabled=True, normalization_changed=False)
    (output_dir/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-db', type=Path, default=Path('judgments.db'))
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    rebuild(args.raw_db, args.output_dir)
