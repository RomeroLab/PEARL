"""Bounded unapplied decision drafts and literal condition differences."""
from copy import deepcopy
import hashlib
import json
from pearl.runtime.experiment_decision import EXPERIMENT_FIELDS
MAX_DRAFT_BYTES = 32768
REJECTION_TYPE = 'decision_submission_rejected'
SCOPE = 'Rejected, unapplied model submission for explicit correction or abandonment; not evidence, an accepted decision, a pending scientific obligation or an execution authorization. Condition differences are literal record differences, not scientific judgments. Retaining existing conditions requires an explicit reference/partial update; changing them still requires authored experiment_change. No submitted conclusion is selected by this feedback.'

def condition_comparison(value, current):
    unavailable = {'status': 'not_comparable', 'changes': []}
    if not isinstance(value, dict):
        return unavailable
    previous = current['decision'].get('decision_basis', {}).get('experiment') if current else None
    reference = current['event_id'] if current else None
    partial = 'updates' in value
    if partial:
        if not current or value.get('decision_ref') != reference or (not isinstance(value['updates'], dict)):
            return unavailable
        basis = value['updates'].get('decision_basis', {})
    elif set(value) == {'decision_ref'}:
        return {'status': 'compared', 'changes': []} if current and value['decision_ref'] == reference else unavailable
    else:
        basis = value.get('decision_basis', {})
    if not isinstance(basis, dict):
        return unavailable
    if 'retain_experiment_from' in basis:
        if not current or basis['retain_experiment_from'] != reference or 'experiment' in basis:
            return unavailable
        after = previous
    elif partial:
        proposed = basis.get('experiment', {})
        if not isinstance(proposed, dict):
            return unavailable
        after = {**(previous or {}), **proposed}
    else:
        after = basis.get('experiment')
    if after is not None and (not isinstance(after, dict)):
        return unavailable
    before, after = (previous or {}, after or {})
    changes = []
    for key in sorted(EXPERIMENT_FIELDS):
        if (key in before) != (key in after) or before.get(key) != after.get(key):
            changes.append({'path': 'decision_basis.experiment.' + key, 'before_present': key in before, 'before': deepcopy(before.get(key)), 'after_present': key in after, 'after': deepcopy(after.get(key))})
    return {'status': 'compared', 'changes': changes}

def rejection_snapshot(value, current):
    snapshot = {'state': 'rejected_unapplied', 'omitted': False, 'submitted_decision': deepcopy(value), 'condition_comparison': condition_comparison(value, current), 'scope': SCOPE}
    try:
        encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, sort_keys=True).encode('utf-8')
    except (TypeError, ValueError):
        return {'state': 'rejected_unapplied', 'omitted': True, 'reason': 'non_json_submission', 'scope': SCOPE}
    if len(encoded) > MAX_DRAFT_BYTES:
        return {'state': 'rejected_unapplied', 'omitted': True, 'reason': 'draft_byte_limit', 'original_bytes': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest(), 'scope': SCOPE}
    return snapshot

def rejected_memory(events, current_ref):
    for event in reversed(events):
        if getattr(event, 'observation_type', None) == REJECTION_TYPE and event.source_agent in ('reasoner', 'predictor', 'actor'):
            if event.payload['current_decision_ref'] != current_ref:
                return None
            return {'event_id': event.event_id, **deepcopy(event.payload)}
    return None

def validation_cause(message):
    encoded = str(message).encode('utf-8')
    return {'message': encoded[:2048].decode('utf-8', errors='ignore'), 'truncated': len(encoded) > 2048, 'original_bytes': len(encoded)}
