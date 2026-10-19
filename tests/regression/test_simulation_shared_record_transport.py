"""Exact non-camera list packing must preserve scientific and review inputs."""
import copy
import json
from pearl.runtime.transport import compact_context, expand_context

def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())

def review_context():
    return {'active_concerns': {'keep': {'rationale': 'unresolved concern', 'status': None}}, 'scientific_reviews': [{'review_id': 'review-1', 'rationale': 'Acquired evidence supports this bounded review. ' * 30, 'verdict': 'supported', 'selected': ['camera-a'], 'adopted': None}, {'review_id': 'review-2', 'rationale': 'Acquired evidence supports this bounded review. ' * 30, 'verdict': 'supported', 'selected': ['camera-b']}], 'camera': {'measurements': [{'measurement_id': 'camera-a', 'location': 'plate:A1', 'captured_at_s': 1.0, 'rgb': [1, 2, 3]}, {'measurement_id': 'camera-b', 'location': 'plate:A2', 'captured_at_s': 1.0, 'rgb': [1, 2, 3]}]}}

def test_repeated_review_fields_reduce_bytes_without_losing_current_concerns_or_evidence():
    original = review_context()
    packed = compact_context(original)
    assert size(packed) < 0.7 * size(original)
    assert expand_context(packed) == original
    assert packed['active_concerns'] == original['active_concerns']
    records = packed['scientific_reviews']['records']
    assert records[0]['adopted'] is None and 'adopted' not in records[1]

def test_tiny_non_camera_records_do_not_grow_and_source_remains_independent():
    original = {'rows': [{'x': 0, 'y': None}, {'x': 0, 'y': 1}], 'extension': []}
    saved = copy.deepcopy(original)
    packed = compact_context(original)
    assert size(packed) <= size(original)
    assert packed == original
    packed['rows'][0]['x'] = 999
    assert original == saved

def test_shared_fields_never_merge_json_boolean_number_or_integer_float_types():
    original = {'rows': [{'review_id': 'one', 'type_sensitive': True, 'number_sensitive': 1, 'rationale': 'detail ' * 200}, {'review_id': 'two', 'type_sensitive': 1, 'number_sensitive': 1.0, 'rationale': 'detail ' * 200}]}
    expanded = expand_context(compact_context(original))
    assert type(expanded['rows'][0]['type_sensitive']) is bool
    assert type(expanded['rows'][1]['type_sensitive']) is int
    assert type(expanded['rows'][0]['number_sensitive']) is int
    assert type(expanded['rows'][1]['number_sensitive']) is float
    assert size(compact_context(original)) < size(original)

def test_shared_camera_payload_is_not_inherited_by_non_camera_records():
    original = {'calculations': [{'id': 'a', 'basis': 'retained selected evidence ' * 100, 'observations': [{'measurement_id': 'camera-a', 'location': 'plate:A1', 'captured_at_s': 1.0}]}, {'id': 'b', 'basis': 'retained selected evidence ' * 100, 'observations': [{'measurement_id': 'camera-a', 'location': 'plate:A1', 'captured_at_s': 1.0}]}]}
    packed = compact_context(original)
    assert size(packed) < size(original)
    assert 'observations' not in packed['calculations']['shared']
    for row in packed['calculations']['records']:
        measurement = row['observations']['records'][0]
        assert measurement == {'measurement_id': 'camera-a', 'location': 'plate:A1', 'captured_at_s': 1.0}
    assert expand_context(packed) == original

def test_literal_extension_that_resembles_transport_encoding_roundtrips():
    original = {'extension': {'format': 'shared_records', 'shared': {'x': None}, 'records': [{'id': 'literal'}]}}
    assert expand_context(compact_context(original)) == original

def test_nested_shared_records_decode_selected_and_adopted_evidence():
    original = {'calculations': [{'id': 'a', 'basis': 'same bounded calculation ' * 100, 'decisions': [{'id': 'd1', 'basis': 'nested decision ' * 100, 'selected': ['camera-a']}, {'id': 'd2', 'basis': 'nested decision ' * 100, 'adopted': ['camera-b']}]}, {'id': 'b', 'basis': 'same bounded calculation ' * 100, 'decisions': []}]}
    packed = compact_context(original)
    assert size(packed) < 0.65 * size(original)
    assert expand_context(packed) == original

def test_camera_shared_fields_preserve_boolean_and_numeric_types():
    original = {'camera': {'measurements': [{'measurement_id': 'a', 'location': 'plate:A1', 'captured_at_s': 1.0, 'quality_flag': True}, {'measurement_id': 'b', 'location': 'plate:A2', 'captured_at_s': 2.0, 'quality_flag': 1}]}}
    decoded = expand_context(compact_context(original))
    assert type(decoded['camera']['measurements'][0]['quality_flag']) is bool
    assert type(decoded['camera']['measurements'][1]['quality_flag']) is int
