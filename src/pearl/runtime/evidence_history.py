"""Neutral landmarks of acquired evidence and acknowledged public commands.

This is a presentation index, not a quality assessment or selection policy.
Material identities follow transfers in event order; mixes change command
context but do not create a new material identity. Archive offsets follow the
canonical acquired-evidence insertion order used by read_measurements.
"""
from bisect import bisect_left, bisect_right
from copy import deepcopy
from pearl.runtime.acquisition_context import acquisition_context
from pearl.runtime.analysis_memory import calculation_measurements, calculation_records
from pearl.runtime.notebook import action_history
REFERENCE_FIELDS = ('working_plan', 'working_plan_observations', 'decision_memory', 'rejected_decision_memory', 'scientific_review_memory', 'pending_reviews', 'analysis_memory', 'recorded_analysis_intervals', 'color_comparison_memory', 'proposed_report', 'proposed_decision', 'proposed_action', 'cohort_memory')

def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)

def evidence_history_view(events, evidence, context):
    """Build detached facts using only public typed events and public context.

    Membership starts with all explicit cohort members, including unbound and
    nonadopted members. Acquired citations and explicitly referenced material
    identities add units. Values, fit quality and scenario names never select
    units or observations. Null anchors mean missing public records.
    """
    references = set(_strings({k: context[k] for k in REFERENCE_FIELDS if k in context}))
    calculations = calculation_records(events)
    for cid in references.intersection(calculations):
        references.update(calculation_measurements(cid, calculations))
    pinned = references.intersection(evidence)
    units = {}
    for cohort in context.get('cohort_memory', []):
        for member in cohort.get('members', []):
            location, pid = (member['location'], member.get('preparation_id'))
            key = (location, pid) if pid is not None else (cohort['cohort_id'], member['member_id'], None)
            row = units.setdefault(key, {'location': location, 'preparation_id': pid, 'declared_members': []})
            row['declared_members'].append({'cohort_id': cohort['cohort_id'], 'purpose': cohort['purpose'], 'member': deepcopy(member)})
    if not units and (not pinned) and (not any(('@' in ref for ref in references))):
        return None
    offsets, counts = ({}, {})
    for mid, record in evidence.items():
        location = record['location']
        offsets[mid] = counts.get(location, 0)
        counts[location] = offsets[mid] + 1
    observations, positions, commands, material, stages, acquired = ({}, {}, {}, {}, {}, {})
    for seq, event in enumerate(events):
        for command in action_history([event]):
            action, params = (command['action'], command['params'])
            if action not in ('transfer', 'mix'):
                continue
            affected = [params['location']] if action == 'mix' else list(dict.fromkeys([params['source'], params['target']]))
            for location in affected:
                commands.setdefault(location, []).append((seq, command))
                if action == 'transfer':
                    pid = location + '@' + event.event_id
                    material[location] = pid
                    stages[location, pid] = seq
        if getattr(event, 'observation_type', None) != 'camera':
            continue
        for record in event.payload.get('measurements', []):
            mid, location = (record['measurement_id'], record['location'])
            if mid not in evidence:
                continue
            if mid in acquired or record != evidence[mid]:
                raise ValueError('Evidence history requires uniquely acquired, unaltered camera records')
            pid = material.get(location)
            acquired[mid] = (location, pid)
            observations.setdefault(location, []).append((seq, mid))
            positions.setdefault(location, []).append(seq)
    unresolved = [{'measurement_id': mid, 'location': evidence[mid]['location'], 'reason': 'missing_public_camera_event'} for mid in evidence if mid in pinned and mid not in acquired]
    for location, pid in stages:
        if pid in references:
            units.setdefault((location, pid), {'location': location, 'preparation_id': pid, 'declared_members': []})
    for mid in evidence:
        if mid in pinned and mid in acquired:
            location, pid = acquired[mid]
            units.setdefault((location, pid), {'location': location, 'preparation_id': pid, 'declared_members': []})
    if not units and (not unresolved):
        return None
    selected_global = set()
    for row in units.values():
        location, pid = (row['location'], row['preparation_id'])
        rows = observations.get(location, [])
        seqs = positions.get(location, [])
        bound = (location, pid) in stages
        initial = pid is None and (not row['declared_members'])
        start = stages.get((location, pid), -1)
        changes = [(seq, cmd) for seq, cmd in commands.get(location, []) if cmd['action'] == 'transfer' and seq > start]
        end, closing = changes[0] if (bound or initial) and changes else (len(events), None)
        stage_rows = rows[bisect_right(seqs, start):bisect_left(seqs, end)] if bound or initial else []
        boundary_rows = [(seq, cmd) for seq, cmd in commands.get(location, []) if (bound or initial) and start <= seq < end]
        if closing is not None:
            boundary_rows.append((end, closing))
        selected = {mid for _, mid in stage_rows if mid in pinned}
        if stage_rows:
            selected.add(stage_rows[-1][1])
        boundaries = []
        for seq, command in boundary_rows:
            before = bisect_left(seqs, seq) - 1
            after = bisect_right(seqs, seq)
            before_id = rows[before][1] if before >= 0 else None
            after_end = next((pos for pos, cmd in commands.get(location, []) if pos > seq and cmd['action'] == 'transfer'), len(events))
            after_id = rows[after][1] if after < len(rows) and rows[after][0] < after_end else None
            boundaries.append({'command': deepcopy(command), 'before_measurement_id': before_id, 'after_measurement_id': after_id})
            selected.update((mid for mid in (before_id, after_id) if mid is not None))
        row['binding_status'] = 'public_transfer_bound' if bound else 'initial_acquired_history' if initial else 'unbound_declaration'
        row['boundaries'] = boundaries
        row['next_material_change'] = deepcopy(closing)
        row['pinned_measurement_ids'] = [mid for _, mid in stage_rows if mid in pinned]
        row['observations'] = [deepcopy(evidence[mid]) for _, mid in rows if mid in selected]
        row['acquired_count'] = len(stage_rows)
        row['shown_in_stage_count'] = sum((mid in selected for _, mid in stage_rows))
        row['omitted_ranges'] = []
        gap = []

        def flush_gap():
            if not gap:
                return
            first, last = (gap[0], gap[-1])
            row['omitted_ranges'].append({'count': len(gap), 'first_measurement_id': first, 'last_measurement_id': last, 'first_captured_at_s': evidence[first]['captured_at_s'], 'last_captured_at_s': evidence[last]['captured_at_s'], 'read_tool': 'read_measurements', 'read_arguments': {'location': location, 'offset': offsets[first], 'limit': min(64, len(gap))}, 'through_offset_exclusive': offsets[last] + 1})
            gap.clear()
        for _, mid in stage_rows:
            if mid in selected:
                flush_gap()
            else:
                if gap and offsets[mid] != offsets[gap[-1]] + 1:
                    flush_gap()
                gap.append(mid)
        flush_gap()
        selected_global.update(selected)
    selected_records = [record for mid, record in evidence.items() if mid in selected_global]
    return {'coverage': 'landmarks_and_explicit_references_not_complete_courses', 'basis': 'Declared membership and acquired citations, ordered by public events. Command boundaries and nominal composition do not establish physical onset, delivery, mixing or scientific suitability. Missing anchors remain null; omitted interiors remain unexamined. No quality, cause, exclusion or recovery judgment is supplied.', 'selection': 'Last acquired observation before and first after acknowledged material/mix boundaries, last available observation in each material stage, and acquired references. Before/after anchors may belong to neighboring preparations; their acquisition contexts are authoritative.', 'archive_scope': 'read_measurements offsets are per-location canonical insertion order. Stop each omitted range at through_offset_exclusive; request at most 64 or the remaining count per page. Records and original public events remain unchanged.', 'units': list(units.values()), 'unresolved_camera_references': unresolved, 'acquisition_context': acquisition_context(selected_records, events, context['setup']['reagents'])}
