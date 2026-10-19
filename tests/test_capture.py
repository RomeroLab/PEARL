import threading
import time
from types import SimpleNamespace
from uuid import uuid4
import pytest


def driver_fixture(interval=.005):
    from pearl.runtime.blackboard import Blackboard
    from pearl.runtime.continuous_camera import ContinuousCamera
    origin = time.monotonic()
    capture_times = []
    class World:
        inventory = {'plate:A1': 10.}
        camera = SimpleNamespace(capture_duration_s=0.)
        _failed = False
        def __init__(self):
            self.robot = SimpleNamespace(stop=lambda: None)
        def latch_failure(self, reason):
            self._failed = True
            self.robot.stop()
        @property
        def time_s(self): return time.monotonic()-origin
        def capture_actual(self, locations):
            start = self.time_s; time.sleep(.001); end = self.time_s
            capture_times.append(end)
            return {'frame_id': uuid4().hex, 'captured_at_s': end, 'acquisition_started_at_s': start,
                    'measurements': [{'measurement_id': uuid4().hex, 'location': l, 'captured_at_s': end,
                                      'rgb': [10, 20, 30], 'od_estimate': .2, 'clipped': False} for l in locations]}
    world = World()
    run = SimpleNamespace(world=world, board=Blackboard(), _evidence={}, _collect_findings=lambda: None)
    d = ContinuousCamera(run, interval)
    d.active = False
    return run, d, capture_times


def test_capture_occurs_during_model_latency_without_backdating_or_future_delivery():
    run, d, captures = driver_fixture()
    try:
        time.sleep(.01)
        assert captures == []
        d.activate(); d.inspect(['plate:A1'])
        initial = set(run._evidence)
        def callback():
            before = time.monotonic()
            time.sleep(.025)
            assert set(run._evidence) == initial
            assert len(captures) >= 2
            return before
        d.call('reasoner', callback)
        assert d.snapshot_evidence['reasoner'] == initial
        assert len(run._evidence) > len(initial)
        assert captures == sorted(captures) and len(set(captures)) == len(captures)
        assert all(e.payload['acquisition_started_at_s'] <= e.payload['captured_at_s']
                   for e in run.board.event_log if e.observation_type == 'camera')
        assert all(run.board.camera_for(r) == run.board.camera_for('actor')
                   for r in ('reasoner', 'predictor', 'knowledge', 'watchdog'))
    finally:
        d.close()
    assert not d.thread.is_alive()


def test_capture_failure_stops_physical_backend_and_propagates_to_owner():
    run, d, captures = driver_fixture()
    stopped = []
    run.world.robot.stop = lambda: stopped.append(True)
    def broken(locations): raise RuntimeError('camera disconnected')
    run.world.capture_actual = broken
    try:
        d.activate()
        with pytest.raises(RuntimeError): d.inspect(['plate:A1'])
        assert run.world._failed and stopped
    finally:
        d.close()


def test_worker_never_publishes_into_event_bus_or_changes_evidence_itself():
    run, d, captures = driver_fixture()
    owner = threading.get_ident(); publishers = []
    run.board._event_sink = lambda e: publishers.append(threading.get_ident())
    try:
        d.activate(); time.sleep(.02)
        assert captures and not run._evidence and not publishers
        d.drain()
        assert run._evidence and set(publishers) == {owner}
    finally:
        d.close()


def test_inflight_timestamped_frame_finishes_before_command_acknowledgement():
    from pearl.state.events import ToolCallEvent
    from pearl.runtime.acquisition_context import acquisition_context
    run, d, captures = driver_fixture(interval=1.)
    entered, release = threading.Event(), threading.Event()
    original = run.world.capture_actual
    def delayed(locations):
        packet = original(locations)
        entered.set()
        assert release.wait(2.)
        return packet
    run.world.capture_actual = delayed
    try:
        d.activate(); assert entered.wait(2.)
        completed = run.world.time_s
        releaser = threading.Timer(.02, release.set); releaser.start()
        d.drain(through_s=completed)
        run.board.publish(ToolCallEvent(source_agent='actor', tool_name='transfer',
            params={'source':'reservoir:A1','target':'plate:A1','volume_ul':10},
            result={'ok':True,'observation':{'completed_at_s':completed}}, executed=True, tool_call_id='a'))
        release.set(); releaser.join()
        time.sleep(.005); d.drain()
        rows = list(run._evidence.values())
        assert rows and rows[0]['captured_at_s'] < completed
        acquired = acquisition_context(rows, run.board.event_log, {'reservoir:A1': {'volume_ul':100}})
        assert acquired['captures'][0]['preparation_id'] is None
    finally:
        release.set(); d.close()


def test_capture_request_identity_is_frozen_before_raw_read():
    run, d, captures = driver_fixture(interval=1.)
    entered, release = threading.Event(), threading.Event()
    original = run.world.capture_actual
    def delayed(locations):
        entered.set(); assert release.wait(2.); return original(locations)
    run.world.capture_actual = delayed
    try:
        d.inspection_request_id = 'earlier'; d.activate(); assert entered.wait(2.)
        d.inspection_request_id = 'later'; release.set()
        deadline = time.monotonic()+2.
        while not run._evidence and time.monotonic() < deadline:
            d.drain(); time.sleep(.001)
        frames = [e for e in run.board.event_log if e.observation_type == 'camera']
        assert frames[0].payload['request_id'] == 'earlier'
    finally:
        release.set(); d.close()


def test_observation_overlapping_liquid_operation_has_no_definite_preparation():
    from pearl.state.events import ObservationEvent, ToolCallEvent
    from pearl.runtime.acquisition_context import acquisition_context
    from pearl.runtime.measured_kinetics import _preparations
    ack = ToolCallEvent(source_agent='actor', tool_name='transfer', executed=True, tool_call_id='first',
        params={'source':'reservoir:A1','target':'plate:A1','volume_ul':10},
        result={'ok':True,'observation':{'completed_at_s':1.}})
    m = {'measurement_id':'m','location':'plate:A1','captured_at_s':2.,'acquisition_started_at_s':1.5,
         'overlapping_action_ids':['during'],'rgb':[20,30,40],'od_estimate':.2,'clipped':False}
    frame = ObservationEvent(observation_type='camera', payload={'captured_at_s':2.,'measurements':[m]})
    events = [ack, frame]
    reagents = {'reservoir:A1':{'volume_ul':100}}
    ctx = acquisition_context([m], events, reagents)
    assert ctx['captures'][0]['preparation_id'] is None
    assert ctx['preparations'][0]['nominal_preparation'] is None
    assert ctx['captures'][0]['preparation_status'] == 'ambiguous_during_operation'
    with pytest.raises(ValueError): _preparations(['m'], events, reagents)
