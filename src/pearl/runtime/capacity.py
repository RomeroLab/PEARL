"""Conditional volume bounds from public dispatch records, never physical truth."""
from copy import deepcopy
import math
from pearl.state.events import ToolCallEvent

def _nonnegative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (not math.isfinite(value)) or (value < 0):
        raise ValueError(f'{name} must be finite and nonnegative')
    return value

def _sum(values):
    try:
        return _nonnegative(math.fsum(values), 'calculated bound')
    except OverflowError as exc:
        raise ValueError('Calculated bound exceeds finite numeric range') from exc

def plate_transfer_accounting(events, initial_total):
    transfers = {}
    evidence = []
    for event in events:
        if not isinstance(event, ToolCallEvent) or event.source_agent != 'actor' or event.tool_name != 'transfer' or (event.executed is False):
            continue
        key = event.tool_call_id or event.event_id
        volume = _nonnegative(event.params.get('volume_ul'), 'recorded transfer volume')
        if key in transfers and transfers[key] != volume:
            raise ValueError('Conflicting volumes for a dispatched transfer')
        transfers[key] = volume
        evidence.append(event.event_id)
    return {'basis': 'Declared initial plate inventory and dispatched command volumes, not measured physical contents', 'declared_initial_total_ul': _nonnegative(initial_total, 'initial plate total'), 'gross_commanded_additions_ul': _sum(transfers.values()), 'transfer_count': len(transfers), 'event_ids': evidence, 'withdrawal_credit_ul': 0, 'limitations': 'Every plate transfer counts as a possible addition, including internal relocations and uncertain dispatches. No location assignment or withdrawal reduces this pooled bound.'}

def calculate_capacity_bound(accounting, capacity, arguments):
    keys = ('initial_total_upper_ul', 'transfer_upper_factor', 'per_transfer_extra_ul', 'unlogged_addition_upper_ul', 'proposed_transfer_ul')
    basis = arguments.get('assumption_basis')
    if not isinstance(basis, str) or not basis.strip():
        raise ValueError('Explicit assumption_basis is required')
    for key in keys:
        if key not in arguments:
            raise ValueError(f'Missing {key}; use null for an unknown bound')
        if arguments[key] is not None:
            _nonnegative(arguments[key], key)
    factor = arguments['transfer_upper_factor']
    if factor is not None and factor < 1:
        raise ValueError('Transfer upper factor cannot understate commanded volume')
    initial = arguments['initial_total_upper_ul']
    if initial is not None and initial < accounting['declared_initial_total_ul']:
        raise ValueError('Initial upper bound is below the declared initial total')
    result = {'basis': 'conditional calculation, not a volume measurement or placement diagnosis', 'accounting': deepcopy(accounting), 'inputs': deepcopy(arguments), 'capacity_ul': _nonnegative(capacity, 'capacity'), 'execution_authorized': False, 'conditional_max_well_volume_ul': None, 'capacity_margin_ul': None, 'assumptions': 'Initial total and unlogged additions are bounded as supplied; each dispatched/proposed amount is at most factor times its commanded volume plus the stated absolute error. Volumes add and material remains in the declared plate. These are user/model hypotheses, not independently verified facts.', 'limitations': 'Missing inputs are not evidence of unlimited physical volume. A nonnegative margin is conditional on all supplied bounds. A negative margin only means this pooled bound cannot certify capacity; it is not an observation of overflow or proof that every placement exceeds capacity. No transfer, withdrawal, mixing or safety override is authorized.'}
    missing = [key for key in keys if arguments[key] is None]
    if missing:
        return {**result, 'status': 'bound_not_established', 'unknown_inputs': missing, 'decision_effect': 'incomplete_calculation_neither_approval_nor_prohibition'}
    proposed = arguments['proposed_transfer_ul']
    upper = _sum((initial, (accounting['gross_commanded_additions_ul'] + proposed) * factor, (accounting['transfer_count'] + (1 if proposed > 0 else 0)) * arguments['per_transfer_extra_ul'], arguments['unlogged_addition_upper_ul']))
    _nonnegative(upper, 'calculated bound')
    return {**result, 'status': 'conditional_bound', 'conditional_max_well_volume_ul': upper, 'capacity_margin_ul': capacity - upper}
