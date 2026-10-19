"""Public arithmetic for a model-declared common-age comparison."""
from copy import deepcopy
import math

def timing_schema():
    number = {'type': ['number', 'null'], 'minimum': 0}
    return {'type': ['object', 'null'], 'description': "Optional chosen common-age comparison, not a universal assay requirement. Use null when no such comparison is selected. Null fields mean unresolved choices; no time or tolerance is supplied automatically. Applies only to this plan's explicitly cited observations.", 'properties': {'reference': {'type': ['string', 'null'], 'enum': ['addition', 'mix', 'change', None], 'description': 'Age since the last acknowledged command of this kind at acquisition, not measured reaction onset.'}, 'target_age_s': number, 'tolerance_s': number, 'rationale': {'type': 'string', 'minLength': 1}}, 'required': ['reference', 'target_age_s', 'tolerance_s', 'rationale'], 'additionalProperties': False}

def validate_timing(value):
    if value is None:
        return None
    fields = {'reference', 'target_age_s', 'tolerance_s', 'rationale'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('comparison_timing requires reference, target_age_s, tolerance_s and rationale, or null')
    if value['reference'] not in ('addition', 'mix', 'change', None):
        raise ValueError('Choose an acknowledged addition, mix or change reference, or null')
    for key in ('target_age_s', 'tolerance_s'):
        number = value[key]
        if number is None:
            continue
        valid = not isinstance(number, bool) and isinstance(number, (int, float))
        try:
            valid = valid and math.isfinite(number) and (number >= 0)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f'{key} must be a finite nonnegative number or null')
    if all((value[k] is not None for k in ('target_age_s', 'tolerance_s'))):
        try:
            finite_window = math.isfinite(value['target_age_s'] + value['tolerance_s'])
        except OverflowError:
            finite_window = False
        if not finite_window:
            raise ValueError('The declared timing window must have a finite representable upper age')
    if not isinstance(value['rationale'], str) or not value['rationale'].strip():
        raise ValueError('Explain the chosen comparison timing or unresolved choices')
    return deepcopy(value)

def timing_context(declaration, acquisition):
    if declaration is None:
        return None
    unresolved = [key for key in ('reference', 'target_age_s', 'tolerance_s') if declaration[key] is None]
    rows = []
    for capture in acquisition['captures']:
        elapsed = capture.get(f"elapsed_since_{declaration['reference']}_s")
        delta = None if elapsed is None or declaration['target_age_s'] is None else elapsed - declaration['target_age_s']
        within = None
        if not unresolved and delta is not None:
            within = abs(delta) <= declaration['tolerance_s'] + 1e-08
        rows.append({'measurement_id': capture['measurement_id'], 'command_context_id': capture['command_context_id'], 'preparation_id': capture.get('preparation_id'), 'elapsed_s': elapsed, 'deviation_s': delta, 'within_declared_tolerance': within})
    return {'declaration': deepcopy(declaration), 'unresolved_fields': unresolved, 'observations': rows, 'scope': "Arithmetic for explicitly cited observations at acquisition against the model's chosen common-age premise. Null is unresolved or lacks an acknowledged reference, not a match. Matching timing alone does not establish comparable chemistry, signal quality, independent replication, measured reaction onset, or final adoption. No observations are excluded and no actions are authorized by this check."}

def endpoint_timing_schema():
    value = timing_schema()
    value['description'] = 'Optional calculation-specific timing premise with explicitly scoped acquired measurement IDs. Null means no common-age premise for this calculation. If omitted, only selected IDs already cited by the active plan inherit its premise. Explain applicability and exceptions in comparison_rationale; controls need not share sample ages unless included in this scope.'
    value['properties']['measurement_ids'] = {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'uniqueItems': True}
    value['required'].append('measurement_ids')
    return value

def endpoint_timing_audit(selection, explicit, current, cited, selected_ids, acquisition):
    if explicit:
        if selection is None:
            return None
        if not isinstance(selection, dict) or 'measurement_ids' not in selection:
            raise ValueError('Calculation timing requires explicitly scoped measurement IDs')
        ids = selection['measurement_ids']
        if not isinstance(ids, list) or not ids or any((not isinstance(i, str) or i not in selected_ids for i in ids)) or (len(set(ids)) != len(ids)):
            raise ValueError('Calculation timing scope must contain distinct selected sample or control IDs')
        declaration = validate_timing({k: v for k, v in selection.items() if k != 'measurement_ids'})
        source = 'explicit_calculation_scope'
    else:
        declaration = validate_timing(current)
        ids = [i for i in selected_ids if i in {m['measurement_id'] for m in cited}]
        source = 'explicit_plan_references'
    if declaration is None or not ids:
        return None
    scoped = {**acquisition, 'captures': [r for r in acquisition['captures'] if r['measurement_id'] in ids]}
    result = timing_context(declaration, scoped)
    result.update(scope_measurement_ids=list(ids), scope_source=source)
    return result
