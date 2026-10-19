"""One shared clock must preserve independently chosen course starts."""
from copy import deepcopy
from pearl.brain.analysis_utilities import execute_utility

def args():
    return {'available_locations': ['x:A', 'x:B', 'x:C', 'x:D'], 'unavailable_locations': [], 'current_time_s': 60, 'location_policy': 'distinct_per_reading', 'courses': [{'id': 'later-start', 'start_time_s': 90, 'readings': [{'location': 'x:C', 'time_s': 120}, {'location': 'x:D', 'time_s': 180}]}, {'id': 'earlier-start', 'start_time_s': 60, 'readings': [{'location': 'x:A', 'time_s': 60}, {'location': 'x:B', 'time_s': 120}]}]}

def test_global_timeline_requires_wait_between_distinct_timepoint_groups():
    supplied = args()
    before = deepcopy(supplied)
    result = execute_utility('analyze_measurement_schedule', supplied)
    assert result['timeline'] == [{'time_s': 60, 'wait_from_previous_s': 0, 'readings': [{'course': 'earlier-start', 'reading_index': 0, 'location': 'x:A', 'elapsed_time_s': 0}]}, {'time_s': 120, 'wait_from_previous_s': 60, 'readings': [{'course': 'later-start', 'reading_index': 0, 'location': 'x:C', 'elapsed_time_s': 30}, {'course': 'earlier-start', 'reading_index': 1, 'location': 'x:B', 'elapsed_time_s': 60}]}, {'time_s': 180, 'wait_from_previous_s': 60, 'readings': [{'course': 'later-start', 'reading_index': 1, 'location': 'x:D', 'elapsed_time_s': 90}]}]
    assert result['execution_approved'] is False
    assert supplied == before

def test_past_reading_has_no_executable_wait_and_does_not_move_clock_backwards():
    supplied = args()
    supplied['current_time_s'] = 100
    result = execute_utility('analyze_measurement_schedule', supplied)
    assert result['constraints_satisfied_for_supplied_plan'] is False
    assert [row['wait_from_previous_s'] for row in result['timeline']] == [None, 20, 60]
    assert result['timeline'][0]['time_s'] == 60
