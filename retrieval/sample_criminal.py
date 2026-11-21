"""先篩選刑事 CAIL 資料，再按主要罪名取最新案件；只輸出 JSONL，不建立索引。"""
import argparse
from collections import Counter, defaultdict
from datetime import date
import heapq
import json
from pathlib import Path


def exclusion(record):
    m = record['meta']
    if not isinstance(record.get('fact'), str) or not record['fact'].strip():
        return 'empty_fact'
    defendants = m.get('criminals')
    if (not isinstance(defendants, list) or len(defendants) != 1
            or not isinstance(defendants[0], str) or not defendants[0].strip()):
        return 'not_single_defendant'
    detail = m.get('reextraction') or m.get('label_detail') or {}
    if (m.get('reextraction') is not None and detail.get('defendant_status') != '單被告'):
        return 'not_single_defendant'
    valid = m.get('task_validity') or {}
    if not all(valid.get(k) is True for k in ('accusation', 'article')):
        return 'invalid_task'
    for key in ('accusation', 'relevant_articles'):
        labels = m.get(key)
        if not isinstance(labels, list) or not labels or not all(isinstance(x, str) and x.strip() for x in labels):
            return 'empty_labels'
    term = m.get('term_of_imprisonment') or {}
    months = term.get('imprisonment')
    death, life = term.get('death_penalty') is True, term.get('life_imprisonment') is True
    reason = detail.get('term_reason')
    prison = (valid.get('imprisonment') is True
              and reason == 'single_prison_sentence' and m.get('sentence_kind') == '有期徒刑'
              and type(months) in (int, float) and 0 < months < float('inf') and not death and not life)
    special = (valid.get('imprisonment') is True
               and reason == 'single_special_sentence' and m.get('sentence_kind') == '死刑或無期徒刑'
               and death != life and months == 0)
    days = m.get('detention_days')
    detention = (reason == 'detention_not_prison' and m.get('sentence_kind') == '拘役'
                 and type(days) is int and days > 0 and months == 0 and not death and not life)
    if not (prison or special or detention):
        return 'not_single_sentence'
    if 'selected_sentence' in detail and len(detail['selected_sentence'] or []) != 1:
        return 'not_single_sentence'
    try:
        date.fromisoformat(m['judgment_date'])
    except (KeyError, TypeError, ValueError):
        return 'invalid_date'
    return None


def sample(source: Path, out: Path, per_charge=2000):
    if per_charge < 1:
        raise ValueError('per_charge 必須大於 0')
    report_path = out.with_suffix('.report.json')
    if out.exists() or report_path.exists():
        raise FileExistsError('輸出已存在，請指定新的 --out 路徑')
    heaps = defaultdict(list)
    counts, eligible = Counter(), Counter()
    with source.open(encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            record = json.loads(line)
            counts['source_rows'] += 1
            reason = exclusion(record)
            if reason:
                counts[reason] += 1
                continue
            m = record['meta']
            charge = m['accusation'][0]
            eligible[charge] += 1
            item = (m['judgment_date'], line_no)
            heap = heaps[charge]
            if len(heap) < per_charge:
                heapq.heappush(heap, item)
            else:
                heapq.heappushpop(heap, item)
    keep = {n for heap in heaps.values() for _, n in heap}
    if not keep:
        raise ValueError(f'沒有符合條件的資料：{dict(counts)}')
    out.parent.mkdir(parents=True, exist_ok=True)
    with source.open(encoding='utf-8') as src, out.open('x', encoding='utf-8') as dst:
        for line_no, line in enumerate(src, 1):
            if line_no in keep:
                record = json.loads(line)
                record['meta'].setdefault('retrieval_source_line', line_no)
                dst.write(json.dumps(record, ensure_ascii=False) + '\n')
    report = dict(source=str(source.resolve()), per_charge=per_charge, selected=len(keep),
                  counts=dict(counts), eligible_by_charge=dict(sorted(eligible.items())),
                  selected_by_charge={k: len(v) for k, v in sorted(heaps.items())},
                  policy='主要罪名（第一個罪名）分組，日期較新優先；同日以來源行號較大者優先',
                  limitations=['舊版資料以 criminals 單一姓名與既有單一刑期標記判定，未重新解析全文。',
                               '刑期條件為有效單一刑期或單一拘役；拘役不要求 imprisonment 有效。排除僅罰金案件。'])
    with report_path.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--per-charge', type=int, default=2000)
    args = parser.parse_args()
    report = sample(args.data, args.out, args.per_charge)
    print(f"已抽取 {report['selected']:,} 件、{len(report['selected_by_charge'])} 個主要罪名 → {args.out}")


if __name__ == '__main__':
    main()
