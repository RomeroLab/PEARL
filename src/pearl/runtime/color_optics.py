"""Common synthetic transmission optics, separate from named-color judgments."""
from copy import deepcopy
import math
from itertools import product
from pearl.math.public_color_mix import _lab, _rgb
from pearl.eyes.color_calibration import ColorCalibrator
TRANSMISSION_MODEL = 'channel_transmittance_srgb'
ENCODED_MODEL = 'volume_weighted_encoded_rgb_approximation'

def srgb_to_linear(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

def linear_to_srgb(value):
    return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055

def _references(calibration):
    if not isinstance(calibration, dict):
        raise ValueError('Public encoded blank/dark references are required')
    blank, dark = (calibration.get('blank_rgb'), calibration.get('dark_rgb'))
    if any((not isinstance(row, (list, tuple)) or len(row) != 3 for row in (blank, dark))):
        raise ValueError('Public encoded blank/dark triples are required')
    if any((type(v) not in (int, float) or not math.isfinite(v) for v in (*blank, *dark))):
        raise ValueError('Optical references must be finite')
    if any((not 0 <= d < b < 255 for b, d in zip(blank, dark))):
        raise ValueError('Each dark reference must lie below its unclipped blank')
    return (tuple((srgb_to_linear(v / 255) for v in blank)), tuple((srgb_to_linear(v / 255) for v in dark)))

def _log_transmission(rgb, references):
    rgb = _rgb(list(rgb)) if isinstance(rgb, (list, tuple)) else _rgb(rgb)
    blank, dark = references
    signals = [(srgb_to_linear(v / 255) - d) / (b - d) for v, b, d in zip(rgb, blank, dark)]
    if any((t <= 0 for t in signals)):
        raise ValueError('Signals at or below dark do not resolve positive transmission')
    return tuple((math.log(t) for t in signals))

def _encoded_mix(logs, weights, references):
    blank, dark = references
    return [255 * linear_to_srgb(d + (b - d) * math.exp(math.fsum((weight * row[channel] for row, weight in zip(logs, weights))))) for channel, (b, d) in enumerate(zip(blank, dark))]

def _quantize(values):
    return tuple((round(min(255, max(0, value))) for value in values))

def predict_transmission_mix(components, calibration):
    """Predict from supplied encoded observations, without reading a physical world."""
    if not isinstance(components, list) or not 1 <= len(components) <= 256:
        raise ValueError('Choose 1..256 acquired source components')
    if any((not isinstance(part, (list, tuple)) or len(part) != 2 for part in components)):
        raise ValueError('Each component needs RGB and a positive nominal volume')
    volumes = [part[1] for part in components]
    if any((type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in volumes)):
        raise ValueError('Nominal volumes must be finite and positive')
    total = sum(volumes)
    if not math.isfinite(total):
        raise ValueError('Total nominal volume must be finite')
    references = _references(calibration)
    logs = [_log_transmission(rgb, references) for rgb, _ in components]
    rgb = _quantize(_encoded_mix(logs, [v / total for v in volumes], references))
    lab = ColorCalibrator.bgr_to_lab(tuple(reversed(rgb)))
    return {'status': 'ok', 'model': TRANSMISSION_MODEL, 'rgb': list(rgb), 'hex': '#' + ''.join((f'{v:02x}' for v in rgb)), 'lab': list(lab), 'total_volume_ul': total, 'delta_e': None, 'metric': 'CIE76', 'limitations': 'Conditional fixed-path log-transmission arithmetic, not an acquired product or validated applicability. Acquired endmember point estimates retain noise, quantization and possible above-blank signals; no uncertainty correction or acceptance is inferred.'}

def _fraction_domain(fraction_bounds):
    if not isinstance(fraction_bounds, list) or len(fraction_bounds) != 2 or any((type(v) not in (int, float) or not math.isfinite(v) for v in fraction_bounds)) or (not 0 <= fraction_bounds[0] <= fraction_bounds[1] <= 1):
        raise ValueError('Ordered finite fraction bounds within 0..1 are required')
    return fraction_bounds

def _quantized_domain(values_at, crossings):
    ordered = sorted(crossings)
    probes = sorted(crossings | {(a + b) / 2 for a, b in zip(ordered, ordered[1:])})
    enclosure, witnesses = (set(), {})
    margin = 1e-09
    for fraction in probes:
        values = values_at(fraction)
        actual = _quantize(values)
        witnesses.setdefault(actual, fraction)
        cells = [range(max(0, math.ceil(v - 0.5 - margin)), min(255, math.floor(v + 0.5 + margin)) + 1) for v in values]
        enclosure.update(product(*cells))
    enclosure.update(witnesses)
    return (enclosure, witnesses, max(0, len(ordered) - 1))

def _transmission_domain(first_color, second_color, fraction_bounds, calibration):
    low, high = _fraction_domain(fraction_bounds)
    references = _references(calibration)
    logs = [_log_transmission(rgb, references) for rgb in (first_color, second_color)]
    crossings = {low, high}
    blank, dark = references
    for channel in range(3):
        slope = logs[0][channel] - logs[1][channel]
        if slope == 0:
            continue
        for code in range(255):
            t = (srgb_to_linear((code + 0.5) / 255) - dark[channel]) / (blank[channel] - dark[channel])
            if t > 0:
                fraction = (math.log(t) - logs[1][channel]) / slope
                if low < fraction < high:
                    crossings.add(fraction)
    return _quantized_domain(lambda f: _encoded_mix(logs, [f, 1 - f], references), crossings)

def analyze_untargeted_range(first_color, second_color, fraction_bounds, model, calibration):
    """Enclose numeric channels without interpreting a named or numerical goal."""
    if model == TRANSMISSION_MODEL:
        enclosure, _, intervals = _transmission_domain(first_color, second_color, fraction_bounds, calibration)
    elif model == ENCODED_MODEL:
        low, high = _fraction_domain(fraction_bounds)
        first, second = (_rgb(first_color), _rgb(second_color))
        crossings = {low, high}
        for a, b in zip(first, second):
            if a != b:
                for code in range(255):
                    fraction = (code + 0.5 - b) / (a - b)
                    if low < fraction < high:
                        crossings.add(fraction)
        enclosure, _, intervals = _quantized_domain(lambda f: [a * f + b * (1 - f) for a, b in zip(first, second)], crossings)
    else:
        raise ValueError('Choose an available explicit color mixing model')
    pairs = ((0, 1), (0, 2), (1, 2))
    return {'status': 'ok', 'model': model, 'scope': 'conditional_model_only', 'fraction_bounds': list(fraction_bounds), 'metric': None, 'encoded_rgb_bounds': [[min((row[i] for row in enclosure)), max((row[i] for row in enclosure))] for i in range(3)], 'channel_difference_bounds': [{'channels': [i, j], 'bounds': [min((row[i] - row[j] for row in enclosure)), max((row[i] - row[j] for row in enclosure))]} for i, j in pairs], 'partition_intervals': intervals, 'evaluated_rgb_count': len(enclosure), 'rgb_numerical_margin': 1e-09, 'limitations': 'Bounds enclose the entire selected fraction domain of the chosen quantized model, including conservative closed rounding cells. They are conditional on the supplied endmember point estimates and calibration; numerical margin is not measurement uncertainty. No target, named-color interpretation, physical applicability, acquired product or scientific acceptance is inferred.'}

def analyze_transmission_range(first_color, second_color, target_lab, fraction_bounds, calibration):
    """Enclose the entire quantized conditional model, including rounding boundaries."""
    target = _lab(target_lab)
    enclosure, witnesses, intervals = _transmission_domain(first_color, second_color, fraction_bounds, calibration)
    metrics = {}
    for rgb in enclosure:
        lab = ColorCalibrator.bgr_to_lab(tuple(reversed(rgb)))
        metrics[rgb] = (ColorCalibrator.delta_e(lab, target), lab)
    witness = min(witnesses, key=lambda rgb: (metrics[rgb][0], witnesses[rgb]))
    distance, lab = metrics[witness]
    return {'status': 'ok', 'model': TRANSMISSION_MODEL, 'scope': 'conditional_model_only', 'fraction_bounds': list(fraction_bounds), 'metric': 'CIE76', 'distance_lower_bound': min((row[0] for row in metrics.values())), 'distance_upper_bound': distance, 'witness': {'first_fraction': witnesses[witness], 'rgb': list(witness), 'lab': list(lab), 'delta_e': distance}, 'partition_intervals': intervals, 'evaluated_rgb_count': len(metrics), 'rgb_numerical_margin': 1e-09, 'limitations': 'Bounds enclose only this quantized fixed-path sRGB transmission model and selected fraction domain. Closed rounding cells may relax the lower bound. The witness is a model value; numerical margin is not measurement uncertainty. No physical applicability, acquired mixture, target interpretation or scientific success is established.'}
