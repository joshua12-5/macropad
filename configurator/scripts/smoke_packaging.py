#!/usr/bin/env python3
"""Headless smoke: release packaging helpers.

* ``packaging/release_tools.py``: tag ↔ version.py ↔ FW_VERSION ↔ CHANGELOG
  check (current tree passes; a mismatched copy fails), CHANGELOG section
  extraction, SHA256SUMS generation.
* ``macropad_config.paths``: source-mode resource root, first-run seeding of
  the user data dir (never overwrites user files).
* Entry point: ``python -m macropad_config --version`` and the non-Qt part of
  ``--self-test`` (the full Qt check runs in release CI on every runner).

Usage:
  cd configurator
  python scripts/smoke_packaging.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO / "packaging"))

import release_tools as rt

from macropad_config import __version__, paths, selftest
from macropad_config import version as ver

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  FAIL: {msg}")


def main() -> int:
    tag = f"v{ver.HOST_APP_VERSION}"

    # --- release_tools against the real tree ---------------------------------
    expect(rt.host_version() == ver.HOST_APP_VERSION == __version__, "host/package version mismatch")
    expect(
        rt.fw_version() == (ver.FW_VERSION_MAJOR_EXPECTED, ver.FW_VERSION_MINOR_CURRENT),
        f"FW_VERSION {rt.fw_version()} != version.py expectation",
    )
    problems = rt.check(tag)
    expect(problems == [], f"check({tag}) problems: {problems}")
    expect(rt.check("v9.9.9") != [], "check(v9.9.9) should fail")
    expect(rt.check("0.24.0") != [] and rt.check("v0.24") != [], "malformed tags accepted")
    notes = rt.changelog_section(ver.HOST_APP_VERSION)
    expect("###" in notes and "## [" not in notes, "notes should hold one section only")
    expect("[Unreleased]:" not in notes, "link footer leaked into notes")
    expect(rt.main(["check", tag]) == 0, "CLI check exit != 0")

    sample = (
        "# Changelog\n\n## [Unreleased]\n\n- wip\n\n## [1.2.3] — 2026-01-01\n\n### Added\n\n"
        "- thing\n\n## [1.2.2] — 2025-12-01\n\n- old\n\n[1.2.3]: https://x/y\n"
    )
    expect(rt.changelog_section("1.2.3", sample) == "### Added\n\n- thing", "section parse")
    expect(rt.changelog_section("1.2.2", sample) == "- old", "last section / footer stop")
    try:
        rt.changelog_section("1.0.0", sample)
        expect(False, "missing section should raise")
    except rt.ReleaseError:
        pass

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        # Mismatched firmware version in a copy of the tree must be caught.
        for rel in (
            "configurator/macropad_config/version.py",
            "configurator/macropad_config/__init__.py",
            "firmware/include/config_protocol.h",
            "CHANGELOG.md",
        ):
            (t / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, t / rel)
        expect(rt.check(tag, repo=t) == [], "copied tree should pass")
        h = t / "firmware/include/config_protocol.h"
        h.write_text(
            h.read_text().replace(
                f"FW_VERSION_MINOR        {ver.FW_VERSION_MINOR_CURRENT}u", "FW_VERSION_MINOR        99u"
            )
        )
        p = rt.check(tag, repo=t)
        expect(any("firmware FW_VERSION" in x for x in p), f"fw mismatch not detected: {p}")

        # SHA256SUMS
        a = t / "assets"
        a.mkdir()
        (a / "b.zip").write_bytes(b"bbb")
        (a / "a.uf2").write_bytes(b"aaa")
        (a / "a.uf2.sha256").write_text("x")
        text = rt.sha256sums(a)
        lines = text.strip().splitlines()
        expect(
            lines
            == [
                f"{hashlib.sha256(b'aaa').hexdigest()}  a.uf2",
                f"{hashlib.sha256(b'bbb').hexdigest()}  b.zip",
            ],
            f"sha256sums: {lines}",
        )
        expect((a / "SHA256SUMS.txt").read_text() == text, "SHA256SUMS.txt not written")

        # --- paths: seeding ---------------------------------------------------
        expect(paths.resource_root() == REPO, f"resource_root {paths.resource_root()}")
        expect(not paths.is_frozen(), "source run reported frozen")
        dest = t / "user"
        paths.seed_user_data(dest, REPO)
        n_prof = len(list((REPO / "profiles").glob("*.json")))
        expect(len(list((dest / "profiles").glob("*.json"))) == n_prof, "profiles not seeded")
        expect((dest / "macros/library.json").is_file(), "macro library not seeded")
        expect((dest / "autoswitch/rules.json").is_file(), "rules not seeded")
        (dest / "macros/library.json").write_text('{"user": true}')
        (dest / "profiles/Gaming.json").unlink()
        paths.seed_user_data(dest, REPO)
        expect(
            json.loads((dest / "macros/library.json").read_text()) == {"user": True},
            "seeding overwrote user macro library",
        )
        expect(not (dest / "profiles/Gaming.json").exists(), "deleted profile resurrected")
        os.environ["MACROPAD_USER_DATA"] = str(dest)
        expect(paths.user_data_dir() == dest, "MACROPAD_USER_DATA ignored")
        del os.environ["MACROPAD_USER_DATA"]

    # --- entry point ---------------------------------------------------------
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run(
        [sys.executable, "-m", "macropad_config", "--version"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    expect(proc.returncode == 0, f"--version exit {proc.returncode}: {proc.stderr[-300:]}")
    expect(
        f"Macropad Configurator {ver.HOST_APP_VERSION} (source" in proc.stdout,
        f"--version output: {proc.stdout!r}",
    )

    # Non-Qt self-test checks in-process (Qt/imports need a GUI-capable libEGL).
    for name, fn in selftest.CHECKS:
        if name in ("imports", "qt"):
            continue
        try:
            detail = fn()
            print(f"  self-test {name}: {detail}")
        except Exception as exc:
            expect(False, f"self-test check {name}: {type(exc).__name__}: {exc}")

    if FAILS:
        print(f"smoke_packaging: {len(FAILS)} failure(s)")
        return 1
    print("smoke_packaging: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
