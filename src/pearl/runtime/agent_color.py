"""Acquired color codes with optional, explicitly authored comparison premises."""
from copy import deepcopy
import math
import numpy as np
from pearl.brain.analysis_utilities import execute_utility
from pearl.eyes.color_calibration import ColorCalibrator, predict_mix_color
from pearl.runtime.acquisition_context import acquisition_context
from pearl.runtime.analysis_memory import require_eligible
from pearl.runtime.color_optics import ENCODED_MODEL, TRANSMISSION_MODEL, predict_transmission_mix, analyze_transmission_range, analyze_untargeted_range
TARGET_FIELDS = {'target_rgb', 'target_measurement_id', 'target_basis'}
LIMITATIONS = 'Encoded RGB/HEX and conventional RGB-to-Lab arithmetic do not establish calibrated colorimetry, identity, composition, delivery or chemical cause. A caller-proposed reference is not a supplied color standard or verified interpretation of the goal. Clipped observations are censored. No acceptance threshold or pass judgment is applied.'

def _ids(ids, evidence):
    if not isinstance(ids, list) or not 1 <= len(ids) <= 256 or any((not isinstance(mid, str) or mid not in evidence for mid in ids)) or (len(set(ids)) != len(ids)):
        raise ValueError('Choose 1..256 distinct acquired measurement IDs')
    return [deepcopy(evidence[mid]) for mid in ids]

def _target(args, evidence):
    rgb, mid, basis = (args[k] for k in ('target_rgb', 'target_measurement_id', 'target_basis'))
    if rgb is None and mid is None:
        if basis is not None:
            raise ValueError('A target basis requires a target reference')
        return None
    if rgb is not None and mid is not None:
        raise ValueError('Choose only one target reference')
    if not isinstance(basis, str) or not basis.strip() or len(basis) > 4096:
        raise ValueError('State the authored target interpretation and limitations')
    if mid is not None:
        row = _ids([mid], evidence)[0]
        if row['clipped']:
            raise ValueError('A clipped observation cannot define an exact target')
        rgb = row['rgb']
        kind = 'acquired_measurement'
    else:
        if not isinstance(rgb, list) or len(rgb) != 3 or any((type(v) not in (int, float) or not math.isfinite(v) or (not 0 <= v <= 255) for v in rgb)):
            raise ValueError('A proposed encoded RGB target needs three finite channels within 0..255')
        kind = 'caller_proposed_rgb'
    lab = ColorCalibrator.bgr_to_lab(tuple(reversed(rgb)))
    return {'kind': kind, 'measurement_id': mid, 'rgb': deepcopy(rgb), 'lab': dict(zip(('L', 'a', 'b'), map(float, lab))), 'basis': basis, 'scientific_validity': 'not_verified'}

def _context(rows, target, evidence, events, setup):
    records = {r['measurement_id']: r for r in rows}
    if target and target['measurement_id'] is not None:
        mid = target['measurement_id']
        records.setdefault(mid, deepcopy(evidence[mid]))
    require_eligible(list(records), events)
    return acquisition_context(list(records.values()), events, setup['reagents'])

def selected_color(args, evidence, events, setup):
    if not isinstance(args, dict) or set(args) != {'measurement_ids'} | TARGET_FIELDS:
        raise ValueError('Supply acquired measurement IDs and explicit optional target fields')
    rows = _ids(args['measurement_ids'], evidence)
    target = _target(args, evidence)
    context = _context(rows, target, evidence, events, setup)
    comparisons = []
    groups = {}
    preps = {p['context_id']: p for p in context['preparations']}
    captures = {c['measurement_id']: c for c in context['captures']}
    target_lab = np.asarray(list(target['lab'].values())) if target else None
    for row in rows:
        lab = np.asarray(ColorCalibrator.bgr_to_lab(tuple(reversed(row['rgb']))))
        exact = not row['clipped']
        comparisons.append({**row, 'hex': '#' + ''.join((f'{v:02X}' for v in row['rgb'])), 'lab': list(map(float, lab)) if exact else None, 'delta_e': float(np.linalg.norm(lab - target_lab)) if exact and target else None})
        prep = preps[captures[row['measurement_id']]['command_context_id']]
        groups.setdefault((row['location'], prep['last_change_event_id']), []).append(row)
    summaries = []
    for (location, change_id), members in groups.items():
        numeric = [m for m in members if not m['clipped']]
        labs = np.asarray([ColorCalibrator.bgr_to_lab(tuple(reversed(m['rgb']))) for m in numeric])
        mean = labs.mean(axis=0) if numeric else None
        spread = labs.std(axis=0, ddof=1) if len(numeric) > 1 else None
        summaries.append({'location': location, 'last_change_event_id': change_id, 'measurement_ids': [m['measurement_id'] for m in members], 'frame_count': len(members), 'unique_capture_count': len({m['captured_at_s'] for m in members}), 'numeric_measurement_ids': [m['measurement_id'] for m in numeric], 'censored_measurement_ids': [m['measurement_id'] for m in members if m['clipped']], 'mean_lab': dict(zip(('L', 'a', 'b'), map(float, mean))) if mean is not None else None, 'sample_sd_lab': dict(zip(('L', 'a', 'b'), map(float, spread))) if spread is not None else None, 'delta_e_of_mean_to_target': float(np.linalg.norm(mean - target_lab)) if mean is not None and target else None, 'independent_preparation_count': None, 'scope': 'Descriptive frames grouped by location and last acknowledged material change. Frames and command groups do not establish independence or total uncertainty; exact moments omit disclosed censored readings.'})
    return {'status': 'ok', 'metric': 'CIE76' if target else None, 'comparisons': comparisons, 'observation_groups': summaries, 'target_reference': target, 'acquisition_context': context, 'scientific_acceptance': None, 'evidence_status': 'Acquired camera codes; optional caller-authored comparison premise.', 'limitations': LIMITATIONS + ' Sample spread is not total uncertainty or goal agreement.'}

def selected_mix(args, evidence, events, setup):
    if not isinstance(args, dict) or set(args) != {'components', 'model'} | TARGET_FIELDS:
        raise ValueError('Supply acquired components, explicit model and optional target fields')
    if args['model'] not in (ENCODED_MODEL, TRANSMISSION_MODEL):
        raise ValueError('Choose an available explicit color mixing model')
    components = args['components']
    if not isinstance(components, list) or not 1 <= len(components) <= 256:
        raise ValueError('Choose 1..256 components')
    if any((not isinstance(c, dict) or set(c) != {'measurement_id', 'volume_ul'} for c in components)):
        raise ValueError('Each component requires an acquired measurement_id and volume_ul')
    rows = _ids([c['measurement_id'] for c in components], evidence)
    if any((r['clipped'] for r in rows)):
        raise ValueError('Clipped sources cannot define an exact mixing prediction')
    target = _target(args, evidence)
    context = _context(rows, target, evidence, events, setup)
    if args['model'] == TRANSMISSION_MODEL:
        result = predict_transmission_mix([(r['rgb'], c['volume_ul']) for r, c in zip(rows, components)], setup['calibration'])
        if target:
            result['delta_e'] = ColorCalibrator.delta_e(tuple(result['lab']), tuple(target['lab'].values()))
    else:
        result = execute_utility('simulate_observed_color_mix', {'components': [{'id': r['measurement_id'], 'volume_ul': c['volume_ul'], 'color': r['rgb']} for r, c in zip(rows, components)], 'target_hex': None, 'target_lab': list(target['lab'].values()) if target else None})
    if result.get('status') != 'ok':
        raise ValueError('Invalid hypothetical mixing input: ' + result.get('message', 'unknown input'))
    result.update(target_reference=target, source_measurement_ids=[r['measurement_id'] for r in rows], source_measurements=rows, acquisition_context=context, scientific_acceptance=None, evidence_status='Hypothetical chosen-model blend of acquired sources; not an acquired mixture.')
    result['limitations'] += ' ' + LIMITATIONS
    return result

def selected_range(args, evidence, events, setup):
    fields = {'source_measurement_ids', 'fraction_bounds', 'model', 'model_applicability', 'validation_samples'} | TARGET_FIELDS
    if not isinstance(args, dict) or set(args) != fields:
        raise ValueError('Supply acquired references, model/domain/applicability, validation and explicit target fields')
    sources = _ids(args['source_measurement_ids'], evidence)
    if len(sources) != 2:
        raise ValueError('Choose exactly two distinct acquired source IDs')
    if any((s['clipped'] for s in sources)):
        raise ValueError('Clipped sources cannot define an exact model')
    rationale = args['model_applicability']
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4096:
        raise ValueError('State the authored model applicability rationale')
    target = _target(args, evidence)
    samples = args['validation_samples']
    if not isinstance(samples, list) or len(samples) > 256:
        raise ValueError('Supply zero to 256 validation samples')
    seen = set(args['source_measurement_ids'])
    observations = []
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != {'measurement_id', 'first_fraction'}:
            raise ValueError('Each validation sample requires an acquired ID and nominal fraction')
        row = _ids([sample['measurement_id']], evidence)[0]
        fraction = sample['first_fraction']
        if row['measurement_id'] in seen or row['clipped']:
            raise ValueError('Validation IDs must be distinct uncensored acquired samples, different from sources')
        if type(fraction) not in (int, float) or not math.isfinite(fraction) or (not 0 <= fraction <= 1):
            raise ValueError('A finite nominal fraction in 0..1 is required')
        seen.add(row['measurement_id'])
        observations.append(row)
    context = _context(sources + observations, target, evidence, events, setup)
    if target is None:
        result = analyze_untargeted_range(sources[0]['rgb'], sources[1]['rgb'], args['fraction_bounds'], args['model'], setup['calibration'])
    elif args['model'] == TRANSMISSION_MODEL:
        result = analyze_transmission_range(sources[0]['rgb'], sources[1]['rgb'], list(target['lab'].values()), args['fraction_bounds'], setup['calibration'])
    else:
        result = execute_utility('analyze_observed_color_range', {'first_color': sources[0]['rgb'], 'second_color': sources[1]['rgb'], 'target_lab': list(target['lab'].values()), 'fraction_bounds': args['fraction_bounds'], 'model': args['model']})
    if result.get('status') != 'ok':
        raise ValueError('Invalid conditional range input: ' + result.get('message', 'unknown input'))
    residuals = []
    for sample, observation in zip(samples, observations):
        f = sample['first_fraction']
        if args['model'] == TRANSMISSION_MODEL:
            parts = [(s['rgb'], v) for s, v in zip(sources, (f, 1 - f)) if v > 0]
            predicted = predict_transmission_mix(parts, setup['calibration'])['rgb']
        else:
            predicted = list(predict_mix_color([(tuple(sources[0]['rgb']), f), (tuple(sources[1]['rgb']), 1 - f)])['rgb'])
        residuals.append({'measurement': observation, 'first_fraction': f, 'fraction_kind': 'caller_supplied_nominal', 'predicted_rgb': predicted, 'rgb_residual': [a - b for a, b in zip(observation['rgb'], predicted)], 'delta_e': ColorCalibrator.delta_e(ColorCalibrator.bgr_to_lab(tuple(reversed(observation['rgb']))), ColorCalibrator.bgr_to_lab(tuple(reversed(predicted)))), 'in_requested_domain': args['fraction_bounds'][0] <= f <= args['fraction_bounds'][1]})
    result.update(source_measurement_ids=list(args['source_measurement_ids']), source_measurements=sources, target_reference=target, model_applicability={'rationale': rationale, 'status': 'caller_asserted_not_verified'}, validation_samples=residuals, acquisition_context=context, scientific_acceptance=None, evidence_status='Conditional model using acquired codes; not a physical validation or impossibility proof.')
    result['limitations'] += ' Validation fractions are caller-supplied nominal inputs, not measured composition. ' + LIMITATIONS
    return result
