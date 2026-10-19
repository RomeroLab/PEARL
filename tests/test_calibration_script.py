import json
from types import SimpleNamespace
import pytest


def test_standalone_capture_builds_explicit_json_consumable_by_execution(tmp_path):
    from pearl.production.calibration_cli import capture_blank, save_calibration
    from pearl.production.optics import load_calibration
    calls = []
    state = {'manual_controls_verified':True,'exposure':-4.}
    reader = SimpleNamespace(binding={'camera_id': 2, 'effective_camera_state': state})
    def capture(locations, **kwargs):
        calls.append(locations)
        return {'frame_path': 'frame.png', 'effective_camera_state_before':state,
                'effective_camera_state_after':state, 'measurements': [
            {'location': l, 'rgb': [200., 210., 220.]} for l in locations]}
    reader.capture = capture
    data = capture_blank(reader, ['A1', 'A2'], samples=2)
    assert calls == [['plate:A1','plate:A2'], ['plate:A1','plate:A2']]
    p = tmp_path/'blank.json'; save_calibration(p, data)
    c = load_calibration(p)
    assert c.blank_rgb == (200.,210.,220.) and c.binding == {'camera_id': 2, 'effective_camera_state': state}
    assert load_calibration(None).od((120.,120.,120.)) == pytest.approx(0.3010299956639812)
    with pytest.raises(FileExistsError): save_calibration(p, data)


def test_blank_capture_preserves_readout_noise_assumption():
    from pearl.production.calibration_cli import capture_blank
    state = {'manual_controls_verified':True,'exposure':-4.}
    reader = SimpleNamespace(binding={'effective_camera_state':state}, capture=lambda *a, **k: {
        'effective_camera_state_before':state,'effective_camera_state_after':state,
        'frame_path': 'p.png', 'measurements': [{'rgb': [201., 211., 221.]}]})
    data = capture_blank(reader, ['A1'], samples=1)
    assert data['noise_sd_counts'] == 0.35
    assert data['optical_constants'] == {'epsilon_M_cm': 39000.,
        'path_length_cm_per_100uL': 0.28, 'wavelength_nm': 652.}
    with pytest.raises(ValueError): capture_blank(reader, ['A1'], samples=0)


def test_blank_series_rejects_camera_state_change_after_initial_admission():
    from copy import deepcopy
    from pearl.production.calibration_cli import capture_blank
    expected = {'manual_controls_verified': True, 'exposure': -4., 'white_balance': 4500., 'focus': 50.}
    calls = []
    def capture(*a, **k):
        state = deepcopy(expected)
        if calls: state['exposure'] = -3.
        calls.append(True)
        return {'frame_path': 'p.png', 'measurements': [{'rgb':[200,210,220]}],
            'effective_camera_state_before': state, 'effective_camera_state_after': state}
    reader = SimpleNamespace(binding={'effective_camera_state':expected}, capture=capture)
    with pytest.raises(ValueError): capture_blank(reader, ['A1'], samples=2)


def test_blank_series_rejects_mode_change_within_one_capture():
    from pearl.production.calibration_cli import capture_blank
    expected = {'manual_controls_verified': True, 'exposure': -4.}
    reader = SimpleNamespace(binding={'effective_camera_state':expected}, capture=lambda *a, **k: {
        'frame_path':'p.png','measurements':[{'rgb':[200,210,220]}],
        'effective_camera_state_before':expected,
        'effective_camera_state_after':{'manual_controls_verified':False,'exposure':-4.}})
    with pytest.raises(ValueError): capture_blank(reader, ['A1'], samples=1)
