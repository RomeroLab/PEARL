"""Model-authored experimental conditions and explicit, evidence-scoped revisions."""
from copy import deepcopy
from pearl.runtime.observation_references import ACQUIRED_IDS_DESCRIPTION
EXPERIMENT_FIELDS = {'question', 'completion_conditions', 'comparison_conditions', 'early_stop_conditions'}
CHANGE_TEXT = {'observed_stage', 'comparison_basis', 'challenged_premise', 'rationale', 'recovery_scope'}
CHANGE_IDS = {'evidence_ids', 'reusable_evidence_ids'}
IMPACTS = ('safety', 'validity', 'goal', 'uncertainty')

def experiment_properties():
    text = {'type': 'string', 'minLength': 1}
    ids = {'type': 'array', 'items': text, 'uniqueItems': True, 'description': ACQUIRED_IDS_DESCRIPTION}
    fields = CHANGE_TEXT | CHANGE_IDS | {'impact'}
    return {'experiment': {'type': 'object', 'properties': {k: text for k in sorted(EXPERIMENT_FIELDS)}, 'required': sorted(EXPERIMENT_FIELDS), 'additionalProperties': False}, 'experiment_change': {'type': 'object', 'properties': {**{k: text for k in sorted(CHANGE_TEXT)}, **{k: ids for k in sorted(CHANGE_IDS)}, 'impact': {'type': 'string', 'enum': list(IMPACTS)}}, 'required': sorted(fields), 'additionalProperties': False}}

def _text_object(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields or any((not isinstance(value[k], str) or not value[k].strip() for k in fields)):
        raise ValueError(f'Invalid {label} conditions')

def validate_experiment(basis, current, evidence):
    if 'experiment' in basis:
        _text_object(basis['experiment'], EXPERIMENT_FIELDS, 'experiment')
    previous = current['decision'].get('decision_basis', {}).get('experiment') if current else None
    changed = previous is not None and basis.get('experiment') != previous
    if changed and 'experiment_change' not in basis:
        raise ValueError('Changing or withdrawing declared conditions requires experiment_change')
    if 'experiment_change' not in basis:
        return
    if previous is None:
        raise ValueError('experiment_change requires conditions in the current decision; previous_experiment is superseded history')
    value = basis['experiment_change']
    if not isinstance(value, dict) or set(value) != CHANGE_TEXT | CHANGE_IDS | {'impact'}:
        raise ValueError('Invalid experiment_change fields')
    _text_object({k: value[k] for k in CHANGE_TEXT}, CHANGE_TEXT, 'experiment_change')
    if value['impact'] not in IMPACTS:
        raise ValueError('Invalid experiment_change impact')
    for key in CHANGE_IDS:
        ids = value[key]
        if not isinstance(ids, list) or any((not isinstance(i, str) or i not in evidence for i in ids)) or len(set(ids)) != len(ids):
            raise ValueError('experiment_change requires distinct acquired evidence IDs')

def previous_experiment(record, events):
    """Expose the directly superseded commitment, without interpreting its validity."""
    reference = record.get('supersedes')
    for event in reversed(events):
        if event.event_id == reference and getattr(event, 'source_agent', None) in ('reasoner', 'predictor', 'actor') and (getattr(event, 'observation_type', None) == 'scientific_decision'):
            experiment = event.payload.get('decision_basis', {}).get('experiment')
            if experiment is not None:
                return {'event_id': reference, 'experiment': deepcopy(experiment)}
            break
    return None
