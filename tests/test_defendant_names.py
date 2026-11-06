"""姓名紀錄計數與主文實名／匿名位置匹配；不處理附表。"""
import json
import unittest

from build_structured_review import HEADERS, build_row, classify_defendants
from html_parser import _extract_parties
from refresh_modeldata import apply_review
from structure_tasks import (
    extract_charges, extract_offense_clauses, extract_verdict_charges,
    extract_verdict_descriptions, sentence_data_status,
    split_defendant_names, structure_row, verdict_clause_charges,
)


class TestDefendantNames(unittest.TestCase):
    def test_only_semicolons_split_records(self):
        self.assertEqual(split_defendant_names(' NGUYEN THI MY DUNG；巴蘇亞‧達基安娜;王、小明 '),
                         ['NGUYEN THI MY DUNG', '巴蘇亞‧達基安娜', '王、小明'])
        self.assertEqual(split_defendant_names('王小明；王小明'), ['王小明', '王小明'])
        self.assertEqual(classify_defendants('王小明；王小明', ''), '多被告')
        self.assertEqual(classify_defendants(' ；; ', ''), '不明')

    def test_count_does_not_filter_names_or_require_verdict_presence(self):
        for name in ['洪家煒', 'NGUYEN THI MY DUNG', '巴蘇亞‧達基安娜', '蘊緹唐·凱英',
                     'LONG FOREIGN NAME WITH MORE THAN TWENTY CHARACTERS', '甲', 'A01', '王、小明']:
            with self.subTest(name=name):
                self.assertEqual(classify_defendants(name, '甲○○犯竊盜罪。'), '單被告')

    def test_foreign_or_unmatched_second_name_still_counts(self):
        for delimiter in ['；', ';']:
            names = '王小明' + delimiter + 'NGUYEN THI MY DUNG'
            for verdict in ['王小明、NGUYEN THI MY DUNG均犯竊盜罪。', '王小明犯竊盜罪。', '']:
                self.assertEqual(classify_defendants(names, verdict), '多被告')
            self.assertEqual(sentence_data_status(['拘役10日', '拘役20日'], [], names), '多被告未配對')
        self.assertEqual(sentence_data_status(['拘役10日', '拘役20日'], [], '王小明；'), '僅宣告刑')

    def test_matching_compacts_both_sides_without_overwriting_raw_name(self):
        name = ' NGUYEN  THI MY DUNG '
        source = {'被告／相對人': name, '主文': 'NGUYEN THI MY DUNG竊盜，處拘役拾日。',
                  '理由': '核被告所為，係犯刑法第320條第1項之竊盜罪。'}
        row = dict(zip(HEADERS, build_row(source)[0]))
        self.assertEqual(row['被告／相對人'], name)
        self.assertEqual(json.loads(row['罪名（原始）']), ['竊盜'])
        self.assertEqual(row['被告狀態'], '單被告')
        self.assertEqual(structure_row(source)[6], '[竊盜]')
        exported = apply_review({'fact': '固定事實', 'meta': {}}, row, 'reextracted', 'id')
        self.assertEqual(exported['meta']['accusation'], ['竊盜罪'])
        self.assertTrue(exported['meta']['reextraction']['task_validity']['accusation'])

    def test_names_with_dots_and_long_names_are_removed_before_charge(self):
        for name in ['巴蘇亞‧達基安娜', '蘊緹唐·凱英', 'LONG FOREIGN NAME WITH MANY PARTS']:
            for charge in ['犯竊盜罪', '犯竊盜', '竊盜罪', '竊盜']:
                verdict = f'{name}{charge}，處拘役拾日。'
                expected = charge.removeprefix('犯')
                self.assertEqual(extract_charges(verdict, '', defendants=name), [expected])

    def test_actual_name_precedes_code_and_generic_commit_regex(self):
        for name in ['A01 林某', '犯英傑']:
            offenses = extract_offense_clauses(f'{name}竊盜，處拘役拾日。', name)
            self.assertEqual([x['charge'] for x in offenses], ['竊盜'])
        self.assertEqual(verdict_clause_charges('王小明犯竊盜罪，處拘役拾日：又犯侵占罪，處拘役伍日。', '王小明'),
                         ['竊盜罪', '侵占罪'])
        self.assertEqual(verdict_clause_charges('王小明共同竊盜，處拘役拾日。', '王小明'), ['共同竊盜'])

    def test_anonymous_subject_fallback_and_omitted_suffix(self):
        for subject in ['甲○○', '乙ＯＯ', '丙OO', '丁〇〇', 'A01', 'Ａ０１']:
            self.assertEqual(extract_charges(f'{subject}施用第二級毒品，處有期徒刑貳月。',
                                            '', defendants='洪家煒'), ['施用第二級毒品'])
        self.assertEqual(extract_charges('一、被告甲○○犯竊盜，處拘役拾日。', '',
                                        defendants='洪家煒'), ['竊盜'])

    def test_codes_in_other_roles_or_reasons_are_not_subjects(self):
        self.assertEqual(extract_offense_clauses('扣案手機發還被害人A01。', '洪家煒'), [])
        self.assertEqual(extract_offense_clauses('甲○○無罪。事實與理由：證人A01犯竊盜罪，處拘役拾日。',
                                                '洪家煒'), [])
        # 不從子句中段搜尋代號；未命中仍交原有描述規則，不猜被害人是被告。
        self.assertEqual(verdict_clause_charges('被害人A01竊盜，處拘役拾日。', '洪家煒'),
                         ['被害人A01竊盜'])

    def test_no_subject_match_keeps_existing_path_and_continuations(self):
        self.assertEqual(extract_charges('某人犯竊盜罪，處拘役拾日。', '', defendants='洪家煒'), ['竊盜罪'])
        self.assertEqual(extract_charges('王小明犯竊盜罪，處拘役拾日；又犯侵占罪，處拘役伍日。',
                                        '', defendants='王小明'), ['竊盜罪', '侵占罪'])
        self.assertEqual(extract_charges('王小明、NGUYEN THI MY DUNG均犯竊盜罪，各處拘役拾日。',
                                        '', defendants='王小明;NGUYEN THI MY DUNG'), ['竊盜罪'])

    def test_missing_law_or_unverified_source_is_not_made_eligible(self):
        source = {'被告／相對人': '洪家煒', '主文': '甲○○犯竊盜罪，處拘役拾日；又犯侵占罪，處拘役伍日。',
                  '理由': '核被告所為，係犯刑法第320條第1項之竊盜罪。'}
        row = dict(zip(HEADERS, build_row(source)[0]))
        m = apply_review({'fact': '', 'meta': {}}, row, 'reextracted', 'id')['meta']
        self.assertTrue(m['reextraction']['task_validity']['accusation'])
        self.assertFalse(m['reextraction']['task_validity']['article'])
        row['罪名來源'] = '理由／事實備援'
        self.assertFalse(apply_review({'fact': '', 'meta': {}}, row, 'reextracted', 'id')
                         ['meta']['reextraction']['task_validity']['accusation'])

    def test_appendix_reference_policy_is_unchanged(self):
        for subject in ['NGUYEN THI MY DUNG', '甲○○']:
            for intro in ['犯', '共同犯', '分別犯']:
                clause = f'{subject}{intro}如附表所示之罪，處有期徒刑參月。'
                self.assertEqual(verdict_clause_charges(clause, 'NGUYEN THI MY DUNG'),
                                 extract_verdict_charges(clause)
                                 or extract_verdict_descriptions(clause, 'NGUYEN THI MY DUNG'))

    def test_upstream_defendant_continuations_preserve_full_names(self):
        names = ['王小明', 'NGUYEN THI MY DUNG', '巴蘇亞‧達基安娜',
                 'LONG FOREIGN NAME WITH MORE THAN TWENTY CHARACTERS']
        parties = _extract_parties(['被告 ' + names[0], *names[1:]])
        self.assertEqual(split_defendant_names(parties['defendant']), names)

    def test_real_taipei_main_text_excerpts(self):
        cases = [
            # judgments.id=41176（109簡1615）、80392（107原交簡127）、68806（107簡19）。
            ('NGUYEN THI QUY', 'NGUYEN THI QUY未經許可入國，處有期徒刑貳月。', '未經許可入國'),
            ('撒扶烙‧巴雅斯', '撒扶烙‧巴雅斯吐氣所含酒精濃度達每公升零點二五毫克以上而'
             '駕駛動力交通工具，處有期徒刑貳月。', '吐氣所含酒精濃度達每公升零點二五毫克以上而駕駛動力交通工具'),
            ('黃信學', '甲○○施用第二級毒品，處有期徒刑貳月。', '施用第二級毒品'),
            # id=69686／106訴499：主刑標題後仍先匹配實名。
            ('DAO NGOC TU；NGUYEN THI THU HANG',
             '壹、主刑部分：DAO NGOC TU共同販賣第二級毒品，處有期徒刑壹年伍月。', '共同販賣第二級毒品'),
        ]
        for name, verdict, expected in cases:
            self.assertEqual(classify_defendants(name, verdict), '多被告' if '；' in name else '單被告')
            self.assertEqual(extract_charges(verdict, '', defendants=name), [expected])


if __name__ == '__main__':
    unittest.main()
