"""Benchmark-only scientific role ablations; the full runtime stays the default."""
from copy import deepcopy
import json
from pearl.knowledge.agent import retrieval_audit_to_mapping
from pearl.runtime.backend_contract import validate_backend
from pearl.runtime.knowledge import ROWS
from pearl.runtime.llm_actor import ACTOR
from pearl.runtime.llm_runtime import LLM_ROLES, LlmObservationRuntime
from pearl.runtime.llm_scientific_peers import scientific_peer_prompt, LlmKnowledgePeer, LlmWatchdogPeer
from pearl.runtime.runtime import ObservationRuntime
from pearl.runtime.requirement_provenance import OPERATIONAL_ASSUMPTIONS
from pearl.runtime.scientific_retrieval import ScientificKnowledgeProvider
from pearl.state.events import ToolCallEvent
_DEFAULT_DUTIES = {'reasoner': ['scientific_reasoning', 'planning', 'scientific_decisions'], 'predictor': ['prediction', 'scientific_review'], 'knowledge': ['source_retrieval', 'knowledge_assessment'], 'watchdog': ['scientific_monitoring', 'execution_authorization'], 'actor': ['approved_execution']}
_SINGLE_DUTIES = ['scientific_reasoning', 'planning', 'scientific_decisions', 'prediction', 'source_retrieval', 'knowledge_assessment', 'scientific_monitoring', 'execution_authorization', 'execution']
ABLATION_PROFILES = ('full', 'no_reasoner', 'no_predictor', 'no_knowledge', 'no_watchdog', 'base_llm', 'pearl_minimal')

def profile_metadata(name):
    if name not in ABLATION_PROFILES:
        raise ValueError(f'Unknown ablation profile: {name}')
    duties = deepcopy(_DEFAULT_DUTIES)
    if name in ('base_llm', 'pearl_minimal'):
        duties = {'actor': list(_SINGLE_DUTIES)}
    elif name != 'full':
        removed = name.removeprefix('no_')
        reassigned = duties.pop(removed)
        owners = ['predictor'] if removed == 'reasoner' else ['reasoner']
        if removed in ('knowledge', 'watchdog'):
            owners.append('predictor')
        for role in owners:
            duties[role].extend(reassigned)
    return {'ablation_profile': name, 'llm_roles': [role for role in LLM_ROLES if role in duties], 'role_duties': duties, 'context_management': 'conversation_only' if name == 'base_llm' else 'shared_blackboard'}
SCIENCE = 'Design methods using only public input, camera data, commands and delivered sources.\nSeparate predictive validity from causal identification; Procedure absence alone does not imply incapability.\nOwn experiments/interpretation/stopping; weigh uncertainty/alternatives.\nSeparate observations/hypotheses/conclusions; sources/commands are not measurements.\nGround insufficiency; physical limits bind. ' + OPERATIONAL_ASSUMPTIONS
SINGLE_ACTOR = 'You are the single Actor responsible for scientific reasoning, planning,\nknowledge assessment, prediction, scientific monitoring, final execution authorization\nand execution. You own all\nscientific decisions and select your actions directly. ' + SCIENCE
PLANNER = 'You are the {role} agent. You own scientific reasoning, planning and scientific\ndecisions. Your assigned duties are {duties}. ' + SCIENCE
REVIEWER = 'You are the Predictor agent. Assess proposed experiments, predictions and\nconclusions from public evidence. Your assigned duties are {duties}. Publish your\nown scientific assessment, including uncertainty or concerns when warranted. ' + SCIENCE

class AblationObservationRuntime(LlmObservationRuntime):
    """Compose only present LLM roles, without rule-based replacement peers."""

    def __init__(self, world, *, ablation, **kwargs):
        validate_backend(world)
        if 'knowledge_factory' in kwargs or 'watchdog_factory' in kwargs:
            raise ValueError('Ablation peer composition is selected by its profile')
        self.profile = profile_metadata(ablation)
        self.active_roles = frozenset(self.profile['llm_roles'])
        self.single_agent = ablation in ('base_llm', 'pearl_minimal')
        self.planning_role = 'actor' if self.single_agent else 'reasoner' if 'reasoner' in self.active_roles else 'predictor'
        self.independent_prediction = 'predictor' in self.active_roles
        self._reviewing = False
        self._conversation = []
        self._direct_sources = None
        ObservationRuntime.__init__(self, world, knowledge_factory=lambda board: LlmKnowledgePeer(self, board) if 'knowledge' in self.active_roles else None, watchdog_factory=lambda board, **unused: LlmWatchdogPeer(self, board) if 'watchdog' in self.active_roles else None, **kwargs)
        self._configure_live_observation()

    def _collect_findings(self):
        if self.watchdog is not None:
            return super()._collect_findings()

    def _monitor_boundary(self):
        boundary = super()._monitor_boundary()
        decisions = [e for e in self.board.event_log if e.source_agent == self.planning_role and getattr(e, 'observation_type', '') == 'scientific_decision']
        return (self.planning_role + '_boundary', boundary[1], decisions[-1].event_id if decisions else None)

    def _call(self, role, **extra):
        if role not in self.active_roles:
            raise ValueError(f'Removed LLM role is unavailable: {role}')
        previous = self._reviewing
        self._reviewing = bool(extra.get('review_workflow'))
        try:
            if role == self.planning_role and (not self._reviewing) and (self.watchdog is not None):
                self.watchdog.assess(self._monitor_boundary())
                self._collect_findings()
            result = ObservationRuntime._call(self, role, **extra)
            if self.profile['context_management'] == 'conversation_only':
                self._conversation.append({'role': 'assistant', 'content': json.dumps({'name': result[0], 'arguments': result[1]}, allow_nan=False)})
            return result
        finally:
            self._reviewing = previous

    def _system_prompt(self, role):
        if self.single_agent:
            return SINGLE_ACTOR
        duties = ', '.join(self.profile['role_duties'][role])
        prompt = REVIEWER if self._reviewing else PLANNER
        return prompt.format(role=role.capitalize(), duties=duties)

    def _peer_prompt(self, role):
        return ACTOR if role == 'actor' else scientific_peer_prompt(role, self.planning_role)

    def _role_tools(self, role):
        tool_role = 'predictor' if self._reviewing else 'reasoner'
        return LlmObservationRuntime._role_tools(self, tool_role)

    def _finalize_tools(self, role, tools):
        if self.independent_prediction:
            return tools
        descriptions = {'transfer': 'Select a transfer for physical validation and execution. Assess scientific suitability, expected outcomes and monitoring yourself.', 'mix': 'Select mixing for physical validation and execution. Assess scientific suitability yourself.', 'finish': 'Report your own conclusion or justified stop using acquired evidence. No task grade or further action is implied.'}
        tools = deepcopy(tools)
        for tool in tools:
            function = tool['function']
            if function['name'] in descriptions:
                function['description'] = descriptions[function['name']]
                if function['name'] == 'transfer' and self.continuous_camera:
                    function['description'] += ' mix_after_transfer_ul optionally requests destination mixing immediately after transfer; null means transfer only.'
        if self.watchdog is None:
            tools = [tool for tool in tools if tool['function']['name'] not in ('respond_to_review', 'resolve_review_concern', 'manage_pending_action')]
        return tools

    def _action_workflow(self):
        if self.independent_prediction:
            return super()._action_workflow()
        return {'review_waiting_for_response': bool(self.pending), 'liquid_proposal_tools': ['transfer', 'mix'], 'record_plan_requests_review': False, 'sequence': 'own scientific assessment -> immutable action selection -> final execution authorization -> physical validation -> execution -> camera', 'execution_authority': 'watchdog' if self.watchdog is not None else self.planning_role, 'authorization_policy': 'Only explicit request-bound approve permits execution; hold/reject cannot be overridden by advisory responses.', 'meaning': 'The planning agent owns prediction and scientific suitability. No independent prediction review is created.'}

    def _context(self, role, **extra):
        if self.profile['context_management'] != 'conversation_only':
            return super()._context(role, **extra)
        return {'setup': deepcopy(self.world.briefing()), 'setup_event_id': self._setup_event_id, 'camera': self.board.camera_for(role), 'time_s': self.world.time_s, 'estimated_inventory_ul': deepcopy(self.world.inventory), 'last_tool_result': deepcopy(self.last_result), 'context_management': 'conversation_only', **deepcopy(extra)}

    def _delivery_context(self, canonical, role):
        if self.profile['context_management'] == 'conversation_only':
            return deepcopy(canonical)
        return super()._delivery_context(canonical, role)

    def _prepare_messages(self, role, messages):
        if self.profile['context_management'] != 'conversation_only':
            return messages
        if not self._conversation:
            self._conversation.append(deepcopy(messages[0]))
        self._conversation.append(deepcopy(messages[-1]))
        return deepcopy(self._conversation)

    def _knowledge(self, role, p, *, observation=None):
        if self.knowledge is not None:
            return super()._knowledge(role, p, observation=observation)
        question = p['question']
        if not isinstance(question, str) or not question.strip():
            raise ValueError('A question is required')
        if self._direct_sources is None:
            self._direct_sources = ScientificKnowledgeProvider(ROWS)
        camera = self.board.camera_for(role) if observation is None else observation
        rows = self._direct_sources.retrieve(question, {'evidence_ids': camera['evidence_ids'], 'observations': camera['measurements'], 'provenance': 'shared acquired camera evidence'})
        result = {'rows': deepcopy(rows), 'audit': retrieval_audit_to_mapping(self._direct_sources.retrieval_audit()), 'assessment_owner': role, 'meaning': 'Source access only. Assess applicability and uncertainty yourself.'}
        self.board.publish(ToolCallEvent(source_agent=role, tool_name='search_knowledge', params={'question': question}, result=deepcopy(result), executed=False))
        return result

    def _before_finalize_report(self, report):
        if self.watchdog is not None:
            return super()._before_finalize_report(report)

    def summary(self, termination, **extra):
        return ObservationRuntime.summary(self, termination, **self.profile, scientific_peer_mode='llm' if not self.single_agent else 'single_actor', **extra)

def create_runtime(world, *, ablation='full', **kwargs):
    profile_metadata(ablation)
    if ablation == 'full':
        return LlmObservationRuntime(world, **kwargs)
    return AblationObservationRuntime(world, ablation=ablation, **kwargs)
