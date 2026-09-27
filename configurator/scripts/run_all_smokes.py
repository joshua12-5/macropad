#!/usr/bin/env python3
"""Run all headless configurator smoke scripts; non-zero if any fail.

Usage:
  cd configurator
  python scripts/run_all_smokes.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SMOKES = [
    "smoke_version.py",
    "smoke_protocol.py",
    "smoke_storage.py",
    "smoke_macros_blob.py",
    "smoke_autoswitch.py",
    "smoke_load.py",
    "smoke_edit.py",
    "smoke_profile_mgr.py",
    "smoke_macros.py",
    "smoke_hil_mock.py",
    "smoke_anim_codec.py",
    "smoke_anim_device.py",
    "smoke_packaging.py",
]


def main() -> int:
    results: list[tuple[str, int]] = []
    print(f"run_all_smokes: {len(SMOKES)} scripts under {ROOT / 'scripts'}")
    print("-" * 60)

    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    for name in SMOKES:
        script = ROOT / "scripts" / name
        if not script.is_file():
            print(f"MISSING  {name}")
            results.append((name, 127))
            continue
        print(f"RUN      {name}")
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            env=env,
        )
        status = proc.returncode
        label = "PASS" if status == 0 else "FAIL"
        print(f"{label}     {name} (exit {status})")
        print("-" * 60)
        results.append((name, status))

    failed = [(n, c) for n, c in results if c != 0]
    print()
    print("SUMMARY")
    for name, code in results:
        print(f"  {'PASS' if code == 0 else 'FAIL':4}  {name}")
    print(
        f"total={len(results)} passed={len(results) - len(failed)} "
        f"failed={len(failed)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
