"""Frozen-fact re-extraction must not silently retain old labels or mix sentence tasks."""
import json
from copy import deepcopy
from contextlib import closing, redirect_stdout
import hashlib
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from build_structured_review import HEADERS, build_row
from refresh_modeldata import SOURCE_COLUMNS, apply_review, match_source, read_records, refresh, refreshed_sentence, training_law_key


def base_record():
    return {'fact':'已遮蔽的××事實，原樣保留。','meta':{
        'accusation':['舊罪名'],'accusation_raw':['舊寫法'],'relevant_articles':['舊法第1條'],
        'term_task':True,'term_of_imprisonment':{'death_penalty':False,'life_imprisonment':False,'imprisonment':99},
        'sentence_kind':'有期徒刑','fold':7}}


def review():
    return {'案件結果':'有罪','被告狀態':'單被告','罪名來源':'主文',
            '罪名（原始）':json.dumps(['詐術取財罪']),'罪名（標準化）':json.dumps(['詐欺罪']),
            '法條（對應原始）':json.dumps([['刑法第339條第1項']]),
            '法條（對應標準鍵）':json.dumps([['刑法第339條']]),
            '宣告主刑':json.dumps(['有期徒刑參月']),'應執行刑':'[]',
            '單一刑期':json.dumps(['有期徒刑參月']),'單一刑期來源':'宣告刑','單一刑期風險':''}


class TestRefresh(unittest.TestCase):
    def test_new_labels_and_sentence_preserve_frozen_fact_and_original_record(self):
        old=base_record(); original=deepcopy(old)
        new=apply_review(old,review(),'reextracted','exact_url')
        self.assertEqual(old,original)
        self.assertEqual(new['fact'],old['fact'])
        self.assertEqual(new['meta']['fold'],7)
        self.assertEqual(new['meta']['accusation'],['詐欺罪'])
        self.assertEqual(new['meta']['relevant_articles'],['刑法第339條'])
        self.assertEqual(new['meta']['term_of_imprisonment']['imprisonment'],3)
        self.assertTrue(new['meta']['term_task'])

    def test_missing_raw_judgment_never_silently_falls_back_to_old_labels(self):
        new=apply_review(base_record(),{},'raw_not_found','raw_not_found')
        self.assertEqual(new['meta']['accusation'],[])
        self.assertEqual(new['meta']['relevant_articles'],[])
        self.assertFalse(new['meta']['term_task'])
        self.assertEqual(new['meta']['reextraction']['status'],'raw_not_found')

    def test_missing_standard_article_keeps_matched_law_and_other_tasks(self):
        r=review();r['法條（對應標準鍵）']='[[""]]'
        new=apply_review(base_record(),r,'reextracted','exact_url')
        self.assertEqual(new['meta']['relevant_articles'],['刑法第339條'])
        self.assertTrue(new['meta']['reextraction']['task_validity']['article'])
        self.assertEqual(new['meta']['accusation'],['詐欺罪'])
        self.assertTrue(new['meta']['term_task'])

    def test_outside_whitelist_law_is_retained_with_known_law(self):
        from normalize import normalize_law_label
        outside='著作權法第九十三條第1項'
        self.assertEqual(normalize_law_label(outside),'')
        r=review()
        r['法條（對應原始）']=json.dumps([['刑法第339條第1項',outside]])
        r['法條（對應標準鍵）']=json.dumps([['刑法第339條','']])
        new=apply_review(base_record(),r,'reextracted','exact_url')
        self.assertEqual(new['meta']['relevant_articles'],['刑法第339條','著作權法第93條'])
        self.assertEqual(new['meta']['reextraction']['raw_laws_by_offense'],json.loads(r['法條（對應原始）']))

    def test_unrecognized_format_is_evidence_not_a_training_label(self):
        r=review();r['法條（對應原始）']='[["新法第14條"]]';r['法條（對應標準鍵）']='[[""]]'
        new=apply_review(base_record(),r,'reextracted','exact_url')
        self.assertEqual(new['meta']['relevant_articles'],[])
        self.assertEqual(new['meta']['reextraction']['raw_laws_by_offense'],[['新法第14條']])
        self.assertFalse(new['meta']['reextraction']['task_validity']['article'])
        self.assertEqual(new['meta']['reextraction']['invalid_law_strings'][0]['reason'],
                         'unrecognized_law_name_or_format')

    def test_unmatched_offense_does_not_clear_other_matched_laws(self):
        r=review();r['罪名（原始）']=json.dumps(['詐術取財罪','另一罪'])
        r['法條（對應原始）']=json.dumps([['刑法第339條第1項'],[]])
        r['法條（對應標準鍵）']=json.dumps([['刑法第339條'],[]])
        new=apply_review(base_record(),r,'reextracted','exact_url')
        audit=new['meta']['reextraction']
        self.assertEqual(new['meta']['relevant_articles'],[])
        self.assertFalse(audit['task_validity']['article'])
        self.assertEqual(audit['partial_relevant_articles'],['刑法第339條'])
        self.assertEqual(audit['raw_laws_by_offense'],[['刑法第339條第1項'],[]])
        self.assertIn('partial_offense_laws_missing',audit['task_exclusion_reasons']['article'])

    def test_complete_multiple_offenses_are_valid_independent_of_charge_normalization(self):
        r=review();r['罪名（原始）']=json.dumps(['詐術取財罪','未知罪名'])
        r['罪名（對應標準化）']=json.dumps([['詐欺罪'],[]])
        r['法條（對應原始）']=json.dumps([['刑法第339條第1項'],['著作權法第93條']])
        new=apply_review(base_record(),r,'reextracted','exact_url')['meta']
        self.assertTrue(new['reextraction']['task_validity']['article'])
        self.assertFalse(new['reextraction']['task_validity']['accusation'])
        self.assertEqual(new['relevant_articles'],['刑法第339條','著作權法第93條'])
        self.assertEqual(new['reextraction']['partial_accusation'],['詐欺罪'])

    def test_invalid_reference_never_becomes_a_negative_or_partial_active_answer(self):
        for raw in ('同條例第10條第2項','前揭條例第10條第1項','條例第八十三條第一項',
                    '又犯性騷擾防治法第二十五條第一項','核與刑法第19條第1項',
                    '刑法第320條第0項','刑法第320條其他文字',''):
            with self.subTest(raw=raw):
                r=review();r['法條（對應原始）']=json.dumps([['刑法第339條第1項',raw]])
                new=apply_review(base_record(),r,'reextracted','exact_url')['meta'];audit=new['reextraction']
                self.assertFalse(audit['task_validity']['article'])
                self.assertEqual(new['relevant_articles'],[])
                self.assertEqual(audit['partial_relevant_articles'],['刑法第339條'])
                self.assertEqual(audit['raw_laws_by_offense'],[['刑法第339條第1項',raw]])
                self.assertEqual(audit['standard_laws_by_offense'],[['刑法第339條']])
                self.assertEqual(audit['invalid_law_strings'][0]['law_index'],1)
                self.assertEqual(new['accusation'],['詐欺罪'])

    def test_parseable_citation_keeps_existing_main_article_granularity(self):
        for raw,key in [('刑法第三百三十九條之四第一項第二款','刑法第339條'),
                        ('著作權法第九十三條','著作權法第93條'),
                        ('組織犯罪條例第3條第1項','組織犯罪防制條例第3條')]:
            self.assertEqual(training_law_key(raw),(key,None))

    def test_unverified_fallback_retains_evidence_but_excludes_both_label_tasks(self):
        for source in ('理由／事實備援','主文刑期＋理由／事實正式罪名',''):
            with self.subTest(source=source):
                r=review();r['罪名來源']=source
                new=apply_review(base_record(),r,'reextracted','exact_url')['meta'];audit=new['reextraction']
                self.assertEqual(new['accusation'],[])
                self.assertEqual(new['relevant_articles'],[])
                self.assertEqual(audit['partial_accusation'],['詐欺罪'])
                self.assertEqual(audit['partial_relevant_articles'],['刑法第339條'])
                for task in ('accusation','article'):
                    self.assertFalse(audit['task_validity'][task])
                    self.assertIn('unverified_charge_source',audit['task_exclusion_reasons'][task])
                self.assertTrue(new['term_task'])  # Independent main-verdict sentence remains usable.

    def test_adopted_prosecution_attachment_is_not_reason_only_charge_fallback(self):
        r=review();r['法條來源']=json.dumps(['法院引用附件（適用法條）'])
        new=apply_review(base_record(),r,'reextracted','exact_url')['meta']
        self.assertTrue(new['reextraction']['task_validity']['article'])
        self.assertTrue(new['reextraction']['task_validity']['accusation'])

    def test_appendix_reason_fallback_is_retained_without_training_lighter_offense(self):
        # 112審簡442等案的失敗模式：理由有兩罪，尚未解析主文引用的附表。
        values,_=build_row({'被告／相對人':'甲某',
            '主文':'甲某犯如附表所示之罪，各處如附表所示之刑。',
            '理由':'核被告所為，係犯刑法第339條之4第1項第2款之三人以上共同詐欺取財罪、'
                   '洗錢防制法第14條第1項之一般洗錢罪。'})
        r=dict(zip(HEADERS,values))
        self.assertEqual(r['罪名來源'],'理由／事實備援')
        new=apply_review(base_record(),r,'reextracted','exact_url')['meta'];audit=new['reextraction']
        self.assertEqual(new['accusation'],[])
        self.assertEqual(new['relevant_articles'],[])
        self.assertEqual(audit['partial_accusation'],['詐欺罪','洗錢罪'])
        self.assertEqual(audit['raw_laws_by_offense'],
                         [['刑法第339條之4第1項第2款'],['洗錢防制法第14條第1項']])

    def test_all_empty_and_misaligned_slots_have_distinct_reasons(self):
        for raw,reason in [([[],[]],'all_offense_laws_missing'),
                           ([['刑法第339條']],'law_offense_slot_mismatch')]:
            r=review();r['罪名（原始）']=json.dumps(['詐欺','竊盜']);r['法條（對應原始）']=json.dumps(raw)
            audit=apply_review(base_record(),r,'reextracted','exact_url')['meta']['reextraction']
            self.assertFalse(audit['task_validity']['article'])
            self.assertIn(reason,audit['task_exclusion_reasons']['article'])

    def test_standard_label_alone_cannot_supply_a_missing_pair(self):
        r=review();r['法條（對應原始）']='[[]]'
        new=apply_review(base_record(),r,'reextracted','exact_url')
        self.assertEqual(new['meta']['relevant_articles'],[])

    def test_misaligned_offense_groups_are_not_valid_pairs(self):
        r=review();r['罪名（原始）']='[]'
        new=apply_review(base_record(),r,'reextracted','exact_url')
        self.assertFalse(new['meta']['reextraction']['task_validity']['article'])

    def test_unpaired_law_for_an_offense_is_not_a_complete_label(self):
        r=review();r['法條（對應原始）']='[[]]';r['法條（對應標準鍵）']='[[]]'
        new=apply_review(base_record(),r,'reextracted','exact_url')
        self.assertFalse(new['meta']['reextraction']['task_validity']['article'])

    def test_detention_and_mixed_sentence_are_not_zero_month_prison_targets(self):
        for primaries,selected,expected_days in [(['拘役伍拾日'],['拘役伍拾日'],50),
                (['有期徒刑參月','拘役伍拾日'],['有期徒刑參月'],0)]:
            r=review();r['宣告主刑']=json.dumps(primaries);r['單一刑期']=json.dumps(selected)
            term,valid,kind,days,_=refreshed_sentence(r,True)
            self.assertFalse(valid);self.assertEqual(term['imprisonment'],0);self.assertEqual(days,expected_days)

    def test_match_requires_document_id_or_case_and_date_and_rejects_ambiguity(self):
        meta={'source_url':'https://x/?id=doc','case_number':'案','judgment_date':'2025-01-01'}
        self.assertEqual(match_source(meta,[{}, {'doc':[2]}, {}]),(2,'judgment_id'))
        self.assertEqual(match_source(meta,[{}, {}, {('案','2025-01-01'):[3]}]),(3,'case_and_date'))
        self.assertEqual(match_source(meta,[{meta['source_url']:[1,2]}, {}, {}]),(None,'ambiguous_exact_url'))
        self.assertEqual(match_source(meta,[{}, {}, {('案','2024-01-01'):[3]}]),(None,'raw_not_found'))

    def test_refresh_export_preserves_fact_and_partial_evidence_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);database=root/'source.db';input_path=root/'input.jsonl';output=root/'out'
            source=dict(case_number='測試刑事判決',source_url='https://example.test/?id=1',
                        defendant='甲某',verdict='甲某犯竊盜罪，處拘役拾日；又犯詐欺罪，處拘役拾日。',
                        reasons='核被告所為，係犯刑法第320條第1項之竊盜罪。')
            with closing(sqlite3.connect(database)) as db, db:
                db.execute('CREATE TABLE judgments (id INTEGER,judgment_date TEXT,'+
                           ','.join(key+' TEXT' for key in SOURCE_COLUMNS)+')')
                db.execute('INSERT INTO judgments VALUES ('+','.join('?' for _ in range(len(SOURCE_COLUMNS)+2))+')',
                           [1,'2023-01-01',*(source.get(key,'') for key in SOURCE_COLUMNS)])
            old=base_record();old['meta'].update(source_url=source['source_url'],year=2023)
            input_path.write_text(json.dumps(old,ensure_ascii=False)+'\n',encoding='utf-8')
            db_hash=hashlib.sha256(database.read_bytes()).hexdigest()
            connection=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
            with patch('refresh_modeldata.sqlite3.connect',return_value=connection), redirect_stdout(io.StringIO()):
                report=refresh(input_path,database,output)
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')
            exported=list(read_records(next(output.glob('*.zip'))))[0]
            self.assertEqual(exported['fact'],old['fact'])
            self.assertEqual(exported['meta']['relevant_articles'],[])
            self.assertEqual(exported['meta']['reextraction']['partial_relevant_articles'],['刑法第320條'])
            self.assertEqual(report['counts']['article_valid'],0)
            excluded=json.loads((output/'task_exclusions.jsonl').read_text(encoding='utf-8'))
            self.assertEqual(json.loads((output/'refresh_report.json').read_text(encoding='utf-8')),report)
            self.assertIn('partial_offense_laws_missing',excluded['audit']['task_exclusion_reasons']['article'])
            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(),db_hash)
            with self.assertRaises(FileExistsError):refresh(input_path,database,output)

    def test_refresh_closes_source_when_input_is_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);input_path=root/'input.jsonl'
            input_path.write_text('{',encoding='utf-8')
            connection=sqlite3.connect(':memory:')
            connection.execute('CREATE TABLE judgments (id INTEGER,case_number TEXT,judgment_date TEXT,source_url TEXT)')
            with patch('refresh_modeldata.sqlite3.connect',return_value=connection):
                with self.assertRaises(json.JSONDecodeError):
                    refresh(input_path,root/'source.db',root/'out')
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')


if __name__=='__main__':unittest.main()
