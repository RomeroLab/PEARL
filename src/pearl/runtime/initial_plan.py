"""Immutable initial proposals, peer review and explicit author adoption."""
from copy import deepcopy
import hashlib
import json
from pearl.runtime.contracts import ActionSpec
from pearl.runtime.decision_record import current_decision
from pearl.state.events import ObservationEvent, PeerReviewDispositionEvent
PROPOSAL = 'initial_design_proposal'
ADOPTION = 'initial_design_adopted'

def enabled(runtime):
    return runtime.require_prospective_design and runtime.independent_prediction

def digest(arguments):
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()

def latest_proposal(runtime):
    return next((e for e in reversed(runtime.board.event_log) if getattr(e, 'observation_type', None) == PROPOSAL and e.source_agent == runtime.planning_role), None)

def proposal_review(runtime, proposal_id):
    return next((e for e in reversed(runtime.board.event_log) if getattr(e, 'observation_type', None) == 'scientific_review' and e.source_agent == 'predictor' and (e.payload.get('initial_proposal_ref') == proposal_id)), None)

def review_subject(runtime, action):
    """Resolve an actual immutable proposal; never publish a temporary decision."""
    reference = action.params.get('proposal_ref')
    if reference is None:
        return current_decision(runtime.board.event_log)
    event = latest_proposal(runtime)
    if not enabled(runtime) or event is None or event.event_id != reference or (action.params.get('decision_ref') != reference) or adopted_design_exists(runtime):
        raise ValueError('Review the exact current unadopted initial proposal')
    return {'event_id': event.event_id, 'decision': deepcopy(event.payload['decision']), 'initial_proposal_ref': event.event_id, 'proposed_plan': deepcopy(event.payload['arguments']), 'adoption_status': 'not_adopted'}

def stage(runtime, arguments, record):
    if record is None and 'decision' not in arguments:
        runtime.board.publish(ObservationEvent(source_agent=runtime.planning_role, observation_type='unadopted_planning_note', payload={'arguments': deepcopy(arguments), 'meaning': 'Author notes only; no active design, timing, acquisition or cohort commitment.'}))
        runtime.last_result = {'status': 'notes_recorded_not_adopted', 'executed': False, 'meaning': 'Notes remain public but have not activated a design. A prospective decision with record_plan proposes the initial design for review.'}
        return
    if not isinstance(record, dict) or not record.get('decision_basis'):
        raise ValueError('Initial design proposal requires an explicit prospective scientific decision; observations and calculations remain available')
    event = ObservationEvent(source_agent=runtime.planning_role, observation_type=PROPOSAL, payload={'arguments': deepcopy(arguments), 'decision': deepcopy(record), 'whole_plan_sha256': digest(arguments), 'adoption_status': 'not_adopted'})
    runtime.board.publish(event)
    reviewed = runtime._review(ActionSpec(action_type='decision', params={'decision_ref': event.event_id, 'proposal_ref': event.event_id}), event.event_id)
    runtime.last_result = {'status': 'initial_design_reviewed_not_adopted', 'proposal_ref': event.event_id, 'review': deepcopy(reviewed), 'executed': False, 'meaning': 'The proposal has not changed the active decision, plan, cohorts or acquisition scope. Revise with record_plan, obtain information, stop with grounds, or explicitly adopt the exact proposal using adopt_reviewed_plan. Peer support is advice, not scientific truth or execution permission.'}

def context(runtime):
    event = latest_proposal(runtime)
    if event is None or adopted_design_exists(runtime):
        return None
    review = proposal_review(runtime, event.event_id)
    return {'proposal_ref': event.event_id, **deepcopy(event.payload), 'review': deepcopy(review.payload) if review else None, 'adoption_tool': 'adopt_reviewed_plan', 'meaning': 'Unadopted authored proposal; all earlier proposals and assessments remain public. Review does not require agreement or grant action permission.'}

def adoption_tool():
    return {'type': 'function', 'function': {'name': 'adopt_reviewed_plan', 'description': 'Explicitly adopt the exact reviewed initial proposal with your scientific rationale and actual acquired supporting IDs (or [] for a public-premise argument). Address material peer concerns; agreement is not required. Revise with record_plan instead when content changes. This does not authorize execution.', 'parameters': {'type': 'object', 'properties': {'proposal_ref': {'type': 'string', 'minLength': 1}, 'review_id': {'type': 'string', 'minLength': 1}, 'review_disposition': {'type': 'string', 'enum': ['accept', 'reject', 'acknowledge']}, 'rationale': {'type': 'string', 'minLength': 1}, 'evidence_ids': {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True}}, 'required': ['proposal_ref', 'review_id', 'review_disposition', 'rationale', 'evidence_ids'], 'additionalProperties': False}}}

def prepare_adoption(runtime, arguments):
    event = latest_proposal(runtime)
    if not enabled(runtime) or adopted_design_exists(runtime) or event is None or (arguments.get('proposal_ref') != event.event_id):
        raise ValueError('Adopt only the exact latest unadopted initial proposal')
    review = proposal_review(runtime, event.event_id)
    if review is None or arguments.get('review_id') != review.payload['event_id']:
        raise ValueError('An actual validated assessment of this entire proposal is required')
    if set(arguments) != {'proposal_ref', 'review_id', 'review_disposition', 'rationale', 'evidence_ids'} or arguments.get('review_disposition') not in ('accept', 'reject', 'acknowledge') or (not isinstance(arguments.get('rationale'), str)) or (not arguments['rationale'].strip()):
        raise ValueError('Explain your scientific adoption and response to material peer concerns')
    ids = arguments.get('evidence_ids')
    evidence = runtime._delivered_evidence(runtime.planning_role)
    if not isinstance(ids, list) or any((not isinstance(i, str) or i not in evidence for i in ids)) or len(set(ids)) != len(ids):
        raise ValueError('Adoption evidence must be distinct acquired IDs actually delivered to the planner')
    original = event.payload['arguments']
    if digest(original) != event.payload['whole_plan_sha256']:
        raise ValueError('The reviewed proposal content changed')
    return (deepcopy(original), deepcopy(arguments))

def publish_adoption(runtime, arguments, decision_ref):
    event = latest_proposal(runtime)
    runtime.board.publish(ObservationEvent(source_agent=runtime.planning_role, observation_type=ADOPTION, payload={**deepcopy(arguments), 'decision_ref': decision_ref, 'whole_plan_sha256': event.payload['whole_plan_sha256'], 'execution_authorized': False}))
    runtime.board.publish(PeerReviewDispositionEvent(source_agent=runtime.planning_role, plan_id=event.event_id, review_event_id=arguments['review_id'], proposal_digest=event.payload['whole_plan_sha256'], decision=arguments['review_disposition'], rationale=arguments['rationale'], evidence_ids=deepcopy(arguments['evidence_ids'])))

def _bound_adoption(runtime, event):
    payload = event.payload
    proposal = next((p for p in runtime.board.event_log if p.event_id == payload.get('proposal_ref') and getattr(p, 'observation_type', None) == PROPOSAL and (p.source_agent == runtime.planning_role)), None)
    review = proposal_review(runtime, payload.get('proposal_ref'))
    decision = next((p for p in runtime.board.event_log if p.event_id == payload.get('decision_ref') and getattr(p, 'observation_type', None) == 'scientific_decision' and (p.source_agent == runtime.planning_role)), None)
    return proposal is not None and review is not None and (decision is not None) and (decision.payload == proposal.payload['decision']) and (review.payload['event_id'] == payload.get('review_id')) and (payload.get('whole_plan_sha256') == digest(proposal.payload['arguments'])) and (proposal.trace_sequence < review.trace_sequence < decision.trace_sequence < event.trace_sequence)

def adopted_design_exists(runtime):
    return any((getattr(e, 'observation_type', None) == ADOPTION and e.source_agent == runtime.planning_role and _bound_adoption(runtime, e) for e in runtime.board.event_log))

def reviewed_canonical(runtime, subject):
    """Reuse only the exact proposal assessment after explicit author adoption."""
    for event in reversed(runtime.board.event_log):
        if getattr(event, 'observation_type', None) != ADOPTION or event.source_agent != runtime.planning_role or event.payload.get('decision_ref') != subject:
            continue
        return _bound_adoption(runtime, event)
    return False

def adopted_review_subject(review, events):
    """Resolve the exact adopted identity for durable advice, without a grade."""
    from types import SimpleNamespace
    for event in events:
        if getattr(event, 'observation_type', None) != ADOPTION or event.payload.get('proposal_ref') != review.get('initial_proposal_ref') or event.payload.get('review_id') != review.get('event_id') or (event.source_agent not in ('reasoner', 'predictor', 'actor')):
            continue
        owner = SimpleNamespace(board=SimpleNamespace(event_log=events), planning_role=event.source_agent)
        if _bound_adoption(owner, event):
            decision = next((e for e in events if e.event_id == event.payload['decision_ref']))
            return {'event_id': decision.event_id, 'decision': deepcopy(decision.payload)}
    return None
