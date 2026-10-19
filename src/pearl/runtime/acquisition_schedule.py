"""Advisory capture windows for caller-chosen locations and handling ages."""
from copy import deepcopy
import math
from pearl.runtime.acquisition_context import acquisition_context
from pearl.runtime.comparison_timing import timing_context, validate_timing
from pearl.runtime.notebook import action_history

def validate_locations(value, allowed):
    """An empty list clears the chosen scope; no locations are chosen here."""
    if not isinstance(value, list) or len(value) > len(allowed) or any((not isinstance(location, str) or location not in allowed for location in value)) or (len(set(value)) != len(value)):
        raise ValueError('Choose distinct declared acquisition locations, or [] to clear the scope')
    return list(value)

def _finite_nonnegative(value, name):
    valid = not isinstance(value, bool) and isinstance(value, (int, float))
    try:
        valid = valid and math.isfinite(value) and (value >= 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{name} must be a finite nonnegative number')
    return value

def acquisition_schedule(locations, declaration, events, evidence, setup, now_s):
    """Join public receipts and immutable frames without selecting or executing work."""
    chosen = validate_locations(locations, setup['locations'])
    declaration = validate_timing(declaration)
    now_s = _finite_nonnegative(now_s, 'Current clock')
    duration = _finite_nonnegative(setup['equipment']['capture_duration_s'], 'Declared capture duration')
    commands = action_history(events)
    by_id = {command['event_id']: command for command in commands}
    positions = {command['event_id']: index for index, command in enumerate(commands)}
    anchors = {location: {} for location in chosen}
    for command in commands:
        name, params = (command['action'], command['params'])
        if name not in ('transfer', 'mix'):
            continue
        affected = [params['location']] if name == 'mix' else [params['source'], params['target']]
        for location in affected:
            if location not in anchors:
                continue
            completed = command['completed_at_s']
            if completed is not None:
                _finite_nonnegative(completed, 'Acknowledged completion time')
            anchor = anchors[location]
            anchor['action'] = command['event_id']
            if name == 'mix':
                anchor['mix'] = command['event_id']
            else:
                anchor['change'] = command['event_id']
                if location == params['target']:
                    anchor['addition'] = command['event_id']
    measurements = [measurement for measurement in evidence.values() if measurement['location'] in anchors]
    acquired = acquisition_context(measurements, events, setup['reagents'])
    audit = timing_context(declaration, acquired)
    matches = {observation['measurement_id'] for observation in audit['observations'] if observation['within_declared_tolerance'] is True} if audit is not None else set()
    matching_by_context = {}
    for capture in acquired['captures']:
        ids = matching_by_context.setdefault(capture['command_context_id'], [])
        if capture['measurement_id'] in matches:
            ids.append(capture['measurement_id'])
    reference = declaration['reference'] if declaration is not None else None
    complete = declaration is not None and all((declaration[key] is not None for key in ('reference', 'target_age_s', 'tolerance_s')))

    def identity(location, command_id):
        return location + '@' + (command_id or 'initial')

    def reference_time(event_id):
        return by_id[event_id]['completed_at_s'] if event_id is not None else None
    histories = {location: [] for location in chosen}
    for preparation in acquired['preparations']:
        location = preparation['location']
        reference_id = preparation.get(f'last_{reference}_event_id')
        ids = matching_by_context.get(preparation['context_id'], [])
        histories[location].append({'command_context_id': preparation['context_id'], 'preparation_id': identity(location, preparation.get('last_change_event_id')), 'reference_event_id': reference_id, 'reference_completed_at_s': reference_time(reference_id), 'matching_measurement_count': len(ids), 'matching_measurement_ids': list(ids)})
    rows = []
    for location in chosen:
        anchor = anchors[location]
        reference_id = anchor.get(reference)
        completed = reference_time(reference_id)
        context_id = identity(location, anchor.get('action'))
        preparation_id = identity(location, anchor.get('change'))
        if not any((p['command_context_id'] == context_id for p in histories[location])):
            histories[location].append({'command_context_id': context_id, 'preparation_id': preparation_id, 'reference_event_id': reference_id, 'reference_completed_at_s': completed, 'matching_measurement_count': 0, 'matching_measurement_ids': []})
        start = end = earliest = wait = late = None
        if complete and completed is not None:
            start = _finite_nonnegative(completed + max(0, declaration['target_age_s'] - declaration['tolerance_s']), 'Capture window start')
            end = _finite_nonnegative(completed + declaration['target_age_s'] + declaration['tolerance_s'], 'Capture window end')
            earliest = _finite_nonnegative(now_s + duration, 'Earliest declared capture')
            wait = max(0, start - earliest)
            late = earliest > end + 1e-08
        change_id = anchor.get('change')
        changed = positions[change_id] > positions[reference_id] if change_id is not None and reference_id is not None else None
        rows.append({'location': location, 'preparation_id': preparation_id, 'command_context_id': context_id, 'reference_event_id': reference_id, 'reference_completed_at_s': completed, 'preparation_changed_after_reference': changed, 'capture_window_start_s': start, 'capture_window_end_s': end, 'earliest_capture_at_s': earliest, 'suggested_wait_s': wait, 'capture_would_be_late': late, 'historical_preparations': histories[location]})
    return {'declaration': deepcopy(declaration), 'rows': rows, 'scope': 'Caller-chosen locations and common-age premise only. Future times use acknowledged command references and declared capture duration, not measured reaction onset or guaranteed acquisition. Later material changes are disclosed without invalidating timing arithmetic. Historical matching IDs retain their acquisition preparation; zero matches do not exclude evidence or establish a need for replacement. Timing agreement does not establish scientific applicability, independent replication, eligibility or adoption. No locations, observations or actions are chosen or authorized.'}

def pending_schedule(events, evidence, setup, now_s, cohorts, proposed_action=None):
    """Retain prior public windows for bound pending report preparations only.

    Scope omission changes focus, not disposition. First binding can resolve an
    unbound intention; a later material stage cannot inherit an old deadline.
    This is a clock advisory, never an acquisition or scientific quality gate.
    """
    from pearl.state.events import WorkingPlanDeclaredEvent
    now_s = _finite_nonnegative(now_s, 'Current clock')
    duration = _finite_nonnegative(setup['equipment']['capture_duration_s'], 'Declared capture duration')
    commands = {c['event_id']: c for c in action_history(events)}
    anchors, choices, intents, unbound, ever_bound, captures = ({}, {}, {}, {}, set(), {})

    def stage(location):
        return location + '@' + anchors.get(location, {}).get('change', 'initial')

    def selection(location, declaration, event, first_binding=False):
        anchor = anchors.get(location, {})
        reference = declaration['reference'] if declaration is not None else None
        reference_id = anchor.get(reference)
        if reference_id is not None and commands[reference_id]['index'] < anchor.get('change_index', -1):
            reference_id = None
        if first_binding and reference == 'mix' and (anchor.get('mix_count_since_change', 0) != 1):
            reference_id = None
        return {'declaration_event_id': event.event_id, 'declaration': deepcopy(declaration), 'reference_event_id': reference_id, 'reference_completed_at_s': commands[reference_id]['completed_at_s'] if reference_id else None}
    for index, event in enumerate(events):
        command = commands.get(event.event_id)
        if command is not None:
            command['index'] = index
            name, params = (command['action'], command['params'])
            if name in ('transfer', 'mix'):
                locations = [params['location']] if name == 'mix' else [params['source'], params['target']]
                for location in locations:
                    anchor = anchors.setdefault(location, {})
                    if name == 'transfer':
                        anchor.update(change=event.event_id, change_index=index, mix_count_since_change=0)
                        if location == params['target']:
                            anchor['addition'] = event.event_id
                    else:
                        anchor['mix'] = event.event_id
                        anchor['mix_count_since_change'] = anchor.get('mix_count_since_change', 0) + 1
        if getattr(event, 'observation_type', None) == 'camera':
            for measurement in event.payload.get('measurements', []):
                mid = measurement.get('measurement_id')
                if mid in evidence and measurement == evidence[mid]:
                    captures.setdefault(stage(measurement['location']), []).append((mid, measurement.get('captured_at_s'), deepcopy(anchors.get(measurement['location'], {}))))
        if not isinstance(event, WorkingPlanDeclaredEvent):
            continue
        plan = event.working_plan
        for cohort in plan.get('cohort_updates', []):
            if cohort['purpose'] != 'report_candidate':
                continue
            for member in cohort['members']:
                location = member['location']
                member_key = (cohort['cohort_id'], member['member_id'])
                preparation = member.get('preparation_id')
                if preparation is None:
                    if member['disposition'] == 'pending':
                        unbound[member_key] = location
                    else:
                        unbound.pop(member_key, None)
                        intents.pop(member_key, None)
                    continue
                if member_key in unbound and location not in ever_bound and (member_key in intents):
                    declaration, declared_event = intents[member_key]
                    if preparation == stage(location):
                        choices[preparation] = selection(location, declaration, declared_event, first_binding=True)
                    else:
                        choices[preparation] = {'declaration_event_id': declared_event.event_id, 'declaration': deepcopy(declaration), 'reference_event_id': None, 'reference_completed_at_s': None}
                ever_bound.add(location)
                unbound.pop(member_key, None)
        if 'acquisition_locations' not in plan:
            continue
        locations = validate_locations(plan['acquisition_locations'], setup['locations'])
        declaration = validate_timing(plan.get('comparison_timing'))
        for location in locations:
            choices[stage(location)] = selection(location, declaration, event)
            if location not in ever_bound:
                for member_key, member_location in unbound.items():
                    if member_location == location:
                        intents[member_key] = (declaration, event)
    operation_duration = None
    if isinstance(proposed_action, dict):
        name = proposed_action.get('name')
        arguments = proposed_action.get('arguments', {})
        candidate = arguments.get('seconds') if name == 'wait' and isinstance(arguments, dict) else 0 if name == 'inspect' else setup['equipment'].get(name + '_duration_s') if name in ('transfer', 'mix') else None
        try:
            operation_duration = _finite_nonnegative(candidate, 'Proposed operation duration')
        except ValueError:
            pass
    pending = {}
    for cohort in cohorts:
        if cohort['purpose'] != 'report_candidate':
            continue
        for member in cohort['members']:
            preparation = member.get('preparation_id')
            if member['disposition'] != 'pending' or preparation not in choices:
                continue
            pending.setdefault(preparation, {'location': member['location'], 'members': []})['members'].append({'cohort_id': cohort['cohort_id'], 'member_id': member['member_id']})
    rows = []
    for preparation, membership in pending.items():
        chosen = choices[preparation]
        declaration = chosen['declaration']
        completed = chosen['reference_completed_at_s']
        complete = declaration is not None and all((declaration[k] is not None for k in ('reference', 'target_age_s', 'tolerance_s'))) and (completed is not None)
        start = end = None
        if complete:
            start = _finite_nonnegative(completed + max(0, declaration['target_age_s'] - declaration['tolerance_s']), 'Capture window start')
            end = _finite_nonnegative(completed + declaration['target_age_s'] + declaration['tolerance_s'], 'Capture window end')
        matches = [mid for mid, time, captured_anchors in captures.get(preparation, []) if start is not None and isinstance(time, (int, float)) and (not isinstance(time, bool)) and (time <= now_s + 1e-08) and (captured_anchors.get(declaration['reference']) == chosen['reference_event_id']) and (start - 1e-08 <= time <= end + 1e-08)]
        if matches:
            continue
        current = stage(membership['location'])
        current_reference = anchors.get(membership['location'], {}).get(declaration['reference']) if declaration is not None else None
        status = 'stale_preparation' if current != preparation else 'stale_reference' if complete and current_reference != chosen['reference_event_id'] else 'pending' if complete else 'unresolved'
        earliest = wait = allowance = late = after = after_late = None
        if status == 'pending':
            earliest = _finite_nonnegative(now_s + duration, 'Earliest declared capture')
            wait, allowance = (max(0, start - earliest), max(0, end - earliest))
            late = earliest > end + 1e-08
            if operation_duration is not None:
                after = _finite_nonnegative(earliest + operation_duration, 'Capture after proposed operation')
                after_late = after > end + 1e-08
        else:
            start = end = None
        rows.append({**deepcopy(membership), **deepcopy(chosen), 'preparation_id': preparation, 'current_preparation_id': current, 'current_reference_event_id': current_reference, 'status': status, 'capture_window_start_s': start, 'capture_window_end_s': end, 'earliest_capture_at_s': earliest, 'suggested_wait_s': wait, 'remaining_wait_allowance_s': allowance, 'capture_would_be_late': late, 'matching_measurement_count': 0, 'matching_measurement_ids': [], 'proposed_action_changes_preparation': membership['location'] in (proposed_action['arguments'].get('source'), proposed_action['arguments'].get('target')) if isinstance(proposed_action, dict) and proposed_action.get('name') == 'transfer' and isinstance(proposed_action.get('arguments'), dict) else None, 'capture_after_proposed_action_at_s': after, 'proposed_action_capture_would_be_late': after_late})
    candidates = _unbound_acquired_candidates(cohorts, unbound, intents, captures, commands, now_s)
    return {'rows': rows, **({'unbound_acquired_candidates': candidates, 'unbound_candidate_scope': 'Previously explicit acquisition intentions and actual archived timing matches only. Observed stages are not bound to intended members. No completion, comparability, quality, independence, adoption or action is inferred. ID samples are chronological, not quality-ranked; retrieve full records before use. An absent candidate does not establish archive absence or a need for replacement.'} if candidates else {}), 'scope': 'Previously chosen public timing scopes for explicitly bound pending report-candidate preparations only. Matching immutable acquired frames satisfy a window; omission does not retire a member. Stale or unresolved stages carry no future deadline. Times use acknowledged command references and declared operation/capture duration, not measured reaction onset. No acquisition, action, retirement, exclusion, adoption or scientific applicability is chosen or authorized.'}

def _unbound_acquired_candidates(cohorts, unbound, intents, captures, commands, now_s):
    """Expose retained caller intentions without turning observations into enrollment."""
    rows = []
    for cohort in cohorts:
        if cohort['purpose'] != 'report_candidate':
            continue
        for member in cohort['members']:
            key = (cohort['cohort_id'], member['member_id'])
            if member['disposition'] != 'pending' or member.get('preparation_id') is not None or key not in unbound or (key not in intents):
                continue
            declaration, event = intents[key]
            if declaration is None or any((declaration[k] is None for k in ('reference', 'target_age_s', 'tolerance_s'))):
                continue
            groups = {}
            for preparation, observations in captures.items():
                if not preparation.startswith(member['location'] + '@'):
                    continue
                for mid, time, anchor in observations:
                    reference_id = anchor.get(declaration['reference'])
                    reference = commands.get(reference_id)
                    if reference is None or reference['completed_at_s'] is None or reference['index'] < anchor.get('change_index', -1) or (not isinstance(time, (int, float))) or isinstance(time, bool) or (time > now_s + 1e-08):
                        continue
                    completed = reference['completed_at_s']
                    start = completed + max(0, declaration['target_age_s'] - declaration['tolerance_s'])
                    end = completed + declaration['target_age_s'] + declaration['tolerance_s']
                    if not start - 1e-08 <= time <= end + 1e-08:
                        continue
                    group = groups.setdefault((preparation, reference_id), {'observed_preparation_id': preparation, 'reference_event_id': reference_id, 'reference_completed_at_s': completed, 'matches': []})
                    group['matches'].append((time, mid))
            if not groups:
                continue
            matches = []
            for group in groups.values():
                ids = [mid for _, mid in sorted(group.pop('matches'))]
                matches.append({**group, 'matching_measurement_count': len(ids), 'measurement_id_sample': ids[:8], 'measurement_ids_omitted': max(0, len(ids) - 8)})
            rows.append({'cohort_id': cohort['cohort_id'], 'member_id': member['member_id'], 'location': member['location'], 'preparation_id': None, 'declaration_event_id': event.event_id, 'declaration': deepcopy(declaration), 'timing_matches': matches})
    return rows
