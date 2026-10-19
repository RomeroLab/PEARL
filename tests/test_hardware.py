from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pytest


def setup_data(crop):
    return {'domain': 'enzyme', 'deck': {'plate_slot': 2, 'reservoir_slot': 3},
            'camera': {'crop_config': str(crop)}, 'plate_wells': ['A1', 'A2'],
            'reagents': {'A1': {'label': 'Declared stock', 'volume_ul': 1000,
                              'concentration_value': 1, 'concentration_unit': 'uM'}}}


def setup(tmp_path):
    from pearl.production.settings import validate_setup
    p = tmp_path / 'crop.json'
    p.write_text(json.dumps({'slots': {'2': {'x': 0, 'y': 0, 'w': 1, 'h': .8},
                                       '3': {'x': 0, 'y': .8, 'w': 1, 'h': .2}}}))
    return validate_setup(setup_data(p))


class Robot:
    identity = {'robot_model': 'OT-2'}
    failed = False
    _run_id = 'connected'
    transfer_dispense_times = []
    fail = None
    def transfer_liquid(self, **kwargs):
        if self.fail == 'raise':
            raise RuntimeError('connection lost after dispense')
        if self.fail == 'latched':
            self.failed = True
    def mix(self, *a, **kw):
        if self.fail:
            self.failed = True
    def _auto_select(self, volume): pass
    def pick_up_tip(self): pass
    def drop_tip(self): pass
    def stop(self): self.stopped = True


def backend(tmp_path, robot=None):
    from pearl.production.backend import PhysicalBackend
    from pearl.production.optics import Calibration
    reader = SimpleNamespace(calibration=Calibration(), capture=lambda locations, **k: {
        'captured_at_s': k['clock'](), 'measurements': [], 'evidence_ids': []})
    return PhysicalBackend(setup(tmp_path), robot or Robot(), reader)


def action(kind='transfer', **params):
    from pearl.runtime.contracts import ActionSpec
    if kind == 'transfer':
        params = {'source': 'reservoir:A1', 'target': 'plate:A1', 'volume_ul': 10, **params}
    return ActionSpec(action_id='a', action_type=kind, params=params)


@pytest.mark.parametrize('fail', ['raise', 'latched'])
def test_partial_or_swallowed_device_failure_latches_without_inventory_commit(tmp_path, fail):
    robot = Robot(); robot.fail = fail
    world = backend(tmp_path, robot); before = deepcopy(world.inventory)
    with pytest.raises(RuntimeError):
        world.execute(action())
    assert world.inventory == before and world._failed and robot.stopped
    assert world.command_log[-1]['status'] == 'uncertain_or_failed'
    robot.failed = False; robot.fail = None
    with pytest.raises(RuntimeError): world.execute(action())
    assert world.inventory == before


def test_success_receipt_uses_real_elapsed_time_and_nominal_inventory(tmp_path):
    world = backend(tmp_path)
    before = world.time_s; time.sleep(.01)
    result = world.execute(action())
    assert result.ok and result.observation['completed_at_s'] >= result.observation['started_at_s'] > before
    assert world.inventory['reservoir:A1'] == 990 and world.inventory['plate:A1'] == 10
    assert world.briefing()['calibration']['epsilon_M_cm'] == 39000.
    assert 'noise_sd_counts' not in world.briefing()['equipment']


@pytest.mark.parametrize('params', [
    {'volume_ul': True}, {'volume_ul': float('nan')}, {'volume_ul': .01},
    {'volume_ul': 361}, {'source': 'reservoir:A9'}, {'target': 'plate:H12'},
    {'target': 'reservoir:A1'}, {'volume_ul': 1001}])
def test_physical_preflight_rejects_invalid_operation_without_dispatch(tmp_path, params):
    world = backend(tmp_path)
    with pytest.raises(ValueError): world.validate_action(action(**params))
    assert not world.command_log


def test_actual_receiver_capacity_and_declared_source_residual_are_enforced(tmp_path):
    world = backend(tmp_path); world.inventory['plate:A1'] = 355
    with pytest.raises(ValueError): world.validate_action(action())
    world.inventory['plate:A1'] = 0
    world.inventory['reservoir:A1'] = 15
    world.setup.reagents['A1']['residual_ul'] = 10
    with pytest.raises(ValueError): world.validate_action(action())


def test_uncertain_drop_tip_is_not_swallowed_or_retried(monkeypatch):
    from pearl.production.connection import VerifiedOT2
    from pearl.body.robot import DeckLayout
    robot = VerifiedOT2('192.168.1.2', DeckLayout())
    robot._run_id = 'r'; robot._pipette_id = 'p'; robot._has_tip = True
    calls = []
    def send(kind, params):
        calls.append(kind)
        if kind == 'dropTipInPlace': raise RuntimeError('unknown completion')
        return {'data': {'id': 'cmd', 'status': 'succeeded'}}
    monkeypatch.setattr(robot, '_send_setup_command', send)
    with pytest.raises(RuntimeError): robot.drop_tip()
    assert calls == ['moveToAddressableAreaForDropTip', 'dropTipInPlace']
    assert robot._has_tip


@pytest.mark.parametrize('status', ['running', 'queued', 'failed', None])
def test_device_setup_requires_explicit_succeeded_status(monkeypatch, status):
    from pearl.production.connection import VerifiedOT2
    from pearl.body.ot2_client import OT2HttpClient
    from pearl.body.robot import DeckLayout
    robot = VerifiedOT2('192.168.1.2', DeckLayout())
    monkeypatch.setattr(OT2HttpClient, '_send_setup_command', lambda *a: {'data': {'id': 'c', 'status': status}})
    with pytest.raises(RuntimeError): robot._send_setup_command('home', {})
    assert robot.failed


def test_explicit_calibration_and_crop_fail_instead_of_using_defaults(tmp_path):
    from pearl.production.optics import load_calibration
    from pearl.eyes.deck_scanner import load_crop_config
    assert load_calibration(None).source == 'defaults'
    with pytest.raises(ValueError): load_calibration(tmp_path/'missing.json')
    with pytest.raises((ValueError, OSError)): load_crop_config(tmp_path/'missing.json')


def test_frame_has_raw_roi_coordinates_actual_bounds_and_conditional_uncertainty(tmp_path):
    from pearl.production.optics import CameraReader, Calibration
    image = np.zeros((800, 1200, 3), dtype=np.uint8)
    image[:100, :100] = [30, 20, 10]
    camera = SimpleNamespace(capture_raw=lambda **k: image.copy())
    reader = CameraReader(camera, setup(tmp_path), Calibration(), 0, tmp_path/'frames')
    origin = time.monotonic()
    first = reader.capture(['plate:A1'], clock=lambda: time.monotonic()-origin)
    second = reader.capture(['plate:A1'], clock=lambda: time.monotonic()-origin)
    m = first['measurements'][0]
    assert m['rgb'] == [10., 20., 30.]
    assert m['od_noise_sd_estimate'] == pytest.approx(0.0152003068666138)
    assert m['rgb_noise_sd_counts'] == 0.35
    assert 'assumed' in m['od_noise_basis']
    assert first['acquisition_started_at_s'] <= first['captured_at_s'] < second['captured_at_s']
    assert m['measurement_id'] != second['measurements'][0]['measurement_id']
    assert first['frame_id'] != second['frame_id']
    assert Path(first['frame_path']).is_file()
    assert m['calibration_source'] == 'defaults'


def test_default_optics_are_declared_assay_settings_and_blank_capture_overrides_reference():
    from pearl.production.optics import Calibration, build_blank_calibration
    default = Calibration().mapping()
    assert default['epsilon_M_cm'] == 39000. and default['path_length_cm_per_100uL'] == 0.28
    assert default['wavelength_nm'] == 652. and default['noise_sd_counts'] == 0.35
    assert default['quantitative_calibration'] is False
    with pytest.raises(ValueError): build_blank_calibration([(255, 255, 255)], binding={})
    data = build_blank_calibration([(200, 210, 220), (202, 212, 222)], binding={'camera_id': 0})
    c = Calibration.from_mapping(data)
    assert c.blank_rgb == (201., 211., 221.) and c.od((201., 211., 221.)) == pytest.approx(0.)
    with pytest.raises(ValueError): c.check_binding({'camera_id': 1})


def test_selected_camera_course_converts_nominal_rates_with_default_optics(tmp_path):
    from pearl.production.optics import CameraReader, Calibration
    from pearl.production.settings import validate_setup
    from pearl.production.backend import PhysicalBackend
    from pearl.runtime.agent_analysis import selected_course
    from pearl.runtime.blackboard import Blackboard
    from pearl.state.events import ObservationEvent, ToolCallEvent
    s = setup(tmp_path)
    data = setup_data(s.camera['crop_config'])
    data['reagents'] = {
        'A1': {'label': 'HRP', 'volume_ul': 2000, 'concentration_value': .003, 'concentration_unit': 'uM'},
        'A2': {'label': 'TMB', 'volume_ul': 5000, 'concentration_value': 5., 'concentration_unit': 'mM'},
        'A3': {'label': 'PBS', 'volume_ul': 15000, 'concentration_value': 1., 'concentration_unit': 'x'}}
    s = validate_setup(data)
    pixel = [120]
    camera = SimpleNamespace(capture_raw=lambda **kwargs: np.full((800,1200,3),pixel[0],dtype=np.uint8))
    reader = CameraReader(camera, s, Calibration(), 0, tmp_path/'frames')
    now = [0.]
    world = PhysicalBackend(s, Robot(), reader, monotonic=lambda: now[0])
    board = Blackboard()
    for well, volume in [('A3',49.),('A2',50.),('A1',1.)]:
        operation = action(source='reservoir:'+well, volume_ul=volume)
        result = world.execute(operation)
        board.publish(ToolCallEvent(source_agent='actor', tool_name='transfer',
            tool_call_id=operation.action_id, params=dict(operation.params),
            result={'ok':True,'observation':result.observation}, executed=True))
    evidence = {}
    for elapsed, value in [(10.,120),(20.,60)]:
        now[0] = elapsed; pixel[0] = value
        packet = world.capture_actual(['plate:A1'])
        board.publish(ObservationEvent(source_agent='actor', observation_type='camera', payload=packet))
        evidence.update({m['measurement_id']: m for m in packet['measurements']})
    args = {'location':'plate:A1', 'interval_basis':{'basis':'after_preparation_change','rationale':'Observed course'},
        'from_measurement_id':None, 'through_measurement_id':None,
        'blank_measurement_ids':[], 'blank_correction':'none',
        'substrate_stock':'reservoir:A2','enzyme_stock':'reservoir:A1'}
    result = selected_course(args, evidence, board.event_log, world.briefing())
    assert result['slope_od_per_s'] == pytest.approx(0.03010299956639812)
    assert result['v0_uM_per_s'] == pytest.approx(2.75668494197785)
    assert result['nominal_conditions']['substrate_uM'] == pytest.approx(2500.)
    assert result['nominal_conditions']['enzyme_nM'] == pytest.approx(.03)
    assert result['scientific_acceptance'] is None
    assert result['uncertainty']['slope_se_od_per_s'] is None
    assert result['readout_precision']['noise_rate_sd_uM_per_s'] > 0


def test_selected_calibration_overrides_assumptions_without_changing_raw_signal():
    from pearl.production.optics import Calibration
    c = Calibration.from_mapping({'blank_rgb':[200,200,200], 'gamma':2.,
        'noise_sd_counts':None, 'optical_constants':{'epsilon_M_cm':20000.,
        'path_length_cm_per_100uL':.5,'wavelength_nm':600.}})
    assert c.od((100,100,100)) == pytest.approx(.6020599913279624)
    assert c.od_noise_sd((100,100,100)) is None
    assert c.mapping()['epsilon_M_cm'] == 20000.
    inherited = Calibration.from_mapping({'blank_rgb':[200,200,200]})
    assert inherited.mapping()['path_length_cm_per_100uL'] == .28


@pytest.mark.parametrize('value', [True, -1., float('nan'), float('inf'), '0.35'])
def test_readout_noise_requires_a_finite_nonnegative_assumption(value):
    from pearl.production.optics import Calibration
    with pytest.raises(ValueError):
        Calibration.from_mapping({'blank_rgb':[200,200,200], 'noise_sd_counts':value})



def test_mix_selects_matching_pipette_before_tip_pickup(tmp_path, monkeypatch):
    from pearl.production.connection import VerifiedOT2
    from pearl.production.backend import PhysicalBackend
    from pearl.production.optics import Calibration
    s = setup(tmp_path)
    robot = VerifiedOT2('192.168.1.2', s.deck)
    robot._run_id = 'run'; robot.identity = {'robot_model': 'OT-2'}
    robot._pipette_id = 'primary'; robot._secondary_pipette_id = 'secondary'
    robot._labware_ids = {'plate': 'plate', 'tiprack': 'tips', 'secondary_tiprack': 'small-tips'}
    commands = []
    def send(kind, params):
        commands.append((kind, params))
        return {'data': {'id': str(len(commands)), 'status': 'succeeded'}}
    monkeypatch.setattr(robot, '_send_setup_command', send)
    world = PhysicalBackend(s, robot, SimpleNamespace(calibration=Calibration()))
    world.inventory['plate:A1'] = 50
    result = world.execute(action('mix', location='plate:A1', volume_ul=10))
    assert result.ok
    pickup = next(p for name, p in commands if name == 'pickUpTip')
    aspirates = [p for name, p in commands if name == 'aspirate']
    assert pickup['pipetteId'] == 'secondary' and pickup['labwareId'] == 'small-tips'
    assert all(p['pipetteId'] == 'secondary' for p in aspirates)


def test_mixing_stroke_cannot_exceed_single_pipette_capacity(tmp_path):
    world = backend(tmp_path); world.inventory['reservoir:A1'] = 1000
    with pytest.raises(ValueError):
        world.validate_action(action('mix', location='reservoir:A1', volume_ul=500))


def test_camera_stop_winning_during_transfer_cannot_commit_inventory(tmp_path):
    world = backend(tmp_path)
    before = deepcopy(world.inventory)
    def interrupted(**kwargs):
        world._failed = True
        world.robot.stop()
    world.robot.transfer_liquid = interrupted
    with pytest.raises(RuntimeError): world.execute(action())
    assert world.inventory == before
    assert world.command_log[-1]['status'] == 'uncertain_or_failed'


def test_complete_operation_inside_capture_is_preserved_as_overlap(tmp_path):
    import threading
    world = backend(tmp_path)
    entered, release = threading.Event(), threading.Event()
    packets = []
    def capture(locations, *, clock):
        start = clock(); entered.set()
        assert release.wait(2.)
        return {'frame_id': 'f', 'acquisition_started_at_s': start, 'captured_at_s': clock(),
                'measurements': [{'measurement_id': 'm', 'location': 'plate:A1'}]}
    world.reader.capture = capture
    thread = threading.Thread(target=lambda: packets.append(world.capture_actual(['plate:A1'])))
    thread.start()
    try:
        assert entered.wait(2.)
        world.execute(action())
    finally:
        release.set(); thread.join(2.)
    assert packets[0]['overlapping_action_ids'] == ['a']
    assert packets[0]['measurements'][0]['overlapping_action_ids'] == ['a']


@pytest.mark.parametrize('level', ['slot', 'deck', 'well'])
def test_noncontained_crop_is_rejected_at_every_level(tmp_path, level):
    from pearl.eyes.deck_scanner import load_crop_config
    row = {'x': .5, 'y': 0, 'w': .75, 'h': .5}
    data = {'slots': {'2': {'x': 0, 'y': 0, 'w': 1, 'h': 1}}}
    if level == 'slot': data['slots']['2'] = row
    if level == 'deck': data['deck_region'] = row
    if level == 'well': data['slots']['2']['well_area'] = row
    p = tmp_path/'invalid.json'; p.write_text(json.dumps(data))
    with pytest.raises(ValueError): load_crop_config(p)


def test_effective_camera_binding_detects_changed_readback_with_same_requested_settings(tmp_path):
    from pearl.production.optics import CameraReader, Calibration
    state = {'auto_exposure': 1., 'exposure': -5., 'auto_white_balance': 0.,
             'white_balance': 4500., 'auto_focus': 0., 'focus': 50., 'manual_controls_verified': True}
    camera = SimpleNamespace(capture_raw=lambda **k: np.full((800,1200,3),200,dtype=np.uint8),
                             readback=lambda: deepcopy(state))
    s = setup(tmp_path)
    reader = CameraReader(camera, s, Calibration(), 0, tmp_path/'first')
    assert reader.binding.get('effective_camera_state') == state
    cal = Calibration.from_mapping({'blank_rgb': [200,200,200], 'binding': reader.binding}, source='file')
    state['exposure'] = -4.
    with pytest.raises(ValueError): CameraReader(camera, s, cal, 0, tmp_path/'second')


def test_unknown_effective_camera_settings_do_not_authorize_calibrated_reuse(tmp_path):
    from pearl.production.optics import CameraReader, Calibration
    camera = SimpleNamespace(capture_raw=lambda **k: np.full((800,1200,3),200,dtype=np.uint8))
    s = setup(tmp_path)
    default = CameraReader(camera, s, Calibration(), 0, tmp_path/'default')
    assert default.binding.get('effective_camera_state') is None
    cal = Calibration.from_mapping({'blank_rgb': [200,200,200], 'binding': default.binding}, source='file')
    with pytest.raises(ValueError): CameraReader(camera, s, cal, 0, tmp_path/'second')


def test_camera_driver_readback_keeps_ignored_manual_lock_visible():
    import cv2
    from pearl.eyes.camera import PlateCamera
    values = {cv2.CAP_PROP_AUTO_EXPOSURE: 3., cv2.CAP_PROP_EXPOSURE: -4.,
              cv2.CAP_PROP_AUTO_WB: 1., cv2.CAP_PROP_WB_TEMPERATURE: 5000.,
              cv2.CAP_PROP_AUTOFOCUS: 1., cv2.CAP_PROP_FOCUS: 20.}
    camera = PlateCamera()
    camera._cap = SimpleNamespace(get=lambda key: values.get(key, 0.))
    state = camera.readback()
    assert state['exposure'] == -4. and state['white_balance'] == 5000.
    assert state['manual_controls_verified'] is False


def test_nonempty_but_unusable_pixel_grid_fails_before_model_admission(tmp_path):
    from pearl.production.optics import CameraReader, Calibration
    s = setup(tmp_path)
    p = Path(s.camera['crop_config']); data = json.loads(p.read_text())
    data['slots']['2']['w'] = .001
    p.write_text(json.dumps(data))
    camera = SimpleNamespace(capture_raw=lambda **k: np.full((800,1200,3),200,dtype=np.uint8))
    with pytest.raises(ValueError): CameraReader(camera, s, Calibration(), 0, tmp_path/'frames')


def test_unsupported_zero_camera_readback_is_not_verified_manual_control():
    from pearl.eyes.camera import PlateCamera
    camera = PlateCamera()
    camera._cap = SimpleNamespace(get=lambda key: 0.)
    assert camera.readback()['manual_controls_verified'] is False


def test_unconfirmed_stop_blocks_remaining_low_level_transfer_commands(tmp_path, monkeypatch):
    from pearl.production.connection import VerifiedOT2
    from pearl.production.backend import PhysicalBackend
    from pearl.production.optics import Calibration
    s = setup(tmp_path)
    robot = VerifiedOT2('192.168.1.2', s.deck)
    robot._run_id = 'r'; robot.identity = {'robot_model':'OT-2'}
    robot._pipette_id = 'p'; robot._secondary_pipette_id = 'small'
    robot._labware_ids = {'plate':'plate','reservoir':'reservoir','tiprack':'tips','secondary_tiprack':'small-tips'}
    world = PhysicalBackend(s, robot, SimpleNamespace(calibration=Calibration()))
    commands = []
    def request(method, path, json=None):
        if path.endswith('/actions'):
            raise RuntimeError('stop acknowledgement lost')
        kind = json['data']['commandType']; commands.append(kind)
        if kind == 'aspirate': world.latch_failure('camera disconnected')
        return {'data':{'id':'c','status':'succeeded'}}
    monkeypatch.setattr(robot, '_request', request)
    with pytest.raises(RuntimeError): world.execute(action())
    assert commands == ['pickUpTip', 'aspirate']
    assert robot.failed and world._failed and world.inventory['plate:A1'] == 0


def test_changed_frame_geometry_cannot_reuse_stale_crop_binding(tmp_path):
    from pearl.production.optics import CameraReader, Calibration
    images = iter([np.full((800,1200,3),200,dtype=np.uint8), np.full((400,600,3),200,dtype=np.uint8)])
    camera = SimpleNamespace(capture_raw=lambda **k: next(images))
    reader = CameraReader(camera, setup(tmp_path), Calibration(), 0, tmp_path/'frames')
    with pytest.raises((ValueError,RuntimeError)):
        reader.capture(['plate:A1'], clock=lambda: time.monotonic())
    diagnostic = json.loads((tmp_path/'frames/captures.jsonl').read_text().splitlines()[-1])
    assert diagnostic['status'] == 'unusable' and Path(diagnostic['frame_path']).is_file()
