"""Colour calculations never imply verified measurements or a root cause."""
from copy import deepcopy
import pytest
from pearl.brain.analysis_utilities import execute_utility, utility_schemas

def arguments():
    return {'target_lab': {'L': 100, 'a': 0, 'b': 0}, 'readings': [{'id': 'plate:A1', 'b': 0, 'g': 0, 'r': 0}]}

def test_black_against_white_has_cie76_distance_100_and_negative_lightness_gap():
    data = arguments()
    result = execute_utility('analyze_color_difference', data)
    assert result['status'] == 'ok'
    assert result['metric'] == 'CIE76'
    assert result['comparisons'] == [{'id': 'plate:A1', 'lab': [0, 0, 0], 'delta_e': 100, 'delta_L': -100, 'delta_a': 0, 'delta_b': 0}]
    assert result['evidence_status'] == 'caller_supplied_values_not_verified'
    assert result['cause_status'] == 'unconfirmed'
    assert 'passed' not in result
    assert data == arguments()

def test_bgr_channel_order_and_multiple_samples_use_shared_calibration():
    data = {'target_lab': {'L': 53.2408, 'a': 80.0925, 'b': 67.2032}, 'readings': [{'id': 'red', 'b': 0, 'g': 0, 'r': 255}, {'id': 'blue', 'b': 255, 'g': 0, 'r': 0}]}
    result = execute_utility('analyze_color_difference', data)
    assert result['status'] == 'ok'
    assert result['comparisons'][0]['delta_e'] == pytest.approx(0, abs=0.001)
    assert result['comparisons'][1]['delta_e'] > 170

@pytest.mark.parametrize('defect', ['bool', 'fraction', 'negative', 'over_byte', 'nan', 'infinite_target', 'invalid_L', 'missing', 'extra', 'duplicate_id', 'empty', 'too_many'])
def test_invalid_inputs_are_not_computed(defect):
    data = arguments()
    row = data['readings'][0]
    if defect == 'bool':
        row['b'] = True
    elif defect == 'fraction':
        row['b'] = 0.5
    elif defect == 'negative':
        row['b'] = -1
    elif defect == 'over_byte':
        row['r'] = 256
    elif defect == 'nan':
        row['g'] = float('nan')
    elif defect == 'infinite_target':
        data['target_lab']['a'] = float('inf')
    elif defect == 'invalid_L':
        data['target_lab']['L'] = 101
    elif defect == 'missing':
        del row['g']
    elif defect == 'extra':
        row['concentration'] = 5
    elif defect == 'duplicate_id':
        data['readings'].append(deepcopy(row))
    elif defect == 'empty':
        data['readings'] = []
    elif defect == 'too_many':
        data['readings'] *= 257
    assert execute_utility('analyze_color_difference', data)['status'] == 'invalid_input'

def test_color_schema_is_opt_in_to_avoid_unrelated_input_cost():
    names = lambda schemas: {row['function']['name'] for row in schemas}
    assert 'analyze_color_difference' not in names(utility_schemas())
    assert 'analyze_color_difference' in names(utility_schemas(include_color=True))

def test_signed_lab_axes_preserve_direction_and_reconstruct_distance():
    import math
    result = execute_utility('analyze_color_difference', {'target_lab': {'L': 10, 'a': -20, 'b': 30}, 'readings': [{'id': 'black', 'b': 0, 'g': 0, 'r': 0}]})
    row = result['comparisons'][0]
    assert (row['delta_L'], row['delta_a'], row['delta_b']) == (-10, 20, -30)
    assert row['delta_e'] == pytest.approx(math.sqrt(1400))
    assert result['cause_status'] == 'unconfirmed' and 'passed' not in result
