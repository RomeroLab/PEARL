"""Public declared preparation cohorts, independent of chemistry and quality."""
from copy import deepcopy
from pearl.runtime.analysis_memory import calculation_measurements, calculation_records
from pearl.state.events import WorkingPlanDeclaredEvent
MAX_COHORTS = 128
MAX_MEMBERS = 4096
PURPOSES = {'report_candidate', 'diagnostic', 'control'}
DISPOSITIONS = {'pending', 'nonadopt'}

def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Cohort {name} must be nonempty text')

def _provenance(event):
    return {'event_id': event.event_id, 'trace_sequence': event.trace_sequence, 'timestamp': event.timestamp}

def _merge(state, updates, provenance):
    for update in updates:
        cid = update['cohort_id']
        if cid not in state:
            state[cid] = {'cohort_id': cid, 'purpose': update['purpose'], 'rationale': update['rationale'], 'declared_at': deepcopy(provenance), 'members': {}}
        cohort = state[cid]
        if cohort['purpose'] != update['purpose']:
            raise ValueError('Declared cohort purpose is immutable; dispose members explicitly. Keep the original purpose and record nonadopt with a rationale for members not used in the result. A different prospective cohort needs a distinct cohort_id; retain existing identities and evidence.')
        cohort['rationale'] = update['rationale']
        for member in update['members']:
            previous = cohort['members'].get(member['member_id'])
            if previous is not None:
                if previous['location'] != member['location']:
                    raise ValueError('Declared cohort member location is immutable')
                if previous['preparation_id'] is not None and previous['preparation_id'] != member['preparation_id']:
                    raise ValueError('Bound cohort preparation is immutable')
                if previous['disposition'] == 'nonadopt' and member['disposition'] == 'pending':
                    _text(member['rationale'], 'reinstatement rationale')
            row = deepcopy(member)
            row['declared_at'] = deepcopy(previous['declared_at'] if previous else provenance)
            row['bound_at'] = deepcopy(previous['bound_at'] if previous and previous['preparation_id'] is not None else provenance if member['preparation_id'] is not None else None)
            row['disposition_at'] = deepcopy(previous['disposition_at'] if previous and all((previous[key] == member[key] for key in ('disposition', 'rationale', 'evidence_ids'))) else provenance)
            cohort['members'][member['member_id']] = row
    if len(state) > MAX_COHORTS or sum((len(c['members']) for c in state.values())) > MAX_MEMBERS:
        raise ValueError('Declared cohort ledger exceeds its bounded member capacity')
    pending = set()
    for cohort in state.values():
        bound = set()
        for member in cohort['members'].values():
            prep = member['preparation_id']
            if prep is None:
                continue
            if prep in bound:
                raise ValueError('Use distinct preparation bindings within a cohort; duplicate independence claim')
            bound.add(prep)
            if cohort['purpose'] == 'report_candidate' and member['disposition'] == 'pending':
                if prep in pending:
                    raise ValueError('A preparation has duplicate pending report cohort obligations')
                pending.add(prep)

def _state(events):
    state = {}
    for event in events:
        if isinstance(event, WorkingPlanDeclaredEvent):
            _merge(state, event.working_plan.get('cohort_updates', []), _provenance(event))
    return state

def cohort_memory(events):
    """Return detached current memberships; omissions never retire members."""
    return [{**deepcopy(cohort), 'members': list(deepcopy(cohort['members']).values())} for cohort in _state(events).values()]

def _capture_preparations(events, evidence):
    """Bind acquired IDs to preceding acknowledged material changes, not mixes."""
    anchors, captures = ({}, {})
    for event in events:
        if getattr(event, 'source_agent', None) == 'actor' and getattr(event, 'tool_name', None) == 'transfer' and (getattr(event, 'executed', None) is True) and (event.result or {}).get('ok'):
            for location in (event.params['source'], event.params['target']):
                anchors[location] = event.event_id
        if getattr(event, 'observation_type', None) != 'camera':
            continue
        for row in event.payload.get('measurements', []):
            mid = row.get('measurement_id')
            if mid not in evidence:
                continue
            if mid in captures or row != evidence[mid]:
                raise ValueError('Cohort binding requires unaltered uniquely acquired camera evidence')
            location = row.get('location')
            captures[mid] = location + '@' + anchors[location] if isinstance(location, str) and location.startswith('plate:') and (location in anchors) else None
    return captures

def validate_updates(updates, events, evidence, locations):
    """Validate an entire notes-only update without changing events or inputs."""
    if not isinstance(updates, list) or len(updates) > MAX_COHORTS:
        raise ValueError('Cohort updates must be a bounded list')
    normalized = deepcopy(updates)
    captures = _capture_preparations(events, evidence)
    known_preparations = {pid for pid in captures.values() if pid is not None}
    cohort_ids = set()
    for update in normalized:
        if not isinstance(update, dict) or set(update) != {'cohort_id', 'purpose', 'rationale', 'members'}:
            raise ValueError('Declare cohort ID, purpose, rationale and members')
        _text(update['cohort_id'], 'ID')
        _text(update['rationale'], 'rationale')
        if not isinstance(update['purpose'], str) or update['purpose'] not in PURPOSES:
            raise ValueError('Choose report_candidate, diagnostic or control cohort purpose')
        if update['cohort_id'] in cohort_ids:
            raise ValueError('Use distinct cohort IDs within one update')
        cohort_ids.add(update['cohort_id'])
        if not isinstance(update['members'], list) or not update['members'] or len(update['members']) > MAX_MEMBERS:
            raise ValueError('Cohort members must be a bounded list')
        member_ids = set()
        for member in update['members']:
            if not isinstance(member, dict) or set(member) != {'member_id', 'location', 'preparation_id', 'disposition', 'rationale', 'evidence_ids'}:
                raise ValueError('Declare member ID, location, preparation binding, disposition, rationale and acquired evidence IDs')
            _text(member['member_id'], 'member ID')
            if member['member_id'] in member_ids:
                raise ValueError('Use distinct member IDs within a cohort update')
            member_ids.add(member['member_id'])
            if not isinstance(member['location'], str) or member['location'] not in locations:
                raise ValueError('Declare a known public member location')
            prep = member['preparation_id']
            if prep is not None and (not isinstance(prep, str) or prep not in known_preparations or (not prep.startswith(member['location'] + '@'))):
                raise ValueError('Bind the member to a known acquired preparation at its declared location')
            if not isinstance(member['disposition'], str) or member['disposition'] not in DISPOSITIONS:
                raise ValueError('Choose pending or nonadopt member disposition')
            if not isinstance(member['rationale'], str):
                raise ValueError('Member rationale must be text')
            if member['disposition'] == 'nonadopt':
                _text(member['rationale'], 'nonadopt rationale')
            ids = member['evidence_ids']
            if not isinstance(ids, list) or len(ids) > MAX_MEMBERS or any((not isinstance(mid, str) or mid not in evidence or mid not in captures for mid in ids)) or (len(set(ids)) != len(ids)):
                raise ValueError('Use distinct known acquired evidence IDs for cohort rationale: use camera measurement_id values, not event IDs or calculation IDs. Correct these references and resubmit the intended update; invalid records do not revise the scientific plan.')
    _merge(_state(events), normalized, None)
    return normalized

def adoption_coverage(calculation_ids, events, evidence, *, direct_measurement_ids=None):
    """Reconcile calculation ancestry and explicitly adopted direct observations."""
    direct = [] if direct_measurement_ids is None else direct_measurement_ids
    if not isinstance(direct, list) or any((not isinstance(mid, str) for mid in direct)):
        raise ValueError('Direct adoption requires a list of acquired measurement IDs')
    if not isinstance(calculation_ids, list) or any((not isinstance(cid, str) for cid in calculation_ids)) or len(set(calculation_ids)) != len(calculation_ids):
        raise ValueError('Use distinct recorded calculation IDs for cohort adoption')
    records = calculation_records(events)
    measurements = list(dict.fromkeys([*direct, *(mid for cid in calculation_ids for mid in calculation_measurements(cid, records))]))
    if any((mid not in evidence for mid in measurements)):
        raise ValueError('Cohort adoption references unknown acquired measurement IDs')
    captures = _capture_preparations(events, {mid: evidence[mid] for mid in measurements})
    if set(captures) != set(measurements):
        raise ValueError('Cohort adoption lacks acquired camera lineage')
    preparations = list(dict.fromkeys((captures[mid] for mid in measurements if captures[mid] is not None)))
    cohorts = cohort_memory(events)
    unresolved, conflicts = ([], [])
    for cohort in cohorts:
        for member in cohort['members']:
            row = {'cohort_id': cohort['cohort_id'], 'purpose': cohort['purpose'], **deepcopy(member)}
            present = member['preparation_id'] is not None and member['preparation_id'] in preparations
            if member['disposition'] == 'nonadopt' and present:
                conflicts.append(row)
            elif cohort['purpose'] == 'report_candidate' and member['disposition'] == 'pending' and (not present):
                unresolved.append(row)
    return {'cohorts': cohorts, 'adopted_calculation_ids': deepcopy(calculation_ids), 'adopted_measurement_ids': measurements, 'adopted_direct_measurement_ids': list(dict.fromkeys(direct)), 'adopted_preparation_ids': preparations, 'unresolved_members': unresolved, 'nonadopted_conflicts': conflicts, 'scope': 'Declared cohort accounting only; not a scientific justification, independence or quality verdict. Undeclared acquired observations are not automatically enrolled.'}

def validate_cohort_adoption(calculation_ids, events, evidence, *, direct_measurement_ids=None):
    """Validate achieved adoption; unresolved stopping uses coverage alone."""
    coverage = adoption_coverage(calculation_ids, events, evidence, direct_measurement_ids=direct_measurement_ids)
    if coverage['nonadopted_conflicts']:
        names = ', '.join((f"{row['cohort_id']}/{row['member_id']}" for row in coverage['nonadopted_conflicts']))
        raise ValueError('Adopted calculations include nonadopt cohort members: ' + names + '. Explicitly reinstate with a rationale before adoption.')
    if coverage['unresolved_members']:
        names = ', '.join((f"{row['cohort_id']}/{row['member_id']}" for row in coverage['unresolved_members']))
        raise ValueError('Unresolved report_candidate cohort members: ' + names + '. Bind adopted preparations or explicitly record nonadopt dispositions with rationale.')
    return coverage
