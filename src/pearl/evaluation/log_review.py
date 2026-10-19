"""Prepare public packets and bind independent authored P/A/E assessments."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from pearl.evaluation.scientific_assessment import (
    CONTRACT_ID, RUBRIC_SHA256, available_references, output_contract,
    require_contract, require_success, validate_review_shape, validate_review_structure, validate_rubric,
)
ROOT = Path(__file__).resolve().parents[3]
PUBLIC_NAMES = ('setup.json', 'events.jsonl', 'model.exchanges.jsonl', 'result.json')
CRITERIA = 'PUBLIC_REVIEW_CRITERIA.md'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False); f.write('\n')


def prepare(raw, output, reviewer_identity):
    raw, out = Path(raw).resolve(), Path(output).absolute()
    if not isinstance(reviewer_identity, str) or not reviewer_identity.strip():
        raise ValueError('An independent reviewer identity is required')
    result = read(raw/'result.json')
    require_contract(result)
    out.mkdir(parents=True, exist_ok=False)
    if result.get('termination') != 'completed' or result.get('error_type'):
        value = {'status': 'not_evaluated', 'assessment_contract_id': CONTRACT_ID,
                 'operational_result': result}
        save(out/'operational_outcome.json', value)
        return value
    setup = read(raw/'setup.json'); require_contract(setup)
    for key in ('scenario_id', 'ablation_profile', 'source_manifest_sha256'):
        if not isinstance(setup.get(key), str) or not setup[key] or result.get(key) != setup[key]:
            raise ValueError('Exact source, scenario and ablation identity required')
    for name in PUBLIC_NAMES:
        if (raw/name).is_symlink() or not (raw/name).is_file():
            raise ValueError('Regular immutable public log files required')
    available_references(raw)
    rubric = (ROOT/'docs/evaluation/SCIENTIFIC_EVIDENCE_CONTRACT.md').read_text()
    validate_rubric(rubric)
    raw_hashes = {name: sha(raw/name) for name in PUBLIC_NAMES}
    save(out/'origin_binding.json', {'raw_path': str(raw), 'raw_sha256': raw_hashes})
    public = out/'public'; public.mkdir()
    for name in PUBLIC_NAMES: shutil.copyfile(raw/name, public/name)
    (public/CRITERIA).write_text(rubric)
    bundle = {'assessment_contract_id': CONTRACT_ID, 'scenario_id': setup['scenario_id'],
        'ablation_profile': setup['ablation_profile'], 'source_manifest_sha256': setup['source_manifest_sha256'],
        'raw_sha256': raw_hashes, 'scientific_evidence_contract_sha256': RUBRIC_SHA256,
        'public_file_sha256': {**raw_hashes, CRITERIA: RUBRIC_SHA256},
        'origin_binding_sha256': sha(out/'origin_binding.json'), 'audit_body_not_copied': True,
        'review_output_contract': output_contract()}
    save(out/'PUBLIC_BUNDLE.json', bundle)
    seat = {'assessment_contract_id': CONTRACT_ID, 'scenario_id': setup['scenario_id'],
        'reviewer_identity': reviewer_identity, 'fresh_context': True, 'fork_turns': 'none',
        'coordinator': False, 'public_only': True, 'private_audit_read': False,
        'public_bundle_sha256': sha(out/'PUBLIC_BUNDLE.json')}
    save(out/'REVIEW_SEAT.json', seat)
    instruction = (ROOT/'docs/evaluation/PAE_REVIEWER_DELEGATION.md').read_text()
    assignment = {'assessment_contract_id': CONTRACT_ID, 'reviewer_identity': reviewer_identity,
        'fork_turns': 'none', 'allowed_files': [str(out/name) for name in ('PUBLIC_BUNDLE.json', 'REVIEW_SEAT.json')]
            + [str(public/name) for name in (*PUBLIC_NAMES, CRITERIA)],
        'instruction': instruction, 'rubric': rubric, 'output_contract': output_contract(),
        'output_path': str(out/'INDEPENDENT_REVIEW.json')}
    save(out/'REVIEW_ASSIGNMENT.json', assignment)
    return assignment


def verify_packet(out):
    out = Path(out)
    try:
        bundle, seat = read(out/'PUBLIC_BUNDLE.json'), read(out/'REVIEW_SEAT.json')
        for value in (bundle, seat): require_contract(value)
        if bundle.get('review_output_contract') != output_contract() or bundle.get('scientific_evidence_contract_sha256') != RUBRIC_SHA256:
            raise ValueError('Exact P/A/E output and rubric binding required')
        if bundle.get('audit_body_not_copied') is not True or sha(out/'origin_binding.json') != bundle['origin_binding_sha256']:
            raise ValueError('Public-only original log binding required')
        if seat.get('public_bundle_sha256') != sha(out/'PUBLIC_BUNDLE.json') or seat.get('scenario_id') != bundle['scenario_id']:
            raise ValueError('Review seat differs from packet')
        for key, expected in {'fresh_context': True, 'coordinator': False, 'public_only': True, 'private_audit_read': False}.items():
            if seat.get(key) is not expected: raise ValueError('Independent public review seat required')
        if seat.get('fork_turns') != 'none': raise ValueError('Fresh context required')
        names = {*PUBLIC_NAMES, CRITERIA}
        public = out/'public'
        if {p.name for p in public.iterdir()} != names:
            raise ValueError('Exact public file allowlist required')
        expected_hashes = {**bundle['raw_sha256'], CRITERIA: RUBRIC_SHA256}
        if bundle.get('public_file_sha256') != expected_hashes:
            raise ValueError('Public hash binding differs')
        if any((public/n).is_symlink() or sha(public/n) != expected_hashes[n] for n in names):
            raise ValueError('Public logs or rubric changed')
        validate_rubric((public/CRITERIA).read_text())
        origin = read(out/'origin_binding.json'); raw = Path(origin['raw_path'])
        if origin['raw_sha256'] != bundle['raw_sha256'] or any(sha(raw/n) != bundle['raw_sha256'][n] for n in PUBLIC_NAMES):
            raise ValueError('Original acquired log changed')
        return bundle, seat, available_references(public)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Missing or invalid public review provenance') from exc


def dispatch_assignment(output, client):
    out = Path(output); bundle, seat, refs = verify_packet(out)
    task = read(out/'REVIEW_ASSIGNMENT.json')
    wanted = [str(out/name) for name in ('PUBLIC_BUNDLE.json', 'REVIEW_SEAT.json')]+[
        str(out/'public'/name) for name in (*PUBLIC_NAMES, CRITERIA)]
    if task.get('assessment_contract_id') != CONTRACT_ID or task.get('output_contract') != output_contract() or task.get('allowed_files') != wanted or task.get('reviewer_identity') != seat['reviewer_identity']:
        raise ValueError('Exact new-contract assignment required')
    if task.get('rubric') != (out/'public'/CRITERIA).read_text() or task.get('instruction') != (ROOT/'docs/evaluation/PAE_REVIEWER_DELEGATION.md').read_text():
        raise ValueError('Full exact rubric and reviewer instruction must be delivered')
    return client(deepcopy(task))


def bind_review(output, review_path):
    out = Path(output); bundle, seat, refs = verify_packet(out)
    review_path = Path(review_path)
    review = read(review_path)
    validate_review_structure(review, refs)
    expected = {key: bundle[key] for key in ('scenario_id', 'ablation_profile', 'source_manifest_sha256', 'raw_sha256')}
    expected.update(reviewer_identity=seat['reviewer_identity'], review_seat_sha256=sha(out/'REVIEW_SEAT.json'),
                    public_bundle_sha256=sha(out/'PUBLIC_BUNDLE.json'), public_only=True, private_audit_read=False)
    for key, value in expected.items():
        if (review.get(key) is not value if type(value) is bool else review.get(key) != value):
            raise ValueError(f'Independent review provenance differs: {key}')
    final = {**deepcopy(review), 'independent_review_sha256': sha(review_path)}
    save(out/'evaluation.json', final)
    return final


def require_pass(review):
    validate_review_shape(review)
    require_success(review)
