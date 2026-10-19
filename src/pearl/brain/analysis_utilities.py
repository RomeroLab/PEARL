"""Pure numerical tools: supplied data in, calculations out, no world access.

Results are calculations on the caller's data, not independent experimental
verification. No compiler, protocol card, executor, or evaluator input is read.
"""
from __future__ import annotations
import json
from math import isfinite
from typing import Any
from pearl.math.kinetics import RateRow, _linear_fit, fit_michaelis_menten, initial_rate

def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}

def _rows(properties: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'array', 'items': _object(properties), 'minItems': 1, 'maxItems': 256}
NUMBER = {'type': 'number'}
PARAMETERS = {'analyze_observed_color_range': _object({'first_color': {'type': 'array', 'minItems': 3, 'maxItems': 3, 'items': {'type': 'integer', 'minimum': 0, 'maximum': 255}}, 'second_color': {'type': 'array', 'minItems': 3, 'maxItems': 3, 'items': {'type': 'integer', 'minimum': 0, 'maximum': 255}}, 'target_lab': {'type': 'array', 'minItems': 3, 'maxItems': 3, 'items': NUMBER}, 'fraction_bounds': {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': {'type': 'number', 'minimum': 0, 'maximum': 1}}, 'model': {'type': 'string', 'enum': ['volume_weighted_encoded_rgb_approximation']}}), 'analyze_dilution_balance': _object({**{key: _object({'value': {'type': 'number', 'minimum': 0}, 'unit': {'type': 'string', 'enum': ['M', 'mM', 'uM', 'nM', 'pM']}}) for key in ('stock_concentration', 'target_concentration')}, **{key: {'type': 'number', 'minimum': 0} for key in ('final_volume_ul', 'current_stock_volume_ul', 'current_diluent_volume_ul', 'capacity_ul')}}), 'analyze_preparation_balance': _object({'current': {**_rows({'component': {'type': 'string'}, 'volume_ul': {'type': 'number', 'minimum': 0}}), 'minItems': 0}, 'target': _rows({'component': {'type': 'string'}, 'volume_ul': {'type': 'number', 'minimum': 0}}), 'capacity_ul': {'type': 'number', 'minimum': 0}}), 'analyze_measurement_schedule': _object({'available_locations': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 256, 'description': 'Full location inventory before exclusions, including all locations listed in unavailable_locations.'}, 'unavailable_locations': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 0, 'maxItems': 256, 'description': 'Locations excluded from use; must be a subset of available_locations. Use [] when none are excluded.'}, 'current_time_s': {'type': 'number', 'minimum': 0}, 'location_policy': {'type': 'string', 'enum': ['distinct_per_reading', 'reuse_within_course']}, 'courses': _rows({'id': {'type': 'string'}, 'start_time_s': {'type': 'number', 'minimum': 0}, 'readings': _rows({'location': {'type': 'string'}, 'time_s': {'type': 'number', 'minimum': 0}})})}), 'simulate_observed_color_mix': _object({'components': _rows({'id': {'type': 'string'}, 'volume_ul': NUMBER, 'color': {'type': ['string', 'array'], 'minItems': 3, 'maxItems': 3, 'items': {'type': 'integer', 'minimum': 0, 'maximum': 255}}}), 'target_hex': {'type': ['string', 'null']}, 'target_lab': {'type': ['array', 'null'], 'minItems': 3, 'maxItems': 3, 'items': NUMBER}}), 'analyze_color_difference': _object({'target_lab': _object({'L': {'type': 'number', 'minimum': 0, 'maximum': 100}, 'a': NUMBER, 'b': NUMBER}), 'readings': _rows({'id': {'type': 'string'}, **{channel: {'type': 'integer', 'minimum': 0, 'maximum': 255} for channel in ('b', 'g', 'r')}})}), 'analyze_linear_series': _object({'points': _rows({'x': NUMBER, 'y': NUMBER})}), 'analyze_initial_rate': _object({'points': _rows({'time_s': NUMBER, 'absorbance': NUMBER}), **{key: NUMBER for key in ('blank_od', 'epsilon_M_cm', 'path_length_cm', 'S0_uM', 'od_linear_max', 'min_window_r2', 'max_conversion_fraction')}}), 'analyze_mm_rates': _object({'rates': _rows({'substrate_uM': NUMBER, 'v0_uM_per_s': NUMBER, 'well': {'type': 'string'}, 'enzyme_nM': NUMBER}), 'min_levels': {'type': 'integer', 'minimum': 3, 'maximum': 32}, 'reference_enzyme_nM': {'type': ['number', 'null']}})}

def utility_schemas(*, include_color: bool=False) -> list[dict[str, Any]]:
    descriptions = {'analyze_dilution_balance': 'Calculate a caller-chosen nominal molar dilution using one stock and solute-free diluent only. Supply stock and target concentrations with units (M, mM, uM, nM, pM), desired final volume, existing stock-equivalent and diluent volumes, and capacity, all volumes in uL. Returns desired stock/diluent volumes and signed additions, including whether a partial preparation can reach that target by additions alone. Assumes conserved solute and additive volumes; other contents, chemical activity, available sources and execution feasibility are not inferred. Chooses no concentrations, wells or actions and grants no execution approval.', 'analyze_preparation_balance': 'Compare caller-supplied current and desired component volumes (uL) with a capacity. Returns signed target-minus-current amounts and whether additions alone suffice. Use consistent accounting labels, including existing contents; this does not infer chemical identity, source concentrations, stock availability, or a recipe.', 'analyze_measurement_schedule': 'Check your explicitly chosen course readings against supplied location inventory, unavailable locations, current time and course starts. All timestamps are absolute seconds in one clock. Returns elapsed times, counts, collisions, time-order issues and a chronological timeline grouping your chosen readings. wait_from_previous_s is the required clock advance from supplied current time or the preceding group; null means the reading is already in the past. Groups do not execute themselves; recheck against the public clock after interruption. Choose distinct_per_reading or reuse_within_course from the public layout requirement. It chooses no wells/times and does not advance time, prepare samples, enroll measurements or establish scientific sufficiency.', 'analyze_linear_series': 'Fit y = intercept + slope*x to supplied numerical observations. Return coefficients and fit statistics.', 'analyze_initial_rate': 'Estimate an initial rate from time_s and absorbance using the explicitly supplied calibration and window criteria.', 'analyze_mm_rates': 'Fit Michaelis-Menten parameters and uncertainty from supplied substrate concentrations and measured initial rates, accounting for enzyme concentration. Explain unmet fit and parameter identifiability conditions separately from curve agreement, with conditional design considerations.'}
    if include_color:
        descriptions['analyze_observed_color_range'] = 'Bound CIE76 distance across your chosen first-color fraction interval for two supplied RGB byte colors under model volume_weighted_encoded_rgb_approximation. Supply target_lab and fraction_bounds [low,high]. Returns a conservative model distance lower bound and an attainable model witness upper bound, separating simultaneous rounding alternatives. This is not a physical mixing law, model validation, acquired product or task verdict.'
        descriptions['simulate_observed_color_mix'] = 'Approximate a mixture from supplied component IDs, colors (#RRGGBB or [R,G,B] bytes), and positive volume_ul. Include existing destination contents if relevant. Accepts arbitrary source names; does not map them to canonical dye colors. Optionally compare with target_hex (#RRGGBB) or the public target_lab [L,a,b], not both. Use null for unavailable targets. Optical mixing may be nonlinear.'
        descriptions['analyze_color_difference'] = 'Compare observed byte BGR readings with target CIE Lab (L,a,b). Return CIE76 distance and signed observed-minus-target differences for L, a and b. No acceptance threshold or saturation/concentration diagnosis is inferred.'
    return [{'type': 'function', 'function': {'name': name, 'description': description + ' No acquisition/verification. Separate proposed/observed inputs; note missing inputs.', 'parameters': json.loads(json.dumps(PARAMETERS[name]))}} for name, description in descriptions.items()]

def _validate(value: Any, schema: dict[str, Any]) -> None:
    kind = schema['type']
    if isinstance(kind, list):
        for candidate in kind:
            try:
                _validate(value, {**schema, 'type': candidate})
                return
            except ValueError:
                pass
        raise ValueError('value does not match any allowed input type')
    if kind == 'null':
        if value is not None:
            raise ValueError('null is required')
        return
    if kind == 'object':
        if not isinstance(value, dict) or set(value) != set(schema['properties']):
            raise ValueError('supply exactly the named input fields')
        for key, child in schema['properties'].items():
            _validate(value[key], child)
    elif kind == 'array':
        if not isinstance(value, list) or not schema.get('minItems', 1) <= len(value) <= schema.get('maxItems', 256):
            raise ValueError('supply 1–256 data rows')
        for item in value:
            _validate(item, schema['items'])
    elif kind == 'string':
        if not isinstance(value, str) or not value or len(value) > 128:
            raise ValueError('row identifiers must be nonempty strings of at most 128 characters')
    else:
        if type(value) not in (int, float) or not isfinite(value):
            raise ValueError('numeric inputs must be finite numbers, not booleans')
        if kind == 'integer' and type(value) is not int:
            raise ValueError('an integer is required')
        if value < schema.get('minimum', float('-inf')) or value > schema.get('maximum', float('inf')):
            raise ValueError('numeric input outside the allowed range')

def _mm_scientific_readiness(result: dict[str, Any], rows: list[RateRow]) -> dict[str, Any]:
    """Explain the existing fit outcome; choose no recipe or acceptance criteria."""
    status = result['status']
    unmet = [name for name, passed in result['identifiability'].items() if passed is False]
    considerations = []
    if status == 'insufficient_levels':
        unmet.append('minimum_distinct_substrate_levels')
        interpretation = 'Too few distinct supplied substrate levels to assess the requested parameter fit.'
        considerations.append('Consider additional distinct informative substrate levels; repeated readings at one level do not extend coverage.')
    elif status == 'failed':
        unmet.append('fit_available')
        interpretation = 'No usable parameter fit was obtained; substrate coverage relative to fitted parameters cannot be assessed.'
        considerations.append('Review the supplied rates and their measured initial-rate windows before choosing further measurements.')
    else:
        if result['r2'] is not None and result['r2'] < 0.95:
            unmet.append('fit_r_squared_at_least_0_95')
        interpretation = "Supplied rates meet this calculation's fit and parameter identifiability checks; experimental evidence and task completion still require separate verification." if status == 'ok' else 'A fitted curve does not establish identifiable parameters under all calculation checks. High R² alone cannot resolve the listed unmet conditions.'
        if 'lowest_level_at_or_below_km' in unmet:
            considerations.append('Consider informative lower substrate levels to constrain the low-concentration response.')
        if {'highest_level_at_or_above_2km', 'vmax_approached'} & set(unmet):
            considerations.append('Consider informative higher substrate levels to test curvature and approach to the fitted plateau; treat fitted parameters as provisional design evidence.')
        if 'km_relative_se_below_0_5' in unmet:
            considerations.append('Review rate precision and substrate coverage; consider measurements that reduce parameter uncertainty.')
        if 'fit_r_squared_at_least_0_95' in unmet:
            considerations.append('Review residuals, initial-rate validity and model assumptions before interpreting fitted parameters.')
    return {'evidence_scope': 'caller_supplied_rates_not_verified', 'parameters_supported_by_supplied_rates': status == 'ok', 'unmet_conditions': unmet, 'supplied_substrate_range_uM': [min((row.substrate_uM for row in rows)), max((row.substrate_uM for row in rows))], 'interpretation': interpretation, 'design_considerations': considerations, 'feasibility_scope': 'Any additional measurement must fit public stock, capacity and layout limits. Plan enzyme amount, timing, blanks and replicates together to retain valid initial-rate windows and recovery space. Report unresolved insufficiency honestly; it does not fulfil a goal requiring parameter estimates.' if status != 'ok' else 'This calculation does not verify acquisition, initial-rate validity, public resource feasibility or final goal satisfaction.'}

def execute_utility(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        if name not in PARAMETERS:
            raise ValueError('unknown analysis utility')
        if name == 'simulate_observed_color_mix' and isinstance(arguments, dict):
            arguments = {'target_hex': None, 'target_lab': None, **arguments}
        _validate(arguments, PARAMETERS[name])
        if name in {'analyze_preparation_balance', 'analyze_measurement_schedule', 'analyze_dilution_balance'}:
            from pearl.brain.planning_calculations import preparation_balance, measurement_schedule, dilution_balance
            calculate = {'analyze_preparation_balance': preparation_balance, 'analyze_measurement_schedule': measurement_schedule, 'analyze_dilution_balance': dilution_balance}[name]
            result = {'status': 'ok', 'version': 'public-planning-calculation-v1', **calculate(arguments), 'evidence_status': 'caller_supplied_values_not_verified', 'execution_approved': False, 'cause_confirmed': False}
        elif name == 'analyze_observed_color_range':
            from pearl.math.public_color_range import analyze_color_range
            result = analyze_color_range(**arguments)
        elif name == 'simulate_observed_color_mix':
            from pearl.math.public_color_mix import mix_public_colors
            result = mix_public_colors(arguments['components'], arguments['target_hex'], arguments['target_lab'])
        elif name == 'analyze_color_difference':
            from pearl.eyes.color_calibration import ColorCalibrator
            rows = arguments['readings']
            if len({row['id'] for row in rows}) != len(rows):
                raise ValueError('colour reading identifiers must be distinct')
            target = tuple((arguments['target_lab'][key] for key in ('L', 'a', 'b')))
            comparisons = []
            for row in rows:
                lab = ColorCalibrator.bgr_to_lab(tuple((row[key] for key in ('b', 'g', 'r'))))
                comparisons.append({'id': row['id'], 'lab': list(lab), 'delta_e': ColorCalibrator.delta_e(lab, target), 'delta_L': lab[0] - target[0], 'delta_a': lab[1] - target[1], 'delta_b': lab[2] - target[2]})
            result = {'status': 'ok', 'version': 'public-color-calculation-v1', 'metric': 'CIE76', 'comparisons': comparisons, 'evidence_status': 'caller_supplied_values_not_verified', 'cause_status': 'unconfirmed'}
        elif name == 'analyze_linear_series':
            points = [(row['x'], row['y']) for row in arguments['points']]
            if len({x for x, _ in points}) < 2:
                raise ValueError('at least two distinct x values are required')
            slope, intercept, r2 = _linear_fit(points)
            result = {'status': 'ok', 'slope': slope, 'intercept': intercept, 'r_squared': r2 if len({y for _, y in points}) > 1 else None, 'points_used': len(points), 'distinct_x': len({x for x, _ in points})}
        elif name == 'analyze_initial_rate':
            kwargs = {key: value for key, value in arguments.items() if key != 'points'}
            if any((kwargs[key] <= 0 for key in ('epsilon_M_cm', 'path_length_cm', 'S0_uM', 'od_linear_max'))):
                raise ValueError('calibration factors, initial substrate and detector limit must be positive')
            if not 0 <= kwargs['min_window_r2'] <= 1 or not 0 < kwargs['max_conversion_fraction'] <= 1:
                raise ValueError('window r² and conversion fractions must lie in their physical ranges')
            points = [(row['time_s'], row['absorbance']) for row in arguments['points']]
            if any((t < 0 for t, _ in points)) or len({t for t, _ in points}) != len(points):
                raise ValueError('course times must be nonnegative and distinct')
            result = initial_rate(points, **kwargs).to_mapping()
        else:
            rows = [RateRow(**row) for row in arguments['rates']]
            if any((row.substrate_uM <= 0 or row.enzyme_nM <= 0 or row.v0_uM_per_s < 0 for row in rows)):
                raise ValueError('concentrations must be positive and rates nonnegative')
            reference = arguments['reference_enzyme_nM']
            if reference is not None and reference <= 0:
                raise ValueError('reference enzyme concentration must be positive')
            result = fit_michaelis_menten(rows, min_levels=arguments['min_levels'], reference_enzyme_nM=reference).to_mapping()
            result['scientific_readiness'] = _mm_scientific_readiness(result, rows)
        json.dumps(result, allow_nan=False)
        return result
    except (ValueError, TypeError, ArithmeticError) as exc:
        return {'status': 'invalid_input', 'message': str(exc)}
