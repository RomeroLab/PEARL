"""Conditional readout-noise diagnostics for an already calculated camera window."""
import math

def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False

def readout_precision(course, result, bound, calibration):
    eligible = sorted((m for m in course if m['od_estimate'] <= bound['od_linear_max']), key=lambda m: m['captured_at_s'])
    if result['status'] == 'ok':
        selected = eligible[:result['points_used']]
        scope = 'accepted_window'
    elif result['status'] in ('nonlinear', 'no_signal'):
        selected = eligible[:3]
        scope = 'failed_first_window_diagnostic'
    else:
        selected = []
        scope = 'no_fitted_window'
    diagnostic = {'scope': scope, 'measurement_ids': [m['measurement_id'] for m in selected], 'time_window_s': None, 'duration_s': None, 'od_span': None, 'channel_span_quantization_steps': None, 'noise_slope_sd_od_per_s': None, 'noise_rate_sd_uM_per_s': None, 'relative_noise_slope_sd': None, 'noise_status': 'unavailable', 'quantization_status': 'unavailable', 'basis': 'Selected acquired window only. Propagated declared per-reading OD noise SD assumes independent readout errors and fixed timestamps; a shared constant blank offset cancels in the slope. This is a conditional readout-noise contribution, not total uncertainty, a confidence interval or a quality verdict. Quantization spacing is distinct from noise SD and is not added as Gaussian noise. Optical transformation/clamping, calibration, timing and chemical uncertainty are not quantified here; enzyme activity and causes remain unverified.'}
    if len(selected) < 3:
        return diagnostic
    times = [m['captured_at_s'] for m in selected]
    diagnostic.update(time_window_s=[times[0], times[-1]], duration_s=times[-1] - times[0], od_span=max((m['od_estimate'] for m in selected)) - min((m['od_estimate'] for m in selected)))
    relative_times = [t - times[0] for t in times]
    mean = sum(relative_times) / len(relative_times)
    centered = [t - mean for t in relative_times]
    sxx = sum((t * t for t in centered))
    sigmas = [m.get('od_noise_sd_estimate') for m in selected]
    if _finite(sxx) and sxx > 0 and (not any((m.get('clipped') for m in selected))) and all((_finite(s) and s >= 0 for s in sigmas)):
        sd = math.hypot(*(t * s for t, s in zip(centered, sigmas))) / sxx
        scale = bound['epsilon_M_cm'] * bound['path_length_cm'] * 1e-06
        rate_sd = sd / scale
        slope = result.get('slope_od_per_s')
        relative = sd / abs(slope) if _finite(slope) and slope != 0 else None
        if _finite(sd) and _finite(rate_sd):
            diagnostic.update(noise_status='available', noise_slope_sd_od_per_s=sd, noise_rate_sd_uM_per_s=rate_sd, relative_noise_slope_sd=relative if _finite(relative) else None)
    channel = calibration.get('od_channel')
    counts, steps = ([], [])
    for m in selected:
        rgb = m.get('rgb')
        if m.get('clipped') or type(channel) is not int or (not isinstance(rgb, (list, tuple))) or (not 0 <= channel < len(rgb)) or (not _finite(rgb[channel])):
            break
        step = m.get('rgb_quantization_step_counts')
        if not _finite(step) or step <= 0:
            break
        counts.append(rgb[channel])
        steps.append(step)
    if len(counts) == len(selected) and len(set(steps)) == 1:
        span = (max(counts) - min(counts)) / steps[0]
        if _finite(span):
            diagnostic.update(quantization_status='available', channel_span_quantization_steps=span)
    return diagnostic

def endpoint_readout_precision(samples, blanks, calibration):
    """Describe selected endpoint readout uncertainty without a quality decision."""

    def noise(m):
        sigma = m.get('od_noise_sd_estimate')
        return sigma if _finite(sigma) and sigma >= 0 and (not m.get('clipped')) else None
    blank_sigmas = [noise(m) for m in blanks]
    blank_known = all((s is not None for s in blank_sigmas))
    blank_sd = math.hypot(*blank_sigmas) / len(blanks) if blanks and blank_known else 0.0 if not blanks else None
    if blank_sd is not None and (not _finite(blank_sd)):
        blank_sd = None
    blank_od = math.fsum((m['od_estimate'] for m in blanks)) / len(blanks) if blanks else 0.0
    channel = calibration.get('od_channel')

    def channel_value(m):
        rgb = m.get('rgb')
        step = m.get('rgb_quantization_step_counts')
        if m.get('clipped') or type(channel) is not int or (not isinstance(rgb, (list, tuple))) or (not 0 <= channel < len(rgb)) or (not _finite(rgb[channel])) or (not _finite(step)) or (step <= 0):
            return None
        return (rgb[channel], step)
    blank_channels = [channel_value(m) for m in blanks]
    points = []
    for m in samples:
        sigma = noise(m)
        sd = None
        if sigma is not None and blank_sd is not None:
            weights = {m['measurement_id']: (1.0, sigma)}
            for b, s in zip(blanks, blank_sigmas):
                mid = b['measurement_id']
                previous = weights.get(mid, (0.0, s))
                weights[mid] = (previous[0] - 1 / len(blanks), s)
            sd = math.hypot(*(w * s for w, s in weights.values()))
            if not _finite(sd):
                sd = None
        corrected = m['od_estimate'] - blank_od
        relative = sd / abs(corrected) if sd is not None and corrected != 0 else None
        if relative is not None and (not _finite(relative)):
            relative = None
        sample_channel = channel_value(m)
        steps = None
        if sample_channel is not None and blanks and all((c is not None for c in blank_channels)):
            count, step = sample_channel
            if all((c[1] == step for c in blank_channels)):
                try:
                    mean_count = math.fsum((c[0] / len(blanks) for c in blank_channels))
                    value = (mean_count - count) / step
                except OverflowError:
                    value = None
                if _finite(value):
                    steps = value
        points.append({'measurement_id': m['measurement_id'], 'noise_status': 'available' if sd is not None else 'unavailable', 'corrected_od_noise_sd': sd, 'relative_corrected_od_noise_sd': relative, 'quantization_status': 'available' if steps is not None else 'unavailable', 'signal_quantization_steps': steps})
    covariance = blank_sd * blank_sd if blank_sd is not None else None
    if covariance is not None and (not _finite(covariance)):
        covariance = None
    return {'measurement_ids': [m['measurement_id'] for m in samples], 'blank_measurement_ids': [m['measurement_id'] for m in blanks], 'mean_blank_noise_sd': blank_sd, 'shared_blank_covariance_od2': covariance, 'shared_blank_covariance_scope': 'between_samples_with_no_control_id_overlap', 'sample_control_overlap_measurement_ids': [m['measurement_id'] for m in samples if m['measurement_id'] in {b['measurement_id'] for b in blanks}], 'points': points, 'basis': 'Selected acquired endpoints only. Conditional propagation of declared independent per-reading OD noise SD with fixed readings/calibration. The shared_blank_covariance_od2 is the mean-blank variance and equals covariance only between corrected samples whose IDs do not overlap the controls. Other pairwise covariances are not reported. Reuse of a control as a sample is listed explicitly and accounted for in each point SD by its combined coefficient. This is not total uncertainty, empirical replicate CV, a confidence interval or an acceptance rule. Signal in channel quantization steps is separate from Gaussian noise and requires compatible selected blank metadata. Optical clamping/transformation, calibration, timing, preparation variation and chemical uncertainty are not quantified. Missing, invalid or clipped optional metadata is unavailable; nominal activity and causes remain unverified.'}
