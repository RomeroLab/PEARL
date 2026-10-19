"""Bounded exact public retrieval results shared across successive role contexts."""
from collections import OrderedDict
from copy import deepcopy
import json
from pearl.runtime.transport import compact_context, expand_context
RETRIEVAL_TOOLS = frozenset({'read_measurements', 'read_camera_window', 'read_shared_events', 'read_context_details', 'read_action_history', 'find_acquired_observations', 'consult_knowledge', 'read_operation_observations'})

def receipt_reference(receipt_id, path='', offset=0):
    return {'representation': 'exact_retrieval_reference', 'tool': 'read_retrieval_receipt', 'arguments': {'receipt_event_id': receipt_id, 'path': path, 'offset': offset, 'limit': 64}, 'meaning': 'Exact session-durable public result, not an observation or scientific disposition.'}

class RetrievalMemory:

    def __init__(self, *, max_entries=8, max_bytes=131072):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries = OrderedDict()
        self.evicted_entries = 0
        self.last_omission = None
        self.released_entries = 0
        self.last_release = None
        self._archive = OrderedDict()

    def archive(self, name, arguments, result, receipt_id):
        """Keep exact detached results independently of the bounded working set."""
        if not isinstance(receipt_id, str) or not receipt_id:
            raise ValueError('A receipt ID is required')
        entry = compact_context({'tool_name': name, 'arguments': deepcopy(arguments), 'receipt_event_id': receipt_id, 'result': deepcopy(result)})
        if receipt_id in self._archive:
            from pearl.runtime.context_view import _same_public_value
            if not _same_public_value(self._archive[receipt_id], entry):
                raise ValueError('An immutable receipt cannot be replaced')
            return
        self._archive[receipt_id] = entry

    def read(self, args):
        """Read a receipt or its public index; never re-run the original query."""
        from pearl.runtime.context_view import _page
        import re
        if not isinstance(args, dict) or set(args) != {'receipt_event_id', 'path', 'offset', 'limit'} or type(args['offset']) is not int or (args['offset'] < 0) or (type(args['limit']) is not int) or (not 1 <= args['limit'] <= 64) or (not isinstance(args['path'], str)):
            raise ValueError('Provide receipt_event_id, JSON-pointer path, integer offset and limit1..64')
        mid, path = (args['receipt_event_id'], args['path'])
        if mid is None:
            if path:
                raise ValueError('Receipt index requires an empty path')
            value = [{**{k: deepcopy(v) for k, v in expand_context(e).items() if k != 'result'}, 'result': receipt_reference(key)} for key, e in self._archive.items()]
        else:
            if not isinstance(mid, str) or mid not in self._archive:
                raise ValueError('Unknown public retrieval receipt')
            value = expand_context(self._archive[mid])['result']
            if path:
                if not path.startswith('/') or re.search('~(?![01])', path):
                    raise ValueError('Use a valid JSON pointer')
                for part in path[1:].split('/'):
                    key = part.replace('~1', '/').replace('~0', '~')
                    if isinstance(value, dict) and key in value:
                        value = value[key]
                    elif isinstance(value, list) and re.fullmatch('0|[1-9][0-9]*', key) and (int(key) < len(value)):
                        value = value[int(key)]
                    else:
                        raise ValueError('Receipt path does not exist')
        scalar = not isinstance(value, (dict, list))
        page = _page([value] if scalar else value, args)
        if scalar:
            page['kind'] = 'scalar'
        return {'receipt_event_id': mid, 'path': path, **page}

    def remember(self, name, arguments, result, event_id):
        self.archive(name, arguments, result, event_id)
        key = (name, json.dumps(arguments, sort_keys=True, separators=(',', ':')))
        entry = {'tool_name': name, 'arguments': deepcopy(arguments), 'receipt_event_id': event_id, 'result': deepcopy(result)}
        entry = compact_context(entry)
        size = len(json.dumps(entry, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        previous = self._entries.pop(key, None)
        if size > self.max_bytes:
            self.evicted_entries += int(previous is not None)
            self.last_omission = {'receipt_event_id': event_id, 'tool_name': name, 'reason': 'entry_exceeds_byte_limit', 'entry_bytes': size}
            return
        self._entries[key] = (entry, size)
        while len(self._entries) > self.max_entries or sum((row[1] for row in self._entries.values())) > self.max_bytes:
            dropped, _ = self._entries.popitem(last=False)[1]
            self.evicted_entries += 1
            self.last_omission = {'receipt_event_id': dropped['receipt_event_id'], 'tool_name': dropped['tool_name'], 'reason': 'least_recent_query'}

    def release(self, receipt_event_ids):
        """Atomically release current cache receipts without touching their sources."""
        if not isinstance(receipt_event_ids, list) or not receipt_event_ids or len(receipt_event_ids) > self.max_entries or any((not isinstance(mid, str) or not mid.strip() for mid in receipt_event_ids)) or (len(set(receipt_event_ids)) != len(receipt_event_ids)):
            raise ValueError('Provide a nonempty list of distinct current retrieval receipt IDs')
        by_receipt = {entry['receipt_event_id']: key for key, (entry, _) in self._entries.items()}
        if any((mid not in by_receipt for mid in receipt_event_ids)):
            raise ValueError('Every receipt must identify a current retrieval entry; no entries released')
        for mid in receipt_event_ids:
            del self._entries[by_receipt[mid]]
        self.released_entries += len(receipt_event_ids)
        self.last_release = {'released_receipt_event_ids': list(receipt_event_ids), 'retained_entries': len(self._entries), 'scope': 'Only cached retrieval copies released. Original evidence and prior decisions remain unchanged; release is not exclusion, resolution or scientific adoption.'}
        return deepcopy(self.last_release)

    def view(self):
        return {'scope': 'Exact recent public retrieval results, oldest query first. Repeating a query replaces its cached result. Acquisition timestamps and stage identities remain unchanged; retention is not adoption, verification or scientific relevance. Storage bytes count lossless encoded entries. Cache omissions are explicit. Original records follow their existing archive or snapshot retention rules; receipt IDs identify the retrieval event and may reference an archive summary. Smaller pages can reduce retention size. release_retrievals explicitly releases selected current receipt IDs from this shared working set without changing original evidence or decisions. Re-read through the original retrieval tool when needed; releasing does not resolve scientific uncertainty.', 'entries': [expand_context(row[0]) for row in self._entries.values()], 'max_entries': self.max_entries, 'max_bytes': self.max_bytes, 'retained_bytes': sum((row[1] for row in self._entries.values())), 'evicted_entries': self.evicted_entries, 'last_omission': deepcopy(self.last_omission), 'released_entries': self.released_entries, 'last_release': deepcopy(self.last_release), 'archived_entries': len(self._archive)}
