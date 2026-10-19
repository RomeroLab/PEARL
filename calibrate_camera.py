#!/usr/bin/env python3
"""Capture a fixed blank calibration JSON from an attached computer camera."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent/'src'))
from pearl.production.calibration_cli import main
if __name__ == '__main__':
    raise SystemExit(main())
