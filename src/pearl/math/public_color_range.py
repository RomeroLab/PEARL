"""Conservative complete-domain arithmetic for an explicitly selected RGB model."""
from fractions import Fraction
from itertools import product
import math
from pearl.math.public_color_mix import _lab, _rgb
from pearl.eyes.color_calibration import ColorCalibrator, predict_mix_color
MODEL = 'volume_weighted_encoded_rgb_approximation'
RGB_NUMERICAL_MARGIN = Fraction(1, 10 ** 9)

def analyze_color_range(first_color, second_color, target_lab, fraction_bounds, model):
    if model != MODEL:
        raise ValueError('Select the explicit encoded-RGB approximation')
    first, second, target = (_rgb(first_color), _rgb(second_color), _lab(target_lab))
    if not isinstance(fraction_bounds, list) or len(fraction_bounds) != 2 or any((type(v) not in (int, float) or not math.isfinite(v) for v in fraction_bounds)) or (not 0 <= fraction_bounds[0] <= fraction_bounds[1] <= 1):
        raise ValueError('Ordered finite fraction bounds within 0..1 required')
    low, high = map(Fraction, fraction_bounds)
    changes = [a - b for a, b in zip(first, second)]
    crossings = {low, high}
    for base, change in zip(second, changes):
        if change:
            for code in range(255):
                fraction = (Fraction(2 * code + 1, 2) - base) / change
                if low < fraction < high:
                    crossings.add(fraction)
    ordered = sorted(crossings)
    probes = sorted(crossings | {(a + b) / 2 for a, b in zip(ordered, ordered[1:])})
    enclosure, witnesses = (set(), {})
    for fraction in probes:
        values = [Fraction(base) + change * fraction for base, change in zip(second, changes)]
        fraction_value = float(fraction)
        actual = tuple(predict_mix_color([(first, fraction_value), (second, 1 - fraction_value)])['rgb'])
        witnesses.setdefault(actual, Fraction(fraction_value))
        cells = [range(max(0, math.ceil(v - Fraction(1, 2) - RGB_NUMERICAL_MARGIN)), min(255, math.floor(v + Fraction(1, 2) + RGB_NUMERICAL_MARGIN)) + 1) for v in values]
        enclosure.update(product(*cells))
    enclosure.update(witnesses)
    metrics = {}
    for rgb in enclosure:
        lab = ColorCalibrator.bgr_to_lab(tuple(reversed(rgb)))
        metrics[rgb] = (ColorCalibrator.delta_e(lab, target), lab)
    witness_rgb = min(witnesses, key=lambda rgb: (metrics[rgb][0], witnesses[rgb]))
    fraction = witnesses[witness_rgb]
    distance, witness_lab = metrics[witness_rgb]
    return {'status': 'ok', 'model': MODEL, 'scope': 'conditional_model_only', 'fraction_bounds': list(fraction_bounds), 'metric': 'CIE76', 'distance_lower_bound': min((value[0] for value in metrics.values())), 'distance_upper_bound': distance, 'witness': {'first_fraction': float(fraction), 'first_fraction_exact': str(fraction), 'rgb': list(witness_rgb), 'lab': list(witness_lab), 'delta_e': distance}, 'partition_intervals': max(0, len(ordered) - 1), 'evaluated_rgb_count': len(metrics), 'rgb_numerical_margin': float(RGB_NUMERICAL_MARGIN), 'evidence_status': 'caller_supplied_values_not_verified', 'limitations': 'Bounds cover only the declared quantized encoded-RGB approximation and fraction interval. Boundary rounding relaxation may lower the lower bound; the witness is a model value. Point values use the existing floating-point formatter; the tiny RGB margin covers arithmetic, not measurement uncertainty. Neither bound verifies optical mixing, chemistry, uncertainty, model applicability, an acquired mixture, task satisfaction or execution feasibility.'}
