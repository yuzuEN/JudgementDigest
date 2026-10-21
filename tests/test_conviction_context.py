"""已確認入口／量刑／新舊法比較問題；不恢復案件層級補空。"""
import json
import unittest

from build_structured_review import HEADERS, build_row
from structure_tasks import conviction_context, conviction_passages, extract_laws, laws_in_text


def raw_laws(reason, verdict='甲某犯竊盜罪，處拘役拾日。'):
    values, _ = build_row({'被告／相對人': '甲某', '主文': verdict, '理由': reason})
    return json.loads(dict(zip(HEADERS, values))['法條（對應原始）'])


class TestConvictionContext(unittest.TestCase):
    def test_real_126939_each_criminal_act_is_not_each_commits(self):
        text = ('足認被告為上開各犯行時，並無因精神障礙或其他心智缺陷致不能辨識其行為違法'
                '或欠缺依其辨識而行為之能力，復未因上揭原因致辨識行為違法或依其辨識而行為'
                '之能力有顯著減低之情，核與刑法第19條第1項、第2項規定不符，不得減輕其刑。')
        self.assertEqual(list(conviction_passages(text)), [])
        self.assertEqual(extract_laws(text, ''), [])

    def test_each_commits_an_actual_offense_still_works(self):
        text = '被告二人各犯刑法第320條第1項之竊盜罪。'
        self.assertEqual(extract_laws(text, ''), ['刑法第320條第1項'])
        self.assertEqual(raw_laws(text), [['刑法第320條第1項']])
        for name in ('行使偽造私文書罪', '行求賄賂罪'):
            self.assertTrue(list(conviction_passages(f'被告二人各犯{name}。')))

    def test_real_53614_each_commits_perjury_is_preserved(self):
        # 臺北109審簡2396；人名匿名化，保留實際論罪句型。
        text = '二、論罪科刑：(一)核被告甲某及乙某所為，均係各犯刑法第168條之偽證罪。'
        self.assertEqual(extract_laws(text, ''), ['刑法第168條'])
        self.assertEqual(raw_laws(text, '甲某犯偽證罪，處有期徒刑參月。'), [['刑法第168條']])

    def test_real_73767_and_75151_sentencing_phrases(self):
        for text in ('為累犯，應依刑法第47條第1項規定加重其刑。',
                     '是屬於累犯，應該依照刑法第47條第1項的規定，加重被告的刑度。',
                     '為累犯，請依刑法第47條第1項之規定，加重其刑。'):
            with self.subTest(text=text):
                self.assertEqual(laws_in_text(text), [])
                self.assertEqual(extract_laws('', text), [])
                self.assertNotIn('第47條', ''.join(conviction_passages(text, False)))

    def test_sentencing_filter_is_local_and_not_a_law_name_allowlist(self):
        text = ('核被告所為，係犯測試法第8條之竊盜罪，為累犯，'
                '應依刑法第47條第1項規定加重其刑，另係犯刑法第354條之毀損罪。')
        self.assertEqual(laws_in_text(text), ['測試法第8條', '刑法第354條'])
        self.assertEqual(raw_laws(text), [['測試法第8條']])

    def test_aggravated_offense_and_statutory_penalty_are_not_sentencing(self):
        text = ('核被告所為，係犯刑法第321條第1項第3款之加重竊盜罪。'
                '刑法第321條第1項：處6月以上5年以下有期徒刑。')
        self.assertEqual(raw_laws(text, '甲某犯加重竊盜罪，處有期徒刑陸月。'),
                         [['刑法第321條第1項第3款']])
        self.assertIn('刑法第321條第1項', laws_in_text(text[text.index('。')+1:]))

    def test_bare_general_provision_is_not_removed_by_number(self):
        self.assertEqual(laws_in_text('刑法第11條、刑法第47條第1項'),
                         ['刑法第11條', '刑法第47條第1項'])

    def test_real_53384_comparison_is_not_a_conviction_entry(self):
        text = ('是依上揭規定，被告寄藏前揭改造手槍，於修正後係犯'
                '槍砲彈藥刀械管制條例第7條第4項之罪。'
                '經比較新舊法結果，本案自應適用被告行為時即修正前之'
                '槍砲彈藥刀械管制條例第8條第4項規定論處。')
        self.assertEqual(list(conviction_passages(text)), [])
        self.assertEqual(extract_laws(text, ''), [])
        self.assertEqual(raw_laws(text, '甲某犯非法寄藏槍枝罪，處有期徒刑參年。'), [[]])

    def test_later_explicit_pair_wins_without_guessing_from_comparison(self):
        for version in ('修正前', '修正後'):
            text = ('於修正後係犯槍砲彈藥刀械管制條例第7條第4項之非法寄藏槍枝罪。'
                    f'本案應適用{version}規定。核被告所為，係犯{version}'
                    '槍砲彈藥刀械管制條例第8條第4項之非法寄藏槍枝罪。')
            with self.subTest(version=version):
                self.assertEqual(raw_laws(text, '甲某犯非法寄藏槍枝罪，處有期徒刑參年。'),
                                 [['槍砲彈藥刀械管制條例第8條第4項']])

    def test_no_borrowing_of_other_offense_or_defendants_choice(self):
        text = ('甲某於修正後係犯槍砲彈藥刀械管制條例第7條第4項之非法寄藏槍枝罪。'
                '乙某部分，本案應適用修正前槍砲彈藥刀械管制條例第8條第4項規定。'
                '甲某另係犯刑法第320條第1項之竊盜罪。')
        self.assertEqual(raw_laws(text, '甲某犯非法寄藏槍枝罪，處有期徒刑參年。'), [[]])
        self.assertEqual(raw_laws(text), [['刑法第320條第1項']])

    def test_same_sentence_other_offense_and_final_version_are_preserved(self):
        text = ('於修正前係犯刑法第339條之詐欺取財罪，惟比較後核被告所為，'
                '係犯修正後刑法第339條之4之加重詐欺取財罪。')
        self.assertEqual(raw_laws(text, '甲某犯加重詐欺取財罪，處有期徒刑壹年。'),
                         [['刑法第339條之4']])

    def test_negative_and_prosecution_policy_stays_in_force(self):
        for text in ('公訴意旨認被告係犯刑法第320條之竊盜罪。',
                     '核被告所為，不成立刑法第320條之竊盜罪。'):
            self.assertEqual(raw_laws(text), [[]])

    def test_sentencing_mask_keeps_a_boundary(self):
        text = '係犯刑法第320條，應依刑法第47條第1項規定加重其刑，刑法第354條之毀損罪。'
        self.assertEqual(raw_laws(text, '甲某犯毀損罪，處拘役拾日。'), [['刑法第354條']])
        self.assertEqual(conviction_context(conviction_context(text)), conviction_context(text))


if __name__ == '__main__':
    unittest.main()
