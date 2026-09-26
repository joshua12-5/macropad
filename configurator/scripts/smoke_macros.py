#!/usr/bin/env python3
"""Headless smoke test: load/validate/round-trip macro library (no GUI).

Usage:
  cd configurator
  python scripts/smoke_macros.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macropad_config.models.macro import (  # noqa: E402
    MacroStep,
    default_macros_path,
    load_library,
    macro_names,
    save_library,
)


def main() -> int:
    path = default_macros_path()
    print(f"macros_path = {path}")

    library = load_library(path)
    print(f"schema_version = {library.schema_version}")
    print(f"macros = {len(library.macros)}")

    if len(library.macros) < 5:
        print(f"FAIL: expected at least 5 macros, got {len(library.macros)}")
        return 1

    by_id = {m.id: m for m in library.macros}
    for expected_id in range(5):
        if expected_id not in by_id:
            print(f"FAIL: missing macro id {expected_id}")
            return 1

    hello = by_id[0]
    print(f"macro 0 name = {hello.name!r} steps = {len(hello.steps)}")
    if hello.name != "hello":
        print(f"FAIL: expected name 'hello', got {hello.name!r}")
        return 1

    # Validate hello steps: TAP H, DELAY 30, TAP E, ... END
    ops = [s.op for s in hello.steps]
    if ops[-1] != "END":
        print("FAIL: hello must end with END")
        return 1
    taps = [s for s in hello.steps if s.op == "TAP"]
    keys = "".join(s.key for s in taps)
    if keys != "HELLO":
        print(f"FAIL: hello TAP keys expected HELLO, got {keys!r}")
        return 1
    delays = [s for s in hello.steps if s.op == "DELAY_MS"]
    if not delays or any(s.arg != 30 for s in delays):
        print(f"FAIL: hello delays expected 30 ms, got {[s.arg for s in delays]}")
        return 1

    # Spot-check alt-tab KEY_UP all-release
    alt = by_id[4]
    if alt.name != "alt-tab":
        print(f"FAIL: macro 4 name expected alt-tab, got {alt.name!r}")
        return 1
    ups = [s for s in alt.steps if s.op == "KEY_UP"]
    if not ups or ups[0].key not in ("",):
        print(f"FAIL: alt-tab KEY_UP should use empty key, got {ups}")
        return 1

    names = macro_names(path)
    print(f"macro_names = {names}")
    if names.get(0) != "hello":
        print("FAIL: macro_names missing hello")
        return 1

    # Round-trip to temp
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "library.json"
        save_library(library, dest)
        again = load_library(dest)
        if again.to_dict() != library.to_dict():
            print("FAIL: round-trip dict mismatch")
            print("orig:", json.dumps(library.to_dict(), indent=2)[:500])
            print("again:", json.dumps(again.to_dict(), indent=2)[:500])
            return 1
        # Ensure file is valid JSON and pretty
        raw = json.loads(dest.read_text(encoding="utf-8"))
        if len(raw["macros"]) != len(library.macros):
            print("FAIL: saved macro count mismatch")
            return 1

    # Validate a constructed step
    step = MacroStep.from_dict({"op": "TAP", "mods": ["CTRL"], "key": "C"})
    assert step.op == "TAP" and step.mods == ["CTRL"] and step.key == "C"

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
