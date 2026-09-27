#!/usr/bin/env python3
"""Headless smoke test: profile factory new/duplicate/delete (no GUI).

Usage:
  cd configurator
  python scripts/smoke_profile_mgr.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macropad_config.models.profile import (
    delete_profile_file,
    duplicate_profile,
    is_valid_profile_id,
    load_profile,
    make_blank_profile,
    save_profile,
    suggest_profile_id,
    suggest_profile_path,
)
from macropad_config.models.schema import validate_profile_dict


def main() -> int:
    # --- suggest_profile_id ---
    ids: set[str] = {"default", "gaming"}
    assert suggest_profile_id("My Cool Pad", ids) == "my_cool_pad"
    assert suggest_profile_id("DEFAULT", ids) == "default_2"
    assert suggest_profile_id("123 go", ids) == "p_123_go"
    assert suggest_profile_id("", ids) == "profile"
    assert is_valid_profile_id("my_cool_pad")
    assert not is_valid_profile_id("MyPad")
    assert not is_valid_profile_id("1bad")
    print("OK     suggest_profile_id / is_valid_profile_id")

    # --- make_blank → validate → save → load ---
    blank = make_blank_profile("scratch", "Scratch")
    assert blank.id == "scratch"
    assert blank.name == "Scratch"
    assert blank.oled_title == "Scratch"
    assert blank.source_path is None
    for i in range(1, 13):
        a = blank.action_for_key(i)
        assert a is not None and a["type"] == "DISABLED"
    assert blank.action_for_encoder("cw") == {"type": "VOLUME", "dir": "up"}
    assert blank.action_for_encoder("ccw") == {"type": "VOLUME", "dir": "down"}
    assert blank.action_for_encoder("press") == {"type": "VOLUME", "dir": "mute"}
    assert blank.action_for_encoder("long_press") == {"type": "DISABLED"}
    validate_profile_dict(blank.to_dict())
    print("OK     make_blank_profile validates")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        dest = suggest_profile_path(blank.name, blank.id, tmp_path)
        assert dest.name == "Scratch.json"
        written = save_profile(blank, dest)
        assert written == dest
        assert dest.is_file()
        reloaded = load_profile(dest)
        assert reloaded.id == "scratch"
        assert reloaded.action_for_key(1)["type"] == "DISABLED"
        assert reloaded.action_for_encoder("cw")["dir"] == "up"
        print(f"OK     save/load blank → {written.name}")

        # clash → fall back to id
        clash = suggest_profile_path("Scratch", "scratch_alt", tmp_path)
        assert clash.name == "scratch_alt.json"
        print("OK     suggest_profile_path uniqueness")

        # --- duplicate ---
        blank.set_key_action(3, {"type": "KEY", "key": "X"})
        dup = duplicate_profile(blank, "scratch_copy", "Scratch Copy")
        assert dup.id == "scratch_copy"
        assert dup.name == "Scratch Copy"
        assert dup.source_path is None
        assert dup.action_for_key(3) == blank.action_for_key(3)
        assert dup.action_for_key(3) is not blank.action_for_key(3)  # deep copy
        # mutate source must not affect duplicate
        blank.set_key_action(3, {"type": "DISABLED"})
        assert dup.action_for_key(3)["type"] == "KEY"
        print("OK     duplicate_profile deep copy")

        # --- delete file ---
        delete_profile_file(reloaded)
        assert not dest.exists()
        assert reloaded.source_path is None
        # no-op when already cleared
        delete_profile_file(reloaded)
        print("OK     delete_profile_file")

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
