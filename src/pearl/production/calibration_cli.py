"""Standalone raw blank capture, without robot motion or model access."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4
from pearl.production.settings import load_setup, wells
from pearl.production.connection import open_camera, select_camera
from pearl.production.optics import Calibration, CameraReader, build_blank_calibration, DEFAULT_OPTICAL_CONSTANTS, DEFAULT_NOISE_SD_COUNTS


def capture_blank(reader, blank_wells, *, samples=5, channel_weights=(1.,0.,0.), gamma=1.,
                  noise_sd_counts=DEFAULT_NOISE_SD_COUNTS):
    if type(samples) is not int or samples < 1:
        raise ValueError('Positive integer sample count required')
    expected_state = deepcopy(reader.binding.get('effective_camera_state'))
    if not isinstance(expected_state, dict) or expected_state.get('manual_controls_verified') is not True:
        raise ValueError('A verified effective manual camera state is required for blank calibration')
    observations = []; frames = []
    origin = time.monotonic()
    for _ in range(samples):
        packet = reader.capture(['plate:'+w for w in blank_wells], clock=lambda: time.monotonic()-origin)
        if any(packet.get(key) != expected_state for key in ('effective_camera_state_before', 'effective_camera_state_after')):
            raise ValueError('Effective camera settings changed during blank acquisition; no reusable calibration created')
        observations.extend(m['rgb'] for m in packet['measurements'])
        frames.append(packet['frame_path'])
    data = build_blank_calibration(observations, binding=reader.binding, channel_weights=channel_weights,
                                   gamma=gamma, noise_sd_counts=noise_sd_counts)
    return {**data, 'blank_wells': list(blank_wells), 'frames': frames}


def save_calibration(path, data):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    Calibration.from_mapping(data)
    with p.open('x') as f:
        json.dump(data, f, indent=2, allow_nan=False); f.write('\n')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--setup', type=Path, required=True)
    p.add_argument('--scenario', choices=[f'S{i}' for i in range(1,9)])
    p.add_argument('--camera', type=int)
    p.add_argument('--blank-wells', default='A1')
    p.add_argument('--samples', type=int, default=5)
    p.add_argument('--weights', type=float, nargs=3, default=[1.,0.,0.], metavar=('R','G','B'))
    p.add_argument('--gamma', type=float, default=1.)
    p.add_argument('--noise-sd-counts', type=float, default=DEFAULT_NOISE_SD_COUNTS,
                   help='Assumed readout noise SD in camera counts')
    p.add_argument('--epsilon', type=float, default=DEFAULT_OPTICAL_CONSTANTS['epsilon_M_cm'],
                   help='Declared extinction coefficient in M^-1 cm^-1')
    p.add_argument('--path-length-per-100ul', type=float, default=DEFAULT_OPTICAL_CONSTANTS['path_length_cm_per_100uL'],
                   help='Declared optical path in cm per 100 uL')
    p.add_argument('--wavelength', type=float, default=DEFAULT_OPTICAL_CONSTANTS['wavelength_nm'],
                   help='Declared assay optical reference wavelength in nm')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv); camera = None
    try:
        setup = load_setup(a.setup, a.scenario)
        selected_wells = wells(a.blank_wells)
        if not set(selected_wells) <= set(setup.plate_wells):
            raise ValueError('Blank wells are absent from the configured plate')
        if a.output.exists(): raise FileExistsError('Select a new calibration output path')
        build_blank_calibration([(200,200,200)], binding={}, channel_weights=a.weights,
                                gamma=a.gamma, noise_sd_counts=a.noise_sd_counts)
        constants = {'epsilon_M_cm': a.epsilon, 'path_length_cm_per_100uL': a.path_length_per_100ul,
                     'wavelength_nm': a.wavelength}
        Calibration.from_mapping({'blank_rgb': [200,200,200], 'optical_constants': constants})
        if a.samples < 1: raise ValueError('samples must be positive')
        index = select_camera(a.camera)
        print('Prepare the assay blank in the selected wells using the intended plate, volume, lighting and camera settings.')
        if input('Enter READY when the blank is prepared: ').strip() != 'READY':
            raise RuntimeError('Blank preparation was not confirmed')
        folder = a.output.resolve().parent/(a.output.stem+'_captures_'+uuid4().hex[:8])
        camera = open_camera(index, setup.camera, folder)
        reader = CameraReader(camera, setup, Calibration(), index, folder)
        state = reader.binding.get('effective_camera_state')
        if not isinstance(state, dict) or state.get('manual_controls_verified') is not True:
            raise ValueError('Camera manual settings could not be verified; blank calibration cannot be bound for reuse')
        data = capture_blank(reader, selected_wells, samples=a.samples, channel_weights=a.weights,
                              gamma=a.gamma, noise_sd_counts=a.noise_sd_counts)
        data['optical_constants'] = constants
        save_calibration(a.output, data)
        print(f'Calibration saved to {a.output}. Select it explicitly with --calibration.'); return 0
    except (EOFError,KeyboardInterrupt):
        print('\nCalibration stopped.'); return 130
    except Exception as exc:
        print(f'Calibration stopped: {exc}'); return 1
    finally:
        if camera is not None: camera.release()
