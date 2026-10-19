from __future__ import annotations
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

def normalise_unit(unit: object) -> str:
    """Lower-case, stripped, space-free rendering of a unit string."""
    return str(unit).strip().lower().replace(' ', '')

def _unit_table(raw: dict[str, float]) -> dict[str, float]:
    return {normalise_unit(key): value for key, value in raw.items()}
CONCENTRATION_UNITS_TO_UM: dict[str, float] = _unit_table({'um': 1.0, 'µm': 1.0, 'μm': 1.0, 'mm': 1000.0, 'nm': 0.001, 'm': 1000000.0, 'pm': 1e-06})
RATE_UNITS_TO_UM_PER_S: dict[str, float] = _unit_table({'um/s': 1.0, 'µm/s': 1.0, 'μm/s': 1.0, 'nm/s': 0.001, 'mm/s': 1000.0, 'um/min': 1 / 60.0, 'µm/min': 1 / 60.0, 'nm/min': 0.001 / 60.0, 'mm/min': 1000.0 / 60.0, 'm/s': 1000000.0})
KCAT_UNITS_TO_PER_S: dict[str, float] = _unit_table({'1/s': 1.0, 's^-1': 1.0, 's-1': 1.0, '/s': 1.0, 'per_s': 1.0, 'per s': 1.0, '1/min': 1 / 60.0, 'min^-1': 1 / 60.0, 'min-1': 1 / 60.0, '/min': 1 / 60.0})

def report_quantities_si(report: object) -> tuple[float, float]:
    """(KM in uM, kcat in 1/s) of one kinetic report; NaN where a unit or value is unusable.

    Pure arithmetic over the report's own ``{value, unit}`` objects.  Never
    raises: a malformed quantity is the validator's finding, and a grader
    records NaN as "units not recognised".
    """

    def convert(key: str, table: dict[str, float]) -> float:
        if not isinstance(report, Mapping):
            return float('nan')
        item = report.get(key)
        if not isinstance(item, Mapping):
            return float('nan')
        value = item.get('value')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (not math.isfinite(float(value))):
            return float('nan')
        return float(value) * table.get(normalise_unit(item.get('unit')), float('nan'))
    return (convert('KM', CONCENTRATION_UNITS_TO_UM), convert('kcat', KCAT_UNITS_TO_PER_S))

@dataclass(frozen=True)
class InitialRate:
    status: str
    v0_uM_per_s: float | None
    window_s: tuple[float, float] | None
    points_used: int
    r2: float | None
    conversion_fraction: float | None
    slope_od_per_s: float | None
    note: str = ''

    def to_mapping(self) -> dict[str, object]:
        return {'status': self.status, 'v0_uM_per_s': self.v0_uM_per_s, 'window_s': None if self.window_s is None else list(self.window_s), 'points_used': self.points_used, 'r2': self.r2, 'conversion_fraction': self.conversion_fraction, 'slope_od_per_s': self.slope_od_per_s, 'note': self.note}

def _linear_fit(points: Sequence[tuple[float, float]]) -> tuple[float, float, float]:
    n = len(points)
    mean_x = sum((x for x, _ in points)) / n
    mean_y = sum((y for _, y in points)) / n
    sxx = sum(((x - mean_x) ** 2 for x, _ in points))
    sxy = sum(((x - mean_x) * (y - mean_y) for x, y in points))
    syy = sum(((y - mean_y) ** 2 for _, y in points))
    slope = sxy / sxx if sxx > 0 else 0.0
    intercept = mean_y - slope * mean_x
    r2 = 1.0 if syy == 0 else 1.0 - sum(((y - (intercept + slope * x)) ** 2 for x, y in points)) / syy
    return (slope, intercept, r2)

def initial_rate(course: Sequence[tuple[float, float]], *, blank_od: float, epsilon_M_cm: float, path_length_cm: float, S0_uM: float, od_linear_max: float, min_window_r2: float, max_conversion_fraction: float) -> InitialRate:
    """The initial rate of one well from its timed readings (public data only)."""
    points = sorted(((float(t), float(od) - blank_od) for t, od in course))
    usable = [(t, od) for t, od in points if od + blank_od <= od_linear_max]
    if len(points) >= 2 and len(usable) < 3 and any((od + blank_od > od_linear_max for _, od in points)):
        return InitialRate('saturated', None, None, len(usable), None, None, None, f"readings exceed the detector's linear range ({od_linear_max:g} OD) before three unsaturated points exist")
    if len(usable) < 3:
        return InitialRate('too_few_points', None, None, len(usable), None, None, None, 'fewer than three usable timed readings')
    factor = 1.0 / (epsilon_M_cm * path_length_cm * 1e-06)
    best: InitialRate | None = None
    for end in range(3, len(usable) + 1):
        window = usable[:end]
        slope, _intercept, r2 = _linear_fit(window)
        product_at_end = max(0.0, window[-1][1]) * factor
        conversion = product_at_end / S0_uM if S0_uM > 0 else 0.0
        if r2 >= min_window_r2 and conversion <= max_conversion_fraction and (slope > 0):
            best = InitialRate('ok', slope * factor, (window[0][0], window[-1][0]), end, r2, conversion, slope)
    if best is not None:
        return best
    slope, _i, r2 = _linear_fit(usable[:3])
    if slope <= 0:
        return InitialRate('no_signal', None, None, len(usable), r2, None, slope, 'no rising signal in the first three readings')
    return InitialRate('nonlinear', None, None, len(usable), r2, None, slope, f'no initial window of three or more readings reaches R² {min_window_r2:g} within {max_conversion_fraction:.0%} conversion; read earlier or lower the enzyme')

@dataclass(frozen=True)
class RateRow:
    substrate_uM: float
    v0_uM_per_s: float
    well: str
    enzyme_nM: float

@dataclass(frozen=True)
class FitResult:
    status: str
    KM_uM: float | None
    Vmax_uM_per_s: float | None
    KM_se_uM: float | None
    Vmax_se_uM_per_s: float | None
    r2: float | None
    residuals: tuple[tuple[float, float], ...]
    identifiability: dict[str, bool] = field(default_factory=dict)
    note: str = ''
    levels_used: int = 0

    def to_mapping(self) -> dict[str, object]:
        return {'status': self.status, 'KM_uM': self.KM_uM, 'Vmax_uM_per_s': self.Vmax_uM_per_s, 'KM_se_uM': self.KM_se_uM, 'Vmax_se_uM_per_s': self.Vmax_se_uM_per_s, 'r2': self.r2, 'residuals': [list(item) for item in self.residuals], 'identifiability': dict(self.identifiability), 'note': self.note, 'levels_used': self.levels_used}

def fit_michaelis_menten(rows: Sequence[RateRow], *, min_levels: int=4, reference_enzyme_nM: float | None=None) -> FitResult:
    """Nonlinear least squares of v0 = Vmax·S/(KM+S) with standard errors.

    Courses at DIFFERENT enzyme concentrations (a re-entry that changed the
    enzyme volume) are fitted together on the per-enzyme rate v0/[E]
    (i.e. kcat_app·S/(KM+S)) and Vmax is reported at ``reference_enzyme_nM``
    (default: the mean of the rows' [E]); with one uniform [E] this is the
    plain fit.  Every row's own executed [E] is used; none is assumed.
    """
    enzyme = [r.enzyme_nM for r in rows if r.v0_uM_per_s is not None and r.substrate_uM > 0 and r.enzyme_nM and (r.enzyme_nM > 0)]
    normalise = bool(enzyme) and max(enzyme) - min(enzyme) > 0.05 * max(enzyme)
    reference = reference_enzyme_nM if reference_enzyme_nM is not None else sum(enzyme) / len(enzyme) if enzyme else None
    data = [(r.substrate_uM, r.v0_uM_per_s * (reference / r.enzyme_nM) if normalise and reference and r.enzyme_nM else r.v0_uM_per_s) for r in rows if r.v0_uM_per_s is not None and r.substrate_uM > 0]
    distinct = sorted({s for s, _ in data})
    if len(distinct) < min_levels:
        return FitResult('insufficient_levels', None, None, None, None, None, (), {}, f'{len(distinct)} distinct substrate levels; at least {min_levels} are needed to fit two parameters with a residual check', len(distinct))
    hanes = [(s, s / v) for s, v in data if v > 0]
    if len(hanes) < 3:
        return FitResult('failed', None, None, None, None, None, (), {}, 'fewer than three positive rates', len(distinct))
    slope, intercept, _ = _linear_fit(hanes)
    vmax = 1.0 / slope if slope > 0 else max((v for _, v in data))
    km = intercept * vmax if intercept > 0 else distinct[len(distinct) // 2]
    km = max(km, 1e-06)

    def model(s: float, km_: float, vmax_: float) -> float:
        return vmax_ * s / (km_ + s)

    def sse(km_: float, vmax_: float) -> float:
        return sum(((v - model(s, km_, vmax_)) ** 2 for s, v in data))
    current = sse(km, vmax)
    for _ in range(200):
        j11 = j12 = j22 = g1 = g2 = 0.0
        for s, v in data:
            f = model(s, km, vmax)
            d_km = -vmax * s / (km + s) ** 2
            d_v = s / (km + s)
            r = v - f
            j11 += d_km * d_km
            j12 += d_km * d_v
            j22 += d_v * d_v
            g1 += d_km * r
            g2 += d_v * r
        det = j11 * j22 - j12 * j12
        if det <= 0:
            break
        step_km = (j22 * g1 - j12 * g2) / det
        step_v = (j11 * g2 - j12 * g1) / det
        damping = 1.0
        improved = False
        for _inner in range(30):
            km_new = km + damping * step_km
            vmax_new = vmax + damping * step_v
            if km_new > 0 and vmax_new > 0:
                trial = sse(km_new, vmax_new)
                if trial < current:
                    km, vmax, current = (km_new, vmax_new, trial)
                    improved = True
                    break
            damping /= 2.0
        if not improved or (abs(step_km) < 1e-09 * km and abs(step_v) < 1e-09 * vmax):
            break
    n = len(data)
    mean_v = sum((v for _, v in data)) / n
    sst = sum(((v - mean_v) ** 2 for _, v in data))
    r2 = 1.0 - current / sst if sst > 0 else 0.0
    dof = max(n - 2, 1)
    variance = current / dof
    j11 = j12 = j22 = 0.0
    for s, _v in data:
        d_km = -vmax * s / (km + s) ** 2
        d_v = s / (km + s)
        j11 += d_km * d_km
        j12 += d_km * d_v
        j22 += d_v * d_v
    det = j11 * j22 - j12 * j12
    km_se = math.sqrt(variance * j22 / det) if det > 0 else None
    vmax_se = math.sqrt(variance * j11 / det) if det > 0 else None
    residuals = tuple(((s, v - model(s, km, vmax)) for s, v in data))
    identifiability = {'lowest_level_at_or_below_km': distinct[0] <= km, 'highest_level_at_or_above_2km': distinct[-1] >= 2.0 * km, 'vmax_approached': max((v for _, v in data)) >= 0.6 * vmax, 'km_relative_se_below_0_5': km_se is not None and km_se / km < 0.5}
    status = 'ok' if all(identifiability.values()) and r2 >= 0.95 else 'weak'
    note = '' if status == 'ok' else '; '.join((name for name, ok in identifiability.items() if not ok)) or f'fit R² {r2:.3f} below 0.95'
    if normalise:
        note = (note + '; ' if note else '') + f'courses at different enzyme concentrations were fitted on v0/[E] and Vmax is stated at {reference:.4g} nM'
    return FitResult(status, km, vmax, km_se, vmax_se, r2, residuals, identifiability, note, len(distinct))

@dataclass(frozen=True)
class KcatResult:
    kcat_per_s: float
    enzyme_nM: float
    basis_note: str

def kcat_from_vmax(vmax_uM_per_s: float, *, enzyme_nM: float, basis: str='active-site molar concentration (public stock basis)') -> KcatResult:
    if enzyme_nM <= 0:
        raise ValueError('enzyme concentration must be positive')
    return KcatResult(vmax_uM_per_s / (enzyme_nM * 0.001), enzyme_nM, f'kcat = Vmax / [E]total with [E]total = {enzyme_nM:g} nM on the {basis}')
