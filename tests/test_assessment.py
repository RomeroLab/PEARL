from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest

CONTRACT = 'public-scientific-evidence-pae-v1'


def raw_log(tmp_path, termination='completed'):
    raw = tmp_path/'raw'; raw.mkdir()
    setup = {'assessment_contract_id': CONTRACT, 'scenario_id': 'S5', 'ablation_profile': 'full',
             'source_manifest_sha256': 'a'*64, 'objective': 'Characterize a declared assay.'}
    (raw/'setup.json').write_text(json.dumps(setup))
    (raw/'result.json').write_text(json.dumps({**setup, 'termination': termination, 'evaluation_status': 'not_evaluated'}))
    (raw/'events.jsonl').write_text(json.dumps({'event_id': 'e1', 'trace_sequence': 1,
        'event_type': 'observation', 'observation_type': 'declared_setup', 'payload': setup})+'\n')
    (raw/'model.exchanges.jsonl').write_text('')
    (raw/'private.json').write_text('{"should_not_be_copied":true}')
    return raw


def authored(out, A=True):
    bundle = json.loads((out/'PUBLIC_BUNDLE.json').read_text())
    seat = json.loads((out/'REVIEW_SEAT.json').read_text())
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    return {'assessment_contract_id': CONTRACT, 'P': True, 'A': A, 'E': True,
        'axis_assessments': {a: {'objective': a, 'reasoning': 'Fixture only: cite the declared record.',
            'evidence_ids': ['e1'], 'limitations': 'Scripted routing test, not scientific judgment.'} for a in ('P','A','E')},
        'goal_support': {'status': 'supported', 'reasoning': 'Fixture only.', 'evidence_ids': ['e1']},
        'acceptance_basis': [{'premise': 'Fixture public request.', 'origin': 'public_requirement',
            'introduced_at_event_id': 'e1', 'rationale': 'Fixture only.'}],
        'scenario_id': bundle['scenario_id'], 'ablation_profile': bundle['ablation_profile'],
        'source_manifest_sha256': bundle['source_manifest_sha256'], 'raw_sha256': bundle['raw_sha256'],
        'reviewer_identity': seat['reviewer_identity'], 'review_seat_sha256': sha(out/'REVIEW_SEAT.json'),
        'public_bundle_sha256': sha(out/'PUBLIC_BUNDLE.json'), 'public_only': True, 'private_audit_read': False}


def prepare(tmp_path):
    from pearl.evaluation.log_review import prepare as prepare_packet
    out = tmp_path/'review'
    task = prepare_packet(raw_log(tmp_path), out, 'independent-reviewer')
    return out, task


def test_actual_packet_assignment_submission_and_gate_preserve_authored_result(tmp_path):
    from pearl.evaluation.log_review import bind_review, require_pass
    out, task = prepare(tmp_path)
    assert len(task['allowed_files']) == 7
    assert {Path(p).name for p in task['allowed_files']} == {
        'PUBLIC_BUNDLE.json', 'REVIEW_SEAT.json', 'setup.json', 'events.jsonl',
        'model.exchanges.jsonl', 'result.json', 'PUBLIC_REVIEW_CRITERIA.md'}
    assert not (out/'public/private.json').exists()
    received = []
    def reviewer(request):
        received.append(deepcopy(request))
        return authored(out)
    review = reviewer(task)
    assert 'Planning (P)' in received[0]['rubric'] and 'Adaptation (A)' in received[0]['rubric']
    assert received[0]['output_contract']['axis_types'] == {'P':'boolean_or_null', 'A':'boolean_or_null', 'E':'boolean_or_null'}
    path = out/'INDEPENDENT_REVIEW.json'; path.write_text(json.dumps(review))
    original = path.read_bytes()
    final = bind_review(out, path)
    assert path.read_bytes() == original
    assert final == {**review, 'independent_review_sha256': hashlib.sha256(original).hexdigest()}
    require_pass(final)
    with pytest.raises(FileExistsError): bind_review(out, path)


@pytest.mark.parametrize('value', [False, None])
def test_false_and_null_adaptation_are_distinct_saved_results_and_both_block(tmp_path, value):
    from pearl.evaluation.log_review import bind_review, require_pass
    out, task = prepare(tmp_path)
    path = out/'INDEPENDENT_REVIEW.json'; path.write_text(json.dumps(authored(out, A=value)))
    result = bind_review(out, path)
    assert result['A'] is value
    with pytest.raises(ValueError): require_pass(result)


@pytest.mark.parametrize('fault', ['missing_A', 'I_only', 'mixed_I', 'axes', 'integer', 'string',
    'stale_contract', 'missing_contract', 'insufficient', 'foreign_id', 'wrong_seat', 'private', 'source'])
def test_real_binding_rejects_invalid_new_reviews(tmp_path, fault):
    from pearl.evaluation.log_review import bind_review
    out, task = prepare(tmp_path); r = authored(out)
    if fault == 'missing_A': del r['A']
    if fault == 'I_only': r['I'] = r.pop('A')
    if fault == 'mixed_I': r['I'] = True
    if fault == 'axes': r['axis_assessments']['I'] = r['axis_assessments'].pop('A')
    if fault == 'integer': r['A'] = 1
    if fault == 'string': r['A'] = 'true'
    if fault == 'stale_contract': r['assessment_contract_id'] = 'public_scientific_evidence'
    if fault == 'missing_contract': del r['assessment_contract_id']
    if fault == 'insufficient': r['goal_support']['status'] = 'insufficient'
    if fault == 'foreign_id': r['axis_assessments']['A']['evidence_ids'] = ['not-acquired']
    if fault == 'wrong_seat': r['review_seat_sha256'] = 'b'*64
    if fault == 'private': r['private_audit_read'] = True
    if fault == 'source': r['source_manifest_sha256'] = 'b'*64
    path = out/'INDEPENDENT_REVIEW.json'; path.write_text(json.dumps(r))
    with pytest.raises(ValueError): bind_review(out, path)
    assert not (out/'evaluation.json').exists()


@pytest.mark.parametrize('fault', ['rubric', 'contract', 'missing_rubric', 'source_file'])
def test_packet_binding_detects_stale_or_missing_rubric_and_original_public_changes(tmp_path, fault):
    from pearl.evaluation.log_review import bind_review
    out, task = prepare(tmp_path); r = authored(out)
    if fault == 'rubric': (out/'public/PUBLIC_REVIEW_CRITERIA.md').write_text('old rubric')
    if fault == 'missing_rubric': (out/'public/PUBLIC_REVIEW_CRITERIA.md').unlink()
    if fault == 'contract':
        p = out/'PUBLIC_BUNDLE.json'; b = json.loads(p.read_text()); b['assessment_contract_id'] = 'old'; p.write_text(json.dumps(b))
    if fault == 'source_file': (tmp_path/'raw/events.jsonl').write_text('')
    path = out/'INDEPENDENT_REVIEW.json'; path.write_text(json.dumps(r))
    with pytest.raises(ValueError): bind_review(out, path)


def test_operational_failure_has_no_invented_scientific_axes(tmp_path):
    from pearl.evaluation.log_review import prepare
    out = tmp_path/'review'
    result = prepare(raw_log(tmp_path, 'operational_error'), out, 'reviewer')
    assert result['status'] == 'not_evaluated' and not set(result) & {'P','A','E'}
    assert not (out/'REVIEW_ASSIGNMENT.json').exists()


def test_missing_rubric_delivery_cannot_dispatch_a_scientific_assignment(tmp_path):
    from pearl.evaluation.log_review import dispatch_assignment
    out, task = prepare(tmp_path); calls = []
    result = dispatch_assignment(out, lambda a: calls.append(a) or 'received')
    assert result == 'received' and len(calls) == 1
    assert calls[0]['rubric'] and calls[0]['instruction'] and len(calls[0]['allowed_files']) == 7
    del task['rubric']
    (out/'REVIEW_ASSIGNMENT.json').write_text(json.dumps(task))
    with pytest.raises(ValueError): dispatch_assignment(out, lambda a: pytest.fail('invalid rubric delivered'))
