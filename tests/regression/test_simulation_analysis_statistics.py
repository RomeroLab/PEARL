"""Detached durable numerical records across message construction."""
from copy import deepcopy
import pytest
from pearl.runtime.analysis_memory import analysis_memory
from pearl.state.events import ToolCallEvent

def record(tool, result):
    return ToolCallEvent(source_agent='reasoner', tool_name=tool, params={}, result=result, executed=False)

def test_fit_ancestry_from_context_cannot_rewrite_the_recorded_calculation():
    events = [record('analyze_measured_course', {'calculation_id': 'rate', 'status': 'ok', 'measurement_ids': [], 'blank_measurement_ids': []}), record('analyze_measured_mm_rates', {'calculation_id': 'fit', 'status': 'weak', 'rate_calculation_ids': ['rate'], 'bound_rates': []})]
    before = deepcopy(events[-1].result)
    memory = analysis_memory(events, {})
    memory['calculations'][-1]['rate_calculation_ids'].clear()
    assert events[-1].result == before

@pytest.mark.parametrize('tool,statistics', [('analyze_measured_course', {'r2': 0.991, 'conversion_fraction': 0.08, 'slope_od_per_s': 0.002, 'window_s': [10, 20]}), ('analyze_measured_mm_rates', {'KM_uM': 81, 'Vmax_uM_per_s': 0.2, 'KM_se_uM': 3, 'Vmax_se_uM_per_s': 0.01, 'r2': 0.97, 'residuals': [[10, 0.003]], 'identifiability': {'vmax_approached': False}, 'levels_used': 5})])
def test_success_or_failure_statistics_remain_complete_and_detached(tool, statistics):
    event = record(tool, {'calculation_id': 'calculation', 'status': 'weak', **statistics})
    before = deepcopy(event.result)
    stored = analysis_memory([event], {})['calculations'][0]
    assert stored['status'] == 'weak'
    assert stored['fit_statistics'] == statistics
    for value in stored['fit_statistics'].values():
        if isinstance(value, (list, dict)):
            value.clear()
    stored['fit_statistics'].clear()
    assert event.result == before
