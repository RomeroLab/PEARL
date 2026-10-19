"""Read-only joins of public command receipts and adjacent acquired camera frames."""
from copy import deepcopy
SCOPE = 'Chronological public records only. Adjacent frames are selected by event order, not signal quality. During-operation frames are retained separately. Nominal commands and temporal proximity do not establish delivery, chemical identity, causation, stage completion, scientific applicability or adoption. Other acquired frames remain available by event ID or camera history.'

def _liquid(event):
    return getattr(event, 'source_agent', None) == 'actor' and getattr(event, 'tool_name', None) in ('transfer', 'mix')

def _acknowledged(event):
    return _liquid(event) and getattr(event, 'executed', None) is True and (event.result.get('ok') is True)

def _dispatch(event):
    return _liquid(event) and getattr(event, 'executed', None) is None and (event.result.get('status') == 'dispatching')

def _frame(event):
    return getattr(event, 'observation_type', None) == 'camera'

def _frame_reference(event):
    if event is None:
        return None
    return {'event_id': event.event_id, 'trace_sequence': event.trace_sequence, 'captured_at_s': event.payload.get('captured_at_s'), 'measurement_count': len(event.payload.get('measurements', []))}

def operation_observation_index(events):
    """Join recent command boundaries to complete acquired frames without selection."""
    recent, awaiting, dispatches, dispatch_counts = ([], [], {}, {})
    previous_frame, total = (None, 0)
    for event in events:
        if _dispatch(event):
            for row in awaiting:
                row['status'] = 'no_post_command_frame_before_next_operation'
            awaiting.clear()
            call = event.tool_call_id
            dispatch_counts[call] = dispatch_counts.get(call, 0) + 1
            dispatches[call] = (event, previous_frame, 0)
        elif _frame(event):
            reference = _frame_reference(event)
            for row in awaiting:
                row['after_frame'] = deepcopy(reference)
                row['after_payload'] = deepcopy(event.payload)
                row['status'] = 'observations'
            awaiting.clear()
            for call, (dispatch, before, during) in list(dispatches.items()):
                dispatches[call] = (dispatch, before, during + 1)
            previous_frame = event
        elif _acknowledged(event):
            total += 1
            candidate = dispatches.pop(event.tool_call_id, None)
            valid = candidate is not None and bool(event.tool_call_id) and (dispatch_counts.get(event.tool_call_id) == 1) and (candidate[0].tool_name == event.tool_name) and (candidate[0].plan_id == event.plan_id) and (candidate[0].params == event.params)
            row = {'command_event_id': event.event_id, 'dispatch_event_id': candidate[0].event_id if valid else None, 'nominal_command': {'action': event.tool_name, 'params': deepcopy(event.params)}, 'status': 'awaiting_observation' if valid else 'missing_matching_dispatch', 'before_frame': _frame_reference(candidate[1]) if valid else None, 'after_frame': None, 'before_payload': deepcopy(candidate[1].payload) if valid and candidate[1] is not None else None, 'after_payload': None, 'during_frame_count': candidate[2] if valid else None}
            recent.append(row)
            recent = recent[-16:]
            if valid:
                awaiting.append(row)
    history_fields = ('command_event_id', 'dispatch_event_id', 'nominal_command', 'status', 'before_frame', 'after_frame', 'during_frame_count')
    return {'commands': recent[-2:], 'total_commands': total, 'omitted_earlier_commands': max(0, total - 2), 'history': [{key: deepcopy(row[key]) for key in history_fields} for row in recent], 'history_omitted_earlier_commands': max(0, total - len(recent)), 'read_tool': 'read_operation_observations', 'scope': 'Complete acquired adjacent frame payloads and public chronological references; no signal selection, causation, delivery, identity, mapping or scientific verdict. Read by command_event_id; locations=[] includes all acquired locations.'}

def read_operation_observations(events, args, declared_locations):
    if not isinstance(args, dict) or set(args) != {'command_event_id', 'locations', 'offset', 'limit'}:
        raise ValueError('Provide command_event_id, locations, offset and limit')
    cid, locations, start, limit = (args[k] for k in ('command_event_id', 'locations', 'offset', 'limit'))
    if type(start) is not int or start < 0 or type(limit) is not int or (not 1 <= limit <= 24):
        raise ValueError('Nonnegative integer offset and limit1..24 required')
    if not isinstance(locations, list) or any((not isinstance(loc, str) or loc not in declared_locations for loc in locations)) or len(set(locations)) != len(locations):
        raise ValueError('Locations must be distinct declared locations')
    if cid is not None and (not isinstance(cid, str) or not cid):
        raise ValueError('Choose a public acknowledged command event ID or null')
    end = start + limit
    common = {'retrieval_frontier_event_id': events[-1].event_id if events else None, 'scope': SCOPE}
    if cid is None:
        if locations:
            raise ValueError('Command index requires locations=[]')
        commands = [e.to_dict() for e in events if _acknowledged(e)]
        return {**common, 'status': 'command_index', 'commands': deepcopy(commands[start:end]), 'total': len(commands), 'next_offset': end if end < len(commands) else None}
    matches = [(i, e) for i, e in enumerate(events) if e.event_id == cid and _acknowledged(e)]
    if len(matches) != 1:
        raise ValueError('Choose one successful Actor liquid acknowledgement')
    ack_index, command = matches[0]
    dispatches = [(i, e) for i, e in enumerate(events[:ack_index]) if _dispatch(e) and e.tool_call_id == command.tool_call_id]
    if len(dispatches) != 1 or not command.tool_call_id or dispatches[0][1].tool_name != command.tool_name or (dispatches[0][1].plan_id != command.plan_id) or (dispatches[0][1].params != command.params):
        raise ValueError('An acknowledgement requires its exact public dispatch')
    dispatch_index, dispatch = dispatches[0]
    next_dispatch = next((i for i in range(ack_index + 1, len(events)) if _dispatch(events[i])), len(events))
    before = next((e for e in reversed(events[:dispatch_index]) if _frame(e)), None)
    during = [e for e in events[dispatch_index + 1:ack_index] if _frame(e)]
    after = next((e for e in events[ack_index + 1:next_dispatch] if _frame(e)), None)
    result = {**common, 'command': deepcopy(command.to_dict()), 'dispatch_event_id': dispatch.event_id, 'before_frame': _frame_reference(before), 'after_frame': _frame_reference(after), 'during_frames': [_frame_reference(e) for e in during]}
    if after is None:
        return {**result, 'status': 'awaiting_observation' if next_dispatch == len(events) else 'no_post_command_frame_before_next_operation', 'pairs': [], 'total': 0, 'next_offset': None}
    before_rows = {m['location']: m for m in before.payload.get('measurements', [])} if before else {}
    after_rows = {m['location']: m for m in after.payload.get('measurements', [])}
    chosen = locations or list(dict.fromkeys([*before_rows, *after_rows]))
    pairs = [{'location': loc, 'before': deepcopy(before_rows.get(loc)), 'after': deepcopy(after_rows.get(loc))} for loc in chosen[start:end]]
    return {**result, 'status': 'observations', 'pairs': pairs, 'total': len(chosen), 'next_offset': end if end < len(chosen) else None}
