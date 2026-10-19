"""Repeated evidence must remain exact and available through explicit references."""
import copy
import json
import pytest
from pearl.runtime.transport import compact_context, expand_context, TABLE_GUIDE

def size(value):
    return len(json.dumps(value, separators=(',', ':'), ensure_ascii=False))

def payload():
    return {'selected_ids': [f'camera-{i}' for i in range(80)], 'interval_basis': {'basis': 'after_preparation_mix', 'rationale': 'Measured stage'}, 'uncertainty': None, 'excluded_ids': ['camera-x'], 'measurements': [{'measurement_id': f'camera-{i}', 'location': 'plate:H4', 'captured_at_s': float(i), 'clipped': False, 'od_estimate': i / 1000} for i in range(80)]}

def references(value):
    if isinstance(value, dict):
        if value.get('format') == 'context_reference':
            yield value
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)

def test_cross_field_evidence_is_encoded_once_and_recovers_exactly():
    original = {'recorded': payload(), 'adopted': payload(), 'report': {'basis': payload()}}
    before = copy.deepcopy(original)
    packed = compact_context(original)
    assert list(references(packed))
    assert size(packed) < 0.5 * size(compact_context({'one': payload()})) * 3
    assert expand_context(packed) == original == before
    expanded = expand_context(packed)
    expanded['adopted']['selected_ids'].append('changed')
    assert expanded['recorded'] == before['recorded']
    assert original == before
    assert 'context_reference' in TABLE_GUIDE and 'JSON Pointer' in TABLE_GUIDE

def test_reference_paths_escape_slash_and_tilde_without_changing_keys():
    original = {'one/~': payload(), 'other': payload()}
    packed = compact_context(original)
    assert any((r['path'] == '/one~1~0' for r in references(packed)))
    assert expand_context(packed) == original

def test_type_sensitive_subtrees_are_not_coalesced():
    data = {'ids': list(range(150)), 'value': True}
    original = {'a': data, 'b': {**data, 'value': 1}, 'c': {**data, 'value': 1.0}}
    decoded = expand_context(compact_context(original))
    assert [type(decoded[k]['value']) for k in 'abc'] == [bool, int, float]
    assert decoded == original

def test_literal_reference_objects_are_not_interpreted_as_transport():
    original = {'literal': {'format': 'context_reference', 'path': '/missing'}, 'wrapped': {'format': 'literal_transport_object', 'value': {'format': 'context_reference', 'path': ''}}}
    assert expand_context(compact_context(original)) == original

@pytest.mark.parametrize('reference', [{'format': 'context_reference', 'path': '/missing'}, {'format': 'context_reference', 'path': ''}, {'format': 'context_reference', 'path': 'target'}, {'format': 'context_reference', 'path': '/target/~2'}, {'format': 'context_reference', 'path': 1}, {'format': 'context_reference'}, {'format': 'context_reference', 'path': '/target', 'extra': 1}])
def test_invalid_or_unresolved_references_fail_closed(reference):
    with pytest.raises(ValueError):
        expand_context({'target': [1], 'reference': reference})

def test_reference_cycle_is_rejected_without_recursion_failure():
    original = {'a': {'format': 'context_reference', 'path': '/b'}, 'b': {'format': 'context_reference', 'path': '/a'}}
    with pytest.raises(ValueError, match='[Cc]yclic|cycle'):
        expand_context(original)

def test_current_camera_measurements_keep_identity_fields_explicit():
    camera = payload()['measurements']
    original = {'prior': {'measurements': camera}, 'camera': {'measurements': camera}, 'measurement_history': camera}
    packed = compact_context(original)
    for key in ('camera', 'measurement_history'):
        assert not list(references(packed[key]))
    for row in packed['camera']['measurements']['records']:
        assert {'measurement_id', 'location', 'captured_at_s'} <= row.keys()
    assert expand_context(packed) == original

def test_small_context_does_not_gain_reference_overhead():
    original = {'x': [1, 2, 3], 'y': [1, 2, 3]}
    assert compact_context(original) == original

@pytest.mark.parametrize('shared', [False, True])
def test_literal_reference_inside_camera_metadata_is_preserved(shared):
    literal = {'format': 'context_reference', 'path': '/missing'}
    rows = [{'measurement_id': 'a', 'location': 'plate:A1', 'captured_at_s': 1.0, 'metadata': literal}, {'measurement_id': 'b', 'location': 'plate:A2', 'captured_at_s': 2.0, 'metadata': literal if shared else None}]
    original = {'camera': {'measurements': rows}}
    assert expand_context(compact_context(original)) == original

def test_camera_record_with_reserved_format_is_literal_not_a_reference():
    original = {'camera': {'measurements': [{'measurement_id': 'a', 'location': 'plate:A1', 'captured_at_s': 1.0, 'format': 'context_reference', 'path': '/missing'}]}}
    assert expand_context(compact_context(original)) == original

def test_literal_wrapper_boundaries_survive_non_camera_list_packing():
    original = {'rows': [{'format': 'context_reference', 'path': '/missing' + str(i), 'reason': 'literal field ' * 100} for i in range(10)]}
    assert expand_context(compact_context(original)) == original
