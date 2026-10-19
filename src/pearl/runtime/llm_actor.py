"""Independent LLM Actor with single-use, immutable execution authority."""
from copy import deepcopy
from pearl.runtime.contracts import ProceedSignal
from pearl.runtime.analysis_basis import public_copy
from pearl.runtime.llm_scientific_peers import ScientificPeerError, TEXT, peer_tools
from pearl.state.events import ObservationEvent
ACTOR = 'You are the independent Actor agent. Execute only the already approved\naction in approved_execution. Its execution_permission_id identifies final\npermission already issued for this immutable operation. Select its execution;\nselecting the tool does not acknowledge physical completion. Read public camera and execution records when\nneeded to understand its execution. Select execute_approved_action with the exact\napproval_id, action_id and plan_id; the executor supplies the immutable parameters.\nYou cannot change reagents, quantities, destinations, order or scientific decisions.\nDo not replan, diagnose, exclude evidence or substitute a different action. Report\nan execution problem when the instructions cannot be executed as approved. Physical\nlimits and pending scientific concerns are checked independently before execution.\nAn acknowledgement is a command result, not proof of composition or task success.'

def actor_tools(domain):
    from pearl.runtime.runtime import schema
    tools = [t for t in peer_tools('watchdog', domain) if t['function']['name'].startswith('read_')]
    tools.append(schema('execute_approved_action', 'Select the exact immutable action; execute once only after final execution permission and physical validation.', {key: TEXT for key in ('approval_id', 'action_id', 'plan_id')}))
    tools.append(schema('report_execution_problem', 'Stop this execution with a public explanation.', {'rationale': TEXT}))
    return tools

class LlmActor:

    def __init__(self, run, executor):
        self.run = run
        self.executor = executor
        self._authorization = None

    @property
    def executing(self):
        return self._authorization is not None

    def camera_observations(self):
        return self.run.board.camera_for('actor')

    def dispatch(self, action, plan_id, callback):
        if self.executing:
            raise ScientificPeerError('Actor authorization scope is already active')
        params = public_copy(action.params)
        steps = [{'action_type': action.action_type, 'params': params, 'action_id': action.action_id}]
        if self.run.continuous_camera and action.action_type == 'transfer' and (params.get('mix_after_transfer_ul') is not None):
            first = {k: v for k, v in params.items() if k != 'mix_after_transfer_ul'}
            steps = [{'action_type': 'transfer', 'params': first, 'action_id': action.action_id}, {'action_type': 'mix', 'params': {'location': params['target'], 'volume_ul': params['mix_after_transfer_ul']}}]
        permission = self.run._authorize_execution(action, plan_id, ordered_steps=deepcopy(steps))
        if not getattr(self.run, 'single_agent', False):
            proposal = ObservationEvent(source_agent='actor', observation_type='actor_execution_request', payload={'action_id': action.action_id, 'plan_id': plan_id, 'action': {'action_type': action.action_type, 'params': deepcopy(params)}, 'ordered_steps': deepcopy(steps), 'authorization_status': 'approved', 'execution_permission_id': permission['decision_id']})
            self.run.board.publish(proposal)
            approval = {**deepcopy(proposal.payload), 'approval_id': proposal.event_id}

            def check(answer, frontier, event_ids):
                if 'rationale' in answer:
                    return
                if any((answer[key] != approval[key] for key in ('approval_id', 'action_id', 'plan_id'))):
                    raise ValueError('Actor must select the exact delivered approval, action and plan IDs')
            answer = self.run._consult_peer('actor', lambda: {'approved_execution': deepcopy(approval)}, check)
            if 'rationale' in answer:
                self.run.board.publish(ObservationEvent(source_agent='actor', observation_type='actor_execution_problem', payload={'approval_id': proposal.event_id, **answer}))
                raise ScientificPeerError(answer['rationale'])
            self.run.board.publish(ObservationEvent(source_agent='actor', observation_type='actor_execution_selected', payload=deepcopy(answer)))
        self._authorization = {'plan_id': plan_id, 'remaining': deepcopy(steps), 'execution_permission': permission}
        try:
            result = callback()
            if self._authorization['remaining']:
                raise ScientificPeerError('Actor authorization did not execute the complete approved sequence')
            return result
        finally:
            self._authorization = None

    def execute(self, signal):
        scope = self._authorization
        if scope is None or not isinstance(signal, ProceedSignal) or signal.plan_id != scope['plan_id'] or (len(signal.actions) != 1) or (not scope['remaining']):
            raise ScientificPeerError('Actor execution requires an active single-use authorization')
        action = signal.actions[0]
        actual = {'action_type': action.action_type, 'params': public_copy(action.params)}
        expected = scope['remaining'][0]
        if actual != {k: expected[k] for k in ('action_type', 'params')} or expected.get('action_id', action.action_id) != action.action_id:
            raise ScientificPeerError('Actor execution differs from the ordered approved authorization')
        scope['remaining'].pop(0)
        return self.executor.execute(signal)
