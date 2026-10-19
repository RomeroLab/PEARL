"""Request-bound scientific execution permission; never assigns task grades."""
from copy import deepcopy
from pearl.runtime.llm_scientific_peers import TEXT, IDS, acquired_references, peer_tools
from pearl.runtime.analysis_basis import public_copy
from pearl.state.events import ObservationEvent
from pearl.runtime.requirement_provenance import OPERATIONAL_ASSUMPTIONS
INSTRUCTION = 'You hold final execution authorization for the exact execution_review request.\nAssess whether this is a justified next step, not whether its outcome is guaranteed.\nAn informative, feasible experiment can be approved under uncertainty; uncertainty alone\nis not a reason to block evidence gathering. Assess suitability using the public objective, constraints, acquired evidence,\npeer concerns and intended decision value. Select approve, hold or reject with public grounds.\nApprove permits only this unchanged request, not a different operation or later retry. Hold or\nreject prevents execution; state the relevant uncertainty or objection so the planning owner can\nreconsider, gather information, revise or stop. Do not demand a change when continuation is justified.\nAn advisory response cannot override your denied permission. You cannot rewrite the operation,\nexecute it yourself, prescribe a mandatory remedy, discard evidence or award a task grade.\nMonitoring clear/uncertain is not execution approval. Inspect/read evidence or consult Knowledge\nwhen useful. Physical validation remains independently binding. For final_report, assess whether\npublishing these exact claims and stopping grounds is justified; permission is not independent\nP/A/E success. Honest nonachievement can be reported when its claims and stopping grounds\nare justified; do not require a success claim to permit a report. Use only references\nactually acquired or available in this public consultation. ' + OPERATIONAL_ASSUMPTIONS

class ExecutionAuthorizationDenied(ValueError):

    def __init__(self, decision):
        self.execution_authorization = deepcopy(decision)
        super().__init__('Execution authorization ' + decision['decision'] + ': ' + decision['rationale'] + ' [decision_id=' + decision['decision_id'] + ']')

def tools(domain):
    from pearl.runtime.runtime import schema
    result = [tool for tool in peer_tools('watchdog', domain) if tool['function']['name'] not in ('submit_watchdog_review', 'continue_watchdog_review')]
    result.append(schema('submit_execution_authorization', 'Decide final permission for this exact request: only approve permits execution.', {'request_id': TEXT, 'decision': {'type': 'string', 'enum': ['approve', 'hold', 'reject']}, 'rationale': TEXT, 'measurement_ids': IDS, 'event_ids': IDS}))
    return result

def authorize(run, action, plan_id, *, parent_approval_id=None, kind='action', ordered_steps=None):
    owner = 'watchdog' if run.watchdog is not None else run.planning_role
    original = {'action_type': action.action_type, 'params': public_copy(action.params)}
    request = ObservationEvent(source_agent=run.planning_role, observation_type='execution_authorization_request', payload={'kind': kind, 'action_id': action.action_id, 'plan_id': plan_id, 'action': deepcopy(original), 'parent_approval_id': parent_approval_id, 'ordered_steps': deepcopy(ordered_steps) if ordered_steps is not None else [{'action_id': action.action_id, **deepcopy(original)}], 'requested_at_s': run.world.time_s, 'authorization_owner': owner})
    run.board.publish(request)
    delivered = {}

    def context():
        last = run.board.event_log[-1]
        delivered.update(last_event_id=last.event_id, last_trace_sequence=last.trace_sequence, acquired_measurement_count=len(run._evidence), available_at_s=run.world.time_s)
        return {'execution_review': {'request_id': request.event_id, **deepcopy(request.payload)}, 'authorization_instructions': INSTRUCTION}

    def check(answer, frontier, event_ids):
        if answer['request_id'] != request.event_id:
            raise ValueError('Execution authorization must identify this exact request')
        acquired_references(answer['measurement_ids'], frontier)
        if not set(answer['event_ids']) <= event_ids:
            raise ValueError('Execution authorization requires available public event IDs')
        if not answer['measurement_ids'] and (not answer['event_ids']):
            raise ValueError('Execution authorization requires public scientific grounds')
    answer = run._consult_peer(owner, context, check, purpose='execution_authorization')
    if original != {'action_type': action.action_type, 'params': public_copy(action.params)}:
        raise ValueError('Proposed operation changed during execution authorization')
    decision = ObservationEvent(source_agent=owner, observation_type='execution_authorization', payload={**deepcopy(answer), 'action_id': action.action_id, 'plan_id': plan_id, 'kind': kind, 'information_frontier': deepcopy(delivered), 'decided_at_s': run.world.time_s})
    run.board.publish(decision)
    result = {'decision_id': decision.event_id, **deepcopy(decision.payload)}
    if answer['decision'] != 'approve':
        raise ExecutionAuthorizationDenied(result)
    return result
