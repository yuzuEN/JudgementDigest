"""Production fallback gates execute without Git or experiment diagnostics."""
import unittest
import json
from law_fallback import citation, overlaps, try_fallback
from unittest.mock import patch
from build_structured_review import HEADERS, build_row
from refresh_modeldata import apply_review
from normalize import normalize_charge
import structure_tasks as st


class TestFormalFallbackGates(unittest.TestCase):
    def attempt(self,charge,reason='',applicable='',clause=None):
        args=(charge,normalize_charge(charge),clause if clause is not None else f'甲犯{charge}，處拘役拾日。',
              reason,'',applicable,normalize_charge,())
        state = {}
        result = st.matched_laws(*args, diagnostics=state)
        self.assertFalse(result[0])
        return try_fallback(args,state)

    def test_missing_name_after_court_citation_can_use_old_matcher(self):
        laws,audit=self.attempt('竊盜罪','核被告所為，係犯刑法第320條第1項之罪。')
        self.assertEqual(laws,['刑法第320條第1項'])
        self.assertEqual(audit['legacy_source'],'案件法條備援')
        self.assertTrue(audit['evidence'])

    def test_negative_law_cannot_reenter_through_statute_appendix(self):
        laws,audit=self.attempt('竊盜罪','核被告所為，不成立刑法第320條第1項之竊盜罪。','刑法第320條第1項')
        self.assertEqual(laws,[])
        self.assertIn('law_in_rejected_claim_or_negative_passage',audit['reasons'])

    def test_prosecution_claim_cannot_reenter_through_statute_appendix(self):
        laws,audit=self.attempt('竊盜罪','公訴意旨認被告係犯刑法第320條第1項之竊盜罪。','刑法第320條第1項')
        self.assertEqual(laws,[])
        self.assertIn('law_in_rejected_claim_or_negative_passage',audit['reasons'])

    def test_current_ambiguity_is_not_a_missing_pair(self):
        laws,audit=self.attempt('竊盜罪','核被告所為，係犯刑法第320條第1項之普通竊盜罪、刑法第321條第1項之攜帶兇器竊盜罪。')
        self.assertEqual(laws,[])
        self.assertEqual(audit['reasons'],['new_candidate_ambiguity'])

    def test_incomplete_parallel_assignment_cannot_copy_first_grade_to_second(self):
        laws,audit=self.attempt('施用第二級毒品罪','係犯毒品危害防制條例第10條第1項之施用第一級、第二級毒品罪。')
        self.assertEqual(laws,[])
        self.assertIn('new_incomplete_parallel_assignment',audit['reasons'])

    def test_no_main_verdict_name_cannot_become_a_training_answer(self):
        laws,audit=self.attempt('竊盜罪',applicable='刑法第320條第1項',clause='')
        self.assertEqual(laws,[])
        self.assertEqual(audit['reasons'],['no_main_verdict_offense'])

    def test_attachment_is_not_used_as_a_legacy_fallback_source(self):
        attachment='核被告所為，係犯刑法第320條第1項之罪嫌。依刑事訴訟法第451條第1項聲請逕以簡易判決處刑。'
        laws,audit=self.attempt('竊盜罪','本件犯罪事實及證據引用檢察官聲請簡易判決處刑書之記載。',attachment)
        self.assertEqual(laws,[])
        self.assertEqual(audit['reasons'],['legacy_no_match_in_accepted_court_text'])

    def test_citation_overlap_preserves_subarticles_and_paragraphs(self):
        self.assertTrue(overlaps(citation('刑法第339條之4'),citation('刑法第三百三十九條之四第1項')))
        self.assertFalse(overlaps(citation('刑法第339條'),citation('刑法第339條之4')))
        self.assertFalse(overlaps(citation('毒品危害防制條例第10條第1項'),citation('毒品危害防制條例第10條第2項')))

    def test_unresolved_reference_not_admitted_as_an_experimental_label(self):
        args=('竊盜罪','竊盜罪','甲犯竊盜罪，處拘役拾日。','','','刑法第320條',normalize_charge,())
        with patch('law_fallback.legacy_matched_laws', return_value=(['同法第320條'],'案件法條備援')):
            laws,audit=try_fallback(args,dict(candidates=[],incomplete_parallel_laws=[]))
        self.assertEqual(laws,[])
        self.assertIn('legacy_unparsed_law_string',audit['reasons'])

    def test_current_different_offense_pair_blocks_legacy_result(self):
        args=('施用第二級毒品罪','施用毒品罪','甲犯施用第二級毒品罪，處拘役拾日。',
              '係犯毒品危害防制條例第10條第1項之施用第一級毒品罪。','','',normalize_charge,())
        state = {}
        result = st.matched_laws(*args, diagnostics=state)
        self.assertFalse(result[0])
        laws,audit=try_fallback(args,state)
        self.assertEqual(laws,[])
        self.assertIn('new_parsed_different_offense',audit['reasons'])

    def test_default_entry_only_fills_empty_slots_and_records_provenance(self):
        source = {'被告／相對人': '甲某',
                  '主文': '甲某犯刑法第320條之竊盜罪，處拘役拾日；又犯毀損罪，處拘役拾日。',
                  '適用法條': '刑法第354條'}
        before = dict(zip(HEADERS, build_row(source, use_fallback=False)[0]))
        after = dict(zip(HEADERS, build_row(source)[0]))
        self.assertEqual(json.loads(before['法條（對應原始）']), [['刑法第320條'], []])
        self.assertEqual(json.loads(after['法條（對應原始）']), [['刑法第320條'], ['刑法第354條']])
        self.assertEqual(before['罪名（原始）'], after['罪名（原始）'])
        self.assertEqual(json.loads(after['法條來源']), ['主文同子句', '舊版備援（案件法條備援）'])
        audit = json.loads(after['法條備援紀錄'])
        self.assertIsNone(audit[0])
        self.assertTrue(audit[1]['recovered'])
        self.assertTrue(audit[1]['evidence'])
        record = {'fact': '固定事實', 'meta': {}}
        self.assertFalse(apply_review(record, before, 'reextracted', 'test')['meta']['reextraction']['task_validity']['article'])
        updated = apply_review(record, after, 'reextracted', 'test')
        self.assertTrue(updated['meta']['reextraction']['task_validity']['article'])
        self.assertEqual(updated['fact'], record['fact'])
        self.assertEqual(updated['meta']['reextraction']['law_fallback'], audit)

    def test_reason_only_offense_cannot_use_fallback(self):
        source = {'被告／相對人': '甲某', '主文': '甲某如附表所示，處拘役拾日。',
                  '理由': '係犯刑法第320條之竊盜罪、刑法第354條之毀損罪。'}
        row = dict(zip(HEADERS, build_row(source)[0]))
        record = apply_review({'fact': '固定事實', 'meta': {}}, row, 'reextracted', 'test')
        self.assertFalse(record['meta']['reextraction']['task_validity']['article'])

    def test_known_weak_source_boundary_is_not_reported_as_exact_pairing(self):
        source = {'被告／相對人': '甲某',
                  '主文': '甲某犯詐欺取財罪，處拘役拾日；又犯竊盜罪，處拘役拾日。',
                  '理由': '引用聲請簡易判決處刑書。依刑事訴訟法第449條，刑法第339條、第320條，判決如主文。',
                  '適用法條': '刑法第339條意圖為自己不法所有，以詐術使人交付財物者。附件：原因：[]'}
        row = dict(zip(HEADERS, build_row(source)[0]))
        # Known legacy limitation: statutory text can fill both slots; not a precision assertion.
        self.assertEqual(json.loads(row['法條（對應原始）']), [['刑法第339條'], ['刑法第339條']])
        self.assertTrue(all(s.startswith('舊版備援') for s in json.loads(row['法條來源'])))

    def test_current_context_protection_also_applies_to_fallback(self):
        for reason in ('上開各犯行時，核與刑法第19條規定不符，不得減輕其刑。',
                       '核被告所為，係犯刑法第320條之罪，為累犯，應依刑法第47條第1項規定加重其刑。'):
            row = dict(zip(HEADERS, build_row({'被告／相對人': '甲某',
                '主文': '甲某犯竊盜罪，處拘役拾日。', '理由': reason})[0]))
            laws = json.loads(row['法條（對應原始）'])
            self.assertFalse(any('第19條' in law or '第47條' in law for group in laws for law in group))

    def test_new_entry_vocabulary_does_not_expand_legacy_case_fallback(self):
        # Reduced boundary from 108訴330: a broad entry must not recover confiscation.
        source = {'被告／相對人': '甲某', '主文': '甲某犯竊盜罪，處拘役拾日。',
                  '理由': '核其所為，是犯刑法第38條之1第3項之罪。'}
        row = dict(zip(HEADERS, build_row(source)[0]))
        self.assertEqual(json.loads(row['法條（對應原始）']), [[]])
        self.assertEqual(json.loads(row['法條備援紀錄'])[0]['reasons'],
                         ['legacy_no_match_in_accepted_court_text'])


if __name__=='__main__':unittest.main()
