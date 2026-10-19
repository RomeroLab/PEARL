"""Bind proposed liquid-operation premises to public nominal inventory."""
from copy import deepcopy
import math

def affected_locations(action):
    if action.action_type == 'transfer':
        return list(dict.fromkeys((action.params['source'], action.params['target'])))
    if action.action_type == 'mix':
        return [action.params['location']]
    return []

def validate_volumes(action, rows, inventory):
    locations = affected_locations(action)
    if not isinstance(rows, list) or len(rows) != len(locations):
        raise ValueError(f'Expected volumes must cover exactly these action locations: {locations}. Use current estimated_inventory_ul (nominal accounting, not measured contents).')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'location', 'volume_ul'}:
            raise ValueError('Expected volume rows require only location and volume_ul')
        location, volume = (row['location'], row['volume_ul'])
        if not isinstance(location, str) or location not in locations or location in seen:
            raise ValueError('Expected volume locations must be distinct affected locations')
        seen.add(location)
        try:
            finite = isinstance(volume, (int, float)) and math.isfinite(volume)
        except OverflowError:
            finite = False
        if not isinstance(volume, (int, float)) or isinstance(volume, bool) or (not finite) or (volume < 0):
            raise ValueError('Expected volume must be finite, nonnegative and numeric')
        current = inventory[location]
        if not math.isclose(volume, current, rel_tol=0, abs_tol=1e-08):
            raise ValueError(f'Expected volume for {location} is {volume} uL, but public nominal inventory is {current} uL. Reconcile the acknowledged preparation and intended next operation before submitting again. No values were substituted.')
    return deepcopy(rows)

def preparation_focus(action, inventory, preparations):
    return {'basis': 'Acknowledged nominal inventory, not measured physical contents; observations may contradict it.', 'locations': {location: {**deepcopy(preparations['wells'].get(location, {})), 'volume_ul': inventory[location]} for location in affected_locations(action)}}
