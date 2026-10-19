"""Explicit scientific time-basis claims bound to adopted acquired intervals."""
from copy import deepcopy
from collections.abc import Mapping
from pearl.runtime.analysis_memory import calculation_records, RATE_TOOLS
from pearl.runtime.notebook import action_history
from pearl.runtime.analysis_support import supporting_schema, supporting_observations, validate_supporting_basis, normalize_supporting_basis
BASES = ('after_preparation_change', 'after_preparation_mix', 'explicit_interval')

def basis_schema():
    return {'type': 'array', 'items': {'type': 'object', 'properties': {'rate_calculation_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'uniqueItems': True}, 'basis': {'type': 'string', 'enum': list(BASES)}, 'rationale': {'type': 'string'}, 'supporting_basis': supporting_schema()}, 'required': ['rate_calculation_ids', 'basis', 'rationale', 'supporting_basis'], 'additionalProperties': False}}

def public_copy(value):
    """Thaw immutable action parameters for the public report message."""
    if isinstance(value, Mapping):
        return {k: public_copy(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_copy(v) for v in value]
    return deepcopy(value)

def rate_ids(ids, records):
    leaves = []

    def visit(cid, ancestors):
        if cid not in records or cid in ancestors:
            raise ValueError('Unknown or cyclic adopted calculation lineage')
        record = records[cid]
        if record.tool_name in RATE_TOOLS:
            if cid not in leaves:
                leaves.append(cid)
        else:
            for parent in record.result.get('rate_calculation_ids', []):
                visit(parent, (*ancestors, cid))
    for cid in ids:
        visit(cid, ())
    return leaves

def adoption_intervals(ids, events, evidence):
    records = calculation_records(events)
    rows = []
    for cid in rate_ids(ids, records):
        record = records[cid]
        result = record.result
        window = result.get('window_s')
        if result.get('status') != 'ok' or not window or len(window) != 2:
            raise ValueError('Adopted rate lacks a qualifying acquired interval')
        if result.get('analysis_method') == 'selected_interval_linear_fit':
            ids = result.get('fitted_measurement_ids', [])
            if ids != result.get('measurement_ids') or len(set(ids)) != len(ids) or any((mid not in evidence for mid in ids)):
                raise ValueError('Adopted numerical fit lacks exact acquired ID lineage')
            selected = [evidence[mid] for mid in ids]
            acquired = [m for event in events[:events.index(record)] if getattr(event, 'observation_type', None) == 'camera' for m in event.payload.get('measurements', []) if m['measurement_id'] in ids]
            if len(acquired) != len(ids) or {m['measurement_id']: m for m in acquired} != {m['measurement_id']: m for m in selected}:
                raise ValueError('Adopted numerical fit requires unaltered unique acquired observations')
            if any((m.get('clipped') or m.get('od_estimate') is None or (not window[0] - 1e-08 <= m['captured_at_s'] <= window[1] + 1e-08) for m in selected)):
                raise ValueError('Adopted numerical fit contradicts its acquired interval')
            if result['bound_inputs']['points'] != [{'time_s': m['captured_at_s'], 'absorbance': m['od_estimate']} for m in selected]:
                raise ValueError('Adopted fitted inputs differ from acquired observations')
        else:
            selected = [evidence[mid] for mid in result.get('measurement_ids', []) if mid in evidence and (not evidence[mid].get('clipped')) and (evidence[mid].get('od_estimate') is not None) and (evidence[mid]['od_estimate'] <= result['bound_inputs']['od_linear_max']) and (window[0] - 1e-08 <= evidence[mid]['captured_at_s'] <= window[1] + 1e-08)]
        if not selected or len(selected) != result.get('points_used'):
            raise ValueError('Adopted fitted interval does not match acquired points')
        selected.sort(key=lambda m: m['captured_at_s'])
        location = result['nominal_conditions']['location']
        if any((m['location'] != location for m in selected)):
            raise ValueError('Adopted interval spans unexpected locations')
        prior = events[:events.index(record)]
        history = [h for h in action_history(prior, location) if h['completed_at_s'] is not None and h['completed_at_s'] <= selected[-1]['captured_at_s'] + 1e-08]
        change = next((h for h in reversed(history) if h['action'] == 'transfer'), None)
        mix = next((h for h in reversed(history) if h['action'] == 'mix'), None)
        changed = change['completed_at_s'] if change else None
        mixed = mix['completed_at_s'] if mix and (changed is None or mix['completed_at_s'] >= changed - 1e-08) else None
        rows.append({'calculation_id': cid, 'location': location, **({'calculation_interval_basis': deepcopy(result['course_selection']['interval_basis'])} if result.get('course_selection', {}).get('interval_basis') else {}), **({'selection_diagnostics': deepcopy(result['selection_diagnostics'])} if 'selection_diagnostics' in result else {}), 'supporting_observations': supporting_observations(record, events, evidence), 'declared_calibration': {k: result['bound_inputs'][k] for k in ('epsilon_M_cm', 'path_length_cm')}, 'first_fitted_measurement_id': selected[0]['measurement_id'], 'last_fitted_measurement_id': selected[-1]['measurement_id'], 'first_fitted_at_s': selected[0]['captured_at_s'], 'last_fitted_at_s': selected[-1]['captured_at_s'], 'preparation_changed_at_s': changed, 'preparation_mix_completed_at_s': mixed, 'basis': 'Acquired fitted interval and contemporaneous acknowledged commands; not physical homogeneity or automatic scientific validity.'})
    return rows

def validate_basis(assessments, intervals, *, required=True):
    if not intervals and assessments is None:
        return []
    if not isinstance(assessments, list):
        raise ValueError('Declare analysis_basis for the adopted rate calculations')
    if not required and (not assessments):
        return []
    expected = {row['calculation_id']: row for row in intervals}
    seen = set()
    supporting_choices = {}
    normalized = []
    for assessment in assessments:
        if not isinstance(assessment, dict) or set(assessment) != {'rate_calculation_ids', 'basis', 'rationale', 'supporting_basis'}:
            raise ValueError('Each analysis basis needs rate IDs, basis, rationale and supporting_basis')
        ids = assessment['rate_calculation_ids']
        if not isinstance(ids, list) or not ids or any((not isinstance(i, str) or i not in expected or i in seen for i in ids)) or (len(set(ids)) != len(ids)):
            raise ValueError('Use each adopted rate calculation exactly once in analysis_basis')
        mode = assessment['basis']
        if mode not in BASES or not isinstance(assessment['rationale'], str) or (not assessment['rationale'].strip()):
            raise ValueError('Declare a supported analysis basis and scientific rationale')
        support = [s for cid in ids for s in expected[cid]['supporting_observations']]
        recorded_inputs = {cid: expected[cid]['supporting_observations'] for cid in ids}
        supporting_basis = normalize_supporting_basis(assessment['supporting_basis'], recorded_inputs)
        choices = validate_supporting_basis(supporting_basis, support, recorded_inputs=recorded_inputs)
        for mid, choice in choices.items():
            if mid in supporting_choices and supporting_choices[mid] != choice:
                raise ValueError('Shared supporting observations need consistent temporal claims')
            supporting_choices[mid] = choice
        for cid in ids:
            row = expected[cid]
            declared = row.get('calculation_interval_basis')
            if declared is not None and mode != declared['basis']:
                raise ValueError(f'{cid}: adoption basis differs from the recorded calculation choice. Use a new calculation for a revised temporal premise; preserve the previous result.')
            field = {'after_preparation_change': 'preparation_changed_at_s', 'after_preparation_mix': 'preparation_mix_completed_at_s'}.get(mode)
            if field:
                boundary = row[field]
                if boundary is None:
                    raise ValueError(f'{cid}: no acknowledged boundary supports {mode}. Reconsider the scientific basis using acquired records.')
                if row['first_fitted_at_s'] < boundary - 1e-08:
                    raise ValueError(f"{cid}: fitted observation {row['first_fitted_measurement_id']} at {row['first_fitted_at_s']}s is before the declared {mode} boundary {boundary}s. Recalculate a justified interval or explicitly revise the scientific basis with rationale. No points were removed.")
            seen.add(cid)
        normalized.append({**deepcopy(assessment), 'supporting_basis': supporting_basis})
    if seen != set(expected):
        raise ValueError('analysis_basis must cover every adopted rate, including fit ancestors')
    return normalized

def basis_choices(assessments):
    return {'rates': {cid: row['basis'] for row in assessments for cid in row['rate_calculation_ids']}, 'support': {mid: support['basis'] for row in assessments for support in row['supporting_basis'] for mid in support['measurement_ids']}}
