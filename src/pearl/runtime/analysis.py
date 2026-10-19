"""Interpret failed rate calculations with explicitly scoped window diagnostics."""
from pearl.math.kinetics import _linear_fit

def explain_initial_window(result, args):
    if result.get('status') not in ('nonlinear', 'no_signal'):
        return result
    usable = sorted(((p['time_s'], p['absorbance'] - args['blank_od']) for p in args['points'] if p['absorbance'] <= args['od_linear_max']))
    if len(usable) < 3:
        return result
    scale = args['epsilon_M_cm'] * args['path_length_cm'] * 1e-06

    def describe(points):
        slope, _, r2 = _linear_fit(points)
        conversion = max(0, points[-1][1]) / (scale * args['S0_uM'])
        return dict(points_used=len(points), time_window_s=[points[0][0], points[-1][0]], r2=r2, slope_od_per_s=slope, conversion_fraction=conversion, linearity_criterion_met=r2 >= args['min_window_r2'], conversion_criterion_met=conversion <= args['max_conversion_fraction'], rising_signal=slope > 0)
    first = describe(usable[:3])
    full = describe(usable)
    return {**result, 'points_used': first['points_used'], 'r2': first['r2'], 'slope_od_per_s': first['slope_od_per_s'], 'diagnostic_scope': 'Top-level failed-fit statistics describe the first three eligible points; no rate or accepted time window was obtained. Full eligible course statistics are diagnostic only.', 'note': 'No eligible initial window meets all supplied criteria. The status label describes the first window, not a cause or the entire course. Low R-squared alone cannot distinguish measurement scatter/quantization, an insufficient time span, or chemical curvature. Compare measured signal change, uncertainty and conversion before selecting more acquisition or a concentration change. All thresholds remain unchanged.', 'sampling_assessment': {'cause_status': 'undetermined', 'evidence_scope': 'caller-supplied points; bind to acquired measurements and matched blanks', 'first_window': first, 'full_eligible_window': full, 'first_window_duration_s': usable[2][0] - usable[0][0], 'observed_od_change': max((p[1] for p in usable[:3])) - min((p[1] for p in usable[:3])), 'first_window_conversion_fraction': first['conversion_fraction'], 'linearity_criterion_met': first['linearity_criterion_met'], 'conversion_criterion_met': first['conversion_criterion_met'], 'unmet_first_window_criteria': (['linearity'] if not first['linearity_criterion_met'] else []) + (['conversion'] if not first['conversion_criterion_met'] else []) + (['rising_signal'] if not first['rising_signal'] else [])}}
