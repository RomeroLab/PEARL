"""A selected mathematical domain is distinct from sampled or physical feasibility."""
from fractions import Fraction
import math
import pytest
from pearl.brain.analysis_utilities import execute_utility, utility_schemas
from pearl.eyes.color_calibration import ColorCalibrator, predict_mix_color
MODEL = 'volume_weighted_encoded_rgb_approximation'

def lab(rgb):
    return list(ColorCalibrator.bgr_to_lab(tuple(reversed(rgb))))

def arguments(first=(230, 35, 90), second=(20, 180, 140), target=(100, 110, 115), bounds=(0, 1)):
    return dict(first_color=list(first), second_color=list(second), target_lab=lab(target), fraction_bounds=list(bounds), model=MODEL)

def run(args):
    result = execute_utility('analyze_observed_color_range', args)
    assert result.get('status') == 'ok', result
    return result

def point_distance(args, fraction):
    rgb = predict_mix_color([(tuple(args['first_color']), fraction), (tuple(args['second_color']), 1 - fraction)])['rgb']
    return ColorCalibrator.delta_e(tuple(lab(rgb)), tuple(args['target_lab']))

def test_an_interior_model_match_is_found_without_endpoint_success():
    args = arguments((255, 255, 255), (0, 0, 0), (128, 128, 128))
    result = run(args)
    assert point_distance(args, 0) > 20 and point_distance(args, 1) > 20
    assert result['distance_lower_bound'] == result['distance_upper_bound'] == 0
    assert 0 < result['witness']['first_fraction'] < 1
    assert result['witness']['rgb'] == [128, 128, 128]

@pytest.mark.parametrize('bounds', [(0, 0.25), (0.75, 1), (0.333, 0.333)])
def test_the_caller_domain_is_retained_and_restricts_the_solution(bounds):
    args = arguments((255, 255, 255), (0, 0, 0), (128, 128, 128), bounds)
    result = run(args)
    assert result['fraction_bounds'] == list(bounds)
    assert bounds[0] <= result['witness']['first_fraction'] <= bounds[1]
    assert result['distance_lower_bound'] > 0

@pytest.mark.parametrize('first,second,target,bounds', [((230, 35, 90), (20, 180, 140), (100, 110, 115), (0, 1)), ((2, 7, 4), (9, 1, 8), (4, 4, 6), (0.13, 0.83)), ((7, 40, 210), (240, 90, 3), (73, 68, 140), (0.02, 0.98)), ((82, 82, 82), (82, 82, 82), (0, 0, 0), (0, 1))])
def test_enclosure_covers_an_independent_dense_point_model_oracle(first, second, target, bounds):
    args = arguments(first, second, target, bounds)
    result = run(args)
    distances = [point_distance(args, bounds[0] + (bounds[1] - bounds[0]) * i / 1000) for i in range(1001)]
    assert result['distance_lower_bound'] <= min(distances) + 1e-09
    assert result['distance_lower_bound'] <= result['distance_upper_bound']
    assert result['distance_upper_bound'] <= min(distances) + 0.5
    witness = result['witness']
    fraction = witness['first_fraction']
    assert Fraction(witness['first_fraction_exact']) == Fraction(fraction)
    expected = list(predict_mix_color([(first, fraction), (second, 1 - fraction)])['rgb'])
    assert witness['rgb'] == expected
    assert witness['lab'] == lab(expected)
    assert witness['delta_e'] == ColorCalibrator.delta_e(tuple(lab(expected)), tuple(args['target_lab']))
    assert result['distance_upper_bound'] == witness['delta_e']

@pytest.mark.parametrize('first,second,fraction', [((5, 5, 5), (0, 0, 0), 0.1), ((15, 15, 15), (10, 10, 10), 0.1), ((5, 5, 5), (0, 0, 0), 0.7), ((25, 25, 25), (0, 0, 0), 0.1), ((5, 5, 5), (0, 0, 0), math.nextafter(0.1, 0)), ((5, 5, 5), (0, 0, 0), math.nextafter(0.1, 1))])
def test_singleton_domains_cover_the_existing_float_point_formatter(first, second, fraction):
    expected = predict_mix_color([(first, fraction), (second, 1 - fraction)])['rgb']
    result = run(arguments(first, second, expected, (fraction, fraction)))
    assert result['distance_lower_bound'] == result['distance_upper_bound'] == 0
    assert result['witness']['rgb'] == list(expected)

@pytest.mark.parametrize('bounds', [(0, 1), (0.5, 0.5), (math.nextafter(0.5, 0), math.nextafter(0.5, 1))])
def test_simultaneous_rounding_ties_do_not_turn_a_relaxation_into_a_model_witness(bounds):
    result = run(arguments((1, 1, 1), (0, 0, 0), (0, 1, 0), bounds))
    assert 0 <= result['distance_lower_bound'] <= result['distance_upper_bound']
    assert result['distance_upper_bound'] > 0
    assert result['witness']['rgb'] in ([0, 0, 0], [1, 1, 1])

def test_mathematical_scope_does_not_establish_a_physical_outcome_or_approval():
    result = run(arguments())
    assert result['scope'] == 'conditional_model_only'
    assert result['model'] == MODEL and result['metric'] == 'CIE76'
    assert not any((result.get(k) is True for k in ('physical_model_verified', 'execution_approved', 'cause_confirmed', 'achieved', 'feasible')))
    assert result['evidence_status'] == 'caller_supplied_values_not_verified'

def test_standalone_range_calculation_is_available_only_in_the_color_utility_menu():
    for include_color in (True, False):
        names = {s['function']['name'] for s in utility_schemas(include_color=include_color)}
        assert ('analyze_observed_color_range' in names) is include_color

@pytest.mark.parametrize('field,value', [('first_color', [True, 20, 30]), ('first_color', [1.5, 20, 30]), ('first_color', [-1, 20, 30]), ('second_color', [1, 256, 30]), ('second_color', [1, 20]), ('target_lab', [101, 0, 0]), ('target_lab', [10, float('nan'), 0]), ('target_lab', [True, 0, 0]), ('fraction_bounds', [False, 1]), ('fraction_bounds', [-0.1, 1]), ('fraction_bounds', [0, 1.1]), ('fraction_bounds', [0.8, 0.2]), ('fraction_bounds', [0, float('inf')]), ('fraction_bounds', [0]), ('model', 'physical_truth'), ('quality_threshold', 100)])
def test_invalid_or_scientifically_unowned_inputs_fail_closed(field, value):
    args = arguments()
    args[field] = value
    result = execute_utility('analyze_observed_color_range', args)
    assert result['status'] == 'invalid_input', result
