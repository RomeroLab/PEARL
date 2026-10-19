"""Public command-derived preparation memory, independent of physical truth."""
from copy import deepcopy
from pearl.state.events import ToolCallEvent

def nominal_transfer_balance(params, inventory):
    """Describe one transfer's nominal state, independent of physical contents."""
    source, target = (params['source'], params['target'])
    before = {name: inventory.get(name, 0.0) for name in (source, target)}
    after = dict(before)
    after[source] -= params['volume_ul']
    after[target] += params['volume_ul']
    return {'basis': 'Nominal volumes immediately before and after this acknowledged command; not measured delivery or composition. Later remaining inventory is a different state.', 'locations': {name: {'before_ul': before[name], 'after_ul': after[name]} for name in before}}

def action_history(events, location=None, reagents=None):
    rows = []
    inventory = {name: row['volume_ul'] for name, row in reagents.items()} if reagents is not None else None
    for event in events:
        if not isinstance(event, ToolCallEvent) or event.source_agent != 'actor' or event.executed is not True or (not (event.result or {}).get('ok')):
            continue
        p = event.params
        receipt = event.result.get('observation', {})
        balance = None
        if event.tool_name == 'transfer':
            if inventory is not None:
                balance = nominal_transfer_balance(p, inventory)
                for name, values in balance['locations'].items():
                    inventory[name] = values['after_ul']
            elif 'nominal_volume_balance' in receipt:
                balance = deepcopy(receipt['nominal_volume_balance'])
        if location is not None and location not in (p.get('source'), p.get('target'), p.get('location')) and (location not in p.get('locations', ())):
            continue
        rows.append({'event_id': event.event_id, 'trace_sequence': event.trace_sequence, 'tool_call_id': event.tool_call_id, 'action': event.tool_name, 'params': deepcopy(p), 'completed_at_s': receipt.get('completed_at_s', receipt.get('captured_at_s', receipt.get('time_s'))), **({'nominal_volume_balance': balance} if balance is not None else {})})
    return rows

def preparation_summary(events, reagents):
    contents = {loc: {loc: row['volume_ul']} for loc, row in reagents.items()}
    additions = {}
    mixes = {}
    changed = {}
    for row in action_history(events):
        p = row['params']
        time = row['completed_at_s']
        if row['action'] == 'mix':
            mixes[p['location']] = time
        elif row['action'] == 'transfer':
            src = contents.setdefault(p['source'], {})
            dest = contents.setdefault(p['target'], {})
            volume = sum(src.values())
            if volume <= 0 or p['volume_ul'] > volume + 1e-07:
                raise RuntimeError('Acknowledged command history has inconsistent nominal inventory')
            moved = {k: v * p['volume_ul'] / volume for k, v in src.items()}
            for k, v in moved.items():
                src[k] -= v
                dest[k] = dest.get(k, 0.0) + v
            additions[p['target']] = time
            changed[p['source']] = changed[p['target']] = time
    return {'basis': 'Current nominal stock-equivalent volumes after all acknowledged commands, not the volumes before historical transfers and not measured composition or physical destination.', 'assumptions': 'Additive volumes and homogeneous withdrawal from prepared wells; stock labels and command coordinates are not independently verified. Read action history for all additions and timing; camera evidence may contradict this accounting.', 'wells': {loc: {'volume_ul': round(sum(c.values()), 12), 'source_equivalents_ul': {k: round(v, 12) for k, v in c.items() if v > 1e-10}, 'last_addition_completed_at_s': additions.get(loc), 'last_mix_completed_at_s': mixes.get(loc), 'last_change_completed_at_s': changed.get(loc)} for loc, c in contents.items() if loc.startswith('plate:')}}
