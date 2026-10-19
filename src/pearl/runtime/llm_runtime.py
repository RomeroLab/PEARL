"""Default live composition: five independent LLM roles with bounded authority."""
from contextlib import contextmanager
from copy import deepcopy
import json
from uuid import uuid4
from jsonschema import ValidationError, validate
from pearl.runtime.runtime import ObservationRuntime, PendingReviewError, ToolResponseValidationError, camera_window_tool
from pearl.runtime.transport import TABLE_GUIDE, compact_context, order_context
from pearl.runtime.llm_scientific_peers import scientific_peer_prompt, peer_tools, LlmKnowledgePeer, LlmWatchdogPeer, ScientificPeerError
from pearl.state.events import ObservationEvent, ToolCallEvent
from pearl.runtime.llm_actor import ACTOR, LlmActor, actor_tools
from pearl.runtime.consultation_memory import PeerQueryMemory
from pearl.brain.tool_schema import strict_function_tool
LLM_ROLES = ('reasoner', 'predictor', 'knowledge', 'watchdog', 'actor')

class LlmObservationRuntime(ObservationRuntime):
    review_reports_before_liquid = True
    require_prospective_design = True

    def __init__(self, world, **kwargs):
        from pearl.runtime.backend_contract import validate_backend
        validate_backend(world)
        if 'knowledge_factory' in kwargs or 'watchdog_factory' in kwargs:
            raise ValueError('The live composition requires both LLM scientific peers')
        super().__init__(world, knowledge_factory=lambda board: LlmKnowledgePeer(self, board), watchdog_factory=lambda board, **unused: LlmWatchdogPeer(self, board), **kwargs)
        self._configure_live_observation()

    def _configure_live_observation(self):
        self.actor = LlmActor(self, self.actor)
        self._camera_scope = None
        self.world.camera_request_hook = self._camera_requested
        if self.continuous_camera:
            self.continuous_camera.active = False
        setup = ObservationEvent(source_agent='operator', observation_type='declared_setup', payload=deepcopy(self.world.briefing()))
        self.board.publish(setup)
        self._setup_event_id = setup.event_id
        self._watchdog_report_subject = None
        self._watchdog_report_frontier = None

    def _initialize_observations(self):
        """Only an authored inspection starts observation in the live composition."""

    @contextmanager
    def _camera_request_scope(self, source, trigger, **lineage):
        previous = self._camera_scope
        self._camera_scope = (source, trigger, lineage)
        try:
            yield
        finally:
            self._camera_scope = previous

    def _start_capture(self, locations):
        pass

    def _camera_requested(self, locations):
        source, trigger, lineage = self._camera_scope or ('operator', 'explicit_inspection', {})
        if not self.world.camera_active and trigger != 'explicit_inspection':
            raise ValueError('Only explicit inspection may activate observation')
        request = ObservationEvent(source_agent=source, observation_type='camera_request', payload={'locations': list(locations), 'requested_at_s': self.world.time_s, 'trigger': trigger, **lineage})
        self.board.publish(request)
        if not self.world.camera_active:
            self.world.camera_active = True
            if self.continuous_camera:
                self.continuous_camera.activation_request_id = request.event_id
                self.continuous_camera.activate()
            self.board.publish(ObservationEvent(source_agent=source, observation_type='camera_activation', payload={'activated_at_s': self.world.time_s, 'request_id': request.event_id}))
        if self.continuous_camera:
            self.continuous_camera.inspection_request_id = request.event_id
        else:
            super()._start_capture(locations, request_id=request.event_id)

    def _capture_after_action(self, locations):
        if self.world.camera_active:
            with self._camera_request_scope('actor', 'automatic_post_action', **self._camera_scope[2] if self._camera_scope else {}):
                return super()._capture_after_action(locations)

    def _role_tools(self, role):
        from pearl.runtime.agent_analysis import scientific_tools
        return scientific_tools(super()._role_tools(role))

    def _utility(self, role, name, args):
        from pearl.runtime.agent_analysis import selected_course, selected_mm, selected_color, record_analysis
        from pearl.runtime.agent_color import selected_mix, selected_range
        if name in ('analyze_initial_rate', 'analyze_mm_rates', 'analyze_measured_initial_rate'):
            raise ValueError('Use the current acquired-evidence numerical tools')
        if name == 'analyze_measured_color':
            return record_analysis(self, role, name, args, selected_color(args, self._evidence, self.board.event_log, self.world.briefing()))
        if name in ('simulate_measured_color_mix', 'analyze_measured_color_range'):
            calculate = selected_mix if name == 'simulate_measured_color_mix' else selected_range
            return record_analysis(self, role, name, args, calculate(args, self._evidence, self.board.event_log, self.world.briefing()))
        if name == 'analyze_measured_course':
            result = selected_course(args, self._evidence, self.board.event_log, self.world.briefing())
            return record_analysis(self, role, name, args, result)
        if name == 'analyze_measured_mm_rates':
            return record_analysis(self, role, name, args, selected_mm(args, self.board.event_log))
        return super()._utility(role, name, args)

    def _context(self, role, **extra):
        from pearl.runtime.operation_observations import operation_observation_index
        return {**super()._context(role, **extra), 'setup_event_id': self._setup_event_id, 'operation_observation_index': operation_observation_index(self.board.event_log)}

    def _collect_findings(self):
        pending = {r['event_id'] for r in self.pending}
        for event in self.watchdog.findings():
            if event.event_id not in self._handled and event.event_id not in pending:
                self.pending.append(event.to_dict())
                pending.add(event.event_id)

    def _monitor_boundary(self):
        actions = [e for e in self.board.event_log if isinstance(e, ToolCallEvent) and e.source_agent == 'actor' and (e.executed is True)]
        decisions = [e for e in self.board.event_log if getattr(e, 'observation_type', None) == 'scientific_decision' and e.source_agent == 'reasoner']
        return ('reasoner_boundary', actions[-1].event_id if actions else None, decisions[-1].event_id if decisions else None)

    def _call(self, role, **extra):
        if role == 'reasoner':
            self.watchdog.assess(self._monitor_boundary())
            self._collect_findings()
        return super()._call(role, **extra)

    def _before_finalize_report(self, report):
        from pearl.runtime.report_review import report_subject
        subject = report_subject(report)
        if subject != self._watchdog_report_subject or self._review_frontier() != self._watchdog_report_frontier:
            proposal = ObservationEvent(source_agent=self.planning_role, observation_type='watchdog_report_proposal', payload=deepcopy(report))
            self.board.publish(proposal)
            self.watchdog.assess(('report', proposal.event_id), proposed_report=deepcopy(report), report_id=proposal.event_id)
            self._watchdog_report_subject = subject
            self._watchdog_report_frontier = self._review_frontier()
        self._collect_findings()
        if self.pending:
            raise PendingReviewError('Disposition pending scientific observations before finalizing.', self.pending, self.board.event_log)

    def _dispatch(self, action, plan_id):
        self._collect_findings()
        if self.pending and action.action_type in ('transfer', 'mix'):
            raise PendingReviewError('Disposition pending scientific observations before liquid execution.', self.pending, self.board.event_log)
        if self.actor.executing:
            trigger = 'explicit_inspection' if action.action_type == 'inspect' else 'operation'
            with self._camera_request_scope('actor', trigger, actor_action_id=action.action_id, plan_id=plan_id):
                return super()._dispatch(action, plan_id)
        self._validate_dispatch(action)
        return self.actor.dispatch(action, plan_id, lambda: self._dispatch(action, plan_id))

    def _before_publish_report(self, report):
        from pearl.runtime.contracts import ActionSpec
        return self._authorize_execution(ActionSpec(action_id=uuid4().hex, action_type='report', params=deepcopy(report)), uuid4().hex, kind='final_report')

    def _action_workflow(self):
        return {**super()._action_workflow(), 'sequence': 'operation proposal -> scientific peer review -> final execution authorization -> immutable Actor execution -> physical validation -> execution', 'execution_authority': 'watchdog' if self.watchdog is not None else self.planning_role, 'authorization_policy': 'Only explicit request-bound approve permits execution. Hold/reject cannot be overridden by advisory responses. Revised proposals require a new decision.'}

    def _authorize_execution(self, action, plan_id, **kwargs):
        from pearl.runtime.execution_authority import authorize
        return authorize(self, action, plan_id, **kwargs)

    def _peer_prompt(self, role):
        return ACTOR if role == 'actor' else scientific_peer_prompt(role)

    def _consult_peer(self, role, extra, check, *, search=None, purpose=None):
        authorization = purpose == 'execution_authorization'
        if authorization:
            from pearl.runtime.execution_authority import tools as authorization_tools, INSTRUCTION
            tools = authorization_tools(self.world.domain)
        else:
            tools = actor_tools(self.world.domain) if role == 'actor' else peer_tools(role, self.world.domain)
        if self.continuous_camera:
            tools.append(camera_window_tool())
        by_name = {t['function']['name']: t['function']['parameters'] for t in tools}
        terminals = {'submit_execution_authorization'} if authorization else {'execute_approved_action', 'report_execution_problem'} if role == 'actor' else {'submit_knowledge_response'} if role == 'knowledge' else {'submit_watchdog_review', 'continue_watchdog_review'}
        wire_tools = [strict_function_tool(t) if t['function']['name'] in terminals else deepcopy(t) for t in tools]
        feedback = None
        last_tool_call = None
        submission_repair = None
        failures = 0
        query_memory = PeerQueryMemory()
        history = []
        conversation_history = []
        conversation_only = authorization and getattr(self, 'profile', {}).get('context_management') == 'conversation_only'
        try:
            for turn in range(12):
                canonical = self._context(role)
                fields = ('setup', 'setup_event_id', 'requirement_scope', 'replication_requirement_scope', 'camera', 'camera_archive_index', 'working_plan', 'working_plan_observations', 'working_plan_acquisition_context', 'decision_memory', 'cohort_memory', 'pending_reviews', 'action_workflow', 'scientific_review_memory', 'analysis_memory', 'color_comparison_memory', 'operation_state', 'operation_observation_index', 'shared_messages', 'omitted_earlier_messages')
                context = {k: deepcopy(canonical[k]) for k in fields if k in canonical}
                recent = list(self.board.event_log[-16:])
                for kind in ('plan', 'prediction', 'acknowledged_action'):
                    selected = [e for e in self.board.event_log if (e.event_type == kind if kind in ('plan', 'prediction') else isinstance(e, ToolCallEvent) and e.source_agent == 'actor' and (e.executed is True))]
                    recent.extend(selected[-2:])
                selected = {e.event_id: e for e in recent}
                index = []
                for event in sorted(selected.values(), key=lambda e: e.trace_sequence):
                    header = {k: deepcopy(getattr(event, k)) for k in ('event_id', 'event_type', 'source_agent', 'trace_sequence', 'observation_type', 'tool_name', 'executed', 'plan_id') if hasattr(event, k)}
                    if isinstance(event, ToolCallEvent) and event.source_agent == 'actor':
                        header['params'] = deepcopy(event.params)
                        receipt = (event.result or {}).get('observation')
                        if event.executed is True and isinstance(receipt, dict) and ('completed_at_s' in receipt):
                            header['completed_at_s'] = deepcopy(receipt['completed_at_s'])
                    if event.event_type == 'prediction':
                        header['predicted_outcomes'] = deepcopy(event.predicted_outcomes)
                    index.append(header)
                if not conversation_only:
                    context['public_record'] = {'representation': 'public_event_index', 'events': index, 'total_events': len(self.board.event_log), 'read_tool': 'read_shared_events', 'scope': 'Recent public headers and latest prediction/action references, not complete events. Read exact events by ID; all earlier records remain available.'}
                context.update(extra())
                if feedback is not None:
                    context['last_tool_result'] = deepcopy(feedback)
                if last_tool_call is not None:
                    context['last_tool_call'] = deepcopy(last_tool_call)
                if submission_repair is not None:
                    context['submission_repair'] = deepcopy(submission_repair)
                context['consultation'] = {'turn': turn + 1, 'remaining_turns': 12 - turn, 'caller_waits_for_reply': True, 'query_history': query_memory.summary(), 'meaning': 'A bounded consultation; uncertainty is valid, no scientific conclusion is required. The caller awaits this reply before dispatching its next command. Ongoing reactions, camera acquisition and external activity may continue. Query history covers the six most recently queried distinct requests in this consultation.'}
                if self.compact_messages:
                    context = self._delivery_context(context, role)
                messages = [{'role': 'system', 'content': (f'You are the {role.capitalize()} agent. ' + INSTRUCTION if authorization else self._peer_prompt(role)) + ('\n' + TABLE_GUIDE if self.compact_messages else '')}, *deepcopy(history), {'role': 'user', 'content': json.dumps(compact_context(order_context(context)) if self.compact_messages else order_context(context), allow_nan=False, separators=(',', ':'))}]
                if conversation_only:
                    messages = [messages[0], *deepcopy(self._conversation[1:]), *deepcopy(conversation_history), messages[-1]]
                    conversation_history.append(deepcopy(messages[-1]))
                from pearl.runtime.peer_result_delivery import deduplicate_latest_result
                messages = deduplicate_latest_result(messages, compact=self.compact_messages)
                frontier = frozenset(self._evidence)
                event_ids = frozenset((e.event_id for e in self.board.event_log))
                result = None
                try:
                    callback = lambda: self.chat(role, messages, wire_tools)
                    try:
                        result = self.continuous_camera.call(role, callback) if self.continuous_camera else callback()
                    except (ToolResponseValidationError, RuntimeError):
                        raise
                    except Exception as exc:
                        raise ScientificPeerError(f'{role} provider failed: {exc}') from exc
                    if not isinstance(result, dict) or set(result) != {'name', 'arguments'}:
                        raise ValueError('Return one named tool and its argument object')
                    name, args = (result['name'], result['arguments'])
                    if name not in by_name:
                        raise ValueError('This tool is unavailable to the scientific peer')
                    validate(args, by_name[name])
                    if name in terminals:
                        check(args, frontier, event_ids)
                        if conversation_only:
                            conversation_history.append({'role': 'assistant', 'content': json.dumps({'name': name, 'arguments': args}, allow_nan=False)})
                        return deepcopy(args)
                    selected_call = {'name': name, 'arguments': deepcopy(args)}
                    if name == 'search_knowledge':
                        feedback = search(args['question'])
                    elif name == 'inspect':
                        with self._camera_request_scope(role, 'explicit_inspection'):
                            feedback = self._capture(args['locations'])
                    else:
                        feedback = self._utility(role, name, args)
                    query_memory.record(selected_call, feedback)
                    last_tool_call = selected_call
                    if submission_repair is not None and name not in terminals and (submission_repair['tool_name'] == name):
                        submission_repair = None
                except (ValueError, KeyError, TypeError, ValidationError) as exc:
                    failures += 1
                    feedback = {'status': 'invalid_peer_submission', 'message': exc.message if isinstance(exc, ValidationError) else str(exc), 'effect': 'No assessment or action was applied. Correct structure using public references; uncertainty is valid.'}
                    rejection = ObservationEvent(source_agent=role, observation_type='scientific_peer_validation_error', payload={**deepcopy(feedback), 'rejected_submission': deepcopy(result)})
                    self.board.publish(rejection)
                    diagnostic = feedback['message']
                    submission_repair = {'event_id': rejection.event_id, 'tool_name': result.get('name') if isinstance(result, dict) and isinstance(result.get('name'), str) and (result['name'] in by_name) else None, 'message': diagnostic[:2048], 'message_truncated': len(diagnostic) > 2048}
                    feedback['message'] = submission_repair['message']
                    last_tool_call = None
                if isinstance(result, dict) and isinstance(result.get('name'), str) and (result['name'] in by_name) and isinstance(result.get('arguments'), dict):
                    call_id = 'call_' + uuid4().hex
                    output = compact_context(order_context(deepcopy(feedback))) if self.compact_messages else feedback
                    tool_history = [{'role': 'assistant', 'content': None, 'tool_calls': [{'id': call_id, 'type': 'function', 'function': {'name': result['name'], 'arguments': json.dumps(result['arguments'], allow_nan=False, separators=(',', ':'))}}]}, {'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(output, allow_nan=False, separators=(',', ':'))}]
                    history.extend(tool_history)
                    if conversation_only:
                        conversation_history.extend(deepcopy(tool_history))
                elif conversation_only and result is not None:
                    conversation_history.extend([{'role': 'assistant', 'content': json.dumps(result, default=str)}, {'role': 'user', 'content': json.dumps(feedback, allow_nan=False)}])
                if failures >= 2:
                    raise ScientificPeerError(feedback['message'])
            raise ScientificPeerError(f'{role} did not finish its bounded public consultation')
        finally:
            if conversation_only:
                self._conversation.extend(conversation_history)

    def summary(self, termination, **extra):
        return super().summary(termination, llm_roles=list(LLM_ROLES), scientific_peer_mode='llm', **extra)
