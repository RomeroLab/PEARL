#!/usr/bin/env python3
"""Run PEARL using an OT-2 and attached computer camera."""
__test__ = False
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent/'src'))
from pearl.production.cli import main
if __name__ == '__main__':
    raise SystemExit(main('chat'))
