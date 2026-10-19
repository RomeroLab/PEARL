"""Scoped, model-authored observation-use judgments without automatic selection."""
from jsonschema import ValidationError, validate
from pearl.runtime.observation_references import ACQUIRED_IDS_DESCRIPTION

def evidence_use_schema(*, compact=False):
    text = {'type': 'string', 'minLength': 1, 'pattern': '\\S'}
    ids = {'type': 'array', 'items': text, 'uniqueItems': True, 'maxItems': 4096, 'description': ACQUIRED_IDS_DESCRIPTION}
    judgment = {'type': 'string', 'enum': ['supported', 'challenged', 'unresolved']}
    observation = {'location': text, 'measurement_ids': {**ids, 'minItems': 1}, 'supporting_evidence_ids': ids, 'contrary_evidence_ids': ids, 'assessment': judgment, 'proposed_use': {'type': 'string', 'enum': ['retain', 'qualified', 'exclude', 'defer']}, 'cause_hypothesis': {'anyOf': [text, {'type': 'null'}], 'description': 'Provisional explanation or null; neither establishes cause nor determines selection.'}, 'rationale': text}
    remaining = {'measurement_ids': ids, 'assessment': judgment, 'rationale': text}
    properties = {'intended_use': text, 'assumptions': text, 'observations': {'type': 'array', 'maxItems': 256, 'items': {'type': 'object', 'properties': observation, 'required': list(observation), 'additionalProperties': False}}, 'remaining_evidence': {'type': 'object', 'properties': remaining, 'required': list(remaining), 'additionalProperties': False}}
    result = {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False, 'description': 'Scoped observation-use assessment when material to a decision. Bind exact public locations and acquired IDs; compare supporting and contrary evidence, provisional cause, proposed use and remaining sufficiency under original criteria. No observations, exclusion, cause or success are inferred. Apply selection separately using existing evidence decisions; preserve diagnostic/all-data results.'}
    if compact:

        def trim(node):
            if isinstance(node, dict):
                return {k: trim(v) for k, v in node.items() if k not in ('pattern', 'maxItems') and (k != 'description' or v == ACQUIRED_IDS_DESCRIPTION)}
            if isinstance(node, list):
                return [trim(v) for v in node]
            return node
        result = trim(result)
        result['description'] = 'Authored use assessment; hypotheses and sufficiency are unverified. Selection is explicit, not automatic.'
    return result

def validate_evidence_use(value, evidence):
    """Check references and internal scope, not scientific truth or achievement."""
    try:
        validate(value, evidence_use_schema())
    except ValidationError as exc:
        raise ValueError('evidence_use: ' + exc.message) from exc

    def acquired(ids):
        if any((mid not in evidence for mid in ids)):
            raise ValueError('evidence_use requires acquired measurement IDs')
    seen = set()
    nonused = set()
    for row in value['observations']:
        target = row['measurement_ids']
        acquired(target)
        acquired(row['supporting_evidence_ids'])
        acquired(row['contrary_evidence_ids'])
        if any((evidence[mid].get('location') != row['location'] for mid in target)):
            raise ValueError('evidence_use target IDs must match the exact declared location')
        if seen.intersection(target):
            raise ValueError('evidence_use has repeated or conflicting observational judgments')
        seen.update(target)
        if row['proposed_use'] in ('exclude', 'defer'):
            nonused.update(target)
    remaining = value['remaining_evidence']['measurement_ids']
    acquired(remaining)
    if nonused.intersection(remaining):
        raise ValueError('evidence_use remaining inputs include proposed excluded or deferred observations')
