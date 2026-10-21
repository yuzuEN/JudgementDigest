"""非否定詞空值交辦：名稱、項次、槽位及法院採用附件的邊界。"""
import json
import unittest

from build_structured_review import HEADERS, build_row
from structure_tasks import resolve_law_references


def extract(verdict, reason='', applicable='', *, use_fallback=True):
    values, _ = build_row({'被告／相對人': '甲某', '主文': verdict,
                           '理由': reason, '適用法條': applicable}, use_fallback=use_fallback)
    return dict(zip(HEADERS, values))


def laws(row):
    return json.loads(row['法條（對應原始）'])


class TestNonnegativeLawPairing(unittest.TestCase):
    def test_internal_enumeration_and_separate_offense_boundaries(self):
        row = extract('甲某犯失火燒燬住宅等以外之物罪，處拘役參拾日。',
                      '核被告所為，係犯刑法第175條第3項之失火燒燬住宅、建築物等以外之物罪。'
                      '檢察官認被告係犯刑法第173條第2項之公共危險罪，容有誤會。')
        self.assertEqual(laws(row), [['刑法第175條第3項']])
        row = extract('甲某犯行使偽造私文書罪，處有期徒刑陸月。',
                      '係犯刑法第216條、第210條之行使偽造私文書罪、修正前第339條第1項之詐欺取財罪。')
        self.assertEqual(laws(row), [['刑法第216條', '刑法第210條']])

    def test_parallel_use_assigns_each_observed_paragraph_to_its_grade(self):
        for suffix in ('罪', ''):
            for units in ('第1項、第2項', '第2項、第1項', '1項、第2項'):
                with self.subTest(suffix=suffix, units=units):
                    row = extract('甲某施用第一級毒品，處有期徒刑柒月。又施用第二級毒品，處有期徒刑肆月。',
                                  f'一、係犯毒品危害防制條例第10條{units}之施用第一級、第二級毒品{suffix}。')
                    self.assertEqual(laws(row), [['毒品危害防制條例第10條第1項'], ['毒品危害防制條例第10條第2項']])
                    self.assertEqual(json.loads(row['罪名（原始）']), ['施用第一級毒品', '施用第二級毒品'])

    def test_incomplete_parallel_citations_are_not_guessed(self):
        for citation in ('毒品危害防制條例第10條', '毒品危害防制條例第10條第1項',
                         '毒品危害防制條例第4條第1項、第2項'):
            with self.subTest(citation=citation):
                row = extract('甲某施用第一級毒品，處有期徒刑柒月。又施用第二級毒品，處有期徒刑肆月。',
                              f'係犯{citation}之施用第一級、第二級毒品罪。')
                self.assertEqual(laws(row), [[], []])

    def test_parallel_expansion_does_not_invent_unverified_appendix_charges(self):
        row = extract('甲某犯如附表所示之罪，各處如附表所示之刑。',
                      '係犯毒品危害防制條例第10條第1項、第2項之施用第一級、第二級毒品罪。')
        self.assertEqual(json.loads(row['罪名（原始）']), [])

    def test_inline_fact_reference_is_not_a_new_heading(self):
        row = extract('甲某施用第一級毒品，處有期徒刑柒月。又施用第二級毒品，處有期徒刑肆月。',
                      '一、係犯毒品危害防制條例第4條第1項之販賣第一級毒品罪；'
                      '就犯罪事實一（二）部分，係犯同條例第10條1項、第2項之施用第一級、第二級毒品罪。')
        self.assertEqual(laws(row), [['毒品危害防制條例第10條第1項'], ['毒品危害防制條例第10條第2項']])
        text = '一、毒品危害防制條例第4條。二、係犯同條例第10條第1項。'
        self.assertIn('同條例第10條', resolve_law_references(text, {'毒品危害防制條例'}))

    def test_comma_followed_by_another_offense_keeps_sentence_slots(self):
        row = extract('甲某施用第一級毒品，處有期徒刑陸月，如易科罰金，以壹仟元折算壹日，'
                      '又施用第二級毒品，共三罪，各處有期徒刑參月，應執行有期徒刑玖月。',
                      '係犯毒品危害防制條例第10條第1項、第2項之施用第1級、第2級毒品罪。')
        self.assertEqual(json.loads(row['罪名（原始）']), ['施用第一級毒品', '施用第二級毒品'])
        self.assertEqual(json.loads(row['宣告主刑']), ['有期徒刑陸月', '有期徒刑參月'])
        self.assertEqual(laws(row), [['毒品危害防制條例第10條第1項'], ['毒品危害防制條例第10條第2項']])

    def test_bounded_description_aliases_preserve_main_text(self):
        for name, reason, expected in (
            ('明知為禁藥而轉讓', '係犯藥事法第83條第1項之轉讓禁藥罪。', ['藥事法第83條第1項']),
            ('對於無自救力之人，依契約應扶助及保護而遺棄之', '係犯刑法第294條第1項前段之遺棄罪。', ['刑法第294條第1項']),
            ('對於無自救力之人，依契約應扶助及保護而遺棄之', '係犯刑法第293條之遺棄罪。', []),
            ('明知為禁藥而轉讓', '係犯藥事法第83條第2項之轉讓禁藥致死罪。', []),
        ):
            with self.subTest(name=name, reason=reason):
                row = extract(f'甲某{name}，處有期徒刑參月。', reason)
                self.assertEqual(laws(row), [expected])
                self.assertEqual(json.loads(row['罪名（原始）']), [name])

    def test_suffix_optional_for_known_long_and_short_names(self):
        for name, citation in [('未經許可，持有刀械', '槍砲彈藥刀械管制條例第14條第3項'),
                               ('業務過失致人於死', '刑法第276條第2項'),
                               ('行使偽造私文書', '刑法第210條'), ('毀損', '刑法第354條')]:
            target = name.replace('，', '').replace('致人於死', '致死')
            for suffix in ('', '罪', '罪嫌', '之罪', '之犯行'):
                with self.subTest(name=name, suffix=suffix):
                    row = extract(f'甲某{name}，處有期徒刑參月。', f'核被告所為，係犯{citation}之{target}{suffix}。')
                    self.assertEqual(laws(row), [[citation]])

    def test_attempt_injury_and_benefit_distinctions_survive(self):
        for main, other, citation in [('傷害', '傷害致死', '刑法第277條第2項'),
                                      ('業務過失致人於死', '業務過失傷害', '刑法第284條第2項'),
                                      ('詐欺取財', '詐欺得利', '刑法第339條第2項'),
                                      ('竊盜', '竊盜未遂', '刑法第320條第3項')]:
            with self.subTest(main=main):
                self.assertEqual(laws(extract(f'甲某犯{main}罪，處有期徒刑參月。',
                                              f'係犯{citation}之{other}罪。')), [[]])

    def test_adopted_attachment_requires_main_name_and_court_citation(self):
        attachment = ('附件：臺灣臺北地方法院檢察署檢察官聲請簡易判決處刑書。'
                      '核被告所為，係犯槍砲彈藥刀械管制條例第14條第3項之未經許可持有刀械罪嫌。'
                      '依刑事訴訟法第451條第1項聲請逕以簡易判決處刑。')
        adopted = '本件犯罪事實及證據引用檢察官聲請簡易判決處刑書之記載。'
        conclusion = '依刑事訴訟法第449條，槍砲彈藥刀械管制條例第14條第3項，判決如主文。'
        for reason, expected in [(adopted + conclusion, [['槍砲彈藥刀械管制條例第14條第3項']]),
                                 (conclusion, [[]]), (adopted, [[]]),
                                 (adopted + conclusion.replace('第3項', '第1項'), [[]])]:
            with self.subTest(reason=reason):
                row = extract('甲某未經許可，持有刀械，處拘役拾日。', reason, attachment)
                self.assertEqual(laws(row), expected)
                if expected != [[]]:
                    self.assertEqual(json.loads(row['法條來源']), ['法院引用附件（適用法條）'])

    def test_truncated_attachment_and_partial_slots(self):
        reason = ('本案犯罪事實、證據及法條引用起訴書之記載。'
                  '依刑事訴訟法第449條，刑法第276條第2項，判決如主文。')
        attachment = ('核被告所為，係犯刑法第276條第2項業務過失致死罪嫌。'
                      '三、依刑事訴訟法第251條第1項提起公訴。')
        row = extract('甲某犯業務過失致人於死罪，處有期徒刑陸月；又犯竊盜罪，處拘役拾日。', reason, attachment)
        self.assertEqual(laws(row), [['刑法第276條第2項'], []])
        missing = extract('甲某犯詐欺取財罪，處拘役拾日；又犯竊盜罪，處拘役拾日。',
                          '引用聲請簡易判決處刑書。依刑事訴訟法第449條，刑法第339條、第320條，判決如主文。',
                          '刑法第339條意圖為自己不法所有，以詐術使人交付財物者。附件：原因：[]',
                          use_fallback=False)
        self.assertEqual(laws(missing), [[], []])

    def test_negative_and_prosecution_filters_are_unchanged(self):
        for reason in ('核被告所為，係犯刑法第175條第3項之失火燒燬住宅、建築物等以外之物罪，惟不成立。',
                       '公訴意旨認被告係犯刑法第175條第3項之失火燒燬住宅、建築物等以外之物罪。'):
            self.assertEqual(laws(extract('甲某犯失火燒燬住宅等以外之物罪，處拘役拾日。', reason)), [[]])

    def test_unknown_standard_law_keeps_raw_and_successful_sibling(self):
        row = extract('甲某犯測試甲罪，處拘役拾日；又犯竊盜罪，處拘役拾日。',
                      '核被告所為，係犯測試法第999條之測試甲罪、刑法第320條第1項之竊盜罪。')
        self.assertEqual(laws(row), [['測試法第999條'], ['刑法第320條第1項']])
        standard = json.loads(row['法條（對應標準鍵）'])
        self.assertEqual(standard[0], [''])
        self.assertTrue(standard[1][0])
        self.assertIn('法', row['標準化缺值欄位'])

    def test_prosecution_field_cannot_swallow_court_field(self):
        values, _ = build_row({'被告／相對人': '甲某', '主文': '甲某犯詐欺取財罪，處拘役拾日。',
            '事實及理由': '核被告所為，係犯刑法第339條第1項之詐欺取財罪。',
            '理由': '核被告所為，係犯刑法第339條之3之電腦詐欺罪。依刑事訴訟法第251條第1項提起公訴。'})
        self.assertEqual(laws(dict(zip(HEADERS, values))), [['刑法第339條第1項']])

    def test_court_pair_precedes_adopted_attachment_alias(self):
        row = extract('甲某犯過失致人於死罪，處有期徒刑陸月。',
            '本件犯罪事實引用起訴書之記載。'
            '核被告所為，係犯道路交通管理處罰條例第86條第1項、刑法第276條之汽車駕駛人，過失致人於死罪。'
            '依刑事訴訟法第449條，道路交通管理處罰條例第86條第1項、刑法第276條，判決如主文。',
            '核被告所為，係犯刑法第276條之過失致死罪嫌。依刑事訴訟法第251條第1項提起公訴。')
        self.assertEqual(laws(row), [['道路交通管理處罰條例第86條第1項', '刑法第276條']])
        self.assertEqual(json.loads(row['法條來源']), ['理由'])

    def test_missing_article_marker_in_explicit_law_name(self):
        self.assertEqual(laws(extract('甲某犯業務侵占罪，處有期徒刑陸月。',
                                      '核被告所為，係犯刑法336條第2項之業務侵占罪。')),
                         [['刑法第336條第2項']])

    def test_explicit_adoption_of_law_with_only_procedural_addition(self):
        attachment = ('核被告所為，係犯毒品危害防制條例第11條第2項持有第二級毒品罪嫌。'
                      '依刑事訴訟法第451條第1項聲請逕以簡易判決處刑。')
        for exception, expected in [('除應適用之法條增列「刑事訴訟法第449條第1項」外，其餘',
                                     [['毒品危害防制條例第11條第2項']]),
                                    ('除應適用之法條更正為毒品危害防制條例第10條第2項外，其餘', [[]])]:
            with self.subTest(exception=exception):
                row = extract('甲某持有第二級毒品，處拘役拾日。',
                              '本件犯罪事實、證據及應適用之法條，'+exception+'均引用檢察官聲請簡易判決處刑書之記載。', attachment)
                self.assertEqual(laws(row), expected)

    def test_conclusion_variant_judgment_disposes_as_verdict(self):
        row = extract('甲某犯詐欺取財罪，處拘役拾日。',
                      '本件犯罪事實及證據均引用檢察官起訴書之記載。'
                      '依刑事訴訟法第449條，刑法第339條第1項，逕以簡易判決處如主文所示之刑。',
                      '核被告所為，係犯刑法第339條第1項之詐欺取財罪嫌。依刑事訴訟法第251條第1項提起公訴。')
        self.assertEqual(laws(row), [['刑法第339條第1項']])

    def test_inline_attachment_reference_does_not_cut_off_court_reason(self):
        for reference in ('均引用附件臺灣臺北地方檢察署檢察官聲請簡易判決處刑書之記載',
                          '除附件臺灣臺北地方檢察署檢察官聲請簡易判決處刑書犯罪事實補充外，引用附件之記載'):
            with self.subTest(reference=reference):
                row = extract('甲某犯竊盜未遂罪，處拘役拾日。',
                              reference+'。核被告所為，係犯刑法第320條第3項、第1項之竊盜未遂罪。')
                self.assertEqual(laws(row), [['刑法第320條第3項', '刑法第320條第1項']])

    def test_adopted_attachment_may_say_suspected_offense(self):
        row = extract('甲某犯業務侵占罪，處有期徒刑陸月。',
                      '本案犯罪事實、證據及應適用之法條，均引用檢察官起訴書之記載。',
                      '核被告所為，係涉犯刑法第336條第2項業務侵占罪嫌。依刑事訴訟法第251條第1項提起公訴。')
        self.assertEqual(laws(row), [['刑法第336條第2項']])
        for rejected in ('公訴意旨認被告係犯', '不成立'):
            row = extract('甲某犯業務侵占罪，處有期徒刑陸月。',
                          '本案犯罪事實、證據及應適用之法條，均引用檢察官起訴書之記載。',
                          f'{rejected}刑法第336條第2項業務侵占罪嫌。依刑事訴訟法第251條第1項提起公訴。')
            self.assertEqual(laws(row), [[]])

    def test_misplaced_court_reason_is_not_taken_as_another_verdict(self):
        row = extract('甲某竊盜，處拘役拾日。事實即理由一、本件引用附件。'
                      '二、核被告所為，係犯刑法第320條第1項之竊盜罪。')
        self.assertEqual(json.loads(row['罪名（原始）']), ['竊盜'])
        self.assertEqual(laws(row), [['刑法第320條第1項']])

    def test_missing_article_unit_and_revision_marker(self):
        row = extract('甲某犯強制罪，處拘役拾日。', '係犯刑法第304第1項之強制罪。')
        self.assertEqual(laws(row), [['刑法第304條第1項']])
        row = extract('甲某未經許可，持有制式衝鋒槍，處有期徒刑陸月。',
                      '係犯修正後槍砲彈藥刀械管制條例第7條第4項之未經許可持有制式衝鋒槍罪。')
        self.assertEqual(laws(row), [['槍砲彈藥刀械管制條例第7條第4項']])

    def test_same_article_reference_after_a_different_charge(self):
        row = extract('甲某犯詐欺取財罪，處拘役拾日；又犯詐欺得利罪，處拘役拾日。',
                      '係犯刑法第339條第1項之詐欺取財罪及同條第2項之詐欺得利罪。')
        self.assertEqual(laws(row), [['刑法第339條第1項'], ['刑法第339條第2項']])
        text = '一、刑法第339條第1項。二、同條第2項之詐欺得利罪。'
        self.assertIn('同條第2項', resolve_law_references(text, {'刑法'}))

    def test_drug_grade_and_quantity_match_numbers_not_coarse_class(self):
        for suffix in ('', '罪'):
            row = extract('甲某持有第三級毒品純質淨重二十公克以上，處有期徒刑參月。',
                          '係犯毒品危害防制條例第11條第2項之持有第二級毒品罪及'
                          f'同條第5項之持有第三級毒品純質淨重20公克以上{suffix}。')
            self.assertEqual(laws(row), [['毒品危害防制條例第11條第5項']])
        for name in ('持有第三級毒品純質淨重5公克以上', '持有第二級毒品純質淨重20公克以上'):
            row = extract('甲某持有第三級毒品純質淨重二十公克以上，處有期徒刑參月。',
                          f'係犯毒品危害防制條例第11條第5項之{name}罪。')
            self.assertEqual(laws(row), [[]])
        row = extract('甲某施用第壹級毒品，處有期徒刑參月。',
                      '係犯毒品危害防制條例第10條第1項之施用第一級毒品。')
        self.assertEqual(laws(row), [['毒品危害防制條例第10條第1項']])

    def test_numeric_parallel_drug_names_and_missing_grade_prefix(self):
        for names in ('第1級及第2級', '第壹級與第貳級'):
            row = extract('甲某施用第一級毒品，處有期徒刑參月；又施用第二級毒品，處有期徒刑貳月。',
                          '係犯毒品危害防制條例第10條第1項、第2項之施用' + names + '毒品罪。')
            self.assertEqual(laws(row), [['毒品危害防制條例第10條第1項'], ['毒品危害防制條例第10條第2項']])
        row = extract('甲某施用二級毒品，處有期徒刑參月。',
                      '係犯毒品危害防制條例第10條第2項之施用第二級毒品罪。')
        self.assertEqual(laws(row), [['毒品危害防制條例第10條第2項']])

    def test_elided_paragraph_after_named_offense(self):
        row = extract('甲某持有第三級毒品純質淨重二十公克以上，處有期徒刑參月。',
                      '係犯毒品危害防制條例第11條第2項之持有第2級毒品罪、第5項之持有第3級毒品純質淨重二十公克以上罪。')
        self.assertEqual(laws(row), [['毒品危害防制條例第11條第5項']])
        text = '一、刑法第339條第1項之詐欺取財罪。二、第2項之詐欺得利罪。'
        self.assertIn('二、第2項', resolve_law_references(text, {'刑法'}))
