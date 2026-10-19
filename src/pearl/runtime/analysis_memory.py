"""Public, event-derived scientific decisions and acquired-analysis history."""
from copy import deepcopy
import uuid
from pearl.state.events import ObservationEvent
from pearl.runtime.analysis_advice import advice_memory, require_resolved
from pearl.runtime.analysis_coverage import observation_coverage
from pearl.runtime.notebook import action_history
RATE_TOOLS = {'analyze_measured_initial_rate', 'analyze_measured_course'}
KINETIC_TOOLS = RATE_TOOLS | {'analyze_measured_mm_rates'}
ACQUIRED_TOOLS = KINETIC_TOOLS | {'analyze_measured_endpoint_series'}
DECISION_TYPE = 'kinetic_evidence_decision'

def _course_summary(result):
    if 'course_diagnostics' not in result:
        return {}
    summary = deepcopy(result['course_diagnostics'])
    for half in ('early', 'late'):
        segment = summary['temporal_halves'][half]
        ids = segment.pop('measurement_ids')
        segment.update(first_measurement_id=ids[0] if ids else None, last_measurement_id=ids[-1] if ids else None)
    return {'course_diagnostics': summary}

def _precision_summary(result):
    precision = result.get('readout_precision')
    if precision is None:
        return {}
    ids = precision['measurement_ids']
    return {'readout_precision': {**deepcopy({key: value for key, value in precision.items() if key not in ('basis', 'measurement_ids')}), 'measurement_count': len(ids), 'first_measurement_id': ids[0] if ids else None, 'last_measurement_id': ids[-1] if ids else None}}

def active_exclusions(events):
    active = {}
    for event in events:
        if getattr(event, 'observation_type', None) != DECISION_TYPE:
            continue
        decision = event.payload
        for mid in decision['measurement_ids']:
            if decision['decision'] == 'exclude':
                active[mid] = deepcopy(decision)
            else:
                active.pop(mid, None)
    return active

def _ids(value, evidence):
    if not isinstance(value, list) or not value or len(value) > 4096 or any((not isinstance(i, str) or i not in evidence for i in value)) or (len(set(value)) != len(value)):
        raise ValueError('Use distinct acquired measurement IDs')
    return value

def target_ids(location, ids, evidence):
    """Bind affected observations to an explicitly declared public location."""
    if not isinstance(location, str) or not location.strip():
        raise ValueError('Declare a nonempty target location for the affected measurements')
    selected = _ids(ids, evidence)
    for mid in selected:
        actual = evidence[mid].get('location')
        if actual != location:
            raise ValueError(f'Measurement {mid} was acquired at {actual!r}, not declared target {location!r}. Check the acquired records and submit the intended target and IDs. No IDs were substituted.')
    return selected

def record_decision(board, role, args, evidence):
    if role != getattr(board, 'planning_role', 'reasoner'):
        raise ValueError('Only the planning agent can record a scientific evidence decision')
    if set(args) != {'location', 'measurement_ids', 'decision', 'rationale', 'evidence_ids'}:
        raise ValueError('A decision requires target location, measurement IDs, rationale and acquired evidence')
    ids = target_ids(args['location'], args['measurement_ids'], evidence)
    _ids(args['evidence_ids'], evidence)
    if args['decision'] not in ('exclude', 'reinstate'):
        raise ValueError('Decision must be exclude or reinstate')
    if not isinstance(args['rationale'], str) or not args['rationale'].strip():
        raise ValueError('A scientific rationale is required')
    active = active_exclusions(board.event_log)
    if args['decision'] == 'reinstate' and any((i not in active for i in ids)):
        raise ValueError('Reinstatement requires an active exclusion for every selected measurement')
    result = {**deepcopy(args), 'decision_id': uuid.uuid4().hex, 'scope': 'kinetic_analysis', 'supersedes': list(dict.fromkeys((active[i]['decision_id'] for i in ids if i in active)))}
    board.publish(ObservationEvent(source_agent=role, observation_type=DECISION_TYPE, payload=deepcopy(result)))
    return result

def calculation_records(events):
    return {e.result['calculation_id']: e for e in events if getattr(e, 'tool_name', None) in ACQUIRED_TOOLS and getattr(e, 'executed', None) is False and e.result.get('calculation_id')}

def calculation_measurements(cid, records, ancestors=()):
    if cid not in records or cid in ancestors:
        raise ValueError('Unknown or cyclic kinetic calculation lineage')
    result = records[cid].result
    ids = list(result.get('measurement_ids', [])) + list(result.get('blank_measurement_ids', []))
    for parent in result.get('rate_calculation_ids', []):
        ids.extend(calculation_measurements(parent, records, (*ancestors, cid)))
    return list(dict.fromkeys(ids))

def require_eligible(ids, events):
    require_resolved(ids, events)
    active = active_exclusions(events)
    conflicts = [i for i in dict.fromkeys(ids) if i in active]
    if conflicts:
        raise ValueError('Analysis includes explicitly excluded measurements: ' + ', '.join(conflicts) + '. Select a compatible interval/control or explicitly reinstate with a scientific rationale and acquired evidence. No points were silently removed.')

def validate_adoption(ids, events):
    if not isinstance(ids, list) or any((not isinstance(i, str) for i in ids)) or len(set(ids)) != len(ids):
        raise ValueError('Use distinct recorded calculation IDs')
    records = calculation_records(events)
    for cid in ids:
        if cid not in records or records[cid].result.get('status') != 'ok':
            raise ValueError('Unknown or nonqualifying kinetic calculation')
        timing = records[cid].result.get('comparison_timing_audit')
        if timing is not None and (timing['unresolved_fields'] or any((row['within_declared_tolerance'] is not True for row in timing['observations']))):
            raise ValueError('Selected endpoint calculation contradicts or leaves unresolved its declared comparison timing. Choose acquired matching inputs or explicitly reconsider the method in a new calculation; later notes do not rewrite this result.')
        require_eligible(calculation_measurements(cid, records), events)

def analysis_memory(events, evidence):
    active = active_exclusions(events)
    records = calculation_records(events)
    actions = action_history(events)
    rows = []
    for cid, event in records.items():
        result = event.result
        if event.tool_name == 'analyze_measured_endpoint_series':
            rows.append({'calculation_id': cid, 'source_agent': event.source_agent, 'tool': event.tool_name, **{key: deepcopy(result[key]) for key in ('status', 'axis', 'measurement_ids', 'blank_measurement_ids', 'blank_correction', 'blank_od', 'time_basis', 'comparison_rationale', 'bound_points', 'acquisition_context', 'replicate_summary', 'slope', 'intercept', 'r_squared', 'residuals', 'evidence_scope')}, 'excluded_measurement_ids': [i for i in calculation_measurements(cid, records) if i in active], **{key: deepcopy(result[key]) for key in ('fit_status', 'fit_reason', 'points_used', 'distinct_x', 'requirement_context') if key in result}, **({'endpoint_readout_precision': deepcopy({k: v for k, v in result['endpoint_readout_precision'].items() if k != 'basis'})} if 'endpoint_readout_precision' in result else {}), **({'comparison_timing_audit': deepcopy(result['comparison_timing_audit'])} if 'comparison_timing_audit' in result else {})})
            continue
        ids = result.get('measurement_ids', [])
        selection = result.get('course_selection', {})
        interval = selection.get('interval_observation_ids', ids)
        if all((mid in evidence and evidence[mid].get('captured_at_s') is not None for mid in interval)):
            interval = sorted(interval, key=lambda mid: evidence[mid]['captured_at_s'])
        first = evidence.get(interval[0], {}) if interval else {}
        last = evidence.get(interval[-1], {}) if interval else {}
        rows.append({'calculation_id': cid, 'source_agent': event.source_agent, 'tool': event.tool_name, 'status': result.get('status'), 'location': result.get('nominal_conditions', {}).get('location', selection.get('location', first.get('location'))), 'first_measurement_id': interval[0] if interval else None, 'last_measurement_id': interval[-1] if interval else None, 'start_s': first.get('captured_at_s'), 'end_s': last.get('captured_at_s'), 'input_points': len(ids), 'censored_points': len(selection.get('excluded_observations', [])), **({'interval_basis': deepcopy(selection['interval_basis']), 'selection_boundary_s': selection['boundary_s'], 'preceding_observation_ids': deepcopy(selection['preceding_observation_ids'])} if 'interval_basis' in selection else {}), **({'selection_diagnostics': deepcopy(result['selection_diagnostics'])} if 'selection_diagnostics' in result else {}), 'points_used': result.get('points_used'), 'v0_uM_per_s': result.get('v0_uM_per_s'), 'nominal_conditions': deepcopy(result.get('nominal_conditions')), 'stock_concentrations': deepcopy(result.get('stock_concentrations')), 'enzyme_concentration_bases': deepcopy(result.get('enzyme_concentration_bases')), 'kcat_basis': result.get('kcat_basis'), 'stock_references': {key: deepcopy(event.params[key]) for key in ('substrate_stock', 'enzyme_stock') if key in event.params} if event.tool_name in RATE_TOOLS else None, 'bound_rates': deepcopy(result.get('bound_rates')), **({'uncertainty': deepcopy(result['uncertainty'])} if 'uncertainty' in result else {}), **_course_summary(result), **_precision_summary(result), 'observation_coverage': observation_coverage(interval, evidence, active, actions) if event.tool_name in RATE_TOOLS else None, 'fit_statistics': {key: deepcopy(result[key]) for key in ('window_s', 'r2', 'conversion_fraction', 'slope_od_per_s', 'KM_uM', 'Vmax_uM_per_s', 'KM_se_uM', 'Vmax_se_uM_per_s', 'kcat_per_s', 'kcat_se_per_s', 'residuals', 'identifiability', 'levels_used') if key in result}, 'rate_calculation_ids': deepcopy(result.get('rate_calculation_ids', [])), 'excluded_measurement_ids': [i for i in calculation_measurements(cid, records) if i in active]})
    return {'scope': 'Recorded acquired assay calculations and explicit scientific decisions; not an automatic quality verdict. Each failure applies to its selected inputs, not all acquired history.', **({'readout_precision_basis': next((event.result['readout_precision']['basis'] for event in records.values() if event.result.get('readout_precision') is not None))} if any((event.result.get('readout_precision') is not None for event in records.values())) else {}), **({'endpoint_readout_precision_basis': next((event.result['endpoint_readout_precision']['basis'] for event in records.values() if event.result.get('endpoint_readout_precision') is not None))} if any((event.result.get('endpoint_readout_precision') is not None for event in records.values())) else {}), 'active_exclusions': active, 'peer_advice': advice_memory(events), 'decision_history': [deepcopy(e.payload) for e in events if getattr(e, 'observation_type', None) == DECISION_TYPE], 'calculations': rows}
