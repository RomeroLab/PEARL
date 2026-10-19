"""Numerical analysis of agent-selected acquired evidence, without acceptance gates."""
from copy import deepcopy
import math
import uuid
import numpy as np
from pearl.state.events import ToolCallEvent
from pearl.runtime.acquisition_context import acquisition_context
from pearl.runtime.analysis_memory import require_eligible, validate_adoption
from pearl.runtime.concentrations import declared_molarity
from pearl.runtime.measured_kinetics import _selected, _preparations, _molar
from pearl.runtime.course_diagnostics import describe_course

def scientific_tools(tools):
    tools = deepcopy(tools)
    for tool in tools:
        f = tool['function']
        if f['name'] in ('analyze_measured_color', 'simulate_measured_color_mix', 'analyze_measured_color_range'):
            fields = f['parameters']['properties']
            fields.pop('target_standard')
            fields['target_rgb'] = {'type': ['array', 'null'], 'items': {'type': 'number', 'minimum': 0, 'maximum': 255}, 'minItems': 3, 'maxItems': 3}
            fields['target_basis'] = {'type': ['string', 'null'], 'minLength': 1, 'maxLength': 4096}
            f['parameters']['required'].remove('target_standard')
            f['parameters']['required'] += ['target_rgb', 'target_basis']
            common = 'No named standards. Optional target_rgb is caller-proposed; or use acquired target_measurement_id. Explain target_basis; unused references null, no reference means null basis. No identity, validated colorimetry or scientific acceptance is inferred. '
            if f['name'] in ('simulate_measured_color_mix', 'analyze_measured_color_range'):
                fields['model'] = {'type': 'string', 'enum': ['volume_weighted_encoded_rgb_approximation', 'channel_transmittance_srgb']}
                if 'model' not in f['parameters']['required']:
                    f['parameters']['required'].append('model')
            description = {'analyze_measured_color': 'Describe acquired RGB/HEX/Lab and within-preparation frame spread; optionally calculate CIE76 to an explicit reference. Frames are not independent preparations. ', 'simulate_measured_color_mix': 'Choose a model for hypothetical mixing of acquired source IDs. Transmission uses public blank/dark and sRGB decoding; encoded RGB is an approximation. Not an acquired product. ', 'analyze_measured_color_range': 'Conditional chosen-model bounds over the entire fraction_bounds domain from two acquired source IDs: without a target, encoded RGB channel and pairwise difference bounds; with a target, CIE76 distance bounds. Requires model_applicability. Validation fractions are nominal. Not physical validation or a scientific verdict. '}
            f['description'] = description[f['name']] + common
        elif f['name'] == 'analyze_measured_course':
            fields = f['parameters']['properties']
            fields.pop('od_linear_max')
            fields['blank_correction'] = {'type': 'string', 'enum': ['none', 'subtract_mean']}
            f['parameters']['required'].remove('od_linear_max')
            f['parameters']['required'].append('blank_correction')
            f['description'] = 'Fit a line to ALL acquired observations in the caller-selected unchanged-preparation interval. Choose temporal anchors and interval_basis; null anchors mean the selected boundary/latest acquired observation. No accepted-window search, point removal or quality verdict. Censored observations cannot supply exact OD. Explicitly choose none (no blank IDs) or subtract_mean (acquired enzyme-free blanks matching nominal volume/substrate). Returns bound timestamps, optics, nominal concentrations, residuals, conditional uncertainty and fixed temporal-half slope diagnostics. Optical-equivalent/nominal-substrate ratios are conditional, not verified depletion. Diagnostics do not select or adopt rates. Two points permit arithmetic but cannot test linearity. Decide scientific suitability and limitations; status ok means numerical calculation only. Cite calculation_id when adopting; revised inputs need a new calculation.'
        elif f['name'] == 'analyze_measured_mm_rates':
            f['description'] = 'Fit apparent Michaelis-Menten parameters to selected recorded rate calculation IDs. Uses recorded nominal substrate/enzyme concentrations and all selected rates normalized by each nominal enzyme molarity. Reports residuals, numerical identifiability, conditional uncertainty and shared-input structure. Repeated calculations or frames are not independent preparations. No fixed level/replicate count or fit-quality gate; two distinct positive substrate levels are needed for two-parameter arithmetic, not proof of a valid experiment. status ok means numerical calculation only. Interpret the model, comparison and uncertainty before adoption.'
    return tools

def _number(value):
    return type(value) in (int, float) and math.isfinite(value)

def selected_course(args, evidence, events, setup):
    required = {'location', 'interval_basis', 'from_measurement_id', 'through_measurement_id', 'blank_measurement_ids', 'blank_correction', 'substrate_stock', 'enzyme_stock'}
    if not isinstance(args, dict) or set(args) != required:
        raise ValueError('Select acquired interval anchors, temporal rationale, blank strategy and stock references')
    if args['location'] not in {m['location'] for m in evidence.values()}:
        raise ValueError('Choose an acquired location')
    choice = args['interval_basis']
    if not isinstance(choice, dict) or set(choice) != {'basis', 'rationale'} or choice['basis'] not in ('after_preparation_change', 'after_preparation_mix', 'explicit_interval') or (not isinstance(choice['rationale'], str)) or (not choice['rationale'].strip()):
        raise ValueError('Declare a temporal basis and scientific rationale')
    rows = sorted((m for m in evidence.values() if m['location'] == args['location']), key=lambda m: m['captured_at_s'])
    end = evidence.get(args['through_measurement_id']) if args['through_measurement_id'] is not None else rows[-1]
    if end is None or end['location'] != args['location']:
        raise ValueError('Endpoint must be acquired at the chosen location')
    base = _preparations([end['measurement_id']], events, setup['reagents'])[end['measurement_id']]
    changed = base['last_change_completed_at_s']
    if changed is None:
        raise ValueError('Course requires acknowledged preparation lineage')
    boundary = changed
    if choice['basis'] == 'after_preparation_mix':
        boundary = base.get('last_mix_completed_at_s')
        if boundary is None or boundary < changed:
            raise ValueError('No current-preparation mix supports this interval')
    start = evidence.get(args['from_measurement_id']) if args['from_measurement_id'] is not None else None
    if args['from_measurement_id'] is not None and (start is None or start['location'] != args['location']):
        raise ValueError('Start must be acquired at the chosen location')
    if choice['basis'] == 'explicit_interval':
        if start is None:
            raise ValueError('explicit_interval requires an acquired start')
        boundary = start['captured_at_s']
    lower = start['captured_at_s'] if start is not None else boundary
    if not changed <= boundary <= lower <= end['captured_at_s']:
        raise ValueError('Interval anchors contradict the chosen preparation/temporal boundary')
    course = [m for m in rows if lower <= m['captured_at_s'] <= end['captured_at_s']]
    ids = [m['measurement_id'] for m in course]
    require_eligible(ids + args['blank_measurement_ids'], events)
    course = _selected(ids, evidence)
    blank_ids = args['blank_measurement_ids']
    if args['blank_correction'] == 'none':
        if blank_ids != []:
            raise ValueError('none requires no blank IDs')
        blanks = []
    elif args['blank_correction'] == 'subtract_mean':
        blanks = _selected(blank_ids, evidence)
    else:
        raise ValueError('Choose none or subtract_mean explicitly')
    context = acquisition_context(course + blanks, events, setup['reagents'])
    prep = _preparations(ids + blank_ids, events, setup['reagents'])
    if any((any((prep[m['measurement_id']][k] != base[k] for k in ('source_equivalents_ul', 'volume_ul', 'last_change_completed_at_s'))) for m in course)):
        raise ValueError('Choose one unchanged preparation interval')
    s0 = _molar(base, args['substrate_stock'], setup['reagents'])
    enzyme_nM = 1000 * _molar(base, args['enzyme_stock'], setup['reagents'])
    if not s0 > 0 or not enzyme_nM > 0:
        raise ValueError('Positive nominal substrate and enzyme required')
    for m in blanks:
        b = prep[m['measurement_id']]
        if not math.isclose(b['volume_ul'], base['volume_ul'], rel_tol=1e-09) or _molar(b, args['enzyme_stock'], setup['reagents']) != 0 or (not math.isclose(_molar(b, args['substrate_stock'], setup['reagents']), s0, rel_tol=1e-09)):
            raise ValueError('Unscaled blank subtraction requires matching volume/substrate and no nominal enzyme')
    times = [m['captured_at_s'] for m in course]
    ods = [m['od_estimate'] for m in course]
    cal = setup['calibration']
    epsilon = cal['epsilon_M_cm']
    path = cal['path_length_cm_per_100uL'] * base['volume_ul'] / 100
    if any((not _number(v) for v in times + ods + [epsilon, path, s0, enzyme_nM])) or min(epsilon, path) <= 0:
        raise ValueError('Finite acquired values and positive calibration required')
    if len(course) < 2 or len(set(times)) != len(times) or min(times) < 0:
        raise ValueError('Two or more distinct acquired times required for a numerical line')
    blank_od = math.fsum((m['od_estimate'] for m in blanks)) / len(blanks) if blanks else 0.0
    x = np.asarray(times, dtype=float)
    x = x - x[0]
    y = np.asarray(ods, dtype=float) - blank_od
    centered = x - x.mean()
    sxx = float(centered @ centered)
    slope = float(centered @ (y - y.mean()) / sxx)
    intercept = float(y.mean() - slope * x.mean())
    residual = y - (intercept + slope * x)
    sse = float(residual @ residual)
    sst = float((y - y.mean()) @ (y - y.mean()))
    dof = len(x) - 2
    se = math.sqrt(sse / dof / sxx) if dof > 0 else None
    scale = epsilon * path * 1e-06
    sigmas = [m.get('od_noise_sd_estimate') for m in course]
    noise_se = math.hypot(*(float(c) * sigma for c, sigma in zip(centered, sigmas))) / sxx if all((_number(s) and s >= 0 for s in sigmas)) else None
    selection = {'location': args['location'], 'interval_basis': deepcopy(choice), 'boundary_s': boundary, 'preparation_changed_at_s': changed, 'from_measurement_id': args['from_measurement_id'], 'through_measurement_id': end['measurement_id'], 'interval_observation_ids': list(ids), 'preceding_observation_ids': [m['measurement_id'] for m in rows if changed <= m['captured_at_s'] < lower], 'excluded_observations': [], 'basis': 'All acquired observations in the selected interval; no scientific quality selection.'}
    result = {'status': 'ok', 'analysis_method': 'selected_interval_linear_fit', 'scientific_acceptance': None, 'measurement_ids': list(ids), 'fitted_measurement_ids': list(ids), 'blank_measurement_ids': list(blank_ids), 'blank_correction': args['blank_correction'], 'points_used': len(x), 'window_s': [times[0], times[-1]], 'slope_od_per_s': slope, 'v0_uM_per_s': slope / scale, 'intercept_od_at_window_start': intercept, 'r2': 1 - sse / sst if sst > 0 else None, 'residuals': [{'measurement_id': mid, 'residual_od': float(r)} for mid, r in zip(ids, residual)], 'uncertainty': {'residual_degrees_of_freedom': dof, 'slope_se_od_per_s': se, 'rate_se_uM_per_s': se / scale if se is not None else None, 'assumptions': 'Conditional ordinary least squares with independent equal-variance residuals and fixed timestamps. Not calibration, timing, preparation or total uncertainty.'}, 'readout_precision': {'measurement_ids': list(ids), 'noise_slope_sd_od_per_s': noise_se, 'noise_rate_sd_uM_per_s': noise_se / scale if noise_se is not None else None, 'basis': 'Separate conditional propagation of declared independent per-reading OD noise SD. Shared constant blank offset cancels in slope; not total uncertainty.'}, 'course_diagnostics': describe_course(course, blank_od, scale, s0), 'bound_inputs': {'points': [{'time_s': t, 'absorbance': v} for t, v in zip(times, ods)], 'blank_od': blank_od, 'epsilon_M_cm': epsilon, 'path_length_cm': path, 'S0_uM': s0}, 'nominal_conditions': {'location': args['location'], 'volume_ul': base['volume_ul'], 'substrate_uM': s0, 'enzyme_nM': enzyme_nM}, 'stock_concentrations': {k: {'stock_reference': args[k], **declared_molarity(setup['reagents'][args[k]])} for k in ('substrate_stock', 'enzyme_stock')}, 'acquisition_context': context, 'course_selection': selection, 'limitations': 'A numerical line does not establish initial-rate suitability, chemical identity, comparable timing or linearity. Two points have no residual degrees of freedom. Repeat frames are not independent experimental preparations. Blank suitability and physical onset remain scientific judgments.'}
    return result

def selected_mm(args, events):
    if not isinstance(args, dict) or set(args) != {'rate_calculation_ids'}:
        raise ValueError('Choose recorded rate calculation IDs')
    ids = args['rate_calculation_ids']
    if not isinstance(ids, list) or not ids or len(ids) > 256:
        raise ValueError('Choose 1..256 distinct rate IDs')
    validate_adoption(ids, events)
    records = {e.result.get('calculation_id'): e.result for e in events if getattr(e, 'tool_name', None) == 'analyze_measured_course' and getattr(e, 'executed', None) is False and (e.result.get('analysis_method') == 'selected_interval_linear_fit')}
    if any((cid not in records for cid in ids)):
        raise ValueError('Choose current acquired interval rate calculations')
    rates = [records[cid] for cid in ids]
    conditions = [r['nominal_conditions'] for r in rates]
    ss = [r['substrate_uM'] for r in conditions]
    ee = [r['enzyme_nM'] * 0.001 for r in conditions]
    vv = [r['v0_uM_per_s'] for r in rates]
    if any((not _number(v) for v in ss + ee + vv)) or min(ss + ee) <= 0:
        raise ValueError('Finite rates and positive nominal concentrations required')
    if len(set(ss)) < 2:
        raise ValueError('Two distinct positive substrate levels needed to identify two parameters')
    s = np.asarray(ss)
    y = np.asarray(vv) / np.asarray(ee)
    lo = math.log(min(ss)) - math.log(1000000000.0)
    hi = math.log(max(ss)) + math.log(1000000000.0)

    def profile(z):
        km = math.exp(z)
        f = s / (km + s)
        amp = float(f @ y / (f @ f))
        residual = y - amp * f
        return (float(residual @ residual), amp, km)
    grid = sorted(set(np.linspace(lo, hi, 1025).tolist() + [math.log(v) for v in ss]))
    values = [profile(z)[0] for z in grid]
    candidates = [profile(lo), profile(hi)]
    ratio = (math.sqrt(5) - 1) / 2
    for i in range(1, len(grid) - 1):
        if values[i] > values[i - 1] or values[i] > values[i + 1]:
            continue
        a, b = (grid[i - 1], grid[i + 1])
        c = b - ratio * (b - a)
        d = a + ratio * (b - a)
        for _ in range(100):
            if profile(c)[0] <= profile(d)[0]:
                b, d = (d, c)
                c = b - ratio * (b - a)
            else:
                a, c = (c, d)
                d = a + ratio * (b - a)
        candidates.extend((profile(grid[i]), profile((a + b) / 2)))
    sse, kcat, km = min(candidates, key=lambda item: item[0])
    if kcat <= 0:
        raise ValueError('Supplied rates do not yield a positive apparent MM amplitude; this is not task impossibility')
    fitted = kcat * s / (km + s)
    residual = y - fitted
    j = np.column_stack((-kcat * s / (km + s) ** 2, s / (km + s)))
    rank = int(np.linalg.matrix_rank(j))
    condition = float(np.linalg.cond(j))
    dof = len(y) - 2
    overlaps = []
    for i, left in enumerate(rates):
        left_ids = set(left.get('measurement_ids', []) + left.get('blank_measurement_ids', []))
        for k in range(i + 1, len(rates)):
            right = rates[k]
            shared = sorted(left_ids & set(right.get('measurement_ids', []) + right.get('blank_measurement_ids', [])))
            if shared or conditions[i]['location'] == conditions[k]['location']:
                overlaps.append({'calculation_ids': [ids[i], ids[k]], 'shared_measurement_ids': shared, 'same_location': conditions[i]['location'] == conditions[k]['location']})
    covariance = None
    if dof > 0 and rank == 2 and (not overlaps):
        inverse = np.linalg.pinv(j)
        covariance = sse / dof * (inverse @ inverse.T)
    km_se = math.sqrt(max(0, float(covariance[0, 0]))) if covariance is not None else None
    kcat_se = math.sqrt(max(0, float(covariance[1, 1]))) if covariance is not None else None
    reference = float(np.mean(ee))
    sst = float((y - y.mean()) @ (y - y.mean()))
    rows = [{'substrate_uM': substrate, 'v0_uM_per_s': rate, 'enzyme_nM': enzyme * 1000, 'well': cond['location']} for substrate, rate, enzyme, cond in zip(ss, vv, ee, conditions)]
    result = {'status': 'ok', 'analysis_method': 'selected_rates_mm_fit', 'scientific_acceptance': None, 'rate_calculation_ids': deepcopy(ids), 'bound_rates': rows, 'optimizer': {'method': 'log_grid_bracketed_profile_least_squares', 'grid_points': len(grid), 'candidate_count': len(candidates), 'residual_sum_squares_per_s2': sse, 'scope': 'All bracketed grid minima and numerical boundaries compared; finite-grid search is not a proof of a unique global optimum or scientific adequacy.'}, 'KM_uM': km, 'kcat_per_s': kcat, 'Vmax_uM_per_s': kcat * reference, 'reference_enzyme_nM': reference * 1000, 'KM_se_uM': km_se, 'kcat_se_per_s': kcat_se, 'Vmax_se_uM_per_s': kcat_se * reference if kcat_se is not None else None, 'r2': 1 - sse / sst if sst > 0 else None, 'levels_used': len(set(ss)), 'residuals': [{'calculation_id': cid, 'residual_per_s': float(r)} for cid, r in zip(ids, residual)], 'uncertainty': {'residual_degrees_of_freedom': dof, 'assumptions': 'Equal-weight least squares on rate/nominal enzyme molarity. Conditional iid residual covariance only with positive residual degrees of freedom, full local rank and no detected shared inputs/locations. Absence of detected overlap does not establish independence. No total uncertainty or scientific acceptance.'}, 'identifiability': {'local_jacobian_rank': rank, 'local_jacobian_condition': condition if math.isfinite(condition) else None, 'substrate_range_uM': [min(ss), max(ss)], 'substrate_to_KM_range': [min(ss) / km, max(ss) / km], 'numerical_KM_search_range_uM': [math.exp(lo), math.exp(hi)], 'near_numerical_search_boundary': min(abs(math.log(km) - lo), abs(math.log(km) - hi)) < 1e-05}, 'shared_inputs': overlaps, 'preparation_location_count': len({c['location'] for c in conditions}), 'replicate_counts': {str(level): sum((r['substrate_uM'] == level for r in rows)) for level in sorted(set(ss))}, 'replicate_count_scope': 'Selected calculation rows, not independent experimental replication.', 'enzyme_concentration_bases': [r.get('stock_concentrations', {}).get('enzyme_stock') for r in rates], 'kcat_basis': 'Apparent turnover per declared nominal enzyme molarity; total protein or stock declaration does not measure active sites.', 'limitations': 'Numerical identifiability and residuals do not establish model adequacy, independence, active enzyme concentration, chemical comparability or task success. Search-boundary solutions require interpretation; no observations were selected or removed.'}
    return result

def record_analysis(run, role, name, args, result):
    result = deepcopy(result)
    result['calculation_id'] = uuid.uuid4().hex

    def finite_tree(value):
        if isinstance(value, float) and (not math.isfinite(value)):
            raise ValueError('Nonfinite numerical calculation')
        if isinstance(value, dict):
            for child in value.values():
                finite_tree(child)
        elif isinstance(value, list):
            for child in value:
                finite_tree(child)
    finite_tree(result)
    run.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=deepcopy(args), result=deepcopy(result), executed=False))
    return result
from pearl.runtime.agent_color import selected_color
