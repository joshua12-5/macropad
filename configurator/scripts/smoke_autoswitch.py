#!/usr/bin/env python3
"""Headless smoke: autoswitch matcher + rules load/validate (no hardware).

Usage:
  cd configurator
  python scripts/smoke_autoswitch.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from macropad_config.autoswitch.matcher import (  # noqa: E402
    BUILTIN_SLOT_MAP,
    match_foreground,
    process_basename,
    resolve_slot,
)
from macropad_config.autoswitch.rules import (  # noqa: E402
    RulesError,
    default_rules_path,
    load_rules,
    validate_rules,
)


def expect(cond: bool, msg: str = "") -> None:
    if not cond:
        raise AssertionError(msg or "expectation failed")


def test_load_default_rules() -> None:
    path = default_rules_path()
    expect(path.is_file(), f"missing {path}")
    rules = load_rules(path)
    expect(rules.schema_version == 1)
    expect(rules.enabled is False)
    expect(rules.poll_ms == 750)
    expect(len(rules.rules) >= 4)
    ids = {r.profile_id for r in rules.rules}
    expect({"coding", "browser", "photoshop", "gaming"} <= ids)


def test_basename() -> None:
    expect(process_basename(r"C:\Program Files\Code.exe") == "Code")
    expect(process_basename("/usr/bin/firefox") == "firefox")
    expect(process_basename("chrome.exe") == "chrome")


def test_match_coding() -> None:
    rules = load_rules()
    r = match_foreground(rules, "Code", "main.py — Visual Studio Code")
    expect(r.profile_id == "coding", r)
    expect(r.slot == 2, r)
    expect(r.rule_index == 0, r)


def test_match_browser_casefold() -> None:
    rules = load_rules()
    r = match_foreground(rules, "FIREFOX", "Mozilla Firefox")
    expect(r.profile_id == "browser", r)
    expect(r.slot == BUILTIN_SLOT_MAP["browser"], r)


def test_match_photoshop() -> None:
    rules = load_rules()
    r = match_foreground(rules, "Photoshop.exe", "Untitled-1")
    expect(r.profile_id == "photoshop", r)
    expect(r.slot == 4, r)


def test_match_gaming() -> None:
    rules = load_rules()
    r = match_foreground(rules, "steam", "Steam")
    expect(r.profile_id == "gaming", r)
    expect(r.slot == 1, r)


def test_first_rule_wins() -> None:
    data = {
        "schema_version": 1,
        "enabled": True,
        "poll_ms": 500,
        "fallback_profile_id": "default",
        "rules": [
            {"profile_id": "coding", "process": ["code"], "title_regex": None},
            {"profile_id": "browser", "process": ["code"], "title_regex": None},
        ],
    }
    rules = validate_rules(data)
    r = match_foreground(rules, "code")
    expect(r.profile_id == "coding")
    expect(r.rule_index == 0)


def test_title_regex() -> None:
    data = {
        "schema_version": 1,
        "enabled": True,
        "poll_ms": 500,
        "fallback_profile_id": None,
        "rules": [
            {
                "profile_id": "coding",
                "process": ["chrome"],
                "title_regex": r"GitHub",
            },
            {
                "profile_id": "browser",
                "process": ["chrome"],
                "title_regex": None,
            },
        ],
    }
    rules = validate_rules(data)
    r = match_foreground(rules, "chrome", "GitHub - issues")
    expect(r.profile_id == "coding", r)
    r2 = match_foreground(rules, "chrome", "News")
    expect(r2.profile_id == "browser", r2)


def test_fallback() -> None:
    data = {
        "schema_version": 1,
        "enabled": True,
        "poll_ms": 500,
        "fallback_profile_id": "default",
        "rules": [
            {"profile_id": "coding", "process": ["Code"], "title_regex": None},
        ],
    }
    rules = validate_rules(data)
    r = match_foreground(rules, "notepad")
    expect(r.profile_id == "default")
    expect(r.slot == 0)
    expect(r.reason == "fallback")


def test_no_match_no_change() -> None:
    data = {
        "schema_version": 1,
        "enabled": True,
        "poll_ms": 500,
        "fallback_profile_id": None,
        "rules": [
            {"profile_id": "coding", "process": ["Code"], "title_regex": None},
        ],
    }
    rules = validate_rules(data)
    r = match_foreground(rules, "notepad")
    expect(r.profile_id is None)
    expect(r.slot is None)
    expect(r.reason == "no_match")


def test_explicit_slot() -> None:
    data = {
        "schema_version": 1,
        "enabled": True,
        "poll_ms": 500,
        "fallback_profile_id": None,
        "rules": [
            {
                "profile_id": "custom",
                "process": ["foo"],
                "title_regex": None,
                "slot": 3,
            },
        ],
    }
    rules = validate_rules(data)
    r = match_foreground(rules, "foo-bar")
    expect(r.profile_id == "custom")
    expect(r.slot == 3)


def test_host_list_index() -> None:
    slot = resolve_slot("myprof", host_profile_ids=["a", "b", "myprof", "c", "d"])
    expect(slot == 2)
    expect(resolve_slot("missing", host_profile_ids=["a"]) is None)


def test_validate_rejects_bad() -> None:
    try:
        validate_rules({"schema_version": 99, "rules": []})
        raise AssertionError("expected RulesError")
    except RulesError:
        pass
    try:
        validate_rules(
            {
                "schema_version": 1,
                "poll_ms": 1,
                "rules": [{"profile_id": "x", "process": ["y"]}],
            }
        )
        raise AssertionError("expected RulesError for poll_ms")
    except RulesError:
        pass


def test_set_active_constant() -> None:
    from macropad_config.protocol.frames import (
        CFG_CMD_GET_ACTIVE,
        CFG_CMD_SET_ACTIVE,
        pack_frame,
        unpack_frame,
    )

    expect(CFG_CMD_SET_ACTIVE == 0x30)
    expect(CFG_CMD_GET_ACTIVE == 0x31)
    raw = pack_frame(CFG_CMD_SET_ACTIVE, 7, bytes([2]))
    fr = unpack_frame(raw)
    expect(fr.cmd == 0x30)
    expect(fr.payload == b"\x02")


def main() -> int:
    tests = [
        test_load_default_rules,
        test_basename,
        test_match_coding,
        test_match_browser_casefold,
        test_match_photoshop,
        test_match_gaming,
        test_first_rule_wins,
        test_title_regex,
        test_fallback,
        test_no_match_no_change,
        test_explicit_slot,
        test_host_list_index,
        test_validate_rejects_bad,
        test_set_active_constant,
    ]
    failed = 0
    for t in tests:
        name = t.__name__
        try:
            t()
            print(f"PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
    if failed:
        print(f"\n{failed}/{len(tests)} failed")
        return 1
    print(f"\nAll {len(tests)} smoke_autoswitch tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
