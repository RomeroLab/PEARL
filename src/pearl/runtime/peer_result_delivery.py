"""Share the latest exact peer result within one outgoing request only."""
from copy import deepcopy
import json
from pearl.runtime.transport import expand_context

def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Ambiguous duplicate JSON key')
        value[key] = item
    return value

def _json(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))

def deduplicate_latest_result(messages, *, compact):
    """Reference only an equivalent adjacent result; never change saved history."""
    try:
        if len(messages) < 3:
            return messages
        assistant, output, user = messages[-3:]
        if assistant.get('role') != 'assistant' or output.get('role') != 'tool' or user.get('role') != 'user':
            return messages
        calls = assistant.get('tool_calls')
        if not isinstance(calls, list) or len(calls) != 1:
            return messages
        call = calls[0]
        call_id = call.get('id')
        function = call.get('function', {})
        if call.get('type') != 'function' or not isinstance(call_id, str) or (not call_id) or (output.get('tool_call_id') != call_id) or (not isinstance(function.get('name'), str)) or (not function['name']):
            return messages
        if sum((c.get('id') == call_id for m in messages if m.get('role') == 'assistant' for c in m.get('tool_calls', []))) != 1 or sum((m.get('role') == 'tool' and m.get('tool_call_id') == call_id for m in messages)) != 1:
            return messages
        load = lambda value: json.loads(value, object_pairs_hook=_object)
        if not isinstance(load(function['arguments']), dict):
            return messages
        result, context = (load(output['content']), load(user['content']))
        if compact:
            result, context = (expand_context(result), expand_context(context))
        if not isinstance(context, dict) or 'last_tool_result' not in context:
            return messages
        if _json(result) != _json(context['last_tool_result']):
            return messages
        reference = json.dumps({'format': 'request_tool_result_reference', 'tool_call_id': call_id, 'target': {'message': 'immediately_following_user', 'path': '/last_tool_result'}, 'meaning': 'Exact tool output is last_tool_result in the immediately following user JSON context in this same request. Resolve that context transport encoding; no result fields are omitted.'}, allow_nan=False, separators=(',', ':'))
        wire_bytes = lambda value: len(json.dumps(value, ensure_ascii=False).encode())
        if wire_bytes(reference) >= wire_bytes(output['content']):
            return messages
        delivered = deepcopy(messages)
        delivered[-2]['content'] = reference
        return delivered
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return messages
