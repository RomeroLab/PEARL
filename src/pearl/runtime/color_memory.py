"""Public color comparisons joined to immutable acquisition-time commands."""
from copy import deepcopy
from pearl.runtime.acquisition_context import acquisition_context

def color_comparison_memory(events, evidence, reagents):
    calculations = [e for e in events if getattr(e, 'tool_name', None) == 'analyze_measured_color' and getattr(e, 'executed', None) is False and (e.result.get('status') == 'ok')]
    if not calculations:
        return {}
    ids = list(dict.fromkeys((r['measurement_id'] for e in calculations for r in e.result.get('comparisons', []))))
    context = acquisition_context([evidence[mid] for mid in ids], events, reagents)
    captures = {r['measurement_id']: r for r in context['captures']}
    preparations = {r['context_id']: r for r in context['preparations']}
    rows = []
    for event in calculations:
        for comparison in event.result.get('comparisons', []):
            mid = comparison['measurement_id']
            measurement = evidence[mid]
            prep = preparations[captures[mid]['command_context_id']]
            nominal = prep['nominal_preparation'] or {}
            change = nominal.get('last_change_completed_at_s')
            mix = nominal.get('last_mix_completed_at_s')
            rows.append({'calculation_event_id': event.event_id, 'measurement_id': mid, 'location': measurement['location'], 'captured_at_s': measurement['captured_at_s'], 'rgb': deepcopy(measurement['rgb']), 'clipped': measurement['clipped'], 'target_reference': deepcopy(event.result.get('target_reference')), **{k: deepcopy(comparison[k]) for k in ('lab', 'delta_e', 'delta_L', 'delta_a', 'delta_b') if k in comparison}, 'preparation_id': measurement['location'] + '@' + (prep['last_change_event_id'] or 'initial'), 'nominal_volume_ul': nominal.get('volume_ul'), 'source_equivalents_ul': deepcopy(nominal.get('source_equivalents_ul', {})), 'last_change_completed_at_s': change, 'last_mix_completed_at_s': mix, 'mixed_since_change': None if change is None else mix is not None and mix >= change})
    return {'comparisons': rows, 'scope': 'Recorded calculations and acquired observations, including failed, censored and intermediate results; no adoption, comparability or success is inferred. Preparation and mixing fields describe acknowledged commands at acquisition, not verified delivery, homogeneity or completion of a chosen plan. Repeated observations are not independent preparations. Full receipts remain in read_shared_events.'}
