#!/usr/bin/env python3
"""Headless smoke test: mutate a profile action and save/reload (no GUI).

Usage:
  cd configurator
  python scripts/smoke_edit.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macropad_config.models.profile import (  # noqa: E402
    default_profiles_dir,
    load_profile,
    load_profiles_dir,
    save_profile,
)
from macropad_config.models.schema import SchemaError, validate_action  # noqa: E402


def main() -> int:
    profiles_dir = default_profiles_dir()
    print(f"profiles_dir = {profiles_dir}")

    profiles, errors = load_profiles_dir(profiles_dir)
    if errors:
        for err in errors:
            print(f"ERROR  {err.path.name}: {err.message}")
        print("FAIL: unexpected load errors")
        return 1

    default = next((p for p in profiles if p.id == "default"), None)
    if default is None:
        print("FAIL: Default profile not found")
        return 1

    # Mutate key 1 → SHORTCUT Ctrl+C
    action = {"type": "SHORTCUT", "mods": ["CTRL"], "key": "C"}
    validate_action(action)
    default.set_key_action(1, action)

    got = default.action_for_key(1)
    assert got is not None
    assert got["type"] == "SHORTCUT"
    assert got["mods"] == ["CTRL"]
    assert got["key"] == "C"
    print("OK     set_key_action(1, Ctrl+C)")

    # Encoder mutate round-trip
    default.set_encoder_action("long_press", {"type": "MEDIA", "code": "PLAY_PAUSE"})
    enc = default.action_for_encoder("long_press")
    assert enc is not None and enc["type"] == "MEDIA"
    print("OK     set_encoder_action(long_press, PLAY_PAUSE)")

    # Meta
    default.set_name("DEFAULT")
    default.set_oled_title("DEFAULT")
    print("OK     set_name / set_oled_title")

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "Default.json"
        written = save_profile(default, dest)
        print(f"OK     save_profile → {written}")

        text = dest.read_text(encoding="utf-8")
        assert text.endswith("\n"), "expected trailing newline"
        data = json.loads(text)
        assert data["keys"]["1"]["type"] == "SHORTCUT"
        assert data["keys"]["1"]["mods"] == ["CTRL"]
        assert data["keys"]["1"]["key"] == "C"
        assert data["encoder"]["long_press"]["code"] == "PLAY_PAUSE"
        print("OK     JSON contents match")

        reloaded = load_profile(dest)
        a1 = reloaded.action_for_key(1)
        assert a1 is not None
        assert a1["type"] == "SHORTCUT" and a1["key"] == "C"
        print(f"OK     reload id={reloaded.id!r} key1={a1}")

    # validate_action rejection
    try:
        validate_action({"type": "VOLUME", "dir": "sideways"})
        print("FAIL: expected SchemaError for bad VOLUME")
        return 1
    except SchemaError:
        print("OK     validate_action rejects bad VOLUME")

    # Optional GUI import (do not fail step if EGL missing)
    try:
        from macropad_config.widgets.action_editor import ActionEditor  # noqa: F401
        from macropad_config.main_window import MainWindow  # noqa: F401

        print("OK     GUI modules importable")
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP   GUI import ({exc})")

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
