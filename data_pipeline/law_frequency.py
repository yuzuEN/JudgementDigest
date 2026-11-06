"""從原始法條引用建立跨法律頻率排名；不使用現行標準化結果篩選。"""

import argparse
import json
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from structure_tasks import chinese_number
from structuring import LAW_ALIASES, LAW_WHITELIST as LAW_NAMES

# 補足原有民事導向名稱表缺少的刑事法律；不推定殘缺名稱或承前指涉。
EXTRA_LAW_NAMES = {
    "毒品危害防制條例",
    "刑法施行法", "陸海空軍刑法", "組織犯罪防制條例", "性騷擾防治法",
    "槍砲彈藥刀械管制條例", "懲治走私條例", "貪污治罪條例",
    "跟蹤騷擾防制法", "妨害兵役治罪條例", "廢棄物清理法",
    "公職人員選舉罷免法", "電子遊戲場業管理條例", "醫療器材管理法",
    "護照條例", "替代役實施條例", "菸酒管理法", "妨害國幣懲治條例",
    "嚴重特殊傳染性肺炎防治及紓困振興特別條例", "多層次傳銷管理法",
    "總統副總統選舉罷免法", "化粧品衛生管理條例", "人口販運防制法",
    "國家安全法", "水污染防治法", "水土保持法", "關稅法",
    "動物傳染病防治條例", "郵政法",
}
ALIASES = {**LAW_ALIASES, "組織犯罪條例": "組織犯罪防制條例", "營業祕密法": "營業秘密法"}
NAMES = sorted(set(LAW_NAMES) | EXTRA_LAW_NAMES | set(ALIASES), key=lambda s: (-len(s), s))
LAW_ARTICLE_RE = re.compile(
    r"(?P<law>" + "|".join(map(re.escape, NAMES)) + r")第"
    r"(?P<article>[零〇○一二兩三四五六七八九十百千萬壹貳參叁肆伍陸柒捌玖拾佰仟0-9]+)條"
)
EXCLUDED_ARTICLES = frozenset({
    "道路交通管理處罰條例第86條", "組織犯罪防制條例第2條", "組織犯罪防制條例第12條",
})


def extract_law_keys(raw):
    """只接受明載法名；最長名稱優先，合併項款及條之幾，保留原順序。"""
    keys = []
    for match in LAW_ARTICLE_RE.finditer(re.sub(r"\s+", "", str(raw or ""))):
        law = ALIASES.get(match["law"], match["law"])
        key = f'{law}第{chinese_number(match["article"])}條'
        if key not in keys:
            keys.append(key)
    return keys


def flatten_labels(value):
    if isinstance(value, list):
        for item in value:
            yield from flatten_labels(item)
    elif isinstance(value, str) and value:
        yield value


def article_sort_key(key):
    law, article = key.rsplit("第", 1)
    return law, int(article[:-1])


def rank_articles(case_keys, top=200, min_cases=30):
    """排除指定三條與低頻法條，再取至多 N 類；同頻率依名稱及條號排序。"""
    frequency = Counter(key for keys in case_keys.values() for key in set(keys))
    eligible = {key: count for key, count in frequency.items()
                if key not in EXCLUDED_ARTICLES and count >= min_cases}
    ranked = sorted(eligible.items(), key=lambda item: (-item[1], article_sort_key(item[0])))
    return ranked[:top], frequency


def describe(values):
    """四分位採線性插值；標準差為母體標準差。"""
    values = sorted(values)
    def percentile(p):
        position = (len(values) - 1) * p
        left = int(position)
        right = min(left + 1, len(values) - 1)
        return values[left] + (values[right] - values[left]) * (position - left)
    return {
        "count": len(values), "sum": sum(values), "mean": statistics.mean(values),
        "std_population": statistics.pstdev(values), "min": min(values),
        "q1": percentile(.25), "median": statistics.median(values),
        "q3": percentile(.75), "max": max(values),
    }


def analyze_database(path, top=200, min_cases=30):
    case_keys = defaultdict(set)
    raw_cases = set()
    all_cases = set()
    unmatched = Counter()
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        for case, raw in connection.execute('SELECT 裁判字號, "法條（對應原始）" FROM 罪法刑'):
            all_cases.add(case)
            for label in set(flatten_labels(json.loads(raw or "[]"))):
                raw_cases.add(case)
                keys = extract_law_keys(label)
                if not keys:
                    unmatched[label] += 1
                case_keys[case].update(keys)
    ranked, frequency = rank_articles(case_keys, top, min_cases)
    if not ranked:
        raise ValueError(f"沒有出現至少 {min_cases} 件的合格法條")
    selected = {key for key, _ in ranked}
    covered = sum(bool(keys & selected) for keys in case_keys.values())
    total_pairs = sum(frequency.values())
    eligible_pairs = sum(v for k, v in frequency.items() if k not in EXCLUDED_ARTICLES)
    return {
        "database": str(path), "top": top, "min_cases": min_cases, "all_cases": len(all_cases),
        "raw_law_cases": len(raw_cases), "recognized_law_cases": sum(bool(k) for k in case_keys.values()),
        "recognized_article_types": len(frequency),
        "eligible_article_types": len(frequency.keys() - EXCLUDED_ARTICLES),
        "recognized_case_article_pairs": total_pairs, "eligible_case_article_pairs": eligible_pairs,
        "covered_cases": covered, "frequency_statistics": describe([v for _, v in ranked]),
        "selected_law_counts": dict(Counter(k.rsplit("第", 1)[0] for k, _ in ranked)),
        "frequency_bands": {label: sum(lo <= v <= hi for _, v in ranked) for label, lo, hi in (
            ("1-9", 1, 9), ("10-29", 10, 29), ("30-99", 30, 99),
            ("100-999", 100, 999), ("1000+", 1000, float("inf")))},
        "excluded": {k: frequency[k] for k in sorted(EXCLUDED_ARTICLES)},
        "ranking": [{"rank": i, "key": k, "cases": v} for i, (k, v) in enumerate(ranked, 1)],
        "boundary_ties": sorted([k for k, v in frequency.items() if k not in selected and k not in EXCLUDED_ARTICLES and v == ranked[-1][1]], key=article_sort_key),
        "unmatched_raw_labels": unmatched.most_common(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--top", type=int, default=200)
    parser.add_argument("--min-cases", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top 必須大於零")
    if args.min_cases < 1:
        parser.error("--min-cases 必須大於零")
    report = analyze_database(args.database, args.top, args.min_cases)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("frequency_statistics", "covered_cases", "frequency_bands", "boundary_ties")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
