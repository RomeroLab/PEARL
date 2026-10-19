"""Revisable peer proposals about acquired evidence, independent of action admission."""
from copy import deepcopy
import uuid
from pearl.state.events import ObservationEvent
PROPOSAL = 'kinetic_analysis_advice'
DISPOSITION = 'kinetic_analysis_advice_disposition'

def advice_memory(events):
    proposals = [deepcopy(e.payload) for e in events if getattr(e, 'observation_type', None) == PROPOSAL]
    dispositions = [deepcopy(e.payload) for e in events if getattr(e, 'observation_type', None) == DISPOSITION]
    resolved = {i for d in dispositions for i in d['advice_ids']}
    return {'proposals': proposals, 'pending': [p for p in proposals if p['advice_id'] not in resolved], 'dispositions': dispositions}

def validate_proposals(rows, evidence):
    from pearl.runtime.analysis_memory import _ids, target_ids
    if not isinstance(rows, list):
        raise ValueError('Analysis exclusions must be a list')
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {'location', 'measurement_ids', 'evidence_ids', 'rationale'}:
            raise ValueError('Analysis advice requires target location, acquired IDs, rationale and evidence')
        for field in ('measurement_ids', 'evidence_ids'):
            try:
                _ids(row[field], evidence)
            except ValueError as exc:
                raise ValueError(f'analysis_exclusions[{index}].{field}: provide at least one distinct acquired measurement ID') from exc
        target_ids(row['location'], row['measurement_ids'], evidence)
        if not isinstance(row['rationale'], str) or not row['rationale'].strip():
            raise ValueError('Analysis advice requires a rationale')
    return deepcopy(rows)

def publish_proposals(board, rows, review_id):

    def key(p):
        return (tuple(sorted(p['measurement_ids'])), tuple(sorted(p['evidence_ids'])))
    known = {key(p) for p in advice_memory(board.event_log)['proposals']}
    for row in rows:
        if key(row) in known:
            continue
        known.add(key(row))
        board.publish(ObservationEvent(source_agent='predictor', observation_type=PROPOSAL, payload={**deepcopy(row), 'advice_id': uuid.uuid4().hex, 'review_id': review_id}))

def respond(board, role, args, evidence):
    from pearl.runtime.analysis_memory import _ids, record_decision
    if role != getattr(board, 'planning_role', 'reasoner'):
        raise ValueError('Only the planning agent can dispose scientific analysis advice')
    if set(args) != {'advice_ids', 'decision', 'rationale', 'evidence_ids'}:
        raise ValueError('Disposition requires advice IDs, decision, rationale and evidence')
    available = {p['advice_id']: p for p in advice_memory(board.event_log)['pending']}
    try:
        ids = _ids(args['advice_ids'], available)
    except ValueError:
        raise ValueError('Choose distinct pending advice IDs') from None
    _ids(args['evidence_ids'], evidence)
    if args['decision'] not in ('accept', 'reject') or not isinstance(args['rationale'], str) or (not args['rationale'].strip()):
        raise ValueError('Accept or reject with a scientific rationale')
    if args['decision'] == 'accept':
        rows = validate_proposals([{key: available[i].get(key) for key in ('location', 'measurement_ids', 'evidence_ids', 'rationale')} for i in ids], evidence)
        grouped = {}
        for row in rows:
            grouped.setdefault(row['location'], []).extend(row['measurement_ids'])
        grouped = {location: list(dict.fromkeys(ids)) for location, ids in grouped.items()}
        for measurements in grouped.values():
            _ids(measurements, evidence)
        for location, measurements in grouped.items():
            record_decision(board, role, {'location': location, 'measurement_ids': measurements, 'decision': 'exclude', 'rationale': args['rationale'], 'evidence_ids': args['evidence_ids']}, evidence)
    result = {**deepcopy(args), 'disposition_id': uuid.uuid4().hex}
    board.publish(ObservationEvent(source_agent=role, observation_type=DISPOSITION, payload=deepcopy(result)))
    return result

def require_resolved(ids, events):
    selected = set(ids)
    conflicts = [p['advice_id'] for p in advice_memory(events)['pending'] if selected.intersection(p['measurement_ids'])]
    if conflicts:
        raise ValueError('Analysis uses measurements with unresolved peer advice: ' + ', '.join(conflicts) + '. Use respond_to_analysis_advice to accept or reject with acquired evidence and rationale, or choose unaffected inputs. No action executed and no observations removed.')
