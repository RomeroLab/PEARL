"""Immutable model-owned scientific decisions and independent advisory assessments."""
from copy import deepcopy
from collections.abc import Mapping
from pearl.runtime.experiment_decision import experiment_properties, previous_experiment, validate_experiment
from pearl.runtime.evidence_use import evidence_use_schema, validate_evidence_use
from pearl.runtime.observation_references import ACQUIRED_IDS_DESCRIPTION
from pearl.runtime.task_resolution import read_resolution, resolution_schema
from pearl.runtime.requirement_provenance import constraint_schema, validate_constraints
from pearl.state.events import ObservationEvent
SCOPE_FIELDS = {'claim': 'Distinguish the original requested outcome and constraints from the chosen experiment and its actual limited claim.', 'inference': 'At claim precision, apply actual relations/calculations to proposed settings before endorsing. Separate observations from conditional consequences; a stopping rule is not a goal inference. An unmeasured endpoint alone is not a diagnostic rationale. With no useful model, assess empirical questions. No universal proof required.', 'applicability': 'Assess public priors, conditions and contrary evidence. Quantitative gaps need not refute qualitative consequences; limitations are not counterevidence. Do not invent applicability.', 'decision_relevance': 'Does the limited claim resolve the original request? Distinguish justified task resolution from a completed method or accurate report; identify any decision-changing gap without requiring exhaustive search.'}
STOPPING_FIELDS = {'remaining_question': 'What question remains material to the original request?', 'available_option': 'A concrete option from public evidence, calculation, clarification or physical work; if none, applicable grounds. Having no proposal is not proof of unavailability; do not invent feasibility.', 'decision_value': 'Which plausible outcomes change the decision? Reconcile earlier alternatives and what changed. No exhaustive search required.', 'constraints': 'Current public grounds for feasibility, unavailability or uncertainty. Separate binding limits and missing information from chosen methods.', 'stopping_basis': 'Assess ending the original request, not merely retiring a method. An accurate negative report or no proposed alternative alone does not justify stopping; no exhaustive search is required.'}

def unresolved_report(report):
    """Use the actual submitted report, never the peer's proposed status."""
    return isinstance(report, Mapping) and isinstance(report.get('task_resolution'), Mapping) and (report['task_resolution'].get('status') == 'unresolved')

class DecisionValidationError(ValueError):
    """Rejected submission with public structural repair context; no automatic edits."""

    def __init__(self, message, repair):
        super().__init__(message)
        self.repair = repair

def decision_schema(*, include_updates=False, compact_basis=False):
    inline = resolution_schema()
    inline['properties']['basis'].pop('description')
    inline['properties']['next_step'].pop('description')
    achieved_summary = deepcopy(inline)
    achieved_summary['properties']['status']['enum'] = ['achieved']
    text = {'type': 'string', 'minLength': 1}
    inline['properties'].update(decision_basis={'type': 'object', 'properties': {**experiment_properties(), 'evidence_use': evidence_use_schema(compact=True), 'retain_experiment_from': {**text, 'description': 'Reuse current; omit experiment field'}, **{k: text for k in ('premise', 'alternative', 'expected_information', 'constraints')}, 'evidence_ids': {'type': 'array', 'items': text, 'uniqueItems': True, 'description': ACQUIRED_IDS_DESCRIPTION}, 'working_model': {'type': 'object', 'properties': {k: text for k in ('assumptions', 'applicability', 'implication')}, 'required': ['assumptions', 'applicability', 'implication'], 'additionalProperties': False, 'description': 'Before adoption: model relation/domain entails original goal? Actual consequence, qualitative/numeric precision, settings/predicted response. No applicable model: empirical. Not observations/stopping rule'}}, 'required': ['premise', 'alternative', 'expected_information', 'constraints', 'evidence_ids', 'working_model'], 'additionalProperties': False, 'description': 'Nest premise,alternative,expected_information,constraints,evidence_ids,working_model in decision_basis.'}, supersedes={'type': ['string', 'null'], 'description': 'Current ID or null.'})
    inline['required'] += ['decision_basis', 'supersedes']

    def partial(node):
        result = deepcopy(node)
        if result.get('description') != ACQUIRED_IDS_DESCRIPTION:
            result.pop('description', None)
        if result.get('type') == 'object':
            result.pop('required', None)
            result['minProperties'] = 1
            result['properties'] = {k: partial(v) for k, v in result['properties'].items()}
        return result
    updates = partial(inline)
    updates['properties']['decision_basis']['properties']['experiment_change'] = deepcopy(inline['properties']['decision_basis']['properties']['experiment_change'])
    updates['properties'].pop('supersedes')
    result = {'anyOf': [inline, {'type': 'object', 'properties': {'decision_ref': text}, 'required': ['decision_ref'], 'additionalProperties': False}, {'type': 'object', 'properties': {'decision_ref': text, 'updates': updates}, 'required': ['decision_ref', 'updates'], 'additionalProperties': False, 'description': 'Atomically revise only authored fields of the current decision. Objects merge; arrays replace. experiment_change is a complete fresh object; omitted revision evidence is not inherited. No scientific inference or execution.'}]}
    if not include_updates:
        result['anyOf'].pop()
    result['anyOf'].append(achieved_summary)
    if compact_basis:
        inline['properties']['decision_basis'] = {'type': 'object', 'properties': {}, 'description': 'See record_plan decision_basis for the complete fields. Identical server validation applies; references reuse the exact recorded decision.'}
    return result

def decision_update_schema():
    """Expose a patch without duplicating the full canonical basis schema on the wire."""
    result = decision_schema(include_updates=True)['anyOf'][2]
    result['properties']['updates']['properties']['decision_basis'] = {'type': 'object', 'minProperties': 1, 'properties': {'experiment_change': {'type': 'object', 'required': experiment_properties()['experiment_change']['required']}}, 'description': 'record_plan basis: acquired measurement_id only. Objects merge; arrays replace; experiment_change fresh/complete.'}
    result['description'] = 'Atomic patch; no execution.'
    return result

def calculations_after(reference, events):
    after = False
    for event in events:
        if event.event_id == reference:
            after = True
        elif after and getattr(event, 'tool_name', '').startswith('analyze_') and getattr(event, 'result', {}).get('calculation_id'):
            return True
    return False

def report_review_target(report, report_id):
    """Identify the final-review question and its public basis, without a verdict."""
    return {'scope': 'original_task_disposition', 'objective_ref': '/requirement_scope/original_objective', 'report_id': report_id, 'decision_subject_id': report.get('decision_ref') or report_id}

def design_review_target(decision_subject_id):
    """Name the prospective adoption question without supplying a scientific answer."""
    return {'scope': 'prospective_design_adoption', 'objective_ref': '/requirement_scope/original_objective', 'decision_subject_id': decision_subject_id, 'design_ref': '/proposed_decision', 'plan_ref': '/working_plan'}

def assessment_schema(*, proposed_report=None, proposed_decision=None):
    scope = {k: {'type': 'string', 'minLength': 1, 'description': v} for k, v in SCOPE_FIELDS.items()}
    design_review = proposed_report is None and isinstance(proposed_decision, Mapping)
    if design_review:
        scope.update({k: {'type': 'string', 'minLength': 1, 'description': v} for k, v in {'claim': 'Compare the original public objective and constraints with the complete recorded design, its prospective purpose and limited claim. An unresolved status does not establish design validity.', 'inference': SCOPE_FIELDS['inference'] + ' Assess the predicted endpoint of the whole design, not just an intermediate.', 'applicability': "Assess the relation's public premises, domain and contrary evidence. Uncertain applicability or no useful model may justify an empirical test; identify the specific uncertainty it would resolve. Missing endpoint acquisition alone is not evidence against a model consequence.", 'decision_relevance': 'Does this whole design have a supported path toward the original goal, or an informative diagnostic with decision value? Which plausible outcomes change the next decision and why is acquisition useful beyond current evidence? An unmeasured endpoint or safe first step alone is not that rationale. Do not require a guarantee of success, exhaustive proof or unnecessary work.'}.items()})
    if unresolved_report(proposed_report):
        scope['decision_relevance'] = {'type': 'object', 'description': SCOPE_FIELDS['decision_relevance'], 'properties': {k: {'type': 'string', 'minLength': 1, 'description': v} for k, v in STOPPING_FIELDS.items()}, 'required': list(STOPPING_FIELDS), 'additionalProperties': False}
        scope['decision_relevance']['properties']['constraints'] = constraint_schema()
    return {'type': 'object', 'properties': {'subject_id': {'type': 'string'}, 'verdict': {'type': 'string', 'enum': ['supported', 'concern', 'uncertain']}, 'rationale': {'type': 'string'}, 'evidence_ids': {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True}, 'scope_analysis': {'type': 'object', 'properties': scope, 'required': list(SCOPE_FIELDS), 'additionalProperties': False}}, 'required': ['subject_id', 'verdict', 'rationale', 'evidence_ids', 'scope_analysis'], 'additionalProperties': False, 'description': 'Assess review_target: whether ending the original public task now, as proposed_report states, is justified. Use requirement_scope.original_objective, acquired evidence and applicable constraints. The separate top-level verdict assesses report accuracy; an accurate report or completed authored method does not itself justify ending the task. subject_id binds the decision basis, or the report when no decision exists. Advice is not a grade or execution authority.' if proposed_report is not None else 'Assess review_target: whether adopting the whole recorded design before liquid execution is scientifically justified using currently available public information. Review proposed_decision together with working_plan against the original objective; do not assess only the first operation or whether a product has already been acquired. An accurate unresolved status is not design support. Bind to decision_subject_id. Advice is not a grade or execution authority.' if design_review else 'Assess goal completion or stopping separately from factual accuracy. Bind to decision_subject_id, the canonical decision ID or otherwise proposed report ID. Advice is not a grade or execution authority.'}

def current_decision(events):
    for event in reversed(events):
        if getattr(event, 'source_agent', None) in ('reasoner', 'predictor', 'actor') and getattr(event, 'observation_type', None) == 'scientific_decision':
            prior = previous_experiment(event.payload, events)
            return {'event_id': event.event_id, 'decision': deepcopy(event.payload), 'experiment_state': {'current_declared': event.payload.get('decision_basis', {}).get('experiment') is not None, 'previous_scope': 'superseded' if prior else 'absent'}, **({'previous_experiment': prior} if prior else {})}
    return None

def _ids(value, evidence):
    if not isinstance(value, list) or any((not isinstance(i, str) or i not in evidence for i in value)) or len(set(value)) != len(value):
        raise ValueError('Decision requires distinct acquired evidence IDs')

def field_placement_hints(value):
    """Identify unique schema locations without selecting meaning or changing values."""
    if not isinstance(value, dict):
        return []
    branches = decision_schema(include_updates=True)['anyOf']
    if 'decision_ref' in value or 'updates' in value:
        if set(value) != {'decision_ref', 'updates'} or not isinstance(value['updates'], dict):
            return []
        node, specification, prefix = (value['updates'], branches[2]['properties']['updates'], ['updates'])
    else:
        node, specification, prefix = (value, branches[0], [])
    hints = []

    def visit(submission, schema, path):
        properties = schema.get('properties', {})
        for key in sorted((k for k in submission if isinstance(k, str) and k not in properties)):
            candidates = [name for name, child in properties.items() if child.get('type') == 'object' and key in child.get('properties', {})]
            if len(candidates) != 1:
                continue
            parent = candidates[0]
            if parent in submission and (not isinstance(submission[parent], dict)):
                continue
            target = submission.get(parent, {})
            hints.append({'from': path + [key], 'to': path + [parent, key], 'status': 'collision' if key in target else 'misplaced'})
            if len(hints) == 16:
                return
        for key, child in properties.items():
            if len(hints) == 16:
                return
            if child.get('type') == 'object' and isinstance(submission.get(key), dict):
                visit(submission[key], child, path + [key])
    visit(node, specification, prefix)
    return hints

def prepare_decision(value, events, evidence, *, final=False):
    """Validate without publishing; callers commit only after other validation passes."""
    try:
        prepared = _prepare_decision(value, events, evidence)
        if final and prepared[1] is None and prepared[2] and calculations_after(prepared[2], events):
            raise ValueError('New calculation since this decision: refresh basis and next_step before final reference reuse; use decision_ref with updates')
        return prepared
    except ValueError as exc:
        current = current_decision(events)
        from pearl.runtime.rejected_decision import rejection_snapshot
        repair = {'rejected_submission': rejection_snapshot(value, current), 'schema': decision_schema(), 'current_decision_ref': current['event_id'] if current else None, 'current_status': current['decision']['status'] if current else None, 'active_experiment': deepcopy(current['decision'].get('decision_basis', {}).get('experiment')) if current else None, 'experiment_state': deepcopy(current['experiment_state']) if current else {'current_declared': False, 'previous_scope': 'absent'}, 'reference_policy': 'decision_ref reuses the entire unchanged decision, including its status. It does not declare completion.', 'revision_policy': 'Use decision_ref with updates containing only changed fields, or write a full revision with supersedes. record_decision updates only the decision without replacing plan/timing/cohorts. Experiment changes still require experiment_change. No evidence or decision is inferred by this feedback.', 'field_placement_hints': field_placement_hints(value), 'placement_policy': 'Paths are relative to the submitted decision argument. Correct a misplaced field explicitly only if its declared schema location is intended; preserve its authored value. A collision requires an explicit author choice. No field is moved, overwritten or applied by this feedback.'}
        raise DecisionValidationError(str(exc), repair) from exc

def _prepare_decision(value, events, evidence):
    current = current_decision(events)
    if isinstance(value, dict):
        if 'decision_ref' in value or 'updates' in value:
            allowed = {'decision_ref', 'updates'}
        else:
            allowed = {'status', 'basis', 'next_step', 'decision_basis', 'supersedes'}
        unexpected = set(value) - allowed
        if unexpected:
            names = ', '.join(sorted((str(key)[:80] for key in unexpected))[:10])
            raise ValueError('Invalid scientific decision fields: unexpected ' + names + '. Correct the submitted envelope explicitly; no fields were moved or applied.')
    if isinstance(value, dict) and set(value) == {'decision_ref', 'updates'}:
        if not current or value['decision_ref'] != current['event_id']:
            raise ValueError('Decision revision must name the current canonical decision')
        from jsonschema import validate, ValidationError
        try:
            validate(value, decision_schema(include_updates=True)['anyOf'][2])
        except ValidationError as exc:
            raise ValueError('Invalid decision updates: ' + exc.message) from exc
        if calculations_after(current['event_id'], events) and (not {'basis', 'next_step'} <= set(value['updates'])):
            raise ValueError('New calculation requires explicit basis and next_step refresh, even if reaffirmed unchanged')
        change = value['updates'].get('decision_basis', {})
        if 'experiment' in change and 'retain_experiment_from' in change:
            raise ValueError('retain_experiment_from cannot accompany experiment edits')

        def merge(old, changes):
            result = deepcopy(old)
            for key, item in changes.items():
                result[key] = merge(result.get(key, {}), item) if isinstance(item, dict) else deepcopy(item)
            return result
        prior = deepcopy(current['decision'])
        prior['decision_basis'].pop('retain_experiment_from', None)
        prior['decision_basis'].pop('experiment_change', None)
        value = merge(prior, value['updates'])
        value['supersedes'] = current['event_id']
        if 'retain_experiment_from' in value['decision_basis']:
            value['decision_basis'].pop('experiment', None)
    if isinstance(value, dict) and set(value) == {'decision_ref'}:
        if not current or value['decision_ref'] != current['event_id']:
            raise ValueError('Decision reference must name the current canonical decision')
        record = current['decision']
        return ({k: record[k] for k in ('status', 'basis', 'next_step')}, None, current['event_id'])
    active_experiment = current and current['decision'].get('decision_basis', {}).get('experiment')
    if active_experiment and (value is None or (isinstance(value, dict) and value.get('decision_basis') is None)):
        raise ValueError('An active experiment requires decision_basis or its current decision_ref')
    if value is None:
        return (read_resolution({}), None, None)
    if not isinstance(value, dict) or set(value) - {'status', 'basis', 'next_step', 'decision_basis', 'supersedes'}:
        raise ValueError('Invalid scientific decision fields')
    summary = read_resolution({'task_resolution': {k: v for k, v in value.items() if k in ('status', 'basis', 'next_step')}})
    basis = value.get('decision_basis')
    if basis is None:
        if summary['status'] != 'achieved':
            raise ValueError('An unresolved/conflict conclusion requires decision_basis or a current decision_ref')
        if 'supersedes' in value:
            raise ValueError('Decision revision requires decision_basis')
        return (summary, None, None)
    candidate = {**summary, 'decision_basis': deepcopy(basis), 'supersedes': value.get('supersedes')}
    if current:
        canonical = deepcopy(current['decision'])
        if isinstance(basis, dict) and 'retain_experiment_from' in basis and ('experiment' not in basis):
            canonical.get('decision_basis', {}).pop('experiment', None)
        if candidate == canonical:
            return (summary, None, current['event_id'])
    model = basis.get('working_model') if isinstance(basis, dict) else None
    model_fields = {'assumptions', 'applicability', 'implication'}
    if not isinstance(model, dict) or set(model) != model_fields or any((not isinstance(model[k], str) or not model[k].strip() for k in model_fields)):
        raise ValueError('Decision working_model requires assumptions, applicability and implication')
    fields = {'premise', 'alternative', 'expected_information', 'constraints', 'evidence_ids', 'working_model'}
    if not isinstance(basis, dict) or not fields <= set(basis) or set(basis) - fields - {'experiment', 'experiment_change', 'retain_experiment_from', 'evidence_use'} or any((not isinstance(basis[k], str) or not basis[k].strip() for k in fields - {'evidence_ids', 'working_model'})):
        raise ValueError('Decision basis requires a premise, alternative, expected information, constraints and evidence IDs')
    _ids(basis['evidence_ids'], evidence)
    basis = deepcopy(basis)
    if 'retain_experiment_from' in basis:
        if not current or basis['retain_experiment_from'] != current['event_id'] or (not active_experiment) or ('experiment' in basis):
            raise ValueError('retain_experiment_from requires the current declared experiment and cannot accompany experiment')
        basis['experiment'] = deepcopy(active_experiment)
    record = {**summary, 'decision_basis': deepcopy(basis), 'supersedes': value.get('supersedes')}
    if current and record == current['decision']:
        return (summary, None, current['event_id'])
    validate_experiment(basis, current, evidence)
    if 'evidence_use' in basis:
        validate_evidence_use(basis['evidence_use'], evidence)
    if record['supersedes'] != (current['event_id'] if current else None):
        raise ValueError('Decision revision must explicitly supersede the current event ID')
    return (summary, record, None)

def publish_decision(board, record, reference, *, source_agent='reasoner'):
    if source_agent != getattr(board, 'planning_role', 'reasoner'):
        raise ValueError('Only the planning agent can publish a scientific decision')
    if record is None:
        return reference
    event = ObservationEvent(source_agent=source_agent, observation_type='scientific_decision', payload=deepcopy(record))
    board.publish(event)
    return event.event_id

def _review_fields(value, fields, path, text_fields):

    def pointer(key):
        return path + '/' + str(key).replace('~', '~0').replace('/', '~1')
    expected = ', '.join((pointer(key) for key in fields))
    issues = []
    if not isinstance(value, dict):
        issues.append('expected object')
    else:
        missing = [pointer(key) for key in fields if key not in value]
        unexpected = sorted((pointer(key) for key in value if key not in fields))
        invalid = [pointer(key) for key in fields if key in text_fields and key in value and (not isinstance(value[key], str) or not value[key].strip())]
        if missing:
            issues.append('missing: ' + ', '.join(missing))
        if unexpected:
            issues.append('unexpected: ' + ', '.join(unexpected))
        if invalid:
            issues.append('expected nonblank string: ' + ', '.join(invalid))
    if issues:
        raise ValueError('Decision review structure at ' + path + ': ' + '; '.join(issues) + '. Required fields: ' + expected + '. No fields were changed.')

def validate_assessment(value, subject_id, evidence, *, proposed_report=None, public_setup=None):
    if not isinstance(value, dict) or set(value) != {'subject_id', 'verdict', 'rationale', 'evidence_ids', 'scope_analysis'} or value['subject_id'] != subject_id or (value['verdict'] not in ('supported', 'concern', 'uncertain')) or (not isinstance(value['rationale'], str)) or (not value['rationale'].strip()):
        raise ValueError('Decision assessment requires the exact report subject, verdict and rationale')
    _ids(value['evidence_ids'], evidence)
    scope = value['scope_analysis']
    structured = unresolved_report(proposed_report)
    text_fields = set(SCOPE_FIELDS) - ({'decision_relevance'} if structured else set())
    scope_path = '/decision_assessment/scope_analysis'
    _review_fields(scope, SCOPE_FIELDS, scope_path, text_fields)
    if structured:
        stopping = scope['decision_relevance']
        stopping_path = scope_path + '/decision_relevance'
        _review_fields(stopping, STOPPING_FIELDS, stopping_path, set(STOPPING_FIELDS) - {'constraints'})
        try:
            constraints = validate_constraints(stopping['constraints'], public_setup)
        except ValueError as exc:
            raise ValueError('Decision review provenance at ' + stopping_path + '/constraints: ' + str(exc)) from exc
        result = deepcopy(value)
        result['scope_analysis']['decision_relevance']['constraints'] = constraints
        return result
    return deepcopy(value)

def aggregate_advice(factual, decision, disagreement=False):
    if disagreement or 'concern' in (factual, decision):
        return 'concern'
    return 'uncertain' if 'uncertain' in (factual, decision) else 'supported'
