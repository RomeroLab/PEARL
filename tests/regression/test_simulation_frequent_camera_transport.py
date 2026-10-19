"""Lossless named camera records with identical-only shared metadata."""
from copy import deepcopy
import json
import pytest
from pearl.runtime.transport import compact_context, expand_context

def records():
    return [{'measurement_id': f'acquired-{i}', 'location': f'plate:{i}', 'captured_at_s': 2.5, 'rgb': [255, 255, 255] if i != 7 else [25, 50, 75], 'clipped': i != 7, 'annotation': 'Uninterpreted public acquisition metadata. ' * 20 if i != 8 else None, 'type_sensitive': True if i != 9 else 1, **({'explicit_null': None} if i != 10 else {})} for i in range(96)]

def test_varying_values_stay_explicit_with_identity_and_lossless_roundtrip():
    original = {'camera': records()}
    before = deepcopy(original)
    wire = compact_context(original)
    received = expand_context(json.loads(json.dumps(wire)))
    assert received == before and original == before
    assert type(received['camera'][0]['type_sensitive']) is bool
    assert type(received['camera'][9]['type_sensitive']) is int
    assert received['camera'][8]['annotation'] is None
    assert received['camera'][0]['explicit_null'] is None
    assert 'explicit_null' not in received['camera'][10]
    table = wire['camera']
    assert table['format'] == 'measurement_records'
    assert len(table['records']) == 96
    assert all(({'measurement_id', 'location', 'captured_at_s'} <= row.keys() for row in table['records']))
    assert not {'measurement_id', 'location', 'captured_at_s'} & table['shared'].keys()
    assert 'annotation' not in table['shared']
    assert all(('annotation' in row and 'rgb' in row and ('clipped' in row) for row in table['records']))
    assert table['records'][8]['annotation'] is None
    assert table['records'][7]['rgb'] == [25, 50, 75]

def test_identical_metadata_retains_the_compression_guarantee():
    rows = records()
    for row in rows:
        row['annotation'] = rows[0]['annotation']
    original = {'camera': rows}
    wire = compact_context(original)
    assert expand_context(wire) == original
    assert wire['camera']['shared']['annotation'] == rows[0]['annotation']
    assert len(json.dumps(wire)) < len(json.dumps(original)) / 2

@pytest.mark.parametrize('values', [[True, True, 1], [None, None, False], [0, 0, -0.0]])
def test_factoring_preserves_json_types_for_equal_comparing_python_values(values):
    rows = records()[:3]
    for row, value in zip(rows, values):
        row['typed'] = value
    received = expand_context(compact_context({'camera': rows}))['camera']
    assert [type(row['typed']) for row in received] == [type(v) for v in values]
    assert json.dumps([row['typed'] for row in received]) == json.dumps(values)

def test_absent_values_are_not_invented_by_inherited_metadata():
    original = {'camera': records()}
    del original['camera'][11]['annotation']
    wire = compact_context(original)
    assert expand_context(wire) == original
    assert 'annotation' not in expand_context(wire)['camera'][11]
    assert expand_context(wire)['camera'][8]['annotation'] is None

def test_unique_values_remain_explicit_in_each_acquired_record():
    rows = records()[:3]
    for row in rows:
        row.clear()
    for i, row in enumerate(rows):
        row.update(measurement_id=str(i), location=str(i), captured_at_s=i, x=str(i))
    wire = compact_context({'camera': rows})
    assert expand_context(wire)['camera'] == rows
    assert 'x' not in wire['camera']['shared']
