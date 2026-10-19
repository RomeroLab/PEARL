"""Join acquired observations to preceding public command records."""
from copy import deepcopy
import math
from pearl.runtime.notebook import action_history, preparation_summary

def _elapsed(captured, completed):
    if completed is None:
        return None
    if any((isinstance(v, bool) or not isinstance(v, (int, float)) or (not math.isfinite(v)) for v in (captured, completed))):
        raise ValueError('Acquisition context requires finite recorded timestamps')
    delta = captured - completed
    if delta < -1e-08:
        raise ValueError('Acknowledged command completes after the acquired observation')
    return max(0.0, delta)

def acquisition_context(measurements, events, reagents):
    """No current clock or private physical state participates in this join."""
    wanted = {m['measurement_id']: m for m in measurements}
    if len(wanted) != len(measurements):
        raise ValueError('Use distinct acquired measurements for acquisition context')
    commands, anchors, preparations, captures = ([], {}, {}, {})
    preceding_liquid_command = None
    for event in events:
        for command in action_history([event]):
            if command['action'] not in ('transfer', 'mix'):
                continue
            preceding_liquid_command = command
            commands.append(event)
            p = command['params']
            affected = [p['location']] if command['action'] == 'mix' else [p['source'], p['target']]
            for location in affected:
                anchor = anchors.setdefault(location, {})
                anchor['last_action_event_id'] = event.event_id
                if command['action'] == 'mix':
                    anchor['last_mix_event_id'] = event.event_id
                else:
                    anchor['last_change_event_id'] = event.event_id
                    if location == p['target']:
                        anchor['last_addition_event_id'] = event.event_id
        if getattr(event, 'observation_type', None) != 'camera':
            continue
        matching = [m for m in event.payload.get('measurements', []) if m['measurement_id'] in wanted]
        summary = None
        for m in matching:
            mid, location = (m['measurement_id'], m['location'])
            if mid in captures or m != wanted[mid]:
                raise ValueError('Acquisition context requires unaltered, uniquely acquired camera records')
            anchor = anchors.get(location, {})
            context_id = location + '@' + anchor.get('last_action_event_id', 'initial')
            preparation_id = location + '@' + anchor['last_change_event_id'] if location.startswith('plate:') and anchor.get('last_change_event_id') else None
            overlapping = list(m.get('overlapping_action_ids', []))
            if overlapping:
                context_id = location + '@acquisition:' + mid
                preparation_id = None
            if context_id not in preparations:
                if summary is None:
                    summary = preparation_summary(commands, reagents)['wells']
                preparations[context_id] = {'context_id': context_id, 'preparation_id': preparation_id, 'location': location, 'nominal_preparation': None if overlapping else deepcopy(summary.get(location)), **{key: anchor.get(key) for key in ('last_addition_event_id', 'last_mix_event_id', 'last_change_event_id')}}
            prep = preparations[context_id]['nominal_preparation'] or {}
            captures[mid] = {'measurement_id': mid, 'command_context_id': context_id, 'preparation_id': preparation_id, 'preceding_liquid_command_event_id': preceding_liquid_command['event_id'] if preceding_liquid_command is not None else None, 'elapsed_since_liquid_command_s': _elapsed(m['captured_at_s'], preceding_liquid_command['completed_at_s'] if preceding_liquid_command is not None else None), **{f'elapsed_since_{kind}_s': _elapsed(m['captured_at_s'], prep.get(f'last_{kind}_completed_at_s')) for kind in ('addition', 'mix', 'change')}}
            if overlapping:
                captures[mid].update(preparation_status='ambiguous_during_operation',
                    overlapping_action_ids=overlapping,
                    acquisition_interval_s=[m.get('acquisition_started_at_s'), m['captured_at_s']])
    if set(captures) != set(wanted):
        raise ValueError('Missing acquired camera lineage')
    return {'basis': 'Immutable context at acquisition from preceding acknowledged Actor commands. Local command_context_id groups nominal command history, not physical continuity. Nullable preparation_id is the plate cohort identity from the last acknowledged local material transfer; mixing changes command_context_id without creating a new independent material preparation. It is nominal command lineage, not verified delivery or scientific adoption. preceding_liquid_command_event_id is the latest successful liquid Actor acknowledgement anywhere in public event order; its elapsed age is chronological context, not a causal association, destination mapping, preparation identity or reaction age. Local elapsed times are since recorded command completion, not measured reaction onset. Later clock time or well changes do not alter historical observations. Nominal composition assumes additive volumes and homogeneous withdrawal; delivery, identity and mixing effectiveness remain unverified. Null preparation means no plate preparation is recorded, not an observed empty well. Scientific comparability and use remain explicit decisions.', 'preparations': list(preparations.values()), 'captures': [captures[mid] for mid in wanted]}
