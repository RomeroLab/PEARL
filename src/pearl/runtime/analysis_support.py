"""Public provenance and model-owned eligibility for adopted correction inputs."""
from copy import deepcopy
from collections import Counter
from pearl.runtime.notebook import action_history
SUPPORT_BASES = ('after_preparation_change', 'after_preparation_mix', 'explicit_interval')

def supporting_schema():
    common = {'basis': {'type': 'string', 'enum': list(SUPPORT_BASES)}, 'rationale': {'type': 'string'}}
    selectors = {'measurement_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'uniqueItems': True}, 'calculation_input_refs': {'type': 'array', 'minItems': 1, 'uniqueItems': True, 'description': 'Recorded blanks only; no basis, applicability, rationale or independence.', 'items': {'type': 'object', 'properties': {'rate_calculation_id': {'type': 'string'}, 'input_role': {'type': 'string', 'enum': ['blank']}}, 'required': ['rate_calculation_id', 'input_role'], 'additionalProperties': False}}}
    return {'type': 'array', 'items': {'anyOf': [{'type': 'object', 'properties': {name: selector, **deepcopy(common)}, 'required': [name, 'basis', 'rationale'], 'additionalProperties': False} for name, selector in selectors.items()]}}

class SupportingInputError(ValueError):
    """Public membership diagnostics; never a scientific acceptance decision."""

    def __init__(self, message, details):
        super().__init__(message)
        self.details = deepcopy(details)

def normalize_supporting_basis(assessments, recorded_inputs):
    if not isinstance(assessments, list):
        raise ValueError('Declare supporting_basis for the adopted correction observations')
    normalized = []
    for assessment in assessments:
        if not isinstance(assessment, dict):
            raise ValueError('Each supporting basis needs one input selector, basis and rationale')
        if set(assessment) == {'measurement_ids', 'basis', 'rationale'}:
            normalized.append(deepcopy(assessment))
            continue
        if set(assessment) != {'calculation_input_refs', 'basis', 'rationale'}:
            raise ValueError('Each supporting basis needs exactly one input selector, basis and rationale')
        refs = assessment['calculation_input_refs']
        if not isinstance(refs, list) or not refs:
            raise ValueError('Use distinct references to recorded correction inputs')
        selected, seen_refs = ([], set())
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {'rate_calculation_id', 'input_role'}:
                raise ValueError('Each correction reference needs an adopted rate ID and input role')
            cid, role = (ref['rate_calculation_id'], ref['input_role'])
            if not isinstance(cid, str) or cid not in recorded_inputs or role != 'blank':
                raise ValueError('Correction references must name a recorded blank input of a rate in this group')
            key = (cid, role)
            if key in seen_refs:
                raise ValueError('Use each recorded correction input reference once')
            seen_refs.add(key)
            rows = [row for row in recorded_inputs[cid] if row['role'] == role]
            if not rows:
                raise ValueError('The referenced rate has no recorded correction observations for that role')
            for row in rows:
                mid = row['measurement']['measurement_id']
                if mid not in selected:
                    selected.append(mid)
        normalized.append({'measurement_ids': selected, 'basis': deepcopy(assessment['basis']), 'rationale': deepcopy(assessment['rationale'])})
    return normalized

def _coverage_details(assessments, expected, recorded_inputs):
    supplied = [mid for assessment in assessments if isinstance(assessment, dict) and isinstance(assessment.get('measurement_ids'), list) for mid in assessment['measurement_ids'] if isinstance(mid, str)]
    counts = Counter(supplied)
    return {'rate_calculation_ids': list(recorded_inputs), 'unexpected_measurement_ids': [mid for mid in counts if mid not in expected], 'duplicate_measurement_ids': [mid for mid, count in counts.items() if count > 1], 'missing_measurement_ids': [mid for mid in expected if mid not in counts], 'recorded_input_refs': [{'rate_calculation_id': cid, 'input_role': 'blank'} for cid, rows in recorded_inputs.items() if any((row['role'] == 'blank' for row in rows))]}

def supporting_observations(record, events, evidence):
    prior = events[:events.index(record)]
    rows = []
    for mid in dict.fromkeys(record.result.get('blank_measurement_ids', [])):
        if mid not in evidence:
            raise ValueError('Adopted supporting observation is unavailable')
        measurement = evidence[mid]
        history = [h for h in action_history(prior, measurement['location']) if h['completed_at_s'] is not None and h['completed_at_s'] <= measurement['captured_at_s'] + 1e-08]
        change = next((h for h in reversed(history) if h['action'] == 'transfer'), None)
        mix = next((h for h in reversed(history) if h['action'] == 'mix'), None)
        changed = change['completed_at_s'] if change else None
        mixed = mix['completed_at_s'] if mix and (changed is None or mix['completed_at_s'] >= changed - 1e-08) else None
        rows.append({'role': 'blank', 'measurement': deepcopy(measurement), 'preparation_changed_at_s': changed, 'preparation_mix_completed_at_s': mixed, 'last_preparation_change': deepcopy(change), 'last_mix': deepcopy(mix), 'basis': 'Acquired observation and acknowledged commands at observation time; not proof of composition, homogeneity or applicability.'})
    return rows

def validate_supporting_basis(assessments, observations, *, recorded_inputs=None):
    if not isinstance(assessments, list):
        raise ValueError('Declare supporting_basis for the adopted correction observations')
    expected = {r['measurement']['measurement_id']: r for r in observations}
    details = _coverage_details(assessments, expected, recorded_inputs or {})
    seen = set()
    choices = {}
    for assessment in assessments:
        if not isinstance(assessment, dict) or set(assessment) != {'measurement_ids', 'basis', 'rationale'}:
            raise ValueError('Each supporting basis needs measurement IDs, basis and rationale')
        ids = assessment['measurement_ids']
        if not isinstance(ids, list) or not ids or any((not isinstance(mid, str) or mid not in expected or mid in seen for mid in ids)) or (len(set(ids)) != len(ids)):
            raise SupportingInputError('Use each adopted supporting observation exactly once in its rate group', details)
        mode = assessment['basis']
        if mode not in SUPPORT_BASES or not isinstance(assessment['rationale'], str) or (not assessment['rationale'].strip()):
            raise ValueError('Declare a supported correction-data basis and scientific rationale')
        for mid in ids:
            row = expected[mid]
            field = {'after_preparation_change': 'preparation_changed_at_s', 'after_preparation_mix': 'preparation_mix_completed_at_s'}.get(mode)
            if field:
                boundary = row[field]
                if boundary is None or row['measurement']['captured_at_s'] < boundary - 1e-08:
                    raise ValueError(f'{mid}: no acknowledged boundary supports {mode} for this supporting observation. Reassess its applicability or justify a revised basis. No data were removed.')
            seen.add(mid)
            choices[mid] = mode
    if seen != set(expected):
        raise SupportingInputError('supporting_basis must cover all correction observations used by the adopted rates. Missing measurement IDs: ' + ', '.join(sorted(set(expected) - seen)) + '. Assess these acquired observations and declare their applicable basis and rationale; if they are unsuitable, record a new calculation with justified inputs. No basis or data were changed.', details)
    return choices
