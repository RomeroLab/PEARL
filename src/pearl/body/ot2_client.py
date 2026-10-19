"""HTTP client for controlling a real OT-2 via its built-in firmware API (port 31950).

Unlike RemoteRobot (which talks to our custom Flask server), this client
speaks the OT-2's native HTTP API — no extra software on the robot.

Usage:
    robot = OT2HttpClient("169.254.93.158")
    robot.connect()  # creates a run, loads labware + pipette
    robot.transfer_liquid("reservoir", "A1", "plate", "B1", 50.0)
"""
import logging
from typing import Any, Optional
import requests
from .robot import DeckLayout
logger = logging.getLogger(__name__)
PIPETTE_FLOW_RATES: dict[str, float] = {'p10_single': 5.0, 'p20_single': 7.56, 'p300_single': 46.43, 'p1000_single': 137.35}
DEFAULT_FLOW_RATE = 46.43
PIPETTE_MAX_VOLUMES: dict[str, float] = {'p10_single': 10.0, 'p20_single': 20.0, 'p300_single': 300.0, 'p1000_single': 1000.0}
DEFAULT_MAX_VOLUME = 300.0

def _chunk_volume(total: float, pipette_max: float) -> list[float]:
    """Split ``total`` µL into ≤``pipette_max`` near-equal chunks.
    Returns ``[total]`` when it already fits one pipette load."""
    total = float(total)
    if total <= pipette_max or pipette_max <= 0:
        return [total]
    import math
    n = int(math.ceil(total / pipette_max))
    each = total / n
    return [each] * n
_PICKUPTIP_PRESS_OFFSET_Z_MM = -1.5

class TipTracker:
    """Tracks the next available tip in column-major order (A1→B1→...→H12)."""
    ROWS = 'ABCDEFGH'
    COLS = range(1, 13)

    def __init__(self):
        self._index = 0

    def next_tip(self) -> str:
        if self._index >= 96:
            raise RuntimeError('No tips remaining')
        col = self._index // 8
        row = self._index % 8
        self._index += 1
        return f'{self.ROWS[row]}{self.COLS[col]}'

    @property
    def current_index(self) -> int:
        return self._index

    @current_index.setter
    def current_index(self, value: int) -> None:
        if not 0 <= value <= 96:
            raise ValueError(f'Tip index must be 0-96, got {value}')
        self._index = value

    @property
    def tips_remaining(self) -> int:
        return 96 - self._index

    def reset(self):
        self._index = 0

class OT2HttpClient:
    """HTTP client that controls an OT-2
    via its built-in firmware HTTP API on port 31950.

    The liquid-handling interface lets the Brain layer
    can use any of them interchangeably.
    """

    def __init__(self, host: str, port: int=31950, deck_layout: Optional[DeckLayout]=None, timeout: float=30.0):
        self._base_url = f'http://{host}:{port}'
        self._deck_layout = deck_layout or DeckLayout()
        self._timeout = timeout
        self._z_offset = self._deck_layout.labware_z_offset
        self._run_id: Optional[str] = None
        self._pipette_id: Optional[str] = None
        self._secondary_pipette_id: Optional[str] = None
        self._labware_ids: dict[str, str] = {}
        self._tip_tracker = TipTracker()
        self._secondary_tip_tracker = TipTracker()
        self._has_tip = False
        self._active: str = 'primary'
        self._extra_tiprack_ids: list[str] = []
        self._current_tiprack_idx: int = 0
        self._secondary_extra_tiprack_ids: list[str] = []
        self._current_secondary_tiprack_idx: int = 0

    @property
    def has_tip(self) -> bool:
        return self._has_tip

    def _request(self, method: str, path: str, json: Any=None) -> dict:
        """Send an HTTP request to the OT-2 firmware API.

        All calls go through here so we have a single place for
        error handling and the opentrons-version header.
        """
        url = f'{self._base_url}{path}'
        headers = {'opentrons-version': '*'}
        try:
            resp = requests.request(method, url, json=json, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError as exc:
            raise ConnectionError(f'Cannot reach OT-2 at {self._base_url}: {exc}') from exc
        except requests.Timeout as exc:
            raise ConnectionError(f'OT-2 request timed out: {exc}') from exc
        except requests.HTTPError as exc:
            body = ''
            if exc.response is not None:
                try:
                    body = exc.response.text[:500]
                except Exception:
                    pass
            raise ConnectionError(f"HTTP {(exc.response.status_code if exc.response else '?')} from OT-2: {path}\n{body}") from exc

    def _send_setup_command(self, command_type: str, params: dict) -> dict:
        """Send a setup command that executes immediately.

        Wraps the command in the envelope required by the firmware API.
        """
        body = {'data': {'commandType': command_type, 'params': params, 'intent': 'setup'}}
        data = self._request('POST', f'/runs/{self._run_id}/commands?waitUntilComplete=true', json=body)
        if 'errors' in data:
            detail = data['errors'][0].get('detail', 'Unknown error')
            raise RuntimeError(f'Command {command_type} failed: {detail}')
        cmd_data = data.get('data', {})
        status = cmd_data.get('status')
        if status != 'succeeded':
            detail = cmd_data.get('error', {}).get('detail', 'Unknown error')
            raise RuntimeError(f'Command {command_type} failed: {detail}')
        return data

    def _ensure_connected(self):
        """Lazy auto-connect: if not connected yet, connect now."""
        if self._run_id is None:
            self.connect()

    def _resolve_labware(self, name: str) -> str:
        """Map a labware name ('plate', 'reservoir', 'tiprack') to its firmware ID."""
        labware_id = self._labware_ids.get(name.lower())
        if labware_id is None:
            raise ValueError(f"Unknown labware: {name}. Use: {', '.join(self._labware_ids.keys())}")
        return labware_id

    def connect(self) -> 'OT2HttpClient':
        """Create a run, load labware and pipette, store IDs.

        Returns self for method chaining.
        """
        dl = self._deck_layout
        data = self._request('POST', '/runs', json={'data': {}})
        self._run_id = data['data']['id']
        logger.info(f'Created run: {self._run_id}')
        labware_configs = [('plate', dl.plate_type, dl.plate_slot), ('tiprack', dl.tiprack_type, dl.tiprack_slot)]
        if dl.reservoir_slot is not None and dl.reservoir_type is not None:
            labware_configs.insert(1, ('reservoir', dl.reservoir_type, dl.reservoir_slot))
        for name, labware_type, slot in labware_configs:
            resp = self._send_setup_command('loadLabware', {'loadName': labware_type, 'namespace': 'opentrons', 'version': 1, 'location': {'slotName': str(slot)}})
            self._labware_ids[name] = resp['data']['result']['labwareId']
            logger.info(f'Loaded {name}: {self._labware_ids[name]}')
        resp = self._send_setup_command('loadPipette', {'pipetteName': dl.pipette_type, 'mount': dl.pipette_mount})
        self._pipette_id = resp['data']['result']['pipetteId']
        logger.info(f'Loaded primary pipette: {self._pipette_id}')
        for i, slot in enumerate(dl.extra_tiprack_slots):
            resp = self._send_setup_command('loadLabware', {'loadName': dl.tiprack_type, 'namespace': 'opentrons', 'version': 1, 'location': {'slotName': str(slot)}})
            rack_name = f'extra_tiprack_{i}'
            self._labware_ids[rack_name] = resp['data']['result']['labwareId']
            self._extra_tiprack_ids.append(self._labware_ids[rack_name])
            logger.info(f'Loaded extra tiprack in slot {slot}: {self._labware_ids[rack_name]}')
        if dl.has_secondary_pipette:
            resp = self._send_setup_command('loadLabware', {'loadName': dl.secondary_tiprack_type, 'namespace': 'opentrons', 'version': 1, 'location': {'slotName': str(dl.secondary_tiprack_slot)}})
            self._labware_ids['secondary_tiprack'] = resp['data']['result']['labwareId']
            resp = self._send_setup_command('loadPipette', {'pipetteName': dl.secondary_pipette_type, 'mount': dl.secondary_pipette_mount})
            self._secondary_pipette_id = resp['data']['result']['pipetteId']
            logger.info(f'Loaded secondary pipette: {self._secondary_pipette_id}')
            for i, slot in enumerate(dl.secondary_extra_tiprack_slots):
                resp = self._send_setup_command('loadLabware', {'loadName': dl.secondary_tiprack_type, 'namespace': 'opentrons', 'version': 1, 'location': {'slotName': str(slot)}})
                rack_name = f'secondary_extra_tiprack_{i}'
                self._labware_ids[rack_name] = resp['data']['result']['labwareId']
                self._secondary_extra_tiprack_ids.append(self._labware_ids[rack_name])
                logger.info(f'Loaded secondary extra tiprack in slot {slot}: {self._labware_ids[rack_name]}')
        return self

    def disconnect(self):
        """Reset internal state."""
        self._run_id = None
        self._pipette_id = None
        self._secondary_pipette_id = None
        self._labware_ids = {}
        self._has_tip = False
        self._active = 'primary'
        self._tip_tracker.reset()
        self._secondary_tip_tracker.reset()
        self._extra_tiprack_ids = []
        self._current_tiprack_idx = 0
        self._secondary_extra_tiprack_ids = []
        self._current_secondary_tiprack_idx = 0

    def _auto_select(self, volume: float) -> None:
        """Auto-select the best pipette for *volume*."""
        self._active = self._deck_layout.select_pipette_for_volume(volume)

    @property
    def _active_pipette_id(self) -> str:
        if self._active == 'secondary' and self._secondary_pipette_id:
            return self._secondary_pipette_id
        return self._pipette_id

    @property
    def _active_flow_rate(self) -> float:
        if self._active == 'secondary':
            pip_type = self._deck_layout.secondary_pipette_type
        else:
            pip_type = self._deck_layout.pipette_type
        return PIPETTE_FLOW_RATES.get(pip_type, DEFAULT_FLOW_RATE)

    @property
    def _active_pipette_max_volume(self) -> float:
        if self._active == 'secondary':
            pip_type = self._deck_layout.secondary_pipette_type
        else:
            pip_type = self._deck_layout.pipette_type
        return PIPETTE_MAX_VOLUMES.get(pip_type, DEFAULT_MAX_VOLUME)

    def set_start_tip_global(self, primary_global: int, secondary_global: int=0) -> None:
        """Resume tip consumption from a cumulative global index.

        Unlike directly setting ``_tip_tracker.current_index`` (which is
        bounded to 0-96 and only addresses the CURRENT rack), this
        method takes a cumulative count across all racks: e.g.
        ``primary_global=126`` means 96 tips on primary + 30 on the
        first extra rack.  It divmods into ``(rack_idx, within_idx)``
        and sets both ``_current_tiprack_idx`` and the tracker's
        ``current_index``, so a batch-run trial that exhausted the
        primary mid-trial actually continues from the next rack on the
        following trial — instead of restarting at well A1 of an
        already-empty primary.

        Raises ``ValueError`` if ``primary_global`` or
        ``secondary_global`` lands beyond the racks loaded via
        ``connect()`` (primary + ``len(extra_tiprack_ids)`` racks ×
        96 tips each).
        """
        for label, total, racks_attr, tracker_attr, idx_attr in (('primary', primary_global, '_extra_tiprack_ids', '_tip_tracker', '_current_tiprack_idx'), ('secondary', secondary_global, '_secondary_extra_tiprack_ids', '_secondary_tip_tracker', '_current_secondary_tiprack_idx')):
            if total < 0:
                raise ValueError(f'{label}_global must be >= 0 (got {total})')
            rack_idx, within = divmod(total, 96)
            n_extras = len(getattr(self, racks_attr))
            if rack_idx > n_extras:
                raise ValueError(f'{label}_global={total} lands on rack idx {rack_idx} but only {n_extras} extra rack(s) are loaded (primary + {n_extras} extra = {(n_extras + 1) * 96} tips available)')
            tracker = getattr(self, tracker_attr)
            tracker.reset()
            tracker.current_index = within
            setattr(self, idx_attr, rack_idx)

    def emit_global_tip_count(self) -> tuple[int, int]:
        """Return ``(primary_global, secondary_global)`` cumulative tip
        counts.  Inverse of ``set_start_tip_global``: rolls
        ``rack_idx * 96 + within-rack idx`` for each pipette into a
        single integer the next batch-run trial can resume from."""
        primary = self._current_tiprack_idx * 96 + self._tip_tracker.current_index
        secondary = self._current_secondary_tiprack_idx * 96 + self._secondary_tip_tracker.current_index
        return (primary, secondary)

    def pick_up_tip(self) -> None:
        self._ensure_connected()
        if self._has_tip:
            raise RuntimeError('Already has a tip. Drop it first.')
        if self._active == 'secondary' and self._secondary_pipette_id:
            try:
                well = self._secondary_tip_tracker.next_tip()
            except RuntimeError:
                if self._current_secondary_tiprack_idx < len(self._secondary_extra_tiprack_ids):
                    self._secondary_tip_tracker = TipTracker()
                    self._current_secondary_tiprack_idx += 1
                    logger.info(f'Secondary tiprack exhausted, switching to extra rack {self._current_secondary_tiprack_idx}')
                    well = self._secondary_tip_tracker.next_tip()
                else:
                    raise RuntimeError('No tips remaining (all secondary racks exhausted)')
            if self._current_secondary_tiprack_idx == 0:
                labware_id = self._labware_ids.get('secondary_tiprack', self._resolve_labware('tiprack'))
            else:
                labware_id = self._secondary_extra_tiprack_ids[self._current_secondary_tiprack_idx - 1]
        else:
            try:
                well = self._tip_tracker.next_tip()
            except RuntimeError:
                if self._current_tiprack_idx < len(self._extra_tiprack_ids):
                    self._tip_tracker = TipTracker()
                    self._current_tiprack_idx += 1
                    logger.info(f'Primary tiprack exhausted, switching to extra rack {self._current_tiprack_idx}')
                    well = self._tip_tracker.next_tip()
                else:
                    raise RuntimeError('No tips remaining (all racks exhausted)')
            if self._current_tiprack_idx == 0:
                labware_id = self._resolve_labware('tiprack')
            else:
                labware_id = self._extra_tiprack_ids[self._current_tiprack_idx - 1]
        self._send_setup_command('pickUpTip', {'pipetteId': self._active_pipette_id, 'labwareId': labware_id, 'wellName': well, 'wellLocation': {'origin': 'top', 'offset': {'x': 0, 'y': 0, 'z': _PICKUPTIP_PRESS_OFFSET_Z_MM}}})
        self._has_tip = True
        logger.info('Picked up tip from %s (%s) idx now p=%d,s=%d', well, self._active, self._tip_tracker.current_index, self._secondary_tip_tracker.current_index)

    def drop_tip(self):
        self._ensure_connected()
        if not self._has_tip:
            raise RuntimeError('No tip to drop')
        self._send_setup_command('moveToAddressableAreaForDropTip', {
            'pipetteId': self._active_pipette_id, 'addressableAreaName': 'fixedTrash'})
        self._send_setup_command('dropTipInPlace', {'pipetteId': self._active_pipette_id})
        self._has_tip = False

    _POST_OP_RETRACT_Z_MM = 5.0

    def _retract_to_well_top(self, labware: str, well: str) -> None:
        """Lift the pipette to a safe Z above ``well`` top.

        HARDWARE SAFETY: after aspirate/dispense, the tip is at
        ``z = 4.5mm + labware_z_offset`` above well bottom — well below
        well_top. Without an explicit retract, OT-2 firmware can
        plan a direct path between consecutive aspirate/dispense
        commands that drags the tip through the well wall — snapping
        tips and shifting the plate. Sending an explicit
        ``moveToWell`` with ``origin="top"`` after each operation
        guarantees the tip is above well_top before any next lateral
        motion.

        ``forceDirect: false`` keeps the path planner using its
        retract-then-move strategy from the bottom-of-well start
        position (it cannot path-shortcut through the well rim).
        """
        self._send_setup_command('moveToWell', {'pipetteId': self._active_pipette_id, 'labwareId': self._resolve_labware(labware), 'wellName': well, 'wellLocation': {'origin': 'top', 'offset': {'x': 0, 'y': 0, 'z': self._POST_OP_RETRACT_Z_MM}}, 'forceDirect': False})

    def aspirate(self, *args) -> None:
        """Aspirate liquid.

        2-arg: aspirate(well, volume) — defaults to 'plate' labware
        3-arg: aspirate(labware, well, volume)

        Followed by a safety retract to ``well_top + _POST_OP_RETRACT_Z_MM``
        — see :meth:`_retract_to_well_top`.
        """
        if len(args) == 2:
            well, volume = args
            labware = 'plate'
        elif len(args) == 3:
            labware, well, volume = args
        else:
            raise TypeError(f'aspirate() takes 2 or 3 positional arguments, got {len(args)}')
        self._ensure_connected()
        if not self._has_tip:
            raise RuntimeError('No tip. Pick up a tip first.')
        self._send_setup_command('aspirate', {'pipetteId': self._active_pipette_id, 'labwareId': self._resolve_labware(labware), 'wellName': well, 'volume': volume, 'flowRate': self._active_flow_rate, 'wellLocation': {'origin': 'bottom', 'offset': {'x': 0, 'y': 0, 'z': 4.5 + self._z_offset}}})
        self._retract_to_well_top(labware, well)
        logger.debug(f'Aspirated {volume}µL from {labware}:{well}')

    def dispense(self, *args) -> None:
        """Dispense liquid.

        2-arg: dispense(well, volume) — defaults to 'plate' labware
        3-arg: dispense(labware, well, volume)

        Followed by a safety retract — see :meth:`_retract_to_well_top`.
        """
        if len(args) == 2:
            well, volume = args
            labware = 'plate'
        elif len(args) == 3:
            labware, well, volume = args
        else:
            raise TypeError(f'dispense() takes 2 or 3 positional arguments, got {len(args)}')
        self._ensure_connected()
        if not self._has_tip:
            raise RuntimeError('No tip. Pick up a tip first.')
        self._send_setup_command('dispense', {'pipetteId': self._active_pipette_id, 'labwareId': self._resolve_labware(labware), 'wellName': well, 'volume': volume, 'flowRate': self._active_flow_rate, 'wellLocation': {'origin': 'bottom', 'offset': {'x': 0, 'y': 0, 'z': 4.5 + self._z_offset}}})
        self._retract_to_well_top(labware, well)
        logger.debug(f'Dispensed {volume}µL to {labware}:{well}')

    def mix(self, labware: str, well: str, volume: float, repetitions: int=3) -> None:
        """Mix by repeated aspirate/dispense at the same well.

        Auto-selects the right pipette for ``volume`` first.  Without
        this, the active pipette from the previous transfer carries over
        — a small (5μL) transfer leaves the p20 active, and a follow-up
        ``mix(50μL)`` would then attempt to over-aspirate with p20.
        """
        if not self._has_tip:
            raise RuntimeError('No tip. Pick up a tip first.')
        self._auto_select(volume)
        for _ in range(repetitions):
            self.aspirate(labware, well, volume)
            self.dispense(labware, well, volume)
        logger.debug(f'Mixed {labware}:{well} {repetitions}x with {volume}µL')

    def home(self) -> None:
        """Home all axes."""
        self._ensure_connected()
        self._request('POST', '/robot/home', json={'target': 'robot'})
        logger.info('Homed all axes')

    def transfer_liquid(self, source_labware: str, source_well: str, dest_labware: str, dest_well: str, volume: float, new_tip: bool=True, mix_after: Optional[tuple[int, float]]=None, blow_out: bool=False) -> None:
        """Transfer liquid from source to destination.

        Auto-selects the best pipette for *volume* when dual-pipette is configured.
        Execute a liquid transfer through acknowledged OT-2 commands
        signatures exactly.
        """
        self._ensure_connected()
        self._auto_select(volume)
        logger.info('transfer_liquid %s:%s->%s:%s vol=%s new_tip=%s has_tip=%s active=%s idx(p=%d,s=%d)', source_labware, source_well, dest_labware, dest_well, volume, new_tip, self._has_tip, self._active, self._tip_tracker.current_index, self._secondary_tip_tracker.current_index)
        if new_tip and (not self._has_tip):
            self.pick_up_tip()
        elif new_tip and self._has_tip:
            logger.info('  -> REUSING existing tip (has_tip already True; no new pickup)')
        for chunk in _chunk_volume(volume, self._active_pipette_max_volume):
            self.aspirate(source_labware, source_well, chunk)
            self.dispense(dest_labware, dest_well, chunk)
        if mix_after:
            reps, mix_vol = mix_after
            self.mix(dest_labware, dest_well, mix_vol, reps)
        if blow_out:
            self._send_setup_command('blowout', {'pipetteId': self._active_pipette_id, 'labwareId': self._resolve_labware(dest_labware), 'wellName': dest_well, 'flowRate': self._active_flow_rate})
        if new_tip and self._has_tip:
            self.drop_tip()
        logger.info(f'Transferred {volume}µL: {source_labware}:{source_well} → {dest_labware}:{dest_well}')

    def distribute(self, src_labware: str, src_well: str, dst_labware: str, dst_wells: list[str], volume: float) -> None:
        """Distribute liquid from one source to multiple destinations.

        Single aspirate of total volume, then individual dispenses.
        """
        self._ensure_connected()
        total_volume = volume * len(dst_wells)
        self._auto_select(total_volume)
        self.pick_up_tip()
        pmax = self._active_pipette_max_volume
        remaining_total = total_volume
        in_tip = 0.0
        for well in dst_wells:
            to_dispense = float(volume)
            while to_dispense > 1e-09:
                if in_tip <= 1e-09:
                    load = min(pmax, remaining_total)
                    self.aspirate(src_labware, src_well, load)
                    in_tip = load
                d = min(to_dispense, in_tip)
                self.dispense(dst_labware, well, d)
                in_tip -= d
                to_dispense -= d
                remaining_total -= d
        self.drop_tip()
        logger.info(f'Distributed {volume}µL to {len(dst_wells)} wells')
