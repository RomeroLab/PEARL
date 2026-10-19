"""Independent offline review probes; run from staging with PYTHONPATH=src:."""
from copy import deepcopy
import unittest
import pytest
from pearl.runtime.knowledge import ROWS
from pearl.runtime.scientific_retrieval import ScientificKnowledgeProvider
NARROW = {'traditional_pigment_mixing', 'additive_light_mixing', 'color_mixing_limits'}

def ids(question, rows=ROWS):
    return {row['knowledge_id'] for row in ScientificKnowledgeProvider(rows).retrieve(question)}

class TopicQualificationReview(unittest.TestCase):

    def test_named_additive_model_remains_available(self):
        self.assertIn('additive_light_mixing', ids('Explain additive color mixing'))

    def test_explicit_additive_subtractive_comparison_keeps_both_topics(self):
        self.assertTrue({'additive_light_mixing', 'color_mixing_limits'}.issubset(ids('Compare additive and subtractive color mixing')))

    def test_beams_remain_a_recognized_emitter_topic(self):
        self.assertIn('additive_light_mixing', ids('How do green and blue beams mix?'))

    def test_traditional_primary_secondary_model_remains_available(self):
        self.assertIn('traditional_pigment_mixing', ids('Explain traditional primary and secondary color mixing'))

    def test_incidental_room_light_does_not_establish_additive_mixing_topic(self):
        self.assertFalse(NARROW & ids('For an enzyme premix under room light, explain mixing limitations before substrate addition.'))

    def test_incidental_blue_camera_without_lighting_is_correctly_filtered(self):
        self.assertFalse(NARROW & ids('For a blue camera enzyme endpoint, does mixing before substrate addition establish initiation?'))

    def test_explicit_topics_keep_source_and_neutrality_gates(self):
        for field, value in [('provenance', ''), ('description', 'The hidden answer requires this remedy.')]:
            with self.subTest(field=field):
                rows = deepcopy(ROWS)
                for row in rows:
                    if row['anomaly_id'] in NARROW:
                        row[field] = value
                self.assertFalse(NARROW & ids('Compare emitted light and pigment mixing', rows))

    def test_audit_selection_matches_returned_rows(self):
        provider = ScientificKnowledgeProvider(ROWS)
        result = provider.retrieve('Compare emitted light and pigment mixing')
        self.assertEqual({r['knowledge_id'] for r in result}, {r.protocol_id for r in provider.retrieval_audit().selected})
        self.assertTrue(all((r['relevance']['topic_qualification']['matched_anchor_groups'] for r in result if r['knowledge_id'] in NARROW)))
if __name__ == '__main__':
    unittest.main(verbosity=2)


@pytest.mark.parametrize('question', [
    'HRP-TMB',
    'How should an HRP-TMB reference curve support quantitative assay measurements?',
    'Should I build a reference curve before quantitative HRP-TMB analysis?',
])
def test_hrp_tmb_reference_guidance_is_retrieved_for_assay_questions(question):
    provider = ScientificKnowledgeProvider(ROWS)
    result = provider.retrieve(question)
    selected = {r['knowledge_id']: r for r in result}
    assert 'calibration_range' in selected
    row = selected['calibration_range']
    assert row['evidence_kind'] == 'prior_knowledge'
    assert row['applicability']['conditions'] and row['limitations'] and row['provenance']
    assert {r['knowledge_id'] for r in result} == {r.protocol_id for r in provider.retrieval_audit().selected}


def test_reference_guidance_is_not_selected_from_an_unrelated_dye_mixing_question():
    assert 'calibration_range' not in ids('How do red and yellow dyes mix into orange?')


@pytest.mark.parametrize('field,value', [
    ('provenance',''),('source_kind',''),('description','The hidden answer requires this remedy.')])
def test_reference_guidance_preserves_source_and_neutrality_filters(field, value):
    rows = deepcopy(ROWS)
    next(row for row in rows if row['anomaly_id'] == 'calibration_range')[field] = value
    provider = ScientificKnowledgeProvider(rows)
    result = provider.retrieve('HRP-TMB reference curve')
    assert 'calibration_range' not in {r['knowledge_id'] for r in result}
    rejected = {r.protocol_id:r.reason for r in provider.retrieval_audit().rejected}
    assert rejected['calibration_range'] in ('missing_source_scope','non_neutral_text')


def test_calibration_retrieval_provides_general_guidance_without_a_numeric_reference():
    provider = ScientificKnowledgeProvider(ROWS)
    row = next(r for r in provider.retrieve('HRP-TMB reference curve') if r['knowledge_id']=='calibration_range')
    assert row['evidence_kind'] == 'prior_knowledge'
    assert 'reference_curve' not in row
    assert row['applicability']['conditions'] and row['limitations'] and row['provenance']


def test_peer_changes_to_calibration_guidance_cannot_modify_corpus():
    provider = ScientificKnowledgeProvider(ROWS)
    first = next(r for r in provider.retrieve('HRP-TMB reference curve') if r['knowledge_id']=='calibration_range')
    conditions = deepcopy(first['applicability']['conditions'])
    first['applicability']['conditions'].clear()
    second = next(r for r in provider.retrieve('HRP-TMB reference curve') if r['knowledge_id']=='calibration_range')
    assert second['applicability']['conditions'] == conditions
