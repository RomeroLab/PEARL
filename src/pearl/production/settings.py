"""Validated user configuration shared by the production programs."""
from __future__ import annotations
from dataclasses import dataclass
import ipaddress
import math
from pathlib import Path
import re
from typing import Any
import yaml
from pearl.body.robot import DeckLayout

def robot_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError('A valid OT-2 IP address is required (for example, 169.254.93.158).') from exc
    if address.is_loopback or address.is_unspecified or address.is_multicast:
        raise ValueError('Loopback, unspecified, and multicast addresses cannot identify an OT-2.')
    return str(address)

def select_scenarios(value: str) -> list[str]:
    if value.strip().lower() == 'all':
        return [f'S{i}' for i in range(1, 9)]
    result = []
    for part in value.upper().split(','):
        match = re.fullmatch('S([1-8])(?:-S?([1-8]))?', part.strip())
        if not match:
            raise ValueError('Use all, S2, S1-4, S1-S4, or S1,S3,S8 to select scenarios.')
        lo, hi = (int(match[1]), int(match[2] or match[1]))
        if hi < lo:
            raise ValueError('A scenario range must end at or after its start.')
        for n in range(lo, hi + 1):
            if f'S{n}' not in result:
                result.append(f'S{n}')
    return result

def positive(value: Any, name: str, *, zero: bool=False) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{name}: A number is required.')
    try:
        n = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{name}: A number is required.') from exc
    if not math.isfinite(n) or (n < 0 if zero else n <= 0):
        raise ValueError(f"{name}: A finite {('nonnegative' if zero else 'positive')} value is required.")
    return n

def wells(value: Any) -> list[str]:
    if isinstance(value, str):
        if re.fullmatch('[A-H](?:[1-9]|1[0-2])-[A-H](?:[1-9]|1[0-2])', value):
            a, b = value.split('-')
            if a[0] > b[0] or int(a[1:]) > int(b[1:]):
                raise ValueError('Well ranges must be in ascending order.')
            value = [f'{chr(r)}{c}' for r in range(ord(a[0]), ord(b[0]) + 1) for c in range(int(a[1:]), int(b[1:]) + 1)]
        else:
            value = [s.strip() for s in value.split(',')]
    if not isinstance(value, list) or not value or len(set(value)) != len(value):
        raise ValueError('plate_wells must be a nonempty list of unique wells.')
    if any((not isinstance(w, str) or not re.fullmatch('[A-H](?:[1-9]|1[0-2])', w) for w in value)):
        raise ValueError('Plate wells must be in A1–H12.')
    return value

@dataclass(frozen=True)
class Setup:
    deck: DeckLayout
    reagents: dict[str, dict]
    camera: dict[str, Any]
    plate_wells: list[str]
    domain: str
    public_goal: dict[str, Any]
    source: dict[str, Any]

def validate_setup(data: dict, *, base_dir: Path=Path('.')) -> Setup:
    if not isinstance(data, dict):
        raise ValueError('The setup file must contain a YAML or JSON object.')
    raw = data.get('deck')
    if not isinstance(raw, dict):
        raise ValueError('A deck configuration is required.')
    defaults = dict(reservoir_slot=3, reservoir_type='nest_12_reservoir_15ml')
    try:
        deck = DeckLayout(**{**defaults, **raw})
    except TypeError as exc:
        raise ValueError(f'Unsupported deck field: {exc}') from exc
    if deck.additional_plates:
        raise ValueError('Configure one plate and one 12-channel reservoir.')
    slots = [deck.plate_slot, deck.reservoir_slot, deck.tiprack_slot, *deck.extra_tiprack_slots]
    if deck.has_secondary_pipette:
        slots += [deck.secondary_tiprack_slot, *deck.secondary_extra_tiprack_slots]
    if any((type(s) is not int or not 1 <= s <= 11 for s in slots)) or len(set(slots)) != len(slots):
        raise ValueError('OT-2 slots must be unique integers from 1 to 11.')
    if deck.plate_type != 'corning_96_wellplate_360ul_flat' or deck.reservoir_type != 'nest_12_reservoir_15ml':
        raise ValueError('Supported labware: corning_96_wellplate_360ul_flat and nest_12_reservoir_15ml.')
    if deck.pipette_type not in ('p20_single', 'p300_single', 'p1000_single') or deck.pipette_mount not in ('left', 'right'):
        raise ValueError('Specify a supported single-channel pipette and a left or right mount.')
    if deck.has_secondary_pipette and (deck.secondary_pipette_type not in ('p20_single', 'p300_single', 'p1000_single') or deck.secondary_pipette_mount not in ('left', 'right') or deck.secondary_pipette_mount == deck.pipette_mount):
        raise ValueError('Specify a supported secondary pipette on the opposite mount.')
    for pipette, rack in [(deck.pipette_type, deck.tiprack_type)] + ([(deck.secondary_pipette_type, deck.secondary_tiprack_type)] if deck.has_secondary_pipette else []):
        capacity = {'p20_single': 20, 'p300_single': 300, 'p1000_single': 1000}[pipette]
        if rack != f'opentrons_96_tiprack_{capacity}ul':
            raise ValueError('The pipette and tiprack types and capacities must match.')
    if deck.has_secondary_pipette and int(deck.secondary_pipette_type[1:].split('_')[0]) >= int(deck.pipette_type[1:].split('_')[0]):
        raise ValueError('The secondary pipette must have a smaller capacity than the primary pipette.')
    if not math.isfinite(float(deck.labware_z_offset)):
        raise ValueError('labware_z_offset must be finite.')
    rows = data.get('reagents')
    if not isinstance(rows, dict) or not rows:
        raise ValueError('Each reagent requires a location, label, and volume_ul.')
    reagents = {}
    for well, item in rows.items():
        if not re.fullmatch('A(?:[1-9]|1[0-2])', str(well)) or not isinstance(item, dict):
            raise ValueError('Reservoir reagent locations must be in A1–A12.')
        if not isinstance(item.get('label'), str) or not item['label'].strip():
            raise ValueError(f'{well}: A reagent label is required.')
        if item.get('labware', 'reservoir') != 'reservoir':
            raise ValueError('Place starting reagents in the reservoir and leave the plate empty.')
        volume = positive(item.get('volume_ul'), f'{well}.volume_ul')
        if volume > 15000:
            raise ValueError(f'{well}: The reservoir capacity of 15000 µL was exceeded.')
        reagents[well] = {**item, 'labware': 'reservoir', 'volume_ul': volume}
    camera = dict(data.get('camera') or {})
    if 'crop_config' not in camera:
        raise ValueError('Set camera.crop_config to the slot crop JSON for this camera.')
    crop = Path(camera['crop_config']).expanduser()
    camera['crop_config'] = str((base_dir / crop).resolve() if not crop.is_absolute() else crop)
    for key in ('focus', 'exposure', 'white_balance'):
        if key in camera and (not math.isfinite(float(camera[key]))):
            raise ValueError(f'camera.{key} must be a finite number.')
    domain = data.get('domain', 'color')
    if domain not in ('color', 'enzyme'):
        raise ValueError('domain must be color or enzyme.')
    goal = data.get('public_goal') or {}
    if not isinstance(goal, dict):
        raise ValueError('public_goal must be an object.')
    return Setup(deck, reagents, camera, wells(data.get('plate_wells', 'A1-H12')), domain, goal, data)

def load_setup(path: Path, scenario: str | None=None) -> Setup:
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if isinstance(data, dict) and 'scenarios' in data:
        overrides = data['scenarios']
        if not isinstance(overrides, dict):
            raise ValueError('scenarios must be an object of scenario-specific settings.')
        if scenario and scenario in overrides:
            override = overrides[scenario]
            if not isinstance(override, dict):
                raise ValueError(f'The configuration for {scenario} must be an object.')
            data = {**data, **override, 'deck': {**data.get('deck', {}), **override.get('deck', {})}, 'camera': {**data.get('camera', {}), **override.get('camera', {})}}
    return validate_setup(data, base_dir=path.resolve().parent)
