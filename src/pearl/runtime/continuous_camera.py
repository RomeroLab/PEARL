"""Real concurrent acquisition with a single owner for public evidence delivery."""
from copy import deepcopy
import math
import queue
import threading
import time
from pearl.state.events import ObservationEvent


class ContinuousCamera:
    def __init__(self, run, interval_s, monotonic=None):
        if type(interval_s) not in (int, float) or not math.isfinite(interval_s) or interval_s <= 0:
            raise ValueError('Positive finite camera interval required')
        self.run = run
        self.interval_s = float(interval_s)
        self.monotonic = monotonic or time.monotonic
        self.active = False
        self.activation_request_id = None
        self.inspection_request_id = None
        self.requested_locations = []
        self.last_snapshot = {}
        self.snapshot_evidence = {}
        self._stop = threading.Event()
        self._queue = queue.Queue()
        self._wake = threading.Event()
        self._error = None
        self._condition = threading.Condition()
        self._inflight_started_s = None
        self._pending_packet = None
        self.thread = threading.Thread(target=self._worker, name='pearl-camera', daemon=True)

    def event(self, kind, payload):
        self.run.board.publish(ObservationEvent(source_agent='actor', observation_type=kind, payload=payload))

    def activate(self):
        if not self.active:
            self.active = True
            if self.thread.ident is None:
                self.thread.start()
            self._wake.set()

    def _worker(self):
        while not self._stop.is_set():
            started = self.monotonic()
            with self._condition:
                locations = list(dict.fromkeys([p for p in self.run.world.inventory if p.startswith('plate:')] + list(self.requested_locations)))
                activation_id, request_id = self.activation_request_id, self.inspection_request_id
                self._inflight_started_s = self.run.world.time_s
            try:
                if locations:
                    packet = self.run.world.capture_actual(locations)
                    packet['activation_request_id'] = activation_id
                    packet['request_id'] = request_id
                    with self._condition:
                        self._queue.put(deepcopy(packet))
                if self._queue.qsize() > 1024:
                    raise RuntimeError('Acquisition queue exceeded capacity; no frames discarded silently')
            except BaseException as exc:
                self.run.world.latch_failure(exc)
                with self._condition:
                    self._error = exc
                    self._stop.set()
            finally:
                with self._condition:
                    self._inflight_started_s = None
                    self._condition.notify_all()
            if self._stop.is_set():
                return
            elapsed = self.monotonic()-started
            self._wake.wait(max(0., self.interval_s-elapsed))
            self._wake.clear()

    def drain(self, *, through_s=None):
        if through_s is not None:
            deadline = time.monotonic()+5.
            with self._condition:
                while self._inflight_started_s is not None and self._inflight_started_s <= through_s:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        self.run.world.latch_failure('Camera acquisition watermark timed out')
                        raise RuntimeError('Camera acquisition watermark could not be established')
                    self._condition.wait(remaining)
        if self._error is not None:
            raise RuntimeError('Physical camera acquisition failed; execution stopped') from self._error
        while True:
            if self._pending_packet is not None:
                packet = self._pending_packet
                self._pending_packet = None
            else:
                try: packet = self._queue.get_nowait()
                except queue.Empty: return
            if through_s is not None and packet['captured_at_s'] > through_s:
                self._pending_packet = packet
                return
            self.event('camera_acquisition_started', {
                'started_at_s': packet['acquisition_started_at_s'],
                'capture_duration_s': packet['captured_at_s']-packet['acquisition_started_at_s'],
                'locations': [m['location'] for m in packet['measurements']],
                'frame_id': packet['frame_id'], 'acquisition_mode': 'physical_camera'})
            packet['evidence_ids'] = [m['measurement_id'] for m in packet['measurements']]
            self.run._evidence.update({m['measurement_id']: deepcopy(m) for m in packet['measurements']})
            self.event('camera', packet)
            self.run._collect_findings()

    def call(self, role, callback):
        snapshot = self.run.board.event_log[-1].event_id if self.run.board.event_log else None
        before = self.run.world.time_s
        self.snapshot_evidence[role] = frozenset(self.run._evidence)
        self.last_snapshot[role] = {'role': role, 'evidence_frontier': snapshot, 'experiment_time_s': before}
        self.event('model_snapshot', deepcopy(self.last_snapshot[role]))
        started = self.monotonic()
        try:
            return callback()
        finally:
            self.event('model_elapsed', {'role': role, 'evidence_frontier': snapshot,
                'started_at_s': before, 'elapsed_s': self.monotonic()-started,
                'response_saw_new_frames': False, 'basis': 'Actual elapsed monotonic time; raw camera capture continued concurrently.'})
            self.drain()

    def inspect(self, locations):
        wanted = set(locations)
        if not wanted or not wanted <= set(self.run.world.inventory):
            raise ValueError('Choose declared camera locations')
        self.requested_locations = list(locations)
        request_start = self.run.world.time_s
        self.activate()
        self._wake.set()
        try:
            while True:
                self.drain()
                packet = self.run.board.camera_for('actor')
                rows = [m for m in packet['measurements'] if m['location'] in wanted]
                if len(rows) == len(wanted) and packet.get('acquisition_started_at_s', -1) >= request_start:
                    return {**deepcopy(packet), 'measurements': deepcopy(rows),
                            'evidence_ids': [m['measurement_id'] for m in rows]}
                if self._stop.wait(.002):
                    self.drain()
                    raise RuntimeError('Camera acquisition stopped')
        finally:
            self.requested_locations = []
            self.inspection_request_id = None

    def close(self):
        self._stop.set(); self._wake.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=5.)
            if self.thread.is_alive():
                self.run.world.latch_failure('Camera worker could not be joined')
                raise RuntimeError('Camera worker could not be joined')
        if self._error is None:
            self.drain()

    def archive_index(self):
        index = {}
        for m in self.run._evidence.values():
            row = index.setdefault(m['location'], {'location': m['location'], 'count': 0, 'first_capture_s': m['captured_at_s'], 'last_capture_s': m['captured_at_s']})
            row['count'] += 1
            row['last_capture_s'] = m['captured_at_s']
        return {'locations': list(index.values()), 'retrieval': 'read_camera_window', 'scope': 'All acquired records remain archived; choose explicit times and paginate. No quality-based selection.'}

    def read_window(self, args):
        from pearl.runtime.acquisition_context import acquisition_context
        from copy import deepcopy
        if not isinstance(args, dict) or set(args) != {'location', 'from_s', 'through_s', 'offset', 'limit'}:
            raise ValueError('Choose location, fixed time bounds, offset and limit')
        if args['location'] not in self.run.world.inventory:
            raise ValueError('Choose a declared location')
        for key in ('from_s', 'through_s'):
            if isinstance(args[key], bool) or not isinstance(args[key], (int, float)) or (not math.isfinite(args[key])):
                raise ValueError('Finite time bounds required')
        if not 0 <= args['from_s'] <= args['through_s'] <= self.run.world.time_s + 1e-08:
            raise ValueError('Choose an acquired time range')
        if type(args['offset']) is not int or args['offset'] < 0 or type(args['limit']) is not int or (not 1 <= args['limit'] <= 64):
            raise ValueError('Nonnegative offset and limit1..64 required')
        rows = [m for m in self.run._evidence.values() if m['location'] == args['location'] and args['from_s'] <= m['captured_at_s'] <= args['through_s']]
        start = args['offset']
        end = start + args['limit']
        chosen = deepcopy(rows[start:end])
        return {'measurements': chosen, 'total': len(rows), 'next_offset': end if end < len(rows) else None, 'acquisition_context': acquisition_context(chosen, self.run.board.event_log, self.run.world.briefing()['reagents']), 'scope': 'Recorded observations only; no inference of scientific suitability.'}
