"""Durable dispositions of public scientific reviews, separate from action admission."""
from copy import deepcopy
from pearl.state.events import AnomalyMatchEvent, ObservationEvent, PeerReviewDispositionEvent
RESOLUTION = 'scientific_review_resolution'

class ReviewConcernSelectionError(ValueError):
    """Return active public selectors without resolving or authorizing anything."""

    def __init__(self, message, active_concerns):
        super().__init__(message)
        self.feedback = {'response_tool': 'resolve_review_concern', 'active_concerns': [{'review_id': row['review_id'], 'source_agent': row['source_agent']} for row in active_concerns]}

def report_decision_subject(review, events):
    """Resolve an exact historical decision from a validated scientific or report review."""
    assessment = review.get('decision_assessment') or {}
    reference = review.get('decision_ref')
    if review.get('validation_status') == 'invalid' or not (review.get('report_id') or review.get('review_scope') == 'decision') or (not reference) or (assessment.get('subject_id') != reference):
        return None
    for event in events:
        if event.event_id == reference and event.source_agent in ('reasoner', 'predictor', 'actor') and (getattr(event, 'observation_type', None) == 'scientific_decision'):
            return {'event_id': reference, 'decision': deepcopy(event.payload)}
    if review.get('initial_proposal_ref') == reference:
        from pearl.runtime.initial_plan import adopted_review_subject
        return adopted_review_subject(review, events)
    return None

def review_memory(events):
    reviews, dispositions, resolutions = ({}, [], [])
    for event in events:
        if getattr(event, 'observation_type', None) == 'scientific_review':
            review = event.payload
            if review.get('match_status') not in ('concern', 'uncertain'):
                continue
            reviews[review['event_id']] = {'review_id': review['event_id'], 'source_agent': event.source_agent, 'plan_id': review.get('plan_id', ''), 'rationale': review['rationale'], **{k: deepcopy(review[k]) for k in ('decision_assessment', 'decision_ref', 'initial_proposal_ref', 'review_scope', 'review_target', 'report_id', 'report_support', 'task_resolution', 'task_status_disagreement') if k in review}, **({'decision_subject': report_decision_subject(review, events)} if report_decision_subject(review, events) else {}), 'measurement_ids': list(dict.fromkeys((mid for row in review.get('observation_references', []) for mid in row['measurement_ids'])))}
        elif isinstance(event, AnomalyMatchEvent) and event.source_agent == 'watchdog':
            reviews[event.event_id] = {'review_id': event.event_id, 'source_agent': 'watchdog', 'plan_id': event.evidence.get('plan_id', ''), 'rationale': event.anomaly_id, 'evidence': deepcopy(event.evidence), 'measurement_ids': list(event.evidence.get('measurement_ids', []))}
        elif isinstance(event, PeerReviewDispositionEvent) and event.source_agent in ('reasoner', 'predictor', 'actor'):
            dispositions.append({'review_id': event.review_event_id, 'decision': event.decision, 'rationale': event.rationale, 'evidence_ids': list(event.evidence_ids)})
        elif getattr(event, 'observation_type', None) == RESOLUTION and event.source_agent in ('reasoner', 'predictor', 'actor'):
            resolutions.append(deepcopy(event.payload))
    latest = {row['review_id']: row for row in dispositions}
    resolved = {row['review_id'] for row in resolutions}
    active = [{**deepcopy(review), 'accepted_disposition': deepcopy(latest[rid])} for rid, review in reviews.items() if rid in latest and latest[rid]['decision'] in ('accept', 'revise', 'proceed', 'acknowledge') and (rid not in resolved)]
    return {'active_concerns': active, 'dispositions': deepcopy(dispositions), 'resolutions': resolutions, 'scope': 'Accepted, revised or acknowledged scientific concerns remain advisory until explicitly resolved or rejected with grounds. Canonical report claims may be corrected logically without inventing measurement citations. Proceed authorizes the proposed action, not the underlying scientific claim. New notes, local action support and elapsed time do not resolve them. No automatic evidence exclusion or action authorization.'}

def resolve_concern(board, role, args, evidence):
    if role != getattr(board, 'planning_role', 'reasoner'):
        raise ValueError('Only the planning agent can resolve an accepted scientific concern')
    if not isinstance(args, dict) or set(args) != {'review_id', 'decision', 'rationale', 'evidence_ids'}:
        raise ValueError('Provide review ID, resolution, scientific rationale and evidence IDs')
    if not isinstance(args['review_id'], str):
        raise ValueError('Provide an exact review ID string')
    if args['decision'] not in ('resolved', 'reject') or not isinstance(args['rationale'], str) or (not args['rationale'].strip()):
        raise ValueError('Resolve or reject with a scientific rationale')
    from pearl.runtime.analysis_memory import _ids
    if args['evidence_ids'] != []:
        _ids(args['evidence_ids'], evidence)
    active = {row['review_id']: row for row in review_memory(board.event_log)['active_concerns']}
    if args['review_id'] not in active:
        raise ReviewConcernSelectionError('Choose an active accepted review concern', active.values())
    if args['evidence_ids'] == [] and (not active[args['review_id']].get('decision_subject')):
        _ids(args['evidence_ids'], evidence)
    result = deepcopy(args)
    board.publish(ObservationEvent(source_agent=role, observation_type=RESOLUTION, payload=deepcopy(result)))
    return {**result, 'executed': False, 'effect': 'scientific_memory_only'}
