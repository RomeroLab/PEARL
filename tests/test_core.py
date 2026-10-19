from copy import deepcopy
import json
from types import SimpleNamespace

import pytest


def public_view():
    from pearl.runtime.contracts import ActionResult
    setup = {
        'domain': 'color', 'goal': 'Make a color.', 'public_goal': {},
        'locations': ['reservoir:A1', 'plate:A1'],
        'reagents': {'reservoir:A1': {'label': 'Dye 1', 'volume_ul': 1000}},
        'calibration': {'blank_rgb': [240, 240, 240], 'dark_rgb': [0, 0, 0]},
        'equipment': {'capture_duration_s': 0, 'min_transfer_ul': 1,
                      'well_capacity_ul': 360, 'volume_resolution_ul': 0.1},
        'constraints': {},
    }
    world = SimpleNamespace(domain='color', inventory={'reservoir:A1': 1000., 'plate:A1': 0.},
                            command_log=[], time_s=0., camera_active=False,
                            camera=SimpleNamespace(calibration=None),
                            briefing=lambda: deepcopy(setup), validate_action=lambda a: None)
    def execute(action):
        world.command_log.append(action)
        return ActionResult(action_id=action.action_id, action_type=action.action_type,
                            ok=True, observation={'started_at_s': 0., 'completed_at_s': 1.})
    world.inspect = lambda locations: {'measurements': [], 'evidence_ids': []}
    world.execute = execute
    return world


def context(messages):
    from pearl.runtime.transport import expand_context
    return expand_context(json.loads(messages[-1]['content']))


def permission(c, verdict='approve'):
    return {'name': 'submit_execution_authorization', 'arguments': {
        'request_id': c['execution_review']['request_id'], 'decision': verdict,
        'rationale': 'Evaluate this exact operation against declared constraints.',
        'measurement_ids': [], 'event_ids': [c['setup_event_id']]}}


def execute_reply(c):
    return {'name': 'execute_approved_action', 'arguments': {
        key: c['approved_execution'][key] for key in ('approval_id', 'action_id', 'plan_id')}}


def test_actions_are_recursively_immutable_and_actor_consumes_only_proceed():
    from pearl.runtime.contracts import ActionSpec, Actor, ProceedSignal
    source = {'nested': {'values': [1, 2]}}
    action = ActionSpec(action_id='a', action_type='inspect', params=source)
    source['nested']['values'].append(3)
    assert tuple(action.params['nested']['values']) == (1, 2)
    with pytest.raises(TypeError):
        action.params['nested']['x'] = 1
    actor = Actor(lambda a: a.action_id)
    assert actor.execute(ProceedSignal(plan_id='p', actions=(action,))) == ['a']
    with pytest.raises(TypeError):
        actor.execute(action)


def test_reentrant_blackboard_preserves_publication_and_delivery_order():
    from pearl.runtime.blackboard import Blackboard
    from pearl.state.events import ObservationEvent
    sink, delivered = [], []
    board = Blackboard(event_sink=sink.append)
    def first(e):
        delivered.append(('first', e.observation_type))
        if e.observation_type == 'outer':
            board.publish(ObservationEvent(observation_type='inner'))
    board.subscribe(ObservationEvent, first)
    board.subscribe(ObservationEvent, lambda e: delivered.append(('second', e.observation_type)))
    board.publish(ObservationEvent(observation_type='outer'))
    assert delivered == [('first', 'outer'), ('second', 'outer'), ('first', 'inner'), ('second', 'inner')]
    assert [e['trace_sequence'] for e in sink] == [1, 2]
    packet = {'measurements': [{'measurement_id': 'm', 'rgb': [10, 20, 30]}], 'evidence_ids': ['m']}
    board.publish(ObservationEvent(observation_type='camera', payload=packet))
    for role in ('reasoner', 'predictor', 'knowledge', 'watchdog', 'actor'):
        copy = board.camera_for(role)
        assert copy == packet
        copy['measurements'].clear()
    assert len(board.camera_for('actor')['measurements']) == 1


@pytest.mark.parametrize('profile,roles,owner', [
    ('full', 5, 'watchdog'), ('no_reasoner', 4, 'watchdog'),
    ('no_predictor', 4, 'watchdog'), ('no_knowledge', 4, 'watchdog'),
    ('no_watchdog', 4, 'reasoner'), ('base_llm', 1, 'actor'), ('pearl_minimal', 1, 'actor')])
@pytest.mark.parametrize('verdict', ['approve', 'hold', 'reject'])
def test_actual_profile_permission_precedes_actor_and_hold_blocks(profile, roles, owner, verdict):
    from pearl.runtime.ablation_runtime import create_runtime
    from pearl.runtime.contracts import ActionSpec
    calls = []
    def chat(role, messages, tools):
        c = context(messages)
        calls.append(role)
        return permission(c, verdict) if 'execution_review' in c else execute_reply(c)
    run = create_runtime(public_view(), ablation=profile, chat=chat)
    assert not run.board.camera_for('actor')['measurements']
    action = ActionSpec(action_id='a', action_type='transfer', params={
        'source': 'reservoir:A1', 'target': 'plate:A1', 'volume_ul': 10})
    if verdict == 'approve':
        run._dispatch(action, 'p')
        assert len(run.world.command_log) == 1
        assert calls == ([owner] if roles == 1 else [owner, 'actor'])
    else:
        with pytest.raises(ValueError):
            run._dispatch(action, 'p')
        assert calls == [owner] and not run.world.command_log
    assert len(run.summary('test')['llm_roles']) == roles
    assert run.summary('test')['evaluation_status'] == 'not_evaluated'


def test_peer_terminal_projection_and_local_validation_remain_separate():
    from pearl.runtime.ablation_runtime import create_runtime
    calls = []
    def chat(role, messages, tools):
        c = context(messages)
        calls.append(c)
        fn = next(t['function'] for t in tools if t['function']['name'] == 'submit_watchdog_review')
        assert fn['strict'] is True
        assert set(fn['parameters']['required']) == {'verdict', 'assessment', 'findings'}
        args = {'verdict': 'clear', 'assessment': 'No acquired discrepancy asserted.'}
        if len(calls) > 1:
            args['findings'] = []
        return {'name': 'submit_watchdog_review', 'arguments': args}
    run = create_runtime(public_view(), chat=chat)
    run.watchdog.assess('boundary')
    assert len(calls) == 2 and calls[1]['last_tool_result']['status'] == 'invalid_peer_submission'
    assert not run.watchdog.findings() and not run.world.command_log


def test_unknown_backend_and_unknown_profile_are_rejected_before_model_use():
    from pearl.runtime.ablation_runtime import create_runtime
    def forbidden(*a):
        pytest.fail('provider was invoked before backend admission')
    with pytest.raises((ValueError, TypeError)):
        create_runtime(object(), chat=forbidden)
    with pytest.raises(ValueError):
        create_runtime(public_view(), ablation='no_actor', chat=forbidden)


def test_reference_guidance_reaches_knowledge_and_returns_its_independent_assessment():
    from pearl.runtime.ablation_runtime import create_runtime
    delivered = []
    def chat(role, messages, tools):
        assert role == 'knowledge'
        c = context(messages)
        delivered.extend(c['retrieved_knowledge'])
        assert 'calibration_range' in {r['knowledge_id'] for r in delivered}
        assert all('reference_curve' not in r for r in delivered)
        return {'name':'submit_knowledge_response','arguments':{
            'answer':'Assess calibration coverage and applicability from the acquired evidence.',
            'applicability':'Assess the measurement axes, standards and comparable assay conditions.',
            'limitations':'A reference curve does not establish kinetic parameters by itself.',
            'status':'limited','citations':['calibration_range'],'measurement_ids':[]}}
    run = create_runtime(public_view(), chat=chat, compact_messages=True)
    result = run._knowledge('reasoner', {'question':'HRP-TMB reference curve'})
    assessment = result['audit']['llm_assessment']
    assert assessment['citations'] == ['calibration_range']
    assert assessment['status'] == 'limited'
    assert all(r['evidence_kind'] == 'prior_knowledge' for r in delivered)
    assert not run.world.command_log and not run.world.camera_active
    assert not run.board.camera_for('reasoner')['measurements']


@pytest.mark.parametrize('profile,owner', [
    ('no_knowledge','reasoner'),('base_llm','actor'),('pearl_minimal','actor')])
def test_reference_guidance_remains_available_without_a_dedicated_knowledge_role(profile, owner):
    from pearl.runtime.ablation_runtime import create_runtime
    def forbidden(*args): pytest.fail('Direct corpus access must not instantiate a removed peer')
    run = create_runtime(public_view(), ablation=profile, chat=forbidden)
    result = run._knowledge(owner, {'question':'HRP-TMB reference curve'})
    selected = {r['knowledge_id']:r for r in result['rows']}
    assert 'calibration_range' in selected
    assert selected['calibration_range']['evidence_kind'] == 'prior_knowledge'
    assert all('reference_curve' not in r for r in result['rows'])
    assert result['assessment_owner'] == owner
    assert not run.world.command_log
