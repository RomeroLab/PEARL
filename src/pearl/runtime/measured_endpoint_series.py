"""Endpoint concentration fits bound to acquired optics and public commands."""
from copy import deepcopy
import math
from statistics import stdev
from pearl.brain.analysis_utilities import execute_utility
from pearl.runtime.acquisition_context import acquisition_context
from pearl.runtime.analysis_memory import require_eligible
from pearl.runtime.concentrations import MASS_TO_G_PER_L, MOLAR_TO_UM, PUBLIC_CONCENTRATION_FIELDS
from pearl.runtime.measured_kinetics import _selected
from pearl.runtime.measured_precision import endpoint_readout_precision

def measured_endpoint_series(args, evidence, events, setup):
    if set(args) != {'measurement_ids', 'blank_measurement_ids', 'concentration_stock', 'blank_correction', 'time_basis', 'comparison_rationale'}:
        raise ValueError('Choose acquired endpoints, controls, declared stock, time basis and comparison rationale; do not transcribe numeric observations')
    if not isinstance(args['comparison_rationale'], str) or not args['comparison_rationale'].strip():
        raise ValueError('State the scientific basis and limitations of the endpoint comparison')
    if not isinstance(args['time_basis'], str) or args['time_basis'] not in {'after_last_addition', 'after_last_mix', 'captured_at_s'}:
        raise ValueError('Choose an explicit recorded acquisition-time basis')
    if not isinstance(args['blank_correction'], str) or args['blank_correction'] not in {'none', 'subtract_mean'}:
        raise ValueError('Choose no correction or direct mean blank subtraction')
    samples = _selected(args['measurement_ids'], evidence)
    if args['blank_correction'] == 'none':
        if args['blank_measurement_ids'] != []:
            raise ValueError('No correction requires an empty blank input; controls are not silently ignored')
        blanks = []
    else:
        blanks = _selected(args['blank_measurement_ids'], evidence)
    ids = list(dict.fromkeys(args['measurement_ids'] + args['blank_measurement_ids']))
    require_eligible(ids, events)
    rows = [evidence[mid] for mid in ids]
    if any((type(m.get(key)) not in (int, float) or not math.isfinite(m[key]) for m in rows for key in ('od_estimate', 'captured_at_s'))):
        raise ValueError('Endpoint inputs require finite acquired optical values and timestamps')
    context = acquisition_context(rows, events, setup['reagents'])
    captures = {r['measurement_id']: r for r in context['captures']}
    conditions = {r['context_id']: r for r in context['preparations']}
    stock = args['concentration_stock']
    if not isinstance(stock, str):
        raise ValueError('Choose one declared stock reference')
    declaration = setup['reagents'].get(stock)
    if not declaration:
        raise ValueError('Choose a publicly declared concentration stock')
    value, unit = (declaration.get('concentration_value'), declaration.get('concentration_unit'))
    normalized_unit = unit.replace('µ', 'u').replace('μ', 'u') if isinstance(unit, str) else unit
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0 or (normalized_unit not in MOLAR_TO_UM.keys() | MASS_TO_G_PER_L.keys()):
        raise ValueError('A finite positive declared molar or mass/volume stock concentration is required; no activity or mixture-strength conversion is inferred')

    def condition(m):
        current = conditions[captures[m['measurement_id']]['command_context_id']]
        prep = current['nominal_preparation']
        if not prep or prep['volume_ul'] <= 0:
            raise ValueError('Endpoint requires a recorded nonempty nominal plate preparation')
        return (current, prep)
    for m in rows:
        condition(m)
    for blank in blanks:
        _, prep = condition(blank)
        if prep['source_equivalents_ul'].get(stock, 0) > 0:
            raise ValueError('Selected blank contains the nominal concentration-axis stock')
        if any((not math.isclose(prep['volume_ul'], condition(m)[1]['volume_ul'], rel_tol=1e-09) for m in samples)):
            raise ValueError('Unscaled blank subtraction requires matching sample and control volumes')
    blank_od = math.fsum((m['od_estimate'] for m in blanks)) / len(blanks) if blanks else 0.0
    order = {e.event_id: i for i, e in enumerate(events)}
    points, seen = ([], set())
    for m in samples:
        current, prep = condition(m)
        material_id = current['last_change_event_id']
        identity = (m['location'], material_id)
        if material_id is None or identity in seen:
            raise ValueError('Choose one endpoint per nominal preparation; repeated frames do not create independent endpoint replicates')
        seen.add(identity)
        basis = args['time_basis']
        if basis == 'captured_at_s':
            selected_time = m['captured_at_s']
        else:
            kind = 'mix' if basis == 'after_last_mix' else 'addition'
            selected_time = captures[m['measurement_id']][f'elapsed_since_{kind}_s']
            if selected_time is None:
                raise ValueError('Selected time basis lacks an acknowledged command anchor')
            if kind == 'mix' and order[current['last_mix_event_id']] <= order[material_id]:
                raise ValueError('Post-preparation mix basis requires a completed mix after the last material change')
        capture = captures[m['measurement_id']]
        addition_age = capture['elapsed_since_addition_s']
        mix_age = capture['elapsed_since_mix_s']
        points.append({'measurement_id': m['measurement_id'], 'location': m['location'], 'captured_at_s': m['captured_at_s'], 'selected_time_s': selected_time, 'preparation_id': m['location'] + '@' + material_id, 'command_context_id': current['context_id'], 'command_timing': {**{f'elapsed_since_{kind}_s': capture[f'elapsed_since_{kind}_s'] for kind in ('addition', 'mix', 'change')}, 'last_mix_minus_last_addition_s': addition_age - mix_age if addition_age is not None and mix_age is not None else None}, 'x': value * prep['source_equivalents_ul'].get(stock, 0) / prep['volume_ul'], 'raw_od': m['od_estimate'], 'y': m['od_estimate'] - blank_od})
    if any((not math.isfinite(p[key]) for p in points for key in ('x', 'y', 'selected_time_s'))):
        raise ValueError('Bound curve inputs must remain finite')
    distinct_x = len({p['x'] for p in points})
    if distinct_x < 2:
        result = {'status': 'insufficient_data', 'fit_status': 'unavailable', 'fit_reason': 'A concentration fit requires at least two distinct concentrations. Descriptive endpoint statistics remain available; they do not establish a concentration curve.', 'slope': None, 'intercept': None, 'r_squared': None, 'points_used': len(points), 'distinct_x': distinct_x}
    else:
        result = execute_utility('analyze_linear_series', {'points': [{'x': p['x'], 'y': p['y']} for p in points]})
        if result.get('status') != 'ok':
            raise ValueError('Selected endpoints do not define a numeric concentration fit: ' + str(result))
        result.update(fit_status='available', fit_reason=None)
    groups = []
    for concentration in sorted({p['x'] for p in points}):
        selected = [p for p in points if p['x'] == concentration]
        values = [p['y'] for p in selected]
        mean = math.fsum(values) / len(values)
        sd = stdev(values) if len(values) > 1 else None
        groups.append({'concentration': concentration, 'unit': unit, 'endpoints': len(selected), 'distinct_locations': len({p['location'] for p in selected}), 'distinct_preparations': len({p['preparation_id'] for p in selected}), 'measurement_ids': [p['measurement_id'] for p in selected], 'mean': mean, 'sample_sd': sd, 'cv_percent': 100 * sd / abs(mean) if sd is not None and mean != 0 else None})
    return {**result, 'axis': {'quantity': 'nominal_stock_concentration', 'unit': unit, 'stock_reference': stock, 'stock_declaration': {k: deepcopy(v) for k, v in declaration.items() if k in PUBLIC_CONCENTRATION_FIELDS}}, 'measurement_ids': deepcopy(args['measurement_ids']), 'blank_measurement_ids': deepcopy(args['blank_measurement_ids']), 'blank_correction': args['blank_correction'], 'blank_od': blank_od, 'time_basis': args['time_basis'], 'comparison_rationale': args['comparison_rationale'], 'bound_points': points, 'acquisition_context': context, 'replicate_summary': groups, 'requirement_context': {**{key: deepcopy(setup[key]) for key in ('objective', 'measurement_quality') if key in setup}, 'scope': 'Calculation-time public task declarations, copied with their conditions and exceptions. Missing fields remain unknown. These are not measured facts, an applicability judgment, an exclusion instruction or an acceptance verdict. Compare the relevant complete clauses with the selected evidence; later declarations do not rewrite this snapshot.'}, 'endpoint_readout_precision': endpoint_readout_precision(samples, blanks, setup['calibration']), 'residuals': [p['y'] - (result['intercept'] + result['slope'] * p['x']) for p in points] if result['fit_status'] == 'available' else None, 'evidence_scope': 'Acquired optical endpoints and command-derived nominal preparations; native declared concentration units are retained without inferring active fraction or molecular weight. Numerical fit is not assay quality, independent replication, matched chemical/temporal conditions, justified selection or task success. Control matrix and timing applicability remain scientific decisions. Historical inputs do not change when the clock or well contents change.'}
