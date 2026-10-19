"""Independent offline transport-contract regressions; no scientific grading."""
from copy import deepcopy
import json
from types import SimpleNamespace
from pearl.runtime.context_view import HISTORY_DETAIL_BYTES, project_context
from pearl.runtime.retrieval_memory import RetrievalMemory
from pearl.runtime.runtime import ObservationRuntime
from pearl.runtime.transport import compact_context

def context(units):
    return {'setup': {'reagents': {}}, 'camera': {'measurements': []}, 'evidence_history_view': {'units': units, 'acquisition_context': {}}}

def fields(value, key):
    if isinstance(value, dict):
        for name, child in value.items():
            if name == key:
                yield child
            yield from fields(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from fields(child, key)

def test_omitted_unit_index_preserves_distinct_declared_membership_ids():
    units = [{'location': 'plate:A1', 'preparation_id': None, 'binding_status': 'unbound_declaration', 'observations': [], 'boundaries': [], 'pinned_measurement_ids': [], 'acquired_count': 0, 'declared_members': [{'cohort_id': 'declared-series', 'member': {'member_id': f'planned-{i}', 'location': 'plate:A1', 'preparation_id': None}}]} for i in range(70)]
    history = project_context(context(units), 'predictor')['evidence_history_view']
    assert history['units_omitted'] > 0
    index = history['unit_index']
    assert list(fields(index, 'member_id')) == [f'planned-{i}' for i in range(70)]
    assert list(fields(index, 'cohort_id')) == ['declared-series'] * 70

def test_real_wire_encoded_history_details_respect_byte_limit_for_unicode():
    row = {'location': 'plate:A1', 'preparation_id': None, 'observations': [], 'boundaries': [], 'declared_members': [], 'authored_extension': 'é' * 6000}
    canonical = context([row])
    counted = len(json.dumps(compact_context(row), ensure_ascii=False, separators=(',', ':')).encode())
    assert counted < HISTORY_DETAIL_BYTES
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

def test_small_transient_history_has_exact_durable_read_after_scope_changes():
    from pearl.runtime.transport import expand_context
    canonical = context([{'location': 'plate:A1', 'preparation_id': None, 'observations': [], 'boundaries': [], 'declared_members': [], 'transient_public_scope': 'initial-delivery'}])
    original = deepcopy(canonical['evidence_history_view'])
    runtime = object.__new__(ObservationRuntime)
    runtime._context = lambda role, **extra: deepcopy(canonical)
    runtime.compact_messages = True
    runtime.continuous_camera = None
    runtime._context_snapshots = {}
    runtime._retrieval_memory = RetrievalMemory()
    runtime.world = SimpleNamespace(domain='color')
    events = []
    runtime.board = SimpleNamespace(publish=events.append, event_log=events)
    wires = []

    def chat(role, messages, tools):
        wires.append(expand_context(json.loads(messages[-1]['content'])))
        return {'name': 'consult_knowledge', 'arguments': {'question': 'Public uncertainty'}}
    runtime.chat = chat
    runtime._call('reasoner', proposed_report={'public_scope': 'initial'})
    delivered = wires[0]['evidence_history_view']
    assert delivered['units'] == original['units']
    assert delivered['units_omitted'] == 0
    canonical['evidence_history_view']['units'] = []
    runtime._call('predictor')
    assert 'full_history_read' in delivered
    args = delivered['full_history_read']['arguments']
    for role in ('reasoner', 'predictor'):
        assert runtime._utility(role, 'read_retrieval_receipt', args)['items'] == original
