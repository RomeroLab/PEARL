"""Acquired observation extent alongside historical rate calculations."""
from copy import deepcopy

def observation_coverage(interval, evidence, active_exclusions, actions):
    if not interval or any((mid not in evidence or evidence[mid].get('captured_at_s') is None for mid in interval)):
        return {'status': 'unavailable', 'later_observation_count': None}
    endpoint = max((evidence[mid] for mid in interval), key=lambda row: row['captured_at_s'])
    location = endpoint['location']
    end_s = endpoint['captured_at_s']
    later = sorted((row for row in evidence.values() if row['location'] == location and row['captured_at_s'] > end_s), key=lambda row: row['captured_at_s'])
    preparation = [action for action in actions if action['action'] in ('transfer', 'mix') and location in (action['params'].get('source'), action['params'].get('target'), action['params'].get('location'))]
    subsequent = [action for action in preparation if action['completed_at_s'] is not None and action['completed_at_s'] > end_s]

    def reference(row):
        return {key: row[key] for key in ('measurement_id', 'location', 'captured_at_s')}
    return {'status': 'available', 'scope': 'Acquisition inventory, not eligibility or a recommendation to extend the fitted interval. Inspect measurements and action history before interpretation.', 'later_observation_count': len(later), 'first_later_observation': reference(later[0]) if later else None, 'latest_later_observation': reference(later[-1]) if later else None, 'later_clipped_count': sum((bool(row.get('clipped')) for row in later)), 'later_excluded_count': sum((row['measurement_id'] in active_exclusions for row in later)), 'preparation_operation_count_after_interval': len(subsequent), 'last_preparation_operation_after_interval': deepcopy(subsequent[-1]) if subsequent else None, 'preparation_operations_without_time_count': sum((action['completed_at_s'] is None for action in preparation))}
