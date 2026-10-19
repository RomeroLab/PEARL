"""Bounded operational query history for one synchronous peer consultation."""
from copy import deepcopy
from hashlib import sha256
import json

def _encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))

class PeerQueryMemory:

    def __init__(self):
        self._queries = {}

    def record(self, query, result):
        key = sha256(_encoded(query).encode()).hexdigest()
        result_digest = sha256(_encoded(result).encode()).hexdigest()
        previous = self._queries.pop(key, None)
        same = None if previous is None else previous['result_digest'] == result_digest
        arguments = _encoded(query['arguments'])
        self._queries[key] = {'name': query['name'], 'arguments_preview': arguments[:384], 'arguments_truncated': len(arguments) > 384, 'call_count': 1 if previous is None else previous['call_count'] + 1, 'same_result_as_previous_call': same, 'unchanged_repeat_count': previous['unchanged_repeat_count'] + 1 if same else 0, 'result_digest': result_digest}
        while len(self._queries) > 6:
            del self._queries[next(iter(self._queries))]

    def summary(self):
        return [deepcopy({key: value for key, value in row.items() if key != 'result_digest'}) for row in self._queries.values()]
