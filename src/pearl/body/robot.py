"""Robot connection and control management for Opentrons."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Literal
import logging
logger = logging.getLogger(__name__)
PIPETTE_MAX_VOLUMES: dict[str, float] = {'p10_single': 10.0, 'p20_single': 20.0, 'p300_single': 300.0, 'p1000_single': 1000.0}

@dataclass
class DeckLayout:
    """Standard deck layout for color mixing experiments.

    Supports dual-pipette configuration (default: p20 left + p300 right).

    ``reservoir_slot`` / ``reservoir_type`` are ``None`` when no reservoir
    is present on the deck.  Consumers must guard on ``None`` before
    using reservoir fields.

    ``secondary_pipette_type`` is ``None`` to disable the secondary pipette
    and run in single-pipette mode.
    """
    plate_slot: int = 2
    plate_type: str = 'corning_96_wellplate_360ul_flat'
    additional_plates: list[tuple[int, str]] = field(default_factory=list)
    reservoir_slot: Optional[int] = None
    reservoir_type: Optional[str] = None
    labware_z_offset: float = 0.0
    tiprack_slot: int = 1
    tiprack_type: str = 'opentrons_96_tiprack_300ul'
    extra_tiprack_slots: list[int] = field(default_factory=list)
    pipette_type: str = 'p300_single'
    pipette_mount: str = 'right'
    secondary_tiprack_slot: Optional[int] = 4
    secondary_tiprack_type: Optional[str] = 'opentrons_96_tiprack_20ul'
    secondary_extra_tiprack_slots: list[int] = field(default_factory=list)
    secondary_pipette_type: Optional[str] = 'p20_single'
    secondary_pipette_mount: Optional[str] = 'left'

    @property
    def has_secondary_pipette(self) -> bool:
        """Whether a secondary pipette is configured."""
        return self.secondary_pipette_type is not None

    def select_pipette_for_volume(self, volume: float) -> str:
        """Return 'primary' or 'secondary' based on volume.

        Uses the secondary (smaller) pipette when volume fits within its range,
        for better precision.  Falls back to primary otherwise.
        """
        if not self.has_secondary_pipette:
            return 'primary'
        secondary_max = PIPETTE_MAX_VOLUMES.get(self.secondary_pipette_type, 0)
        if volume <= secondary_max:
            return 'secondary'
        return 'primary'

    def all_plates(self) -> list[tuple[int, str]]:
        """Return [(slot, name), ...] for every plate on the deck.

        Single-plate (BC): primary keeps the name 'plate'.
        Multi-plate: primary auto-renames to 'plate_1' for consistency
        with extras 'plate_2', 'plate_3', ...
        """
        primary_name = 'plate_1' if self.additional_plates else 'plate'
        return [(self.plate_slot, primary_name)] + list(self.additional_plates)
