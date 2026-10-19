"""Color arithmetic bound to acquired public observations, not transcribed channels."""
from copy import deepcopy
import math
from pearl.brain.analysis_utilities import execute_utility

def compare_measured_color(args, evidence):
    if set(args) != {'measurement_ids', 'target_lab'}:
        raise ValueError('Supply measurement_ids and target_lab only; camera channels are read from the acquired log')
    ids = args['measurement_ids']
    if not isinstance(ids, list) or not ids or len(ids) > 256 or any((not isinstance(i, str) or i not in evidence for i in ids)):
        raise ValueError('Select between 1 and 256 acquired measurement IDs')
    if len(set(ids)) != len(ids):
        raise ValueError('Measurement IDs must be distinct')
    measurements = [deepcopy(evidence[i]) for i in ids]
    rows = [{'id': m['measurement_id'], 'r': m['rgb'][0], 'g': m['rgb'][1], 'b': m['rgb'][2]} for m in measurements]
    result = execute_utility('analyze_color_difference', {'readings': rows, 'target_lab': args['target_lab']})
    if result.get('status') != 'ok':
        return result
    for item, m in zip(result['comparisons'], measurements):
        item.update({k: m[k] for k in ['measurement_id', 'location', 'captured_at_s', 'rgb', 'clipped']})
    result['evidence_status'] = 'acquired camera values; target supplied by caller'
    result['limitations'] = 'Camera color distance does not verify identity, composition, delivered volume or chemical cause; clipped values are censored.'
    return result

def resolve_color_target(args, evidence, standards):
    from pearl.eyes.color_calibration import ColorCalibrator
    if set(args) != {'measurement_ids', 'target_standard', 'target_measurement_id'}:
        raise ValueError('Select a declared target_standard or acquired target_measurement_id; set the other to null')
    standard = args['target_standard']
    reference = args['target_measurement_id']
    if (standard is None) == (reference is None):
        raise ValueError('Select exactly one target reference')
    if standard is not None:
        if not isinstance(standard, str) or standard not in standards:
            raise ValueError('Unknown declared color standard')
        target = standards[standard]
        lab = target['lab'] if 'lab' in target else ColorCalibrator.bgr_to_lab(tuple(reversed(target['rgb'])))
    else:
        if not isinstance(reference, str) or reference not in evidence:
            raise ValueError('Unknown target camera measurement')
        if evidence[reference].get('clipped'):
            raise ValueError('A clipped observation cannot define an uncensored target')
        lab = ColorCalibrator.bgr_to_lab(tuple(reversed(evidence[reference]['rgb'])))
    return {'measurement_ids': args['measurement_ids'], 'target_lab': dict(zip(('L', 'a', 'b'), lab))}

def simulate_measured_mix(args, evidence, standards):
    if set(args) != {'components', 'target_standard', 'target_measurement_id'}:
        raise ValueError('Supply measured components and public target references only')
    components = args['components']
    if not isinstance(components, list) or not components or len(components) > 256:
        raise ValueError('Choose 1 to 256 measured source colors')
    resolved = []
    ids = []
    for c in components:
        if not isinstance(c, dict) or set(c) != {'measurement_id', 'volume_ul'}:
            raise ValueError('Each component requires an acquired measurement_id and hypothetical volume_ul')
        mid = c['measurement_id']
        if not isinstance(mid, str) or mid not in evidence:
            raise ValueError('Unknown source camera measurement')
        if evidence[mid]['clipped']:
            raise ValueError('Clipped source colors cannot define an uncensored mixing prediction')
        ids.append(mid)
        resolved.append({'id': mid, 'volume_ul': c['volume_ul'], 'color': evidence[mid]['rgb']})
    target = None
    reference = None
    if args['target_standard'] is not None or args['target_measurement_id'] is not None:
        bound = resolve_color_target({'measurement_ids': ids, 'target_standard': args['target_standard'], 'target_measurement_id': args['target_measurement_id']}, evidence, standards)
        target = list(bound['target_lab'].values())
        reference = {'standard': args['target_standard'], 'measurement_id': args['target_measurement_id'], 'lab': bound['target_lab']}
    result = execute_utility('simulate_observed_color_mix', {'components': resolved, 'target_hex': None, 'target_lab': target})
    result['target_reference'] = reference
    result['source_measurement_ids'] = ids
    result['evidence_status'] = 'hypothetical mixing of acquired source colors; not an observed mixture'
    return result

def measured_color_range(args, evidence, standards):
    fields = {'source_measurement_ids', 'fraction_bounds', 'target_standard', 'target_measurement_id', 'model', 'model_applicability', 'validation_samples'}
    if not isinstance(args, dict) or set(args) != fields:
        raise ValueError('Supply acquired references, explicit model/domain/applicability and validation samples only')
    ids = args['source_measurement_ids']
    if not isinstance(ids, list) or len(ids) != 2 or any((not isinstance(i, str) or i not in evidence for i in ids)) or (len(set(ids)) != 2):
        raise ValueError('Choose exactly two distinct acquired source measurement IDs')
    if any((evidence[i]['clipped'] for i in ids)):
        raise ValueError('Clipped references cannot define an uncensored model')
    rationale = args['model_applicability']
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4096:
        raise ValueError('State the authored model applicability rationale')
    samples = args['validation_samples']
    if not isinstance(samples, list) or len(samples) > 256:
        raise ValueError('Supply zero to 256 explicit acquired validation samples')
    seen = set(ids)
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != {'measurement_id', 'first_fraction'}:
            raise ValueError("Each sample requires an acquired ID and caller's nominal first fraction")
        mid, fraction = (sample['measurement_id'], sample['first_fraction'])
        if not isinstance(mid, str) or mid not in evidence or mid in seen:
            raise ValueError('Validation IDs must be acquired, distinct and different from reference IDs')
        if evidence[mid]['clipped']:
            raise ValueError('Clipped validation data are censored, not an exact model residual')
        if type(fraction) not in (int, float) or not math.isfinite(fraction) or (not 0 <= fraction <= 1):
            raise ValueError('A finite nominal first fraction within 0..1 is required')
        seen.add(mid)
    target = resolve_color_target({'measurement_ids': ids, 'target_standard': args['target_standard'], 'target_measurement_id': args['target_measurement_id']}, evidence, standards)
    sources = [deepcopy(evidence[i]) for i in ids]
    result = execute_utility('analyze_observed_color_range', {'first_color': sources[0]['rgb'], 'second_color': sources[1]['rgb'], 'target_lab': list(target['target_lab'].values()), 'fraction_bounds': args['fraction_bounds'], 'model': args['model']})
    if result.get('status') != 'ok':
        raise ValueError('Invalid conditional range input: ' + result.get('message', 'unknown input'))
    from pearl.eyes.color_calibration import ColorCalibrator, predict_mix_color
    residuals = []
    for sample in samples:
        observation = deepcopy(evidence[sample['measurement_id']])
        fraction = sample['first_fraction']
        predicted = list(predict_mix_color([(tuple(sources[0]['rgb']), fraction), (tuple(sources[1]['rgb']), 1 - fraction)])['rgb'])
        residuals.append({'measurement': observation, 'first_fraction': sample['first_fraction'], 'fraction_kind': 'caller_supplied_nominal', 'predicted_rgb': predicted, 'rgb_residual': [a - b for a, b in zip(observation['rgb'], predicted)], 'delta_e': ColorCalibrator.delta_e(ColorCalibrator.bgr_to_lab(tuple(reversed(observation['rgb']))), ColorCalibrator.bgr_to_lab(tuple(reversed(predicted)))), 'in_requested_domain': args['fraction_bounds'][0] <= fraction <= args['fraction_bounds'][1]})
    result.update(source_measurement_ids=list(ids), source_measurements=sources, target_reference={'standard': args['target_standard'], 'measurement_id': args['target_measurement_id'], 'lab': target['target_lab']}, model_applicability={'rationale': rationale, 'status': 'caller_asserted_not_verified'}, validation_samples=residuals, evidence_status='Acquired reference colors and caller-selected mathematical model; not an acquired mixture')
    result['limitations'] += ' Validation fractions are caller-supplied nominal inputs, not measured composition. Residuals and repeat frames do not certify applicability, independence, delivery or identity; no evidence is excluded or adopted.'
    return result
