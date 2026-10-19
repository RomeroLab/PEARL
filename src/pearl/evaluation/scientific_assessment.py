"""Versioned structural assessment contracts; this module never assigns a grade."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from jsonschema import ValidationError, validate
CONTRACT_ID = 'public-scientific-evidence-pae-v1'
LEGACY_CONTRACT_ID = 'public_scientific_evidence'
AXES = ('P', 'A', 'E')
AXIS_MEANINGS = {'P': 'Planning', 'A': 'Adaptation', 'E': 'Execution'}
RUBRIC_SHA256 = '7659b4c4c2d46242dfddbf7aed235782026ef97fffa944d45326544d3671b1a9'
GOAL_STATUSES = ('supported', 'logical_conflict_supported', 'insufficient', 'contradicted', 'unassessable')
TEXT = {'type': 'string', 'minLength': 1}
IDS = {'type': 'array', 'minItems': 1, 'uniqueItems': True, 'items': TEXT}

def obj(properties):
    return {'type': 'object', 'properties': deepcopy(properties), 'required': list(properties), 'additionalProperties': False}
AXIS_SCHEMA = obj({'objective': TEXT, 'reasoning': TEXT, 'evidence_ids': IDS, 'limitations': TEXT})
REVIEW_SCHEMA = {'type': 'object', 'not': {'anyOf': [{'required': ['I']}, {'required': ['D']}]}, 'if': {'properties': {'E': {'const': True}}}, 'then': {'properties': {'goal_support': {'properties': {'status': {'enum': ['supported', 'logical_conflict_supported']}}}}}, 'required': ['assessment_contract_id', *AXES, 'axis_assessments', 'goal_support', 'acceptance_basis'], 'properties': {'assessment_contract_id': {'const': CONTRACT_ID}, **{axis: {'type': ['boolean', 'null']} for axis in AXES}, 'axis_assessments': obj(dict.fromkeys(AXES, AXIS_SCHEMA)), 'goal_support': obj({'status': {'enum': list(GOAL_STATUSES)}, 'reasoning': TEXT, 'evidence_ids': IDS}), 'acceptance_basis': {'type': 'array', 'minItems': 1, 'items': obj({'premise': TEXT, 'origin': {'enum': ['public_requirement', 'scientific_justification']}, 'introduced_at_event_id': {'type': ['string', 'null']}, 'rationale': TEXT})}}}

def require_contract(value):
    if not isinstance(value, dict) or value.get('assessment_contract_id') != CONTRACT_ID:
        raise ValueError('Exact P/A/E assessment contract required')

def output_contract():
    return {'assessment_contract_id': CONTRACT_ID, 'status': 'reviewed', 'axis_types': dict.fromkeys(AXES, 'boolean_or_null'), 'axis_meanings': deepcopy(AXIS_MEANINGS), 'schema': deepcopy(REVIEW_SCHEMA), 'axis_assessments': {'each_axis_requires': list(AXIS_SCHEMA['required'])}, 'goal_support': {'allowed_statuses': list(GOAL_STATUSES)}, 'required_identity_fields': ['scenario_id', 'source_manifest_sha256', 'raw_sha256', 'ablation_profile', 'reviewer_identity', 'review_seat_sha256', 'public_bundle_sha256', 'public_only', 'private_audit_read'], 'judgment': 'Independent scientific judgment required; structural validity is not scientific truth.'}

def validate_review_shape(review):
    """Check the shared contract shape without asserting evidence sufficiency."""
    require_contract(review)
    if 'I' in review or 'D' in review:
        raise ValueError('Legacy interpretation/detection axes cannot alias Adaptation')
    try:
        validate(review, REVIEW_SCHEMA)
    except ValidationError as exc:
        raise ValueError('Invalid P/A/E review structure: ' + exc.message) from exc
    if any((type(review[axis]) is not bool and review[axis] is not None for axis in AXES)):
        raise ValueError('Actual Boolean or null scientific axes required')

def validate_review_structure(review, refs):
    require_contract(review)
    validate_review_shape(review)
    for row in [*review['axis_assessments'].values(), review['goal_support']]:
        if any((isinstance(v, str) and (not v.strip()) for v in row.values())):
            raise ValueError('Nonblank scientific reasoning required')
        if any((ref not in refs for ref in row['evidence_ids'])):
            raise ValueError('Use real public evidence IDs')
    if review['E'] is True and review['goal_support']['status'] not in ('supported', 'logical_conflict_supported'):
        raise ValueError('Unsupported achieved goal cannot coexist with E=true')
    for row in review['acceptance_basis']:
        if not row['premise'].strip() or not row['rationale'].strip():
            raise ValueError('Nonblank acceptance premise and justification required')
        if row['introduced_at_event_id'] is not None and row['introduced_at_event_id'] not in refs:
            raise ValueError('Premise introduction must identify real public evidence or be null')

def require_success(review):
    require_contract(review)
    if 'I' in review or any((review.get(axis) is not True for axis in AXES)):
        raise ValueError('Stop at first P/A/E false, null, missing axis or incompatible review')

def validate_rubric(content):
    if hashlib.sha256(content.encode('utf-8')).hexdigest() != RUBRIC_SHA256:
        raise ValueError('Exact frozen P/A/E reviewer rubric required')

def available_references(raw):
    """Index public IDs and validate recorded order, without judging sufficiency."""
    refs = {'setup'}
    sequence = 0
    capture_time = -1.0
    acquired = {}
    for line in (Path(raw) / 'events.jsonl').read_text().splitlines():
        event = json.loads(line)
        current = event.get('trace_sequence')
        if type(current) is not int or current <= sequence:
            raise ValueError('Public acquisition/event chronology must preserve trace order')
        sequence = current
        if not isinstance(event.get('event_id'), str) or event['event_id'] in refs:
            raise ValueError('Distinct public event identities required')
        refs.add(event['event_id'])
        if event.get('observation_type') == 'camera':
            payload = event['payload']
            time = payload.get('captured_at_s')
            if type(time) not in (int, float) or not math.isfinite(time) or time < 0 or (time < capture_time):
                raise ValueError('Acquisition time must be finite and chronological')
            capture_time = time
            for sample in payload.get('measurements', []):
                mid = sample['measurement_id']
                if not isinstance(mid, str) or sample.get('captured_at_s') != time:
                    raise ValueError('Measurement identity/time must match its acquired frame')
                if mid in acquired and acquired[mid] != sample:
                    raise ValueError('Acquired measurements are immutable')
                acquired[mid] = deepcopy(sample)
                refs.add(mid)
        result = event.get('result')
        if isinstance(result, dict) and isinstance(result.get('calculation_id'), str):
            refs.add(result['calculation_id'])
    for line in (Path(raw) / 'model.exchanges.jsonl').read_text().splitlines():
        exchange = json.loads(line)
        if isinstance(exchange.get('exchange_id'), str):
            refs.add(exchange['exchange_id'])
    return refs

def operational_outcome(result):
    return {'status': 'not_evaluated', 'operational_result': deepcopy(result)}

def read_historical(value, manifest):
    if manifest.get('evaluation_contract') != LEGACY_CONTRACT_ID or 'assessment_contract_id' in value:
        raise ValueError('An explicit historical I/P/E manifest is required; no axis coercion')
    axes = ('I', 'P', 'E')
    if any((axis not in value or (type(value[axis]) is not bool and value[axis] is not None) for axis in axes)):
        raise ValueError('Original historical axes required')
    return {'assessment_contract_id': LEGACY_CONTRACT_ID, 'source_manifest_sha256': value.get('source_manifest_sha256'), 'ablation_profile': manifest.get('ablation_profile', 'legacy_unspecified'), 'axes': {axis: value[axis] for axis in axes}, 'original': deepcopy(value)}

def read_current(value):
    validate_review_shape(value)
    for field in ('source_manifest_sha256', 'ablation_profile'):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError('Explicit current source and ablation population required')
    return {'assessment_contract_id': CONTRACT_ID, 'source_manifest_sha256': value['source_manifest_sha256'], 'ablation_profile': value['ablation_profile'], 'axes': {axis: value[axis] for axis in AXES}, 'original': deepcopy(value)}

def group_assessments(rows):
    groups = {}
    for row in rows:
        key = (row['assessment_contract_id'], row['source_manifest_sha256'], row['ablation_profile'])
        groups.setdefault(key, []).append(deepcopy(row))
    return groups
