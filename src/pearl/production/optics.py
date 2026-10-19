"""Raw camera observations and explicitly selected fixed blank correction."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4
import threading

DEFAULT_OPTICAL_CONSTANTS = {'epsilon_M_cm': 39000.,
                             'path_length_cm_per_100uL': .28, 'wavelength_nm': 652.}
DEFAULT_NOISE_SD_COUNTS = .35
NOISE_BASIS = ('Conditional propagation of assumed independent channel count noise '
               'with fixed blank, dark and gamma; excludes calibration and preparation uncertainty.')


def triple(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError(f'{name} requires three finite RGB numbers')
    return tuple(float(v) for v in value)


@dataclass(frozen=True)
class Calibration:
    blank_rgb: tuple = (240., 240., 240.)
    dark_rgb: tuple = (0., 0., 0.)
    channel_weights: tuple = (1., 0., 0.)
    gamma: float = 1.
    binding: dict = field(default_factory=dict)
    source: str = 'defaults'
    optical_constants: dict = field(default_factory=lambda: dict(DEFAULT_OPTICAL_CONSTANTS))
    noise_sd_counts: float | None = DEFAULT_NOISE_SD_COUNTS

    @classmethod
    def from_mapping(cls, data, *, source='calibration'):
        if not isinstance(data, dict):
            raise ValueError('Calibration must be a JSON object')
        blank = triple(data.get('blank_rgb'), 'blank_rgb')
        dark = triple(data.get('dark_rgb', [0, 0, 0]), 'dark_rgb')
        weights = triple(data.get('channel_weights', [1, 0, 0]), 'channel_weights')
        gamma = data.get('gamma', 1.)
        if any(not 0 <= d < b <= 255 for b, d in zip(blank, dark)):
            raise ValueError('Each channel requires 0 <= dark < blank <= 255')
        if min(weights) < 0 or sum(weights) <= 0:
            raise ValueError('Nonnegative channel weights with positive sum required')
        if type(gamma) not in (int, float) or not math.isfinite(gamma) or gamma <= 0:
            raise ValueError('Positive finite gamma required')
        binding = data.get('binding', {})
        constants = data.get('optical_constants', {})
        if not isinstance(binding, dict) or not isinstance(constants, dict):
            raise ValueError('Calibration binding and optical_constants must be objects')
        constants = {**DEFAULT_OPTICAL_CONSTANTS, **constants}
        for k in ('epsilon_M_cm', 'path_length_cm_per_100uL', 'wavelength_nm'):
            if constants.get(k) is not None and (type(constants[k]) not in (int, float) or
                not math.isfinite(constants[k]) or constants[k] <= 0):
                raise ValueError(f'{k} must be positive finite or null')
        noise = data.get('noise_sd_counts', DEFAULT_NOISE_SD_COUNTS)
        if noise is not None and (type(noise) not in (int, float) or not math.isfinite(noise) or noise < 0):
            raise ValueError('noise_sd_counts must be finite nonnegative or null')
        return cls(blank, dark, weights, float(gamma), binding, source, constants, noise)

    def check_binding(self, actual):
        for key, value in self.binding.items():
            if actual.get(key) != value:
                raise ValueError(f'Calibration does not match camera setting: {key}')

    def od(self, rgb):
        rgb = triple(rgb, 'sample_rgb')
        if any(not 0 <= v <= 255 for v in rgb):
            raise ValueError('Sample RGB must lie in 0..255')
        signal = sum(w * max(0., (v-d)/255.)**self.gamma for v, d, w in zip(rgb, self.dark_rgb, self.channel_weights))
        reference = sum(w * ((b-d)/255.)**self.gamma for b, d, w in zip(self.blank_rgb, self.dark_rgb, self.channel_weights))
        if signal <= 0:
            return None
        return -math.log10(signal/reference)

    def correct_rgb(self, rgb):
        return tuple(round(min(255., max(0., 255*(v-d)/(b-d))))
                     for v, b, d in zip(triple(rgb, 'sample_rgb'), self.blank_rgb, self.dark_rgb))

    def od_noise_sd(self, rgb):
        if self.noise_sd_counts is None:
            return None
        rgb = triple(rgb, 'sample_rgb')
        if any(not 0 <= v <= 255 for v in rgb):
            raise ValueError('Sample RGB must lie in 0..255')
        channels = [((v-d)/255., w) for v, d, w in zip(rgb, self.dark_rgb, self.channel_weights) if w > 0]
        if any(r <= 0 for r, w in channels):
            return None
        signal = sum(w * r**self.gamma for r, w in channels)
        derivatives = [w*self.gamma*r**(self.gamma-1)/255. for r, w in channels]
        return self.noise_sd_counts * math.hypot(*derivatives) / (math.log(10)*signal)

    def mapping(self):
        return {'blank_rgb': list(self.blank_rgb), 'dark_rgb': list(self.dark_rgb),
                'channel_weights': list(self.channel_weights), 'gamma': self.gamma,
                'od_channel': next((i for i, w in enumerate(self.channel_weights) if w > 0), None)
                              if sum(w > 0 for w in self.channel_weights) == 1 else None,
                'epsilon_M_cm': self.optical_constants.get('epsilon_M_cm'),
                'path_length_cm_per_100uL': self.optical_constants.get('path_length_cm_per_100uL'),
                'wavelength_nm': self.optical_constants.get('wavelength_nm'),
                'noise_sd_counts': self.noise_sd_counts, 'noise_basis': NOISE_BASIS,
                'source': self.source, 'quantitative_calibration': False,
                'basis': 'Fixed camera blank ratio with declared optical constants and conditional readout-noise propagation.'}


def load_calibration(path):
    if path is None:
        return Calibration()
    try:
        return Calibration.from_mapping(json.loads(Path(path).expanduser().read_text()), source=str(Path(path).resolve()))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f'Cannot use the selected calibration file: {path}: {exc}') from exc


def build_blank_calibration(samples, *, binding, channel_weights=(1., 0., 0.), gamma=1.,
                            noise_sd_counts=DEFAULT_NOISE_SD_COUNTS):
    if not samples:
        raise ValueError('Blank samples required')
    rows = [triple(s, 'blank sample') for s in samples]
    if any(any(v < 5 or v >= 250 for v in r) for r in rows):
        raise ValueError('Blank is too dark or clipped; adjust exposure or lighting')
    data = {'blank_rgb': [sum(r[i] for r in rows)/len(rows) for i in range(3)],
            'dark_rgb': [0, 0, 0], 'channel_weights': list(channel_weights),
            'gamma': gamma, 'binding': binding, 'blank_samples_rgb': rows,
            'method': 'Fixed blank ratio; camera-derived optical density',
            'noise_sd_counts': noise_sd_counts, 'noise_basis': NOISE_BASIS,
            'optical_constants': dict(DEFAULT_OPTICAL_CONSTANTS)}
    Calibration.from_mapping(data)
    return data


class CameraReader:
    def __init__(self, camera, setup, calibration, camera_id, output):
        from pearl.eyes.deck_scanner import load_crop_config
        self.camera, self.setup, self.calibration = camera, setup, calibration
        self.output = Path(output); self.output.mkdir(parents=True, exist_ok=True)
        p = Path(setup.camera['crop_config'])
        self.crop = load_crop_config(p)
        for slot in (setup.deck.plate_slot, setup.deck.reservoir_slot):
            if slot not in self.crop.slots:
                raise ValueError(f'Camera crop lacks configured slot {slot}')
        self.binding = {'camera_id': camera_id, 'crop_sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                        'focus': setup.camera.get('focus', 50), 'exposure': setup.camera.get('exposure', -1),
                        'white_balance': setup.camera.get('white_balance', 4500)}
        self.binding['effective_camera_state'] = self.camera_state()
        self.binding['frame_shape'] = list(self.validate_geometry())
        self.validate_binding(self.binding['effective_camera_state'])
        self.lock = threading.Lock()
        self.last_frame = None

    def camera_state(self):
        readback = getattr(self.camera, 'readback', None)
        return readback() if callable(readback) else None

    def validate_binding(self, state):
        if self.calibration.source != 'defaults':
            saved = self.calibration.binding.get('effective_camera_state')
            if not isinstance(saved, dict) or saved.get('manual_controls_verified') is not True:
                raise ValueError('Selected calibration lacks a verified effective camera state')
            if not isinstance(state, dict) or state.get('manual_controls_verified') is not True:
                raise ValueError('Effective manual camera settings are unknown or automatic; calibrated reuse is unsupported')
        self.calibration.check_binding({**self.binding, 'effective_camera_state': state})

    def validate_geometry(self):
        import numpy as np
        shape = getattr(self.camera, 'admission_frame_shape', None)
        if shape is None:
            frame = self.camera.capture_raw(n_frames=1)
            if frame is None:
                raise ValueError('No camera readiness frame available for crop validation')
            shape = frame.shape
        if len(shape) != 3 or shape[2] != 3 or shape[0] <= 0 or shape[1] <= 0:
            raise ValueError('Camera readiness image must have three channels')
        geometry = np.empty(shape, dtype=np.uint8)
        for labware, wells in (('plate', self.setup.plate_wells), ('reservoir', self.setup.reagents)):
            slot = self.setup.deck.plate_slot if labware == 'plate' else self.setup.deck.reservoir_slot
            cropped = self.crop.crop_slot(geometry, slot)
            nr = 8 if labware == 'plate' else 1
            h, w = cropped.shape[:2]
            for well in wells:
                r, c = ord(well[0])-65, int(well[1:])-1
                if round((r+.75)*h/nr) <= round((r+.25)*h/nr) or round((c+.75)*w/12) <= round((c+.25)*w/12):
                    raise ValueError('Camera crop does not resolve the configured well grid')
        return shape

    def capture(self, locations, *, clock):
        import cv2
        import numpy as np
        with self.lock:
            before_state = self.camera_state()
            self.validate_binding(before_state)
            start = clock()
            image = self.camera.capture_raw(n_frames=1)
            end = clock()
            after_state = self.camera_state()
            if image is None or image.ndim != 3 or image.shape[2] != 3 or not image.size:
                raise RuntimeError('No raw camera frame acquired')
            frame_id = uuid4().hex; path = self.output / (frame_id+'.png')
            if not cv2.imwrite(str(path), image):
                raise RuntimeError('Cannot preserve the raw camera frame')
            self.last_frame = str(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            try:
                if list(image.shape) != self.binding['frame_shape']:
                    raise ValueError('Actual camera frame geometry changed from its crop binding')
                self.validate_binding(after_state)
            except ValueError as exc:
                diagnostic = {'frame_id': frame_id, 'frame_path': str(path), 'frame_sha256': digest,
                    'acquisition_started_at_s': start, 'captured_at_s': end,
                    'actual_frame_shape': list(image.shape), 'binding': dict(self.binding),
                    'effective_camera_state_before': before_state, 'effective_camera_state_after': after_state,
                    'status': 'unusable', 'error': str(exc)}
                with (self.output/'captures.jsonl').open('a') as f:
                    f.write(json.dumps(diagnostic, allow_nan=False)+'\n')
                raise
            rows = []
            for location in locations:
                labware, well = location.split(':')
                if labware not in ('plate', 'reservoir') or well not in (
                    self.setup.plate_wells if labware == 'plate' else self.setup.reagents):
                    raise ValueError('Requested location absent from declared setup')
                slot = self.setup.deck.plate_slot if labware == 'plate' else self.setup.deck.reservoir_slot
                crop = self.crop.crop_slot(image, slot)
                nr, nc = (8, 12) if labware == 'plate' else (1, 12)
                r, c = ord(well[0])-65, int(well[1:])-1
                h, w = crop.shape[:2]; dh, dw = h/nr, w/nc
                roi = crop[round((r+.25)*dh):round((r+.75)*dh), round((c+.25)*dw):round((c+.75)*dw)]
                if not roi.size:
                    raise RuntimeError('Empty camera ROI; check crop configuration')
                b, g, red = np.mean(roi.reshape(-1, 3), axis=0)
                rgb = [float(red), float(g), float(b)]
                clipped = bool(np.any((roi == 0) | (roi == 255)))
                rows.append({'measurement_id': uuid4().hex, 'location': location,
                    'captured_at_s': end, 'acquisition_started_at_s': start,
                    'rgb': rgb, 'raw_rgb': list(rgb), 'hex': '#'+''.join(f'{round(v):02x}' for v in rgb),
                    'corrected_rgb': list(self.calibration.correct_rgb(rgb)), 'clipped': clipped,
                    'od_estimate': self.calibration.od(rgb),
                    'od_noise_sd_estimate': None if clipped else self.calibration.od_noise_sd(rgb),
                    'rgb_noise_sd_counts': self.calibration.noise_sd_counts, 'od_noise_basis': NOISE_BASIS,
                    'frame_id': frame_id, 'frame_sha256': digest, 'rgb_quantization_step_counts': 1,
                    'calibration_source': self.calibration.source})
            packet = {'frame_id': frame_id, 'frame_path': str(path), 'frame_sha256': digest,
                'acquisition_started_at_s': start, 'captured_at_s': end,
                'capture_duration_s': end-start, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                'acquisition_mode': 'physical_camera', 'sampling': 'single raw frame; center ROI mean; BGR to RGB',
                'binding': dict(self.binding), 'effective_camera_state_before': before_state,
                'effective_camera_state_after': after_state, 'measurements': rows,
                'evidence_ids': [r['measurement_id'] for r in rows]}
            with (self.output/'captures.jsonl').open('a') as f:
                f.write(json.dumps(packet, allow_nan=False)+'\n')
            return packet
