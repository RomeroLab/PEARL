"""Physical operations and nominal inventory."""
from copy import deepcopy
import math
import time
import threading
from pearl.runtime.contracts import ActionResult
from pearl.production.connection import HardwareStopped


def number(value, name, *, zero=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f'{name} requires a finite {"nonnegative" if zero else "positive"} number')
    return float(value)


class PhysicalBackend:
    def __init__(self, setup, robot, reader, *, monotonic=time.monotonic, sleep=time.sleep):
        if not getattr(robot, 'identity', None) or not getattr(robot, '_run_id', None) or robot.failed:
            raise HardwareStopped('A verified connected OT-2 session is required')
        self.setup, self.robot, self.reader = setup, robot, reader
        self.domain = setup.domain
        self.monotonic, self.sleep = monotonic, sleep
        self.origin = monotonic()
        self.inventory = {**{f'reservoir:{w}': r['volume_ul'] for w, r in setup.reagents.items()},
                          **{f'plate:{w}': 0. for w in setup.plate_wells}}
        self.command_log = []
        self._failed = False
        self.camera_active = False
        self.camera_request_hook = None
        self.clock_driver = None
        self.camera = reader
        self.camera.capture_duration_s = 0.
        self._state_lock = threading.Lock()
        self._active_action = None

    @property
    def time_s(self):
        return self.monotonic()-self.origin

    def briefing(self):
        reagents = {f'reservoir:{w}': {**deepcopy(r), **deepcopy(r.get('public_properties', {}))}
                    for w, r in self.setup.reagents.items()}
        return {'objective': self.setup.public_goal.get('objective'), 'domain': self.domain, 'task': deepcopy(self.setup.public_goal),
            'public_goal': deepcopy(self.setup.public_goal), 'locations': list(self.inventory),
            'reagents': reagents, 'calibration': self.reader.calibration.mapping(),
            'equipment': {'robot': 'OT-2', 'plate_capacity_ul': 300.,
                'camera_requested_settings': {k: self.setup.camera.get(k) for k in ('focus','exposure','white_balance')},
                'effective_camera_state': deepcopy(getattr(self.reader, 'binding', {}).get('effective_camera_state')),
                'minimum_transfer_ul': min(self._pipette_ranges()),
                'maximum_transfer_ul': 15000., 'volume_resolution_ul': None,
                'transfer_duration_s': None, 'mix_duration_s': None, 'capture_duration_s': 0.,
                'capture_duration_basis': 'Zero is an advisory lower bound, not exposure or guaranteed overhead; actual acquisition bounds are recorded per frame.',
                'timing_basis': 'Actual monotonic elapsed time includes provider latency, pipetting, processing, waits and capture.',
                'camera_start_policy': 'on_inspect', 'camera_active': self.camera_active,
                'continuous_camera': {'interval_s': getattr(self, 'continuous_camera_interval_s', None),
                    'field_of_view': 'All declared plate wells, plus requested reservoir locations',
                    'start_policy': 'on_inspect', 'sampling': 'Actual raw frames; missed captures are not reconstructed'}},
            'color_encoding': 'sRGB',
            'color_term_scope': {'property': 'observed_appearance',
                'interpretation_basis': 'Observed camera RGB/HEX, without named-color reference standards; appearance does not establish identity.'}}

    def _pipette_ranges(self):
        names = [self.setup.deck.pipette_type]
        if self.setup.deck.has_secondary_pipette:
            names.append(self.setup.deck.secondary_pipette_type)
        return [{'p20_single': 1., 'p300_single': 20., 'p1000_single': 100.}[n] for n in names]

    def _check_volume(self, volume):
        volume = number(volume, 'volume_ul')
        role = self.setup.deck.select_pipette_for_volume(volume)
        name = self.setup.deck.secondary_pipette_type if role == 'secondary' else self.setup.deck.pipette_type
        maximum = {'p20_single': 20., 'p300_single': 300., 'p1000_single': 1000.}[name]
        minimum = {'p20_single': 1., 'p300_single': 20., 'p1000_single': 100.}[name]
        chunk = volume/math.ceil(volume/maximum)
        if chunk < minimum or volume > 15000:
            raise ValueError('Volume is outside the configured pipette stroke range')
        return volume

    def validate_action(self, action):
        if self._failed or self.robot.failed:
            raise HardwareStopped('Execution remains stopped after an uncertain or failed operation')
        p, kind = action.params, action.action_type
        if kind == 'transfer':
            if set(p) - {'source', 'target', 'volume_ul', 'mix_after_transfer_ul'}:
                raise ValueError('Unknown transfer parameter')
            source, target = p['source'], p['target']
            if source not in self.inventory or target not in self.inventory or source == target:
                raise ValueError('Choose distinct declared source and destination')
            volume = self._check_volume(p['volume_ul'])
            residual = self.setup.reagents.get(source.split(':')[1], {}).get('residual_ul', 0.) if source.startswith('reservoir:') else 0.
            if self.inventory[source]-volume < number(residual, 'residual_ul', zero=True)-1e-8:
                raise ValueError('Transfer exceeds nominal aspiratable inventory')
            capacity = 300. if target.startswith('plate:') else 15000.
            if self.inventory[target]+volume > capacity+1e-8:
                raise ValueError('Transfer exceeds destination capacity')
        elif kind == 'mix':
            if set(p) != {'location', 'volume_ul'} or p['location'] not in self.inventory:
                raise ValueError('Choose a declared mix location and volume')
            volume = self._check_volume(p['volume_ul'])
            role = self.setup.deck.select_pipette_for_volume(volume)
            pipette = self.setup.deck.secondary_pipette_type if role == 'secondary' else self.setup.deck.pipette_type
            if volume > {'p20_single': 20., 'p300_single': 300., 'p1000_single': 1000.}[pipette]:
                raise ValueError('A mixing stroke exceeds selected pipette capacity')
            if volume > self.inventory[p['location']]:
                raise ValueError('Mix volume exceeds nominal available liquid')
        elif kind == 'wait':
            if set(p) != {'seconds'}: raise ValueError('Wait requires seconds only')
            number(p['seconds'], 'seconds', zero=True)
        elif kind == 'inspect':
            locations = p.get('locations')
            if set(p) != {'locations'} or not isinstance(locations, (list, tuple)) or not locations or len(set(locations)) != len(locations) or any(l not in self.inventory for l in locations):
                raise ValueError('Inspect requires distinct declared locations')
        else:
            raise ValueError('Unsupported physical action')

    def latch_failure(self, reason):
        with self._state_lock:
            self._failed = True
            self.robot.failed = True
            self.failure_reason = str(reason)
        try:
            self.robot.stop()
        except BaseException as exc:
            self.stop_error = str(exc)

    def capture_actual(self, locations):
        with self._state_lock:
            if self._failed:
                raise HardwareStopped('Observation stopped after a device error')
        packet = self.reader.capture(list(locations), clock=lambda: self.time_s)
        with self._state_lock:
            records = deepcopy(self.command_log)
            if self._active_action is not None:
                records.append(deepcopy(self._active_action_record))
        intervals = [r for r in records if r['action_type'] in ('transfer', 'mix')
            and r['started_at_s'] <= packet['captured_at_s']
            and r.get('completed_at_s', self.time_s) >= packet['acquisition_started_at_s']]
        packet['overlapping_action_ids'] = list(dict.fromkeys(r['action_id'] for r in intervals))
        for m in packet['measurements']:
            ids = [r['action_id'] for r in intervals if m['location'] in
                   (r['params'].get('source'), r['params'].get('target'), r['params'].get('location'))]
            m['overlapping_action_ids'] = list(dict.fromkeys(ids))
        return packet

    def inspect(self, locations):
        if any(l not in self.inventory for l in locations):
            raise ValueError('Unknown camera location')
        if self.camera_request_hook:
            self.camera_request_hook(locations)
        if self.clock_driver:
            return self.clock_driver.inspect(locations)
        self.camera_active = True
        return self.capture_actual(locations)

    def execute(self, action):
        self.validate_action(action)
        p, kind = action.params, action.action_type
        started = self.time_s
        row = {'action_id': action.action_id, 'action_type': kind, 'params': dict(p), 'started_at_s': started}
        try:
            with self._state_lock:
                if self._failed or self.robot.failed:
                    raise HardwareStopped('Execution stopped before physical dispatch')
                self._active_action = action.action_id
                self._active_action_record = deepcopy(row)
            if kind == 'transfer':
                if p.get('mix_after_transfer_ul') is not None:
                    raise ValueError('Compound transfers must be decomposed into separately authorized operations')
                src, sw = p['source'].split(':'); dst, dw = p['target'].split(':')
                self.robot.transfer_liquid(source_labware=src, source_well=sw, dest_labware=dst,
                                          dest_well=dw, volume=p['volume_ul'], new_tip=True)
            elif kind == 'mix':
                labware, well = p['location'].split(':')
                self.robot._auto_select(p['volume_ul'])
                self.robot.pick_up_tip()
                self.robot.mix(labware, well, p['volume_ul'], repetitions=3)
                self.robot.drop_tip()
            elif kind == 'wait': self.sleep(p['seconds'])
            elif kind == 'inspect':
                packet = self.inspect(p['locations'])
            with self._state_lock:
                if self._failed or self.robot.failed:
                    raise HardwareStopped('Device or observation stopped before command commit')
                if kind == 'transfer':
                    self.inventory[p['source']] -= p['volume_ul']
                    self.inventory[p['target']] += p['volume_ul']
                end = self.time_s
                row.update(completed_at_s=end, status='acknowledged')
                self.command_log.append(row)
            observation = packet if kind == 'inspect' else {**row,
                'basis': 'Acknowledged command and nominal accounting; composition, homogeneity and delivery are not optically verified.'}
            return ActionResult(action_id=action.action_id, action_type=kind, ok=True, observation=observation)
        except BaseException as exc:
            self.latch_failure(exc)
            row.update(completed_at_s=self.time_s, status='uncertain_or_failed', error=str(exc))
            with self._state_lock:
                self.command_log.append(row)
            raise HardwareStopped('Physical execution failed or is uncertain; stopped without retry') from exc
        finally:
            with self._state_lock: self._active_action = None
