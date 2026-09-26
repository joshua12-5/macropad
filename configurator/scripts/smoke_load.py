#!/usr/bin/env python3
"""Headless smoke test: load all profiles without showing a GUI.

Usage:
  cd configurator
  QT_QPA_PLATFORM=offscreen python scripts/smoke_load.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running without install: add configurator/ to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macropad_config.models.profile import default_profiles_dir, load_profiles_dir
from macropad_config.models.schema import SCHEMA_VERSION


def main() -> int:
    profiles_dir = default_profiles_dir()
    print(f"profiles_dir = {profiles_dir}")
    print(f"schema_version expected = {SCHEMA_VERSION}")

    profiles, errors = load_profiles_dir(profiles_dir)
    for err in errors:
        print(f"ERROR  {err.path.name}: {err.message}")
    for profile in profiles:
        print(
            f"OK     {profile.id:12} name={profile.name!r} "
            f"oled={profile.oled_title!r} keys={len(profile.keys)}"
        )

    print(f"loaded={len(profiles)} errors={len(errors)}")
    # Expect the five shipping profiles; SCHEMA.md is not JSON so no error from it
    if len(profiles) < 5:
        print("FAIL: expected at least 5 profiles")
        return 1
    if errors:
        print("FAIL: unexpected load errors")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
