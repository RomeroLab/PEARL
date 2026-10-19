"""Independent, public-evidence LLM Knowledge and scientific Watchdog peers."""
from copy import deepcopy
import hashlib
import json
from pearl.knowledge.agent import retrieval_audit_to_mapping
from pearl.runtime.knowledge import ROWS
from pearl.runtime.requirement_provenance import OPERATIONAL_ASSUMPTIONS
from pearl.runtime.scientific_retrieval import ScientificKnowledgeProvider
from pearl.state.events import KnowledgeRequestEvent, KnowledgeResponseEvent, ObservationEvent, AnomalyMatchEvent

class ScientificPeerError(RuntimeError):
    """A failed bounded consultation; the main planning loop must not retry it."""
_KNOWLEDGE = 'You are the independent Knowledge agent. Answer the public scientific question\nusing retrieved sources and shared camera evidence. Retrieval is source access, not a verdict.\nQuestion premises are hypotheses, not acquired facts. Check their public grounds and contrary observations before accepting the framing.\nDo not turn a chosen verification method into a requirement of the original claim.\nAssess relevance, applicability, limitations, contrary evidence and uncertainty. You may search\nagain or inspect/read public observations. Cite only delivered source IDs and acquired measurement\nIDs. Priors are not observations; a command does not verify composition or chemical identity.\nDo not invent sources, causes, applicability, recipes or success. Insufficient information is a\nvalid answer. Publish your own assessment; {planning_owner} decides whether to use it. You cannot approve\nliquid actions, change the plan, select/exclude evidence or override physical limits. ' + OPERATIONAL_ASSUMPTIONS
_WATCHDOG = 'You are the independent scientific Watchdog agent. Compare public plans,\npredictions, acknowledged actions and camera observations. Focus on unexpected behavior and\nwhether the experiment remains interpretable and suitable for its stated question. Distinguish\nan observation, an explanation and a decision. Describe uncertainties and alternative explanations;\ndo not assert a cause from a label or command. Read public evidence or consult Knowledge when\nuseful. Raise decision-relevant concerns with exact public references. Reuse an incident_key for\nan existing concern; do not repeat an active concern without new material grounds.\ncontinue_watchdog_review maintains existing concerns by their exact review IDs without raising\nnew findings or resolving them. Persistence or a response alone is not new material grounds.\nCompare acquired times with acknowledged completed_at_s, not wall-clock log timestamps.\nScope measurement fitness to its intended use and preparation state; an uninformative state\nalone does not establish that all feasible changed states would be uninformative. Clear or\nuncertain assessments are valid and are not task grades. Monitoring findings are advisory: {planning_owner}\nmust respond but may disagree with scientific grounds. Separately requested execution authorization\nis final for that exact request: approve permits it, hold/reject blocks it. A response to monitoring\nadvice cannot override denied execution permission. You cannot execute, prescribe a mandatory\nremedy, exclude observations, adopt a result or override independent physical limits. ' + OPERATIONAL_ASSUMPTIONS

def scientific_peer_prompt(role, planning_role='reasoner'):
    if planning_role not in ('reasoner', 'predictor', 'actor'):
        raise ValueError('Unknown scientific planning owner')
    template = {'knowledge': _KNOWLEDGE, 'watchdog': _WATCHDOG}[role]
    return template.format(planning_owner=planning_role.capitalize())
KNOWLEDGE = scientific_peer_prompt('knowledge')
WATCHDOG = scientific_peer_prompt('watchdog')
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 2048}
IDS = {'type': 'array', 'items': {'type': 'string', 'minLength': 1}, 'uniqueItems': True, 'maxItems': 256}
KNOWLEDGE_FIELDS = {k: TEXT for k in ('answer', 'applicability', 'limitations')}
KNOWLEDGE_FIELDS.update(status={'type': 'string', 'enum': ['supported', 'limited', 'insufficient']}, citations=IDS, measurement_ids=IDS)
FINDING_FIELDS = {k: TEXT for k in ('incident_key', 'claim', 'rationale')}
FINDING_FIELDS.update(measurement_ids=IDS, event_ids=IDS, hypothesis={'type': ['string', 'null'], 'maxLength': 2048})

def obj(fields):
    return {'type': 'object', 'properties': deepcopy(fields), 'required': list(fields), 'additionalProperties': False}

def peer_tools(role, domain):
    from pearl.runtime.runtime import role_tools, schema
    allowed = {'read_shared_events', 'read_measurements', 'read_action_history', 'read_operation_observations', 'read_camera_window', 'read_retrieval_receipt', 'read_context_details'}
    tools = [deepcopy(t) for t in role_tools('predictor', domain) if t['function']['name'] in allowed]
    tools.append(schema('inspect', 'Acquire public camera observations; no liquid action.', {'locations': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'uniqueItems': True}}))
    if role == 'knowledge':
        tools.append(schema('search_knowledge', 'Retrieve general scientific sources for your query.', {'question': TEXT}))
        tools.append(schema('submit_knowledge_response', 'Publish your sourced scientific assessment.', KNOWLEDGE_FIELDS))
    elif role == 'watchdog':
        tools.append(schema('consult_knowledge', 'Ask the independent Knowledge peer a scientific question.', {'question': TEXT}))
        tools.append(schema('continue_watchdog_review', 'Maintain existing pending or accepted unresolved Watchdog concerns without raising another finding. Select exact active review IDs. This does not resolve, reject or authorize anything; use submit_watchdog_review for new material grounds.', {'assessment': TEXT, 'review_ids': {**IDS, 'minItems': 1}}))
        tools.append(schema('submit_watchdog_review', 'Publish a scoped scientific monitoring assessment. Each finding raises an unresolved advisory. clear requires an empty findings list; concern requires at least one grounded unresolved finding. Put informational, positive or resolved observations in assessment. uncertain is a valid verdict; include findings only for unresolved concerns supported by public references.', {'verdict': {'type': 'string', 'enum': ['clear', 'concern', 'uncertain']}, 'assessment': TEXT, 'findings': {'type': 'array', 'maxItems': 12, 'items': obj(FINDING_FIELDS)}}))
    else:
        raise ValueError('Unknown scientific peer')
    return tools

def acquired_references(ids, frontier):
    if any((mid not in frontier for mid in ids)):
        raise ValueError('Use acquired measurement IDs available in the delivered peer snapshot')

class LlmKnowledgePeer:

    def __init__(self, run, board):
        self.run = run
        self.board = board
        self.provider = ScientificKnowledgeProvider(ROWS)
        board.subscribe(KnowledgeRequestEvent, self._on_request)

    def camera_observations(self):
        return self.board.camera_for('knowledge')

    def _on_request(self, event):
        documents = {}
        audits = []

        def search(question):
            try:
                rows = self.provider.retrieve(question, event.observation)
                audit = retrieval_audit_to_mapping(self.provider.retrieval_audit())
            except Exception as exc:
                raise ScientificPeerError(f'Knowledge source access failed: {exc}') from exc
            audits.append(deepcopy(audit))
            for row in rows:
                documents[row['knowledge_id']] = deepcopy(row)
            from pearl.state.events import ToolCallEvent
            self.board.publish(ToolCallEvent(source_agent='knowledge', tool_name='search_knowledge', params={'question': question}, result={'rows': deepcopy(rows), 'audit': audit}, executed=False))
            return {'rows': deepcopy(rows), 'audit': audit}
        try:
            search(event.goal)

            def context():
                return {'knowledge_request': event.to_dict(), 'retrieved_knowledge': list(deepcopy(documents).values())}

            def check(answer, frontier, event_ids):
                acquired_references(answer['measurement_ids'], frontier)
                if not set(answer['citations']) <= documents.keys():
                    raise ValueError('Citations must identify sources actually delivered to Knowledge')
            answer = self.run._consult_peer('knowledge', context, check, search=search)
            assessment = ObservationEvent(source_agent='knowledge', observation_type='knowledge_assessment', payload={'request_id': event.request_id, **deepcopy(answer)})
            self.board.publish(assessment)
            audit = {**audits[-1], 'source_queries': audits, 'llm_assessment': deepcopy(answer), 'assessment_event_id': assessment.event_id}
            rows = list(documents.values())
        except Exception as exc:
            self.board.publish(KnowledgeResponseEvent(source_agent='knowledge', request_id=event.request_id, rows=[], audit={'error': f'{type(exc).__name__}: {exc}'}))
            if isinstance(exc, RuntimeError):
                raise
            raise ScientificPeerError(f'Knowledge consultation failed: {exc}') from exc
        self.board.publish(KnowledgeResponseEvent(source_agent='knowledge', request_id=event.request_id, rows=deepcopy(rows), audit=deepcopy(audit)))

class LlmWatchdogPeer:

    def __init__(self, run, board):
        self.run = run
        self.board = board
        self._assessed = set()
        self._active = {}
        self._grounds = {}

    def camera_observations(self):
        return self.board.camera_for('watchdog')

    def findings(self):
        return [e for e in self.board.event_log if isinstance(e, AnomalyMatchEvent) and e.source_agent == 'watchdog']

    def _continuable(self):
        from pearl.runtime.review_memory import review_memory
        ids = {r['event_id'] for r in self.run.pending}
        ids.update((r['review_id'] for r in review_memory(self.board.event_log)['active_concerns']))
        return {e.event_id: e for e in self.findings() if e.event_id in ids}

    def _monitoring_memory(self):
        active = list(self._continuable().values())
        reviews = [e for e in self.board.event_log if getattr(e, 'observation_type', None) == 'scientific_monitor_review']
        return {'active_reviews': [{'review_id': e.event_id, 'incident_key': e.anomaly_id, 'reference_scope': deepcopy(e.evidence.get('reference_scope'))} for e in active[-16:]], 'total_active': len(active), 'omitted_active': max(0, len(active) - 16), 'recent_assessment_ids': [e.event_id for e in reviews[-4:]], 'scope': 'Exact existing public references, not new findings or resolutions. Read full events by ID; continuing a concern does not require another advisory.'}

    def assess(self, boundary, **scope):
        if boundary in self._assessed:
            return

        def check(answer, frontier, event_ids):
            if 'review_ids' in answer:
                if not set(answer['review_ids']) <= self._continuable().keys() or not set(answer['review_ids']) <= event_ids:
                    raise ValueError('Continue only an existing active Watchdog concern by its exact public review ID')
                return
            if answer['verdict'] == 'clear' and answer['findings'] or (answer['verdict'] == 'concern' and (not answer['findings'])):
                raise ValueError('Verdict and explicit findings disagree: clear requires findings=[]; concern requires at least one unresolved finding. Findings raise pending advisories; informational or resolved observations belong in assessment. Choose your own verdict from public evidence.')
            seen = set()
            for finding in answer['findings']:
                if not finding['measurement_ids'] and (not finding['event_ids']):
                    raise ValueError('Every explicit finding requires at least one public reference')
                if finding['incident_key'] in seen:
                    raise ValueError('Repeated incident_key in one assessment')
                seen.add(finding['incident_key'])
                acquired_references(finding['measurement_ids'], frontier)
                if not set(finding['event_ids']) <= event_ids:
                    raise ValueError('Use public event IDs available in the delivered peer snapshot')
        try:
            answer = self.run._consult_peer('watchdog', lambda: {'monitoring_boundary': boundary, 'monitoring_memory': self._monitoring_memory(), **deepcopy(scope)}, check)
        except RuntimeError:
            raise
        except Exception as exc:
            raise ScientificPeerError(f'Watchdog consultation failed: {exc}') from exc
        if 'review_ids' in answer:
            answer = {'verdict': 'concern', 'assessment': answer['assessment'], 'findings': [], 'continuing_review_ids': deepcopy(answer['review_ids'])}
        review = ObservationEvent(source_agent='watchdog', observation_type='scientific_monitor_review', payload={'boundary': boundary, **deepcopy(answer)})
        self.board.publish(review)
        for finding in answer['findings']:
            locations = tuple(sorted({self.run._evidence[mid]['location'] for mid in finding['measurement_ids']}))
            scope = ('locations', locations) if locations else ('events', tuple(sorted(finding['event_ids'])))
            key = (finding['incident_key'], scope)
            prior = self._active.get(key)
            signature = hashlib.sha256(json.dumps(finding, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if prior is not None and (prior not in self.run._handled or signature in self._grounds.get(key, set())):
                continue
            event = AnomalyMatchEvent(source_agent='watchdog', anomaly_id=finding['incident_key'], confidence='advisory', trigger='llm', evidence={**deepcopy(finding), 'reference_scope': {scope[0]: list(scope[1])}, 'review_event_id': review.event_id, 'cause': 'undetermined'})
            self.board.publish(event)
            self._active[key] = event.event_id
            self._grounds.setdefault(key, set()).add(signature)
        self._assessed.add(boundary)
