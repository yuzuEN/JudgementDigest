"""Re-extract labels from matched raw judgments, preserving the frozen masked facts."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.parse import parse_qs, urlparse
import zipfile

from build_structured_review import HEADERS, build_row
from law_frequency import LAW_ARTICLE_RE, extract_law_keys
from structure_tasks import LAW_REFERENCE_NAMES, NUM, chinese_number, sentence_to_months

SOURCE_COLUMNS = {
    'case_number':'裁判字號', 'source_url':'裁判書連結', 'defendant':'被告／相對人',
    'judgment_type':'裁判種類', 'case_type':'案件類型', 'verdict':'主文',
    'facts_and_reasons':'事實及理由', 'reasons':'理由', 'facts':'事實',
    'criminal_facts':'犯罪事實', 'applicable_laws':'適用法條',
}

from law_label_validation import TRAINING_LAW_RE, training_law_key


def json_labels(value):
    return json.loads(value or '[]')


def flatten(values):
    for value in values:
        if isinstance(value,list):
            yield from flatten(value)
        else:
            yield value


def unique(values):
    return list(dict.fromkeys(value for value in values if value))


def judgment_id(url):
    for key,values in parse_qs(urlparse(url or '').query).items():
        if key.lower()=='id':
            return values[0].lower()
    return ''


def read_records(path):
    if Path(path).suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as z:
            names=[name for name in z.namelist() if name.endswith('.jsonl')]
            if len(names)!=1:
                raise ValueError('Expected exactly one JSONL in archive')
            with z.open(names[0]) as source, io.TextIOWrapper(source,encoding='utf-8-sig') as text:
                for line in text:
                    if line.strip():yield json.loads(line)
    else:
        with Path(path).open(encoding='utf-8-sig') as source:
            for line in source:
                if line.strip():yield json.loads(line)


def index_sources(connection):
    indexes=[defaultdict(list) for _ in range(3)]
    for row in connection.execute('SELECT id,case_number,judgment_date,source_url FROM judgments'):
        rowid,case,date,url=row
        indexes[0][url].append(rowid)
        if judgment_id(url):indexes[1][judgment_id(url)].append(rowid)
        indexes[2][(case,date)].append(rowid)
    return indexes


def match_source(meta,indexes):
    candidates=(indexes[0].get(meta.get('source_url'),[]),
                indexes[1].get(judgment_id(meta.get('source_url')),[]) if judgment_id(meta.get('source_url')) else [],
                indexes[2].get((meta.get('case_number'),meta.get('judgment_date')),[]))
    for method,values in zip(('exact_url','judgment_id','case_and_date'),candidates):
        if len(values)==1:return values[0],method
        if len(values)>1:return None,'ambiguous_'+method
    return None,'raw_not_found'


def refreshed_sentence(review,base_valid):
    primaries=json_labels(review.get('宣告主刑'))
    executions=json_labels(review.get('應執行刑'))
    selected=json_labels(review.get('單一刑期'))
    all_sentences=primaries+executions
    prison=any(s.startswith('有期徒刑') for s in all_sentences)
    detention=any(s.startswith('拘役') for s in all_sentences)
    special=any(s in ('死刑','無期徒刑') for s in all_sentences)
    kind=('有期徒刑併拘役' if prison and detention else '死刑或無期徒刑' if special
          else '有期徒刑' if prison else '拘役' if detention else '刑期未明')
    term={'death_penalty':False,'life_imprisonment':False,'imprisonment':0}
    eligible=base_valid and len(selected)==1 and not review.get('單一刑期風險')
    if not eligible:
        return term,False,kind,0,'no_safe_single_sentence'
    sentence=selected[0]
    if kind=='有期徒刑併拘役':
        return term,False,kind,0,'mixed_prison_and_detention'
    if sentence in ('死刑','無期徒刑'):
        term['death_penalty']=sentence=='死刑';term['life_imprisonment']=sentence=='無期徒刑'
        return term,True,kind,0,'single_special_sentence'
    if sentence.startswith('有期徒刑'):
        months=sentence_to_months(sentence)
        if months is None or months<=0:
            return term,False,kind,0,'invalid_prison_months'
        term['imprisonment']=months
        return term,True,kind,0,'single_prison_sentence'
    if sentence.startswith('拘役'):
        match=re.fullmatch(r'拘役(.+)日',sentence)
        return term,False,kind,chinese_number(match[1]) if match else 0,'detention_not_prison'
    return term,False,kind,0,'unresolved_sentence'


def apply_review(record,review,status,match_method):
    """Keep extraction evidence; only eligible tasks receive active training labels.

    Consumers must skip invalid tasks, not encode their empty labels as negatives.
    """
    result=deepcopy(record);meta=result['meta']
    base_valid=bool(review) and review.get('案件結果')=='有罪' and review.get('被告狀態')=='單被告'
    raw_charges=json_labels(review.get('罪名（原始）')) if review else []
    standard_charges=json_labels(review.get('罪名（標準化）')) if review else []
    raw_laws=json_labels(review.get('法條（對應原始）')) if review else []
    standard_laws=json_labels(review.get('法條（對應標準鍵）')) if review else []
    aligned_charges=(json_labels(review['罪名（對應標準化）']) if '罪名（對應標準化）' in review
                     else [[label] if label else [] for label in standard_charges])
    partial_charges=unique(flatten(aligned_charges))
    partial_laws=[];invalid_laws=[]
    for offense_index, group in enumerate(raw_laws):
        for law_index, raw in enumerate(group):
            key, reason = training_law_key(raw)
            if reason:
                invalid_laws.append(dict(offense_index=offense_index,law_index=law_index,raw=raw,reason=reason))
            else:
                partial_laws.append(key)
    partial_laws=unique(partial_laws)
    charge_reasons=[];law_reasons=[]
    if not base_valid:
        charge_reasons.append('not_single_defendant_conviction')
        law_reasons.append('not_single_defendant_conviction')
    # Reason-only fallback has not verified the verdict/appendix's convicted offenses.
    if review.get('罪名來源') != '主文':
        charge_reasons.append('unverified_charge_source')
        law_reasons.append('unverified_charge_source')
    if not (raw_charges and len(raw_charges)==len(aligned_charges)
            and all(aligned_charges) and all(flatten(aligned_charges))):
        charge_reasons.append('incomplete_standard_charges')
    if len(raw_laws)!=len(raw_charges):
        law_reasons.append('law_offense_slot_mismatch')
    if not raw_laws or not any(raw_laws):
        law_reasons.append('all_offense_laws_missing')
    elif not all(raw_laws):
        law_reasons.append('partial_offense_laws_missing')
    if invalid_laws:
        law_reasons.append('invalid_law_strings')
    charge_valid=not charge_reasons
    law_valid=not law_reasons
    term,term_valid,kind,days,term_reason=refreshed_sentence(review,base_valid) if review else (
        {'death_penalty':False,'life_imprisonment':False,'imprisonment':0},False,'刑期未明',0,'no_raw_judgment')
    meta.update(accusation=partial_charges if charge_valid else [],
                relevant_articles=partial_laws if law_valid else [],accusation_raw=raw_charges,
                term_of_imprisonment=term,term_task=term_valid,sentence_kind=kind,detention_days=days)
    # Money is not a prediction task here. Avoid silently carrying stale fines across versions.
    fines=json_labels(review.get('罰金')) if review else []
    execution_fines=json_labels(review.get('應執行罰金')) if review else []
    chosen=execution_fines if len(execution_fines)==1 else [x for x in fines if x]
    amount=0 if review and not chosen else None
    if len(chosen)==1:
        match=re.search(r'罰金(?:新臺幣)?(.+)元',chosen[0])
        if match:amount=chinese_number(match[1].replace(',',''))
    meta['punish_of_money']=amount
    meta['reextraction']={
        'version':'v1.2_new_extraction','status':status,'match_method':match_method,
        'fact_policy':'preserved_exactly_from_v1.1_masked_fact',
        'case_result':review.get('案件結果') if review else None,
        'defendant_status':review.get('被告狀態') if review else None,
        'task_validity':{'accusation':bool(charge_valid),'article':bool(law_valid),'imprisonment':bool(term_valid)},
        'eligibility_policy':'complete_observed_slots_verified_main_charge_parseable_laws_v1',
        'task_exclusion_reasons':{'accusation':charge_reasons,'article':law_reasons,
                                  'imprisonment':[] if term_valid else [term_reason]},
        'invalid_law_strings':invalid_laws,
        'partial_accusation':partial_charges,'partial_relevant_articles':partial_laws,
        'standard_charges_by_offense':aligned_charges,
        'raw_laws_by_offense':raw_laws,'standard_laws_by_offense':standard_laws,
        'charge_source':review.get('罪名來源') if review else None,
        'law_source':json_labels(review.get('法條來源')) if review else [],
        'law_fallback':json_labels(review.get('法條備援紀錄')) if review else [],
        'selected_sentence':json_labels(review.get('單一刑期')) if review else [],
        'sentence_source':review.get('單一刑期來源') if review else None,'term_reason':term_reason,
        'money_task':amount is not None,
    }
    return result


def refresh(input_path,raw_db,output_dir,limit=None,version='v1.2'):
    if not re.fullmatch(r'v\d+(?:\.\d+)*',version):
        raise ValueError('Expected a version such as v1.3')
    output_dir=Path(output_dir)
    if output_dir.exists():raise FileExistsError(f'Refusing to replace existing output: {output_dir}')
    output_dir.mkdir(parents=True)
    counts=Counter();changes=Counter();matches=Counter();by_year=defaultdict(Counter);results=Counter();defendants=Counter();term_reasons=Counter()
    before_labels={'accusation':Counter(),'article':Counter()};after_labels={'accusation':Counter(),'article':Counter()}
    stem=f'CAIL格式_刑事判決_2018-2025_{version}_新萃取'
    output=output_dir/(stem+'.jsonl');partial=output.with_suffix('.partial.jsonl')
    original_facts=hashlib.sha256();new_facts=hashlib.sha256()
    with closing(sqlite3.connect(Path(raw_db).resolve().as_uri()+'?mode=ro',uri=True)) as connection:
        connection.row_factory=sqlite3.Row
        indexes=index_sources(connection)
        with partial.open('w',encoding='utf-8') as data, (output_dir/'changes.csv').open('w',encoding='utf-8-sig',newline='') as cf, (output_dir/'task_exclusions.jsonl').open('w',encoding='utf-8') as problems:
            writer=csv.writer(cf);writer.writerow(['source_row','case_number','judgment_date','status','match_method','case_result','defendant_status',
                'old_accusation','new_accusation','old_articles','new_articles','old_term_task','new_term_task','old_term','new_term',
                'old_sentence_kind','new_sentence_kind','accusation_valid','article_valid'])
            for i,record in enumerate(read_records(input_path),1):
                if limit is not None and i>limit:break
                old=record['meta'];rowid,method=match_source(old,indexes);matches[method]+=1
                review={};status='raw_not_found';error=None
                if rowid is not None:
                    raw=connection.execute('SELECT '+','.join(SOURCE_COLUMNS)+' FROM judgments WHERE id=?',(rowid,)).fetchone()
                    source={target:raw[key] for key,target in SOURCE_COLUMNS.items()}
                    try:
                        values,_=build_row(source);review=dict(zip(HEADERS,values));status='reextracted'
                    except (ValueError,TypeError,IndexError,KeyError,re.error) as exc:
                        status='extraction_error';error=f'{type(exc).__name__}: {exc}'
                new=apply_review(record,review,status,method);meta=new['meta'];audit=meta['reextraction'];counts['input']+=1;counts[status]+=1
                audit['version']=version+'_new_extraction'
                counts['old_term_task']+=old.get('term_task') is True
                results[str(audit['case_result'])]+=1;defendants[str(audit['defendant_status'])]+=1;term_reasons[audit['term_reason']]+=1
                if not record['fact']==new['fact']:raise AssertionError('Frozen fact was modified')
                for digest,fact in [(original_facts,record['fact']),(new_facts,new['fact'])]:
                    digest.update(fact.encode());digest.update(b'\n')
                for task,valid in audit['task_validity'].items():
                    counts[task+'_valid']+=valid;by_year[str(old.get('year'))][task+'_valid']+=valid
                by_year[str(old.get('year'))]['input']+=1
                counts['accusation_and_article_valid']+=all(audit['task_validity'][k] for k in ('accusation','article'))
                for task,key in [('accusation','accusation'),('article','relevant_articles')]:
                    before_labels[task].update(set(old.get(key,[])));after_labels[task].update(set(meta.get(key,[])))
                    changed=set(old.get(key,[]))!=set(meta.get(key,[]))
                    changes[task+'_changed']+=changed
                    changes[task+'_changed_matched']+=changed and status=='reextracted'
                    changes[task+'_changed_both_valid']+=changed and bool(old.get(key)) and bool(meta.get(key))
                term_changed=(old.get('term_task'),old.get('term_of_imprisonment'),old.get('sentence_kind'))!=(meta.get('term_task'),meta.get('term_of_imprisonment'),meta.get('sentence_kind'))
                changes['term_changed']+=term_changed
                changes['term_changed_both_valid']+=term_changed and old.get('term_task') is True and meta['term_task']
                data.write(json.dumps(new,ensure_ascii=False,separators=(',',':'))+'\n')
                dump=lambda x:json.dumps(x,ensure_ascii=False,separators=(',',':'))
                writer.writerow([i,old.get('case_number'),old.get('judgment_date'),status,method,audit['case_result'],audit['defendant_status'],
                    dump(old.get('accusation')),dump(meta['accusation']),dump(old.get('relevant_articles')),dump(meta['relevant_articles']),
                    old.get('term_task'),meta['term_task'],dump(old.get('term_of_imprisonment')),dump(meta['term_of_imprisonment']),
                    old.get('sentence_kind'),meta['sentence_kind'],audit['task_validity']['accusation'],audit['task_validity']['article']])
                if status!='reextracted' or not all(audit['task_validity'].values()):
                    problems.write(dump({'source_row':i,'source_url':old.get('source_url'),'case_number':old.get('case_number'),
                                         'status':status,'error':error,'audit':audit})+'\n')
                if i%1000==0:print(f'Processed {i}: {dict(counts)}',flush=True)
    partial.rename(output)
    with (output_dir/'label_frequencies.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['task','label','old_cases','new_valid_cases','difference'])
        for task in ('accusation','article'):
            for label in sorted(before_labels[task].keys()|after_labels[task].keys()):
                a,b=before_labels[task][label],after_labels[task][label]
                writer.writerow([task,label,a,b,b-a])
    root=Path(__file__).resolve().parent
    hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
            ['structure_tasks.py','law_fallback.py','law_label_validation.py','driving_charge.py',
             'normalize.py','build_structured_review.py','law_frequency.py','refresh_modeldata.py']}
    commit=subprocess.run(['git','rev-parse','HEAD'],cwd=root,text=True,capture_output=True).stdout.strip()
    report=dict(version=version,input_file=str(input_path),input_sha256=hashlib.sha256(Path(input_path).read_bytes()).hexdigest(),
                raw_database=str(raw_db),raw_database_open_mode='read_only',code_commit=commit,code_sha256=hashes,
                cohort='same input rows only; excluded upstream cases are not reconstructed',
                fact_policy='unchanged masked facts; no new fact extraction or remasking',
                original_fact_sequence_sha256=original_facts.hexdigest(),new_fact_sequence_sha256=new_facts.hexdigest(),
                task_policy='independent tasks; accusation/article require main-verdict charge provenance; accusation requires complete normalization; article requires aligned nonempty offense slots and fully parseable law strings, independently of the normalization frequency whitelist; raw/partial evidence retained; invalid active labels empty and must be skipped, never negative targets; term_task gates imprisonment; no stale-label fallback',
                global_frequency_filter_reapplied=False,counts=dict(counts),changes=dict(changes),matches=dict(matches),
                case_results=dict(results),defendant_statuses=dict(defendants),term_reasons=dict(term_reasons),
                by_year={k:dict(v) for k,v in sorted(by_year.items())},
                old_class_counts={k:len(v) for k,v in before_labels.items()},new_valid_class_counts={k:len(v) for k,v in after_labels.items()},
                output_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    (output_dir/'refresh_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with zipfile.ZipFile(output_dir/(stem+'.zip'),'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for file in [output,output_dir/'refresh_report.json',output_dir/'label_frequencies.csv']:
            z.write(file,file.name)
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--raw-db',type=Path,default=Path('judgments.db'))
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--version',default='v1.2')
    args=parser.parse_args()
    if args.limit is not None and args.limit<1:parser.error('--limit must be positive')
    refresh(args.input,args.raw_db,args.output_dir,args.limit,args.version)


if __name__=='__main__':
    main()
