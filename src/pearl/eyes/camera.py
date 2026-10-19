"""Camera capture for plate imaging using OpenCV."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging
import numpy as np
logger = logging.getLogger(__name__)

def summarize_camera_lock(*, want_manual_exposure: bool, want_manual_wb: bool, want_manual_focus: bool, auto_exposure: float, auto_wb: float, autofocus: float, exposure: float, wb: float, focus: float) -> tuple[str, list[str]]:
    """Compare requested manual-lock intent vs what the driver reports back.

    UVC webcams frequently accept ``cap.set(...)`` silently but keep running
    in auto mode, so the only reliable "did it lock?" signal is reading the
    AUTO flags back. The lock VALUES (exposure/WB) are logged but NOT asserted
    — their scale is driver-dependent (e.g. V4L2 exposure is absolute units,
    some backends use −13..−1), so an exact match can't be required.

    V4L2 convention: ``CAP_PROP_AUTO_EXPOSURE`` 1 = manual, 3 = auto;
    ``CAP_PROP_AUTO_WB`` 0 = manual (off), 1 = auto; ``CAP_PROP_AUTOFOCUS``
    0 = off, 1 = on.

    Returns ``(summary_line, warnings)``. ``warnings`` is empty when every
    requested manual lock reads back as engaged.
    """
    warnings: list[str] = []
    if want_manual_exposure and auto_exposure not in (1.0, 0.0):
        warnings.append(f'auto-exposure still ON (CAP_PROP_AUTO_EXPOSURE={auto_exposure}; expected 1=manual) — exposure NOT locked')
    if want_manual_wb and auto_wb not in (0.0,):
        warnings.append(f'auto white-balance still ON (CAP_PROP_AUTO_WB={auto_wb}; expected 0=off) — white balance NOT locked')
    if want_manual_focus and autofocus not in (0.0,):
        warnings.append(f'autofocus still ON (CAP_PROP_AUTOFOCUS={autofocus}; expected 0=off) — focus NOT locked')
    summary = f'camera readback: auto_exposure={auto_exposure} exposure={exposure} | auto_wb={auto_wb} wb={wb} | autofocus={autofocus} focus={focus}'
    return (summary, warnings)

class PlateCamera:

    def __init__(self, camera_id: int=0, output_dir: Optional[Path]=None, width: int=1920, height: int=1080, fixed_focus: float=50, fixed_exposure: float=-1, fixed_wb: int=4500):
        """Initialize plate camera.

        Args:
            camera_id: OpenCV camera device ID (0 for default webcam)
            output_dir: Directory to save captured images
            width: Capture width in pixels
            height: Capture height in pixels
            fixed_focus: Disable autofocus and lock to this value
                (0=infinity, 255=closest). Default 50 (overhead deck).
            fixed_exposure: Disable auto exposure and lock to this
                value. Range: -13 to -1 (darker to brighter). Default -1.
            fixed_wb: Disable auto white balance and lock to this
                color temperature in Kelvin. Default 4500K.
        """
        self.camera_id = camera_id
        self.output_dir = Path(output_dir) if output_dir else Path('./captures')
        self.width = width
        self.height = height
        self.fixed_focus = fixed_focus
        self.fixed_exposure = fixed_exposure
        self.fixed_wb = fixed_wb
        self._cap = None
        self._is_initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    def initialize(self) -> bool:
        """Initialize camera connection.

        Returns:
            True if successful, False otherwise
        """
        try:
            import cv2
            self._cap = cv2.VideoCapture(self.camera_id)
            if not self._cap.isOpened():
                logger.error(f'Failed to open camera {self.camera_id}')
                return False
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            if self.fixed_focus is not None:
                self._cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                self._cap.set(cv2.CAP_PROP_FOCUS, self.fixed_focus)
                logger.info(f'Fixed focus set to {self.fixed_focus}')
            if self.fixed_exposure is not None:
                self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
                self._cap.set(cv2.CAP_PROP_EXPOSURE, self.fixed_exposure)
                logger.info(f'Fixed exposure set to {self.fixed_exposure}')
            if self.fixed_wb is not None:
                self._cap.set(cv2.CAP_PROP_AUTO_WB, 0)
                self._cap.set(cv2.CAP_PROP_WB_TEMPERATURE, self.fixed_wb)
                logger.info(f'Fixed white balance set to {self.fixed_wb}K')
            import time
            for _ in range(15):
                self._cap.read()
            time.sleep(0.5)
            if self.fixed_focus is not None:
                self._cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                self._cap.set(cv2.CAP_PROP_FOCUS, self.fixed_focus)
            if self.fixed_exposure is not None:
                self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
                self._cap.set(cv2.CAP_PROP_EXPOSURE, self.fixed_exposure)
            if self.fixed_wb is not None:
                self._cap.set(cv2.CAP_PROP_AUTO_WB, 0)
                self._cap.set(cv2.CAP_PROP_WB_TEMPERATURE, self.fixed_wb)
            for _ in range(5):
                self._cap.read()
            summary, lock_warnings = summarize_camera_lock(want_manual_exposure=self.fixed_exposure is not None, want_manual_wb=self.fixed_wb is not None, want_manual_focus=self.fixed_focus is not None, auto_exposure=self._cap.get(cv2.CAP_PROP_AUTO_EXPOSURE), auto_wb=self._cap.get(cv2.CAP_PROP_AUTO_WB), autofocus=self._cap.get(cv2.CAP_PROP_AUTOFOCUS), exposure=self._cap.get(cv2.CAP_PROP_EXPOSURE), wb=self._cap.get(cv2.CAP_PROP_WB_TEMPERATURE), focus=self._cap.get(cv2.CAP_PROP_FOCUS))
            logger.info(summary)
            for w in lock_warnings:
                logger.warning(f'camera lock: {w}')
            self.effective_settings = self.readback()
            self._is_initialized = True
            logger.info(f'Camera {self.camera_id} initialized ({self.width}x{self.height})')
            return True
        except ImportError:
            raise ImportError('OpenCV (cv2) not found. Install with:\n  conda install -c conda-forge opencv\n  OR: pip install opencv-python')
        except Exception as e:
            logger.error(f'Camera initialization failed: {e}')
            return False

    def readback(self):
        import cv2
        import math
        if self._cap is None:
            return None
        properties = {'auto_exposure': cv2.CAP_PROP_AUTO_EXPOSURE,
            'exposure': cv2.CAP_PROP_EXPOSURE, 'auto_white_balance': cv2.CAP_PROP_AUTO_WB,
            'white_balance': cv2.CAP_PROP_WB_TEMPERATURE, 'auto_focus': cv2.CAP_PROP_AUTOFOCUS,
            'focus': cv2.CAP_PROP_FOCUS}
        state = {}
        for name, prop in properties.items():
            try:
                value = float(self._cap.get(prop))
                state[name] = value if math.isfinite(value) else None
            except Exception:
                state[name] = None
        state['manual_controls_verified'] = (
            state['auto_exposure'] in (0., 1.) and state['auto_white_balance'] == 0.
            and state['auto_focus'] == 0.
            and all(state[k] is not None for k in ('exposure', 'white_balance', 'focus'))
            and state['white_balance'] > 0)
        return state

    def release(self) -> None:
        """Release camera resources."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._is_initialized = False
        logger.info('Camera released')

    def capture_raw(self, *, drain: int=4, n_frames: int=1) -> Optional[np.ndarray]:
        """Capture a fresh raw frame, optionally median-stacked over N reads.

        USB webcams hold 1-3 frames in their buffer, so a naïve ``read()``
        can return a frame from up to ~100ms ago. ``drain`` ``grab()`` calls
        discard those before the real read. ``n_frames > 1`` then captures
        N consecutive frames and returns their per-pixel median, which
        smooths out per-frame noise (sensor jitter, exposure micro-flicker)
        without the ghosting that mean-blending produces if anything moves.

        Args:
            drain: Frames to grab+discard before capturing (clears USB buffer).
            n_frames: Frames to capture and median-stack. 1 = single frame.

        Returns:
            BGR image as numpy array, or None if all reads failed.
        """
        if not self._is_initialized:
            raise RuntimeError('Camera not initialized. Call initialize() first.')
        for _ in range(drain):
            self._cap.grab()
        if n_frames <= 1:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                logger.error('Failed to capture frame')
                return None
            return frame
        frames = []
        for _ in range(n_frames):
            ret, frame = self._cap.read()
            if ret and frame is not None:
                frames.append(frame)
        if not frames:
            logger.error('Failed to capture any of %d frames', n_frames)
            return None
        stack = np.stack(frames, axis=0)
        return np.median(stack, axis=0).astype(np.uint8)
