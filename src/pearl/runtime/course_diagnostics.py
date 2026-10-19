"""Descriptive checks of a caller-selected acquired interval, without selection."""
import math
import numpy as np

def _segment(rows, blank_od, scale):
    result = {'measurement_ids': [r['measurement_id'] for r in rows], 'points_used': len(rows), 'window_s': [rows[0]['captured_at_s'], rows[-1]['captured_at_s']] if rows else None, 'slope_od_per_s': None, 'rate_uM_per_s': None, 'residual_degrees_of_freedom': max(0, len(rows) - 2), 'slope_se_od_per_s': None}
    if len(rows) < 2:
        return result
    x = np.asarray([r['captured_at_s'] - rows[0]['captured_at_s'] for r in rows])
    y = np.asarray([r['od_estimate'] - blank_od for r in rows])
    centered = x - x.mean()
    sxx = float(centered @ centered)
    slope = float(centered @ (y - y.mean()) / sxx)
    residual = y - y.mean() - slope * centered
    dof = len(rows) - 2
    result.update(slope_od_per_s=slope, rate_uM_per_s=slope / scale, slope_se_od_per_s=math.sqrt(float(residual @ residual) / dof / sxx) if dof > 0 else None)
    return result

def describe_course(course, blank_od, scale, nominal_substrate_uM):
    """Use a fixed temporal midpoint, never an optimized or accepted window."""
    start, end = (course[0]['captured_at_s'], course[-1]['captured_at_s'])
    midpoint = start + (end - start) / 2
    early = _segment([r for r in course if r['captured_at_s'] <= midpoint], blank_od, scale)
    late = _segment([r for r in course if r['captured_at_s'] >= midpoint], blank_od, scale)
    first_slope, last_slope = (early['slope_od_per_s'], late['slope_od_per_s'])
    product = [(r['od_estimate'] - blank_od) / scale for r in (course[0], course[-1])]
    return {'temporal_halves': {'split_at_s': midpoint, 'early': early, 'late': late, 'shared_measurement_ids': sorted(set(early['measurement_ids']) & set(late['measurement_ids'])), 'late_minus_early_slope_od_per_s': last_slope - first_slope if first_slope is not None and last_slope is not None else None}, 'optical_equivalents': {'measurement_ids': [course[0]['measurement_id'], course[-1]['measurement_id']], 'endpoint_product_equivalent_uM': product, 'endpoint_product_equivalent_to_nominal_substrate': [v / nominal_substrate_uM for v in product], 'limitations': 'Conditional blank-corrected optical equivalents under declared extinction/path and nominal substrate. Not verified product identity, stoichiometry or substrate depletion. Negative values remain visible.'}, 'scope': 'Descriptive fixed temporal halves of the selected acquired interval, not adopted rates or a window search. Overlapping observations and one preparation do not give independent replication. Segment SE is conditional residual OLS, not total uncertainty. Sparse halves have null fits. No acceptance, cause, exclusion or required response is inferred.'}
