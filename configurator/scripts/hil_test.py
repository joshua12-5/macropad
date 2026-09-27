#!/usr/bin/env python3
"""Hardware-in-the-loop tests over the vendor config HID interface.

Usage:
  cd configurator
  python scripts/hil_test.py --list
  python scripts/hil_test.py [--allow-flash-write] [--json report.json]
  python scripts/hil_test.py --mock            # headless, no hardware

See ``--help`` and docs/HARDWARE_TEST.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macropad_config.hil.cli import main

if __name__ == "__main__":
    sys.exit(main())
