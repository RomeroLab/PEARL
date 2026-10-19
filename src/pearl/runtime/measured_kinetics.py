"""Kinetic calculations bound to acquired observations and public command records."""
import math
from copy import deepcopy
from collections import Counter
from pearl.brain.analysis_utilities import execute_utility
from pearl.math.kinetics import initial_rate
from pearl.runtime.analysis import explain_initial_window
from pearl.runtime.notebook import preparation_summary
from pearl.runtime.concentrations import declared_molarity
from pearl.runtime.measured_precision import readout_precision

def _selected(ids, evidence):
    if isinstance(ids, list) and len(ids) > 4096:
        raise ValueError('At most 4096 acquired measurements per calculation; choose an explicit interval')
    if not isinstance(ids, list) or not ids or any((not isinstance(i, str) or i not in evidence for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('Choose distinct acquired measurement IDs')
    rows = [evidence[i] for i in ids]
    if any((m.get('clipped') or m.get('od_estimate') is None for m in rows)):
        raise ValueError('Clipped or non-optical observations cannot define a numeric rate')
    return rows

def _preparations(ids, events, reagents):
    wanted = set(ids)
    out = {}
    for index, event in enumerate(events):
        if getattr(event, 'observation_type', None) != 'camera':
            continue
        measurements = event.payload.get('measurements', [])
        matching = [m for m in measurements if m['measurement_id'] in wanted]
        if matching:
            summary = preparation_summary(events[:index], reagents)['wells']
            for m in matching:
                if m.get('overlapping_action_ids'):
                    raise ValueError('An observation overlapping a liquid operation lacks an unambiguous fixed preparation interval')
                prep = summary.get(m['location'])
                if not prep or prep['volume_ul'] <= 0:
                    raise ValueError('Measurement lacks an acknowledged plate preparation')
                out[m['measurement_id']] = prep
    if set(out) != wanted:
        raise ValueError('Missing public preparation lineage')
    return out

def _molar(prep, stock, reagents):
    if stock not in reagents:
        raise ValueError('Select a declared stock reference')
    return declared_molarity(reagents[stock])['stock_uM'] * prep['source_equivalents_ul'].get(stock, 0) / prep['volume_ul']

def select_rate_course(args, evidence, events, setup):
    required = {'location', 'from_measurement_id', 'through_measurement_id', 'blank_measurement_ids', 'substrate_stock', 'enzyme_stock', 'od_linear_max'}
    if set(args) not in (required, required | {'interval_basis'}):
        raise ValueError('Choose a location and acquired interval anchors, not sparse points')
    rows = [m for m in evidence.values() if m['location'] == args['location']]
    if not rows:
        raise ValueError('No acquired observations for location')
    end_id = args['through_measurement_id']
    end = rows[-1] if end_id is None else evidence.get(end_id)
    if not end or end['location'] != args['location']:
        raise ValueError('Endpoint must be an acquired observation at the selected location')
    prep = _preparations([end['measurement_id']], events, setup['reagents'])[end['measurement_id']]
    changed = prep['last_change_completed_at_s']
    if changed is None:
        raise ValueError('Course lacks an acknowledged preparation interval')
    start_id = args['from_measurement_id']
    start = evidence.get(start_id) if start_id is not None else None
    if start_id is not None and (not start or start['location'] != args['location'] or (not changed <= start['captured_at_s'] <= end['captured_at_s'])):
        raise ValueError("Start anchor must belong to the endpoint's preparation interval")
    choice = args.get('interval_basis')
    boundary = changed
    if 'interval_basis' in args:
        if not isinstance(choice, dict) or set(choice) != {'basis', 'rationale'} or choice.get('basis') not in ('after_preparation_change', 'after_preparation_mix', 'explicit_interval') or (not isinstance(choice.get('rationale'), str)) or (not choice['rationale'].strip()):
            raise ValueError('interval_basis needs a temporal basis and scientific rationale')
        if choice['basis'] == 'after_preparation_mix':
            mixed = prep.get('last_mix_completed_at_s')
            if mixed is None or mixed < changed:
                raise ValueError('No acknowledged current-preparation mix supports this interval basis')
            boundary = mixed
        elif choice['basis'] == 'explicit_interval':
            if start is None:
                raise ValueError('explicit_interval requires an acquired start anchor and rationale')
            boundary = start['captured_at_s']
        if start is not None and start['captured_at_s'] < boundary:
            raise ValueError('Start anchor precedes the selected temporal boundary; choose consistent inputs or revise the premise')
    lower = start['captured_at_s'] if start else boundary
    interval = [m for m in rows if lower <= m['captured_at_s'] <= end['captured_at_s']]
    selected, excluded = ([], [])
    for m in interval:
        reason = 'clipped' if m.get('clipped') else 'non_optical' if m.get('od_estimate') is None else None
        if reason:
            excluded.append({'measurement_id': m['measurement_id'], 'reason': reason})
        else:
            selected.append(m['measurement_id'])
    bound = {k: args[k] for k in required if k not in {'location', 'from_measurement_id', 'through_measurement_id'}}
    bound['measurement_ids'] = selected
    return (bound, {'location': args['location'], 'preparation_changed_at_s': changed, **({'interval_basis': deepcopy(choice), 'boundary_s': boundary, 'preceding_observation_ids': [m['measurement_id'] for m in rows if changed <= m['captured_at_s'] < lower and m['captured_at_s'] <= end['captured_at_s']]} if choice is not None else {}), 'from_measurement_id': start_id, 'through_measurement_id': end['measurement_id'], 'interval_observation_ids': [m['measurement_id'] for m in interval], 'excluded_observations': excluded, 'basis': 'Every acquired observation in the chosen unchanged-preparation interval; censored points are disclosed, never treated as numeric OD. Window quality is calculated separately.'})

def measured_initial_rate(args, evidence, events, setup):
    if set(args) != {'measurement_ids', 'blank_measurement_ids', 'substrate_stock', 'enzyme_stock', 'od_linear_max'}:
        raise ValueError('Use acquired course/blank IDs and declared stock references; do not transcribe time, OD or concentrations')
    course = _selected(args['measurement_ids'], evidence)
    blanks = _selected(args['blank_measurement_ids'], evidence)
    if len({m['location'] for m in course}) != 1:
        raise ValueError('One rate course must use one observed location')
    if len({m['captured_at_s'] for m in course}) < 3:
        raise ValueError('At least three distinct acquired times are required')
    prep = _preparations(args['measurement_ids'] + args['blank_measurement_ids'], events, setup['reagents'])
    base = prep[course[0]['measurement_id']]
    if any((prep[m['measurement_id']]['source_equivalents_ul'] != base['source_equivalents_ul'] or prep[m['measurement_id']]['last_change_completed_at_s'] != base['last_change_completed_at_s'] for m in course)):
        raise ValueError('Preparation changed during selected course; select a single preparation interval')
    s0 = _molar(base, args['substrate_stock'], setup['reagents'])
    enzyme = _molar(base, args['enzyme_stock'], setup['reagents']) * 1000
    if s0 <= 0 or enzyme <= 0:
        raise ValueError('Course requires positive nominal substrate and enzyme')
    for m in blanks:
        b = prep[m['measurement_id']]
        if not math.isclose(b['volume_ul'], base['volume_ul'], rel_tol=1e-09):
            raise ValueError('Blank and reaction volumes must match for this unscaled blank correction')
        if _molar(b, args['enzyme_stock'], setup['reagents']) > 0:
            raise ValueError('Selected blank contains nominal enzyme')
        blank_substrate = _molar(b, args['substrate_stock'], setup['reagents'])
        if not math.isclose(blank_substrate, s0, rel_tol=1e-09):
            raise ValueError(f"Blank {m['measurement_id']} has nominal substrate concentration {blank_substrate:g} uM; the reaction has {s0:g} uM. Direct unscaled blank correction requires matching substrate concentration, volume, and no nominal enzyme. Select compatible acquired blank measurements; equal optical readings alone do not establish matching preparation conditions.")
    quality = setup['measurement_quality']['initial_rate_if_used']
    cal = setup['calibration']
    bound = {'points': [{'time_s': m['captured_at_s'], 'absorbance': m['od_estimate']} for m in course], 'blank_od': sum((m['od_estimate'] for m in blanks)) / len(blanks), 'epsilon_M_cm': cal['epsilon_M_cm'], 'path_length_cm': cal['path_length_cm_per_100uL'] * base['volume_ul'] / 100, 'S0_uM': s0, 'od_linear_max': args['od_linear_max'], 'min_window_r2': quality['minimum_window_r_squared'], 'max_conversion_fraction': quality['maximum_substrate_conversion_fraction']}
    kwargs = {k: v for k, v in bound.items() if k != 'points'}
    points = [(p['time_s'], p['absorbance']) for p in bound['points']]
    numeric = list(kwargs.values()) + [v for point in points for v in point]
    if any((type(v) not in (int, float) or not math.isfinite(v) for v in numeric)):
        raise ValueError('Calculation inputs must be finite numbers')
    if any((kwargs[k] <= 0 for k in ('epsilon_M_cm', 'path_length_cm', 'S0_uM', 'od_linear_max'))):
        raise ValueError('Calibration, substrate and OD limit must be positive')
    if not 0 <= kwargs['min_window_r2'] <= 1 or not 0 < kwargs['max_conversion_fraction'] <= 1:
        raise ValueError('Quality thresholds are outside physical ranges')
    if any((t < 0 for t, _ in points)) or len({t for t, _ in points}) != len(points):
        raise ValueError('Acquired course times must be nonnegative and distinct')
    result = explain_initial_window(initial_rate(points, **kwargs).to_mapping(), bound)
    return {**result, 'readout_precision': readout_precision(course, result, bound, cal), 'bound_inputs': bound, 'measurement_ids': args['measurement_ids'], 'blank_measurement_ids': args['blank_measurement_ids'], 'stock_concentrations': {key: {'stock_reference': args[key], **declared_molarity(setup['reagents'][args[key]])} for key in ('substrate_stock', 'enzyme_stock')}, 'blank_substrate_uM': [_molar(prep[m['measurement_id']], args['substrate_stock'], setup['reagents']) for m in blanks], 'nominal_conditions': {'location': course[0]['location'], 'volume_ul': base['volume_ul'], 'substrate_uM': s0, 'enzyme_nM': enzyme}, 'basis': 'Exact acquired absolute timestamps and camera OD; concentrations and path length from declared calibration and acknowledged nominal preparations. Blank selection and chemical applicability require scientific interpretation.'}

def measured_mm(args, events, setup):
    if set(args) != {'rate_calculation_ids'}:
        raise ValueError('Select recorded rate calculation IDs only')
    ids = args['rate_calculation_ids']
    if not isinstance(ids, list) or not ids or len(ids) > 256 or any((not isinstance(i, str) for i in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('Choose distinct rate calculation IDs')
    found = {e.result.get('calculation_id'): e.result for e in events if getattr(e, 'tool_name', None) in ('analyze_measured_initial_rate', 'analyze_measured_course') and getattr(e, 'executed', None) is False and (e.result.get('status') == 'ok')}
    if any((i not in found for i in ids)):
        raise ValueError('Unknown or nonqualifying measured rate calculation')
    chosen = [found[i] for i in ids]
    wells = [r['nominal_conditions']['location'] for r in chosen]
    if len(set(wells)) != len(wells):
        raise ValueError('Repeated analyses of one well are not independent replicates')
    rows = [{'substrate_uM': r['nominal_conditions']['substrate_uM'], 'v0_uM_per_s': r['v0_uM_per_s'], 'well': r['nominal_conditions']['location'], 'enzyme_nM': r['nominal_conditions']['enzyme_nM']} for r in chosen]
    result = execute_utility('analyze_mm_rates', {'rates': rows, 'min_levels': setup['measurement_quality']['minimum_concentration_levels'], 'reference_enzyme_nM': None})
    result.update({'rate_calculation_ids': ids, 'bound_rates': rows, 'enzyme_concentration_bases': [r.get('stock_concentrations', {}).get('enzyme_stock') for r in chosen], 'kcat_basis': 'Vmax divided by the declared nominal enzyme molarity. A mass-derived denominator is total protein, not measured active sites; interpret turnover as apparent on that basis. Missing source basis does not establish active-site concentration.', 'replicate_counts': dict(Counter((r['substrate_uM'] for r in rows))), 'basis': 'Selected recorded acquired-data rate calculations; nominal concentrations. Curve fit is not independent confirmation of chemical identity or activity.'})
    return result

def course_selection_diagnostics(selection, result, evidence, events, setup):
    """Report conditional arithmetic at acquired boundaries, never select a window."""
    bound = result.get('bound_inputs')
    if not bound:
        return {'status': 'no_numeric_basis', 'selected_points': result.get('points_used'), 'basis': 'No bound optical and concentration calculation is available.'}
    interval = sorted((evidence[mid] for mid in selection['interval_observation_ids']), key=lambda m: m['captured_at_s'])
    rows = sorted((m for m in evidence.values() if m['location'] == selection['location']), key=lambda m: m['captured_at_s'])
    before = [m for m in rows if m['captured_at_s'] < interval[0]['captured_at_s']]
    after = [m for m in rows if m['captured_at_s'] > interval[-1]['captured_at_s']]
    fitted = result.get('readout_precision', {}).get('measurement_ids', [])
    points = {'first_in_requested_interval': interval[0], 'last_in_requested_interval': interval[-1], 'last_before_requested_interval': before[-1] if before else None, 'first_after_requested_interval': after[0] if after else None, 'first_in_fitted_prefix': evidence[fitted[0]] if fitted else None, 'last_in_fitted_prefix': evidence[fitted[-1]] if fitted else None}
    endpoint_id = interval[-1]['measurement_id']
    base = _preparations([endpoint_id], events, setup['reagents'])[endpoint_id]
    preparations = {endpoint_id: base}
    for m in points.values():
        if m is None or m['measurement_id'] in preparations:
            continue
        mid = m['measurement_id']
        try:
            preparations[mid] = _preparations([mid], events, setup['reagents'])[mid]
        except ValueError:
            preparations[mid] = None
    boundary = selection.get('boundary_s', selection['preparation_changed_at_s'])

    def point(m):
        if m is None:
            return None
        prep = preparations[m['measurement_id']]
        same = bool(prep and all((prep.get(k) == base.get(k) for k in ('last_change_completed_at_s', 'source_equivalents_ul', 'volume_ul'))))
        same_mix = bool(prep and prep.get('last_mix_completed_at_s') == base.get('last_mix_completed_at_s'))
        temporal = m['captured_at_s'] >= boundary
        od = m.get('od_estimate')
        numeric = type(od) in (int, float) and math.isfinite(od)
        status = 'different_preparation' if not same else 'outside_temporal_basis' if not temporal or not same_mix else 'censored' if m.get('clipped') else 'non_numeric' if not numeric else 'quantified'
        conversion = None
        if status == 'quantified':
            conversion = max(0.0, od - bound['blank_od']) / (bound['epsilon_M_cm'] * bound['path_length_cm'] * 1e-06 * bound['S0_uM'])
        return {'measurement_id': m['measurement_id'], 'location': m['location'], 'captured_at_s': m['captured_at_s'], 'od_estimate': od if numeric else None, 'clipped': bool(m.get('clipped')), **({'od_lower_bound': m['od_lower_bound']} if 'od_lower_bound' in m else {}), 'same_preparation': same, 'same_mix_stage': same_mix, 'at_or_after_temporal_boundary': temporal, 'numeric_status': status, 'conversion_fraction': conversion, 'conversion_limit_exceeded': conversion > bound['max_conversion_fraction'] if conversion is not None else None, 'optical_limit_exceeded': od > bound['od_linear_max'] if status == 'quantified' else None}
    return {'status': 'computed', **{name: point(m) for name, m in points.items()}, 'selected_points': result.get('points_used'), 'thresholds': {'maximum_conversion_fraction': bound['max_conversion_fraction'], 'od_linear_max': bound['od_linear_max']}, 'calculation_inputs': {k: bound[k] for k in ('blank_od', 'epsilon_M_cm', 'path_length_cm', 'S0_uM')}, 'basis': 'Acquired observations available at this calculation only. Conversion is total blank-corrected product divided by nominal initial substrate, not reset at the chosen start or mix. Comparisons use the bound declared optics, blank, nominal preparation and temporal stage. Requested interval and fitted prefix are distinct. Point flags do not establish interval linearity, chemical applicability, an exclusion reason or adoption; no window or narrative is changed.'}
