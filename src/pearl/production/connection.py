"""Real OT-2 admission and latched, non-retryable command failures."""
from __future__ import annotations
import json
import time
from pathlib import Path
from datetime import datetime, timezone
import requests
from pearl.body.ot2_client import OT2HttpClient
from pearl.production.settings import robot_ip

class HardwareStopped(RuntimeError):
    pass

def probe_robot(host: str, *, get=None) -> dict:
    address = robot_ip(host)
    formatted = f'[{address}]' if ':' in address else address
    try:
        response = (get or requests.get)(f'http://{formatted}:31950/health', timeout=5, headers={'opentrons-version': '*'}, allow_redirects=False)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError('Invalid health response format')
        if data.get('robot_model') not in ('OT-2 Standard', 'OT-2'):
            raise ValueError('The device did not identify itself as an OT-2.')
        if any((data.get(k) not in (None, False) for k in ('is_simulator', 'isSimulator', 'simulation', 'simulate'))):
            raise ValueError('Simulators are not supported.')
        for key in ('robot_serial', 'fw_version', 'board_revision', 'api_version'):
            if not isinstance(data.get(key), str) or not data[key].strip() or data[key].lower() in ('unknown', 'none', 'simulator'):
                raise ValueError(f'Missing device identity: {key}')
        return data
    except Exception as exc:
        raise ConnectionError(f'OT-2 connection or identity check failed ({address}): {exc}') from exc

class VerifiedOT2(OT2HttpClient):

    def __init__(self, host, deck_layout, *, receipt_path: Path | None=None):
        address = robot_ip(host)
        super().__init__(f'[{address}]' if ':' in address else address, deck_layout=deck_layout, timeout=120.0)
        self.host = address
        self.failed = False
        self.receipt_path = receipt_path
        self.identity = None
        self.transfer_dispense_times = []

    def _log(self, row):
        if self.receipt_path:
            self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
            with self.receipt_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), **row}, default=str) + '\n')

    def connect(self):
        if self.failed:
            raise HardwareStopped('A session cannot resume after a hardware error.')
        self.identity = probe_robot(self.host)
        self._log({'kind': 'health', 'identity': self.identity})
        try:
            return super().connect()
        except Exception as exc:
            self.failed = True
            self.stop()
            raise HardwareStopped(f'OT-2 initialization failed: {exc}') from exc

    def _send_setup_command(self, command_type, params):
        if self.failed:
            raise HardwareStopped('Execution is stopped after a hardware error.')
        params = dict(params)
        if command_type == 'aspirate':
            labware = next((name for name, value in self._labware_ids.items() if value == params.get('labwareId')), None)
            if labware not in ('plate', 'reservoir'):
                raise ValueError('Unknown aspiration labware')
            params['wellLocation'] = {'origin': 'bottom', 'offset': {'x': 0, 'y': 0, 'z': {'plate': 0.5, 'reservoir': 1.0}[labware] + self._z_offset}}
        if command_type == 'loadPipette':
            params['pipetteName'] = params['pipetteName'] + '_gen2'
        if command_type == 'pickUpTip':
            params.pop('wellLocation', None)
        self._log({'kind': 'command_requested', 'command': command_type, 'params': params})
        try:
            result = super()._send_setup_command(command_type, params)
            data = result.get('data', {})
            if not data.get('id') or data.get('status') != 'succeeded':
                raise RuntimeError(f"Command completion could not be confirmed: {data.get('status')}")
            if command_type == 'dispense':
                self.transfer_dispense_times.append(time.monotonic())
            self._log({'kind': 'command_completed', 'command': command_type, 'receipt': data, 'receipt_monotonic_s': time.monotonic()})
            return result
        except Exception as exc:
            self.failed = True
            self._log({'kind': 'command_uncertain_or_failed', 'command': command_type, 'error': str(exc)})
            self.stop()
            raise HardwareStopped(f'{command_type} failed or completion is unknown. Stopping without retry: {exc}') from exc

    def transfer_liquid(self, *args, **kwargs):
        self.transfer_dispense_times = []
        return super().transfer_liquid(*args, **kwargs)

    def stop(self):
        if self._run_id:
            try:
                self._request('POST', f'/runs/{self._run_id}/actions', json={'data': {'actionType': 'stop'}})
                self._log({'kind': 'stop_requested'})
            except Exception as exc:
                self._log({'kind': 'stop_unconfirmed', 'error': str(exc)})

def list_cameras(limit: int=10, *, capture_factory=None) -> list[dict]:
    import cv2
    factory = capture_factory or cv2.VideoCapture
    found = []
    for index in range(limit):
        camera = factory(index)
        try:
            if camera.isOpened():
                ok, frame = camera.read()
                if ok and frame is not None:
                    found.append({'index': index, 'width': int(frame.shape[1]), 'height': int(frame.shape[0])})
        finally:
            camera.release()
    return found

def select_camera(index: int | None, *, input_fn=input, print_fn=print) -> int:
    if index is not None:
        if index < 0:
            raise ValueError('The camera index must be nonnegative.')
        return index
    found = list_cameras()
    if not found:
        raise RuntimeError('No attached camera could provide a frame.')
    for row in found:
        print_fn(f"Camera {row['index']}: {row['width']} × {row['height']}")
    selected = int(input_fn('Select a camera index: '))
    if selected not in [r['index'] for r in found]:
        raise ValueError('Select a camera index from the list.')
    return selected

def open_camera(index, settings, output):
    from pearl.eyes.camera import PlateCamera
    camera = PlateCamera(camera_id=index, output_dir=output, fixed_focus=settings.get('focus', 50), fixed_exposure=settings.get('exposure', -1), fixed_wb=settings.get('white_balance', 4500))
    try:
        if not camera.initialize():
            raise RuntimeError(f'Camera {index} initialization failed')
        admission = camera.capture_raw()
        if admission is None:
            raise RuntimeError(f'Camera {index} frame check failed')
        camera.admission_frame_shape = tuple(admission.shape)
        return camera
    except BaseException:
        camera.release()
        raise
