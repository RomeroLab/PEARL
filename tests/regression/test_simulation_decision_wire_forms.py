"""The model-facing forms preserve the authoritative decision distinctions."""
from copy import deepcopy
import pytest
from jsonschema import ValidationError, validate
from pearl.runtime.decision_record import decision_schema, prepare_decision
from pearl.runtime.runtime import role_tools
from pearl.state.events import ObservationEvent

def full_decision(status='unresolved', supersedes=None):
    return {'status': status, 'basis': 'Synthetic transport fixture, not experimental evidence.', 'next_step': 'Retain the explicitly authored fixture scope.', 'decision_basis': {'premise': 'An explicit fixture premise.', 'alternative': 'A distinct fixture interpretation.', 'expected_information': 'No acquisition is requested.', 'constraints': 'No physical claim or action is authorized.', 'evidence_ids': [], 'working_model': {'assumptions': 'Fixture assumptions only.', 'applicability': 'This transport test only.', 'implication': 'No scientific attainment is inferred.'}}, 'supersedes': supersedes}

@pytest.mark.parametrize('status', ['unresolved', 'conditional_conflict'])
@pytest.mark.parametrize('include_supersedes', [False, True])
def test_wire_rejects_a_missing_basis_already_rejected_by_the_server(status, include_supersedes):
    value = {k: v for k, v in full_decision(status).items() if k in {'status', 'basis', 'next_step'}}
    if include_supersedes:
        value['supersedes'] = None
    with pytest.raises(ValueError, match='requires decision_basis'):
        prepare_decision(value, [], {})
    with pytest.raises(ValidationError):
        validate(value, decision_schema())

def test_full_revision_cannot_omit_the_required_authored_supersession_field():
    prior = ObservationEvent(source_agent='reasoner', observation_type='scientific_decision', payload=full_decision())
    value = full_decision()
    value['next_step'] = 'A changed authored next step.'
    value.pop('supersedes')
    original = deepcopy(value)
    with pytest.raises(ValueError, match='explicitly supersede'):
        prepare_decision(value, [prior], {})
    with pytest.raises(ValidationError):
        validate(value, decision_schema())
    assert value == original

def test_legacy_initial_record_acceptance_does_not_add_an_authored_field():
    value = full_decision()
    value.pop('supersedes')
    original = deepcopy(value)
    _, record, reference = prepare_decision(value, [], {})
    assert record == {**original, 'supersedes': None}
    assert value == original and reference is None

@pytest.mark.parametrize('status', ['achieved', 'conditional_conflict', 'unresolved'])
def test_complete_authored_records_remain_valid_for_every_status(status):
    value = full_decision(status)
    validate(value, decision_schema())
    summary, record, reference = prepare_decision(value, [], {})
    assert summary == {k: value[k] for k in ('status', 'basis', 'next_step')}
    assert record == value and reference is None

def test_achieved_summary_needs_neither_a_dilemma_nor_supersession():
    value = {'status': 'achieved', 'basis': 'Scoped fixture result.', 'next_step': 'None.'}
    validate(value, decision_schema())
    assert prepare_decision(value, [], {}) == (value, None, None)
    with pytest.raises(ValueError, match='requires decision_basis'):
        prepare_decision({**value, 'supersedes': None}, [], {})
    with pytest.raises(ValidationError):
        validate({**value, 'supersedes': None}, decision_schema())

def test_explicit_full_revision_and_partial_reference_keep_authored_provenance():
    prior = ObservationEvent(source_agent='reasoner', observation_type='scientific_decision', payload=full_decision())
    changed = full_decision(supersedes=prior.event_id)
    changed['next_step'] = 'A changed authored next step.'
    validate(changed, decision_schema())
    assert prepare_decision(changed, [prior], {})[1] == changed
    reference = {'decision_ref': prior.event_id}
    validate(reference, decision_schema())
    assert prepare_decision(reference, [prior], {})[2] == prior.event_id
    patch = {**reference, 'updates': {'next_step': 'Only this authored field changes.'}}
    validate(patch, decision_schema(include_updates=True))
    record = prepare_decision(patch, [prior], {})[1]
    assert record['next_step'] == patch['updates']['next_step']
    assert record['decision_basis'] == prior.payload['decision_basis']
    assert record['supersedes'] == prior.event_id

@pytest.mark.parametrize('domain', ['color', 'enzyme'])
@pytest.mark.parametrize('tool_name,field', [('record_plan', 'decision'), ('finish', 'task_resolution')])
def test_reasoner_wire_forms_do_not_reintroduce_missing_full_record_fields(domain, tool_name, field):
    tool = next((t['function'] for t in role_tools('reasoner', domain) if t['function']['name'] == tool_name))
    schema = tool['parameters']['properties'][field]
    value = full_decision()
    value.pop('supersedes')
    with pytest.raises(ValidationError):
        validate(value, schema)
    validate(full_decision(), schema)
    validate({'status': 'achieved', 'basis': 'Scoped fixture.', 'next_step': 'None.'}, schema)
