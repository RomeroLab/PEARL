import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
logger = logging.getLogger(__name__)

class SlotCropRegion(BaseModel):
    """Fractional bounding box for a single deck slot in the camera image.

    ``well_area`` (optional) is a *nested* fractional sub-crop applied to the
    slot crop — used when a slot crop bounds the labware footprint but the
    well grid is inset within it (plate plastic margin, reservoir wall trim,
    etc). Coordinates are fractions of the slot crop (not the full image).
    """
    model_config = ConfigDict(extra='forbid')
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)
    well_area: Optional['SlotCropRegion'] = None

    @model_validator(mode='after')
    def contained(self):
        if self.x+self.w > 1.+1e-12 or self.y+self.h > 1.+1e-12:
            raise ValueError('Crop rectangle must remain inside its parent, within 1e-12 numerical tolerance')
        return self

class DeckCropConfig(BaseModel):
    """Configuration mapping each deck slot to a crop region in the camera image.

    If ``deck_region`` is set, the full camera image is first cropped to just
    the deck area.  Slot regions are then interpreted as fractions of that
    cropped deck image (not the full camera frame).
    """
    model_config = ConfigDict(extra='forbid')
    slots: dict[int, SlotCropRegion]
    deck_region: Optional[SlotCropRegion] = None
    image_width: int = 1280
    image_height: int = 720
    description: str = ''

    def to_pixels(self, slot: int, img_w: int, img_h: int) -> tuple[int, int, int, int]:
        """Convert fractional region to pixel coordinates (x, y, w, h)."""
        r = self.slots[slot]
        return (int(r.x * img_w), int(r.y * img_h), int(r.w * img_w), int(r.h * img_h))

    def crop_deck(self, image: 'np.ndarray') -> 'np.ndarray':
        """Pre-crop full camera image to the deck region.

        Returns the original image unchanged if deck_region is None.
        """
        if self.deck_region is None:
            return image
        ih, iw = image.shape[:2]
        dr = self.deck_region
        x, y = (int(dr.x * iw), int(dr.y * ih))
        w, h = (int(dr.w * iw), int(dr.h * ih))
        return image[y:y + h, x:x + w]

    def crop_slot(self, image: 'np.ndarray', slot: int) -> 'np.ndarray':
        """Crop full camera image to a single slot's well-grid area.

        Pipeline: deck_region → slot bbox → well_area sub-crop (if set).
        Use this whenever you want the final image that should be divided
        into a rows×cols well grid.
        """
        deck = self.crop_deck(image)
        region = self.slots[slot]
        dh, dw = deck.shape[:2]
        sx, sy = (int(region.x * dw), int(region.y * dh))
        sw, sh = (int(region.w * dw), int(region.h * dh))
        slot_img = deck[sy:sy + sh, sx:sx + sw]
        wa = region.well_area
        if wa is not None:
            h, w = slot_img.shape[:2]
            wx, wy = (int(wa.x * w), int(wa.y * h))
            ww, wh = (int(wa.w * w), int(wa.h * h))
            slot_img = slot_img[wy:wy + wh, wx:wx + ww]
        return slot_img
_GRID_DIMS_FOR_CATEGORY: dict[str, tuple[int, int]] = {'plate_96': (8, 12), 'plate_384': (16, 24), 'reservoir_12': (1, 12), 'trough_1': (1, 1)}

def load_crop_config(path):
    if path is None:
        raise ValueError('An explicit camera crop configuration is required')
    return DeckCropConfig.model_validate_json(Path(path).read_text())

def save_crop_config(config: DeckCropConfig, path: Path) -> None:
    """Save crop config to JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(config.model_dump_json(indent=2))
CATEGORY_TO_API: dict[str, str] = {'tip_rack_10': 'opentrons_96_tiprack_10ul', 'tip_rack_20': 'opentrons_96_tiprack_20ul', 'tip_rack_300': 'opentrons_96_tiprack_300ul', 'tip_rack_1000': 'opentrons_96_tiprack_1000ul', 'plate_96': 'corning_96_wellplate_360ul_flat', 'plate_384': 'corning_384_wellplate_112ul_flat', 'reservoir_12': 'nest_12_reservoir_15ml', 'trough_1': 'agilent_1_reservoir_290ml'}
TIP_TO_PIPETTE: dict[str, str] = {'opentrons_96_tiprack_10ul': 'p10_single', 'opentrons_96_tiprack_20ul': 'p20_single', 'opentrons_96_tiprack_300ul': 'p300_single', 'opentrons_96_tiprack_1000ul': 'p1000_single'}
_TIP_CATEGORIES = {'tip_rack_10', 'tip_rack_20', 'tip_rack_300', 'tip_rack_1000'}
_PLATE_CATEGORIES = {'plate_96', 'plate_384'}
_RESERVOIR_CATEGORIES = {'reservoir_12', 'trough_1'}
