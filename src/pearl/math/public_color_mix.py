"""Approximate color arithmetic on explicitly supplied colors, without a world."""
import math
import re
from pearl.eyes.color_calibration import ColorCalibrator, predict_mix_color

def _rgb(value):
    if isinstance(value, str) and re.fullmatch('#[0-9a-fA-F]{6}', value):
        return tuple((int(value[i:i + 2], 16) for i in (1, 3, 5)))
    if isinstance(value, list) and len(value) == 3 and all((type(v) is int and 0 <= v <= 255 for v in value)):
        return tuple(value)
    raise ValueError('Supply a #RRGGBB color or three integer RGB bytes')

def _lab(value):
    if not isinstance(value, list) or len(value) != 3 or any((type(x) not in (int, float) or not math.isfinite(x) for x in value)) or (not 0 <= value[0] <= 100):
        raise ValueError('Target Lab must be three finite numbers [L, a, b], with L in [0, 100]')
    return tuple((float(x) for x in value))

def mix_public_colors(components, target_hex=None, target_lab=None):
    if target_hex is not None and target_lab is not None:
        raise ValueError('Supply target_hex or target_lab, not both')
    if not isinstance(components, list) or not 1 <= len(components) <= 256:
        raise ValueError('Supply 1–256 components')
    identifiers = set()
    parts = []
    for row in components:
        if not isinstance(row, dict) or set(row) != {'id', 'color', 'volume_ul'}:
            raise ValueError('Each component requires exactly id, color and volume_ul')
        identifier = row['id']
        volume = row['volume_ul']
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 128 or (identifier in identifiers):
            raise ValueError('Distinct nonempty component identifiers are required')
        if type(volume) not in (int, float) or not math.isfinite(volume) or volume <= 0:
            raise ValueError('Volumes must be finite and positive')
        identifiers.add(identifier)
        parts.append((_rgb(row['color']), volume))
    total = sum((v for _, v in parts))
    if not math.isfinite(total):
        raise ValueError('Total volume must be finite')
    prediction = predict_mix_color(parts)
    r, g, b = prediction['rgb']
    lab = ColorCalibrator.bgr_to_lab((b, g, r))
    delta = None
    comparison_lab = None
    if target_lab is not None:
        comparison_lab = _lab(target_lab)
        delta = ColorCalibrator.delta_e(lab, comparison_lab)
    elif target_hex is not None:
        if not isinstance(target_hex, str):
            raise ValueError('Target must be #RRGGBB or null')
        tr, tg, tb = _rgb(target_hex)
        delta = ColorCalibrator.delta_e(lab, ColorCalibrator.bgr_to_lab((tb, tg, tr)))
    return {'status': 'ok', 'version': 'public-observed-color-mix-v2' if target_lab is not None else 'public-observed-color-mix-v1', **({'target_lab': list(comparison_lab)} if comparison_lab is not None else {}), 'rgb': [r, g, b], 'hex': prediction['hex'].lower(), 'lab': list(lab), 'total_volume_ul': total, 'delta_e': delta, 'metric': 'CIE76', 'model': 'volume_weighted_encoded_rgb_approximation', 'limitations': 'Optical and chemical mixing may be nonlinear; lighting/calibration differences are not corrected.', 'evidence_status': 'caller_supplied_values_not_verified', 'cause_status': 'unconfirmed'}
