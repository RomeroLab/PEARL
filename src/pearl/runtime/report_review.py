"""Review identity and bounded public computation context; no scientific verdicts."""
import json
from copy import deepcopy
SUBJECT_FIELDS = ('conclusion', 'decision_ref', 'task_resolution', 'measurement_ids', 'adopted_measurement_ids', 'calculation_ids', 'analysis_basis', 'cohort_adoption_coverage')

def report_subject(report):
    """Exact claims, canonical decisions and selected evidence/methods."""
    return json.dumps({k: report[k] for k in SUBJECT_FIELDS if k in report}, sort_keys=True, separators=(',', ':'), allow_nan=False)

def report_changes(previous, current, report_id):
    before, after = (json.loads(previous) if previous else {}, json.loads(current))
    return {'previous_report_id': report_id, 'changed_fields': [k for k in SUBJECT_FIELDS if before.get(k) != after.get(k)], 'scope': 'Changed claims, decisions, evidence or methods require review. Reuse the exact reviewed report to reaffirm it; wording changes conservatively receive review. Read the previous report by event ID.'}

def _computation(event):
    return getattr(event, 'event_type', None) == 'tool_call' and getattr(event, 'executed', None) is False and (event.tool_name != 'find_acquired_observations') and (not event.tool_name.startswith(('read_', 'record_')))

def report_frontier(events):
    """New observations, executed actions or computations invalidate old review coverage."""
    return next((e.event_id for e in reversed(events) if getattr(e, 'observation_type', None) == 'camera' or getattr(e, 'executed', None) is True or _computation(e)), None)

def _computation_identity(event):
    row = {'event_id': event.event_id, 'tool_name': event.tool_name}
    if isinstance(event.result, dict) and isinstance(event.result.get('calculation_id'), str):
        row['calculation_id'] = event.result['calculation_id']
    return row

def computation_index(events):
    """Bounded identities, not copies, adoption or scientific judgments."""
    results = [e for e in events if _computation(e)]
    return {'total': len(results), 'omitted': max(0, len(results) - 16), 'recent_results': [_computation_identity(e) for e in results[-16:]], 'scope': 'Public nonexecuting tool identities only. Read exact records by event_id using read_shared_events; chronological pages retain older records. Retention and citation do not establish adoption, applicability or scientific validity.'}

def computation_context(events):
    """Keep small exact results; large/older records remain retrievable by event ID."""
    results = [e for e in events if _computation(e)]
    rows = []
    for event in results[-16:]:
        row = _computation_identity(event)
        detail = {'params': event.params, 'result': event.result}
        if len(json.dumps(detail, allow_nan=False).encode()) <= 2048:
            row.update(deepcopy(detail))
        else:
            row['read_full_event'] = True
        rows.append(row)
    return {'total': len(results), 'omitted': max(0, len(results) - 16), 'recent_results': rows, 'calculation_ids_scope': 'acquired_kinetic_analyses', 'scope': 'Exact public nonexecuting tool results, not acquired outcomes or proof of general validity. Formal calculation_ids select acquired kinetic analyses; other computations retain their report/decision citations and exact public event lineage. Check new claims against counterexamples and assumptions. Use read_shared_events for full referenced results or chronological pages of older results.'}
