"""Independent exact-byte boundary checks on the actual context wire."""
from copy import deepcopy
import json
from types import SimpleNamespace
from pearl.runtime.context_view import HISTORY_DETAIL_BYTES
from pearl.runtime.retrieval_memory import RetrievalMemory
from pearl.runtime.runtime import ObservationRuntime
from pearl.runtime.transport import compact_context

def test_whole_context_reference_paths_preserve_actual_unit_byte_bound():
    shared = {'neutral_extension': 'n' * 400}
    row = {'location': 'plate:A1', 'preparation_id': None, 'observations': [], 'boundaries': [], 'declared_members': [], 'padding': '', 'extension_a': shared, 'extension_b': deepcopy(shared), 'extension_c': deepcopy(shared)}
    initial = len(json.dumps(compact_context(row), separators=(',', ':')).encode())
    row['padding'] = 'p' * (HISTORY_DETAIL_BYTES - initial - 2)
    counted = len(json.dumps(compact_context(row), separators=(',', ':')).encode()) + 2
    assert counted == HISTORY_DETAIL_BYTES
    canonical = {'setup': {'reagents': {}}, 'camera': {'measurements': []}, 'evidence_history_view': {'units': [row], 'acquisition_context': {}}}
    runtime = object.__new__(ObservationRuntime)
    runtime._context = lambda role, **extra: deepcopy(canonical)
    runtime.compact_messages = True
    runtime.continuous_camera = None
    runtime._context_snapshots = {}
    runtime._retrieval_memory = RetrievalMemory()
    runtime.world = SimpleNamespace(domain='color')
    wires = []

    def chat(role, messages, tools):
        wires.append(json.loads(messages[-1]['content']))
        return {'name': 'consult_knowledge', 'arguments': {'question': 'Public uncertainty'}}
    runtime.chat = chat
    runtime._call('reasoner')
    encoded_units = wires[0]['evidence_history_view']['units']
    wire_bytes = len(json.dumps(encoded_units, separators=(',', ':')).encode())
    assert wire_bytes <= HISTORY_DETAIL_BYTES, (counted, wire_bytes)
