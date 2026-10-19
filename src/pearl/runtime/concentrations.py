"""Unit conversions for declared stock concentrations."""
from copy import deepcopy
import json
import math
from pathlib import Path
PUBLIC_CONCENTRATION_FIELDS = frozenset({'concentration_value', 'concentration_unit', 'concentration_basis', 'molecular_weight_kDa'})
MOLAR_TO_UM = {'M': 1000000.0, 'mM': 1000.0, 'uM': 1.0, 'nM': 0.001, 'pM': 1e-06}
MASS_TO_G_PER_L = {'g/L': 1.0, 'mg/mL': 1.0, 'mg/L': 0.001, 'ug/mL': 0.001, 'ug/L': 1e-06, 'ng/mL': 1e-06, 'g/mL': 1000.0}

def nominal_stock_declarations(scenario_id):
    path = Path(__file__).resolve().parents[3] / 'config' / 'observation_stock_declarations.json'
    return json.loads(path.read_text()).get(scenario_id, {})

def declared_molarity(reagent):
    """Return nominal total molecular concentration; never infer active sites."""
    value = reagent.get('concentration_value')
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Declared concentration must be a finite nonnegative number')
    unit = reagent.get('concentration_unit')
    unit = unit.replace('µ', 'u').replace('μ', 'u') if isinstance(unit, str) else unit
    if unit in MOLAR_TO_UM:
        molar = value * MOLAR_TO_UM[unit]
        basis = 'declared_molar_concentration'
    elif unit in MASS_TO_G_PER_L:
        mw = reagent.get('molecular_weight_kDa')
        if type(mw) not in (int, float) or not math.isfinite(mw) or mw <= 0:
            raise ValueError('Mass conversion requires a declared finite positive molecular weight in kDa')
        molar = value * MASS_TO_G_PER_L[unit] / mw * 1000
        basis = 'nominal_total_molecular_concentration'
    else:
        raise ValueError('Select a declared molar or mass/volume stock with molecular weight; activity, normality and mixture strength are not molarity')
    if not math.isfinite(molar):
        raise ValueError('Converted concentration must be finite')
    return {'stock_uM': molar, 'molar_basis': basis, 'declaration': {key: deepcopy(value) for key, value in reagent.items() if key in PUBLIC_CONCENTRATION_FIELDS}, 'activity_basis': 'No active fraction is inferred or applied. Mass-derived molarity describes total declared molecules, not titrated active sites. Native molarity retains its declared basis.'}
