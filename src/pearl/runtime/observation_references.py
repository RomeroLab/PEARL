"""Bind explicit scientific citations to acquired public observations."""
from copy import deepcopy
import json
import re
from pearl.runtime.analysis_memory import target_ids
ACQUIRED_IDS_DESCRIPTION = 'Acquired measurement_id.'

def acquired_reference_diagnostics(tool_name, args, acquired, public_event_ids):
    """Describe invalid acquired-ID references without repairing a rejected draft."""
    if tool_name not in ('record_plan', 'record_decision') or not isinstance(args, dict):
        return None
    public_ids = set(public_event_ids)
    errors = []
    total = 0

    def check(node, key, path):
        nonlocal total
        values = node.get(key) if isinstance(node, dict) else None
        if not isinstance(values, list):
            return
        for index, reference in enumerate(values):
            if not isinstance(reference, str) or reference in acquired:
                continue
            total += 1
            if len(errors) < 16:
                errors.append({'path': f'{path}/{key}/{index}', 'reference': reference[:80], 'reference_truncated': len(reference) > 80, 'expected_kind': 'acquired_measurement_id', 'actual_kind': 'public_event_id' if reference in public_ids else 'unknown_reference'})
    decision = args.get('decision')
    path = '/decision'
    if isinstance(decision, dict) and 'updates' in decision:
        decision = decision['updates']
        path += '/updates'
    basis = decision.get('decision_basis') if isinstance(decision, dict) else None
    if isinstance(basis, dict):
        path += '/decision_basis'
        check(basis, 'evidence_ids', path)
        change = basis.get('experiment_change')
        for key in ('evidence_ids', 'reusable_evidence_ids'):
            check(change, key, path + '/experiment_change')
        use = basis.get('evidence_use')
        if isinstance(use, dict):
            observations = use.get('observations')
            if isinstance(observations, list):
                for index, row in enumerate(observations):
                    for key in ('measurement_ids', 'supporting_evidence_ids', 'contrary_evidence_ids'):
                        check(row, key, f'{path}/evidence_use/observations/{index}')
            check(use.get('remaining_evidence'), 'measurement_ids', path + '/evidence_use/remaining_evidence')
    cohorts = args.get('cohort_updates')
    if isinstance(cohorts, list):
        for index, cohort in enumerate(cohorts):
            members = cohort.get('members') if isinstance(cohort, dict) else None
            if isinstance(members, list):
                for member_index, member in enumerate(members):
                    check(member, 'evidence_ids', f'/cohort_updates/{index}/members/{member_index}')
    if not total:
        return None
    result = {'errors': errors, 'total_errors': total, 'truncated': total > len(errors)}
    while len(json.dumps(result).encode()) > 6000:
        errors.pop()
        result['truncated'] = True
    return result

def _literal_ids(text, evidence):
    if not evidence:
        return []
    identifiers = '|'.join((re.escape(mid) for mid in evidence))
    return list(dict.fromkeys(re.findall('(?<![\\w-])(?:' + identifiers + ')(?![\\w-])', text)))

def bind_references(rows, evidence, text, *, known_evidence=None):
    """Normalize authored exact IDs; never infer a judgment or repair wrong rows."""
    resolve_references(rows, evidence, '')
    if not isinstance(text, str):
        raise ValueError('Scientific interpretation must be text')
    cited = _literal_ids(text, evidence if known_evidence is None else known_evidence)
    if any((mid not in evidence for mid in cited)):
        raise ValueError('An authored citation is outside the delivered acquired frontier')
    canonical = deepcopy(rows)
    seen = {mid for row in rows for mid in row['measurement_ids']}
    added = [mid for mid in cited if mid not in seen]
    for mid in added:
        location = evidence[mid]['location']
        row = next((r for r in canonical if r['location'] == location), None)
        if row is None:
            row = {'location': location, 'measurement_ids': []}
            canonical.append(row)
        row['measurement_ids'].append(mid)
    resolve_references(canonical, evidence, text)
    return (canonical, {'literal_bound_ids': added, 'scope': 'Only exact acquired IDs literally cited by the author; location binding is not evidence selection, diagnosis, adoption or agreement.'})

def resolve_references(rows, evidence, text):
    if not isinstance(rows, list) or len(rows) > 4096:
        raise ValueError('observation_references must be a list of acquired location/ID references')
    if not isinstance(text, str):
        raise ValueError('Scientific interpretation must be text')
    selected = []
    seen = set()
    errors = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'location', 'measurement_ids'}:
            errors.append('Each observation reference requires only location and measurement_ids')
            continue
        try:
            ids = target_ids(row['location'], row['measurement_ids'], evidence)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if seen.intersection(ids):
            errors.append('Use distinct measurement IDs across observation references')
            continue
        seen.update(ids)
        if len(seen) > 4096:
            raise ValueError('At most 4096 distinct observations may be referenced')
        selected.extend(ids)
    if evidence:
        cited = set(_literal_ids(text, evidence))
        missing = cited - seen
        if missing:
            errors.append('Acquired IDs cited in the interpretation need location-bound observation_references: ' + ', '.join(sorted(missing)))
    if errors:
        raise ValueError('\n'.join(dict.fromkeys(errors)))
    return [deepcopy(evidence[mid]) for mid in selected]
