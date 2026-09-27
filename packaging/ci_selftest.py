#!/usr/bin/env python3
"""Run a packaged MacropadConfigurator's --version and --self-test (release CI).

    python packaging/ci_selftest.py <exe> <report.txt> [--expect-version X.Y.Z]

Works for console-less (windowed) executables too: output is collected via
``--report`` and the process exit code comes from subprocess (no console
needed). Exit 0 only if the exe exits 0 *and* the report says SELF-TEST OK.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(exe: Path, args: list[str], report: Path, timeout: float) -> tuple[int, str]:
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        report.unlink()
    proc = subprocess.run(
        [str(exe), *args, "--report", str(report)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        text=True,
        errors="replace",
    )
    text = report.read_text(encoding="utf-8", errors="replace") if report.exists() else ""
    if proc.stdout and proc.stdout.strip() and (not text or proc.returncode != 0):
        text += "\n--- process stdout/stderr ---\n" + proc.stdout
    return proc.returncode, text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("report")
    ap.add_argument("--expect-version")
    ap.add_argument("--timeout", type=float, default=300.0)
    a = ap.parse_args()
    exe = Path(a.exe).resolve()
    report = Path(a.report).resolve()
    if not exe.is_file():
        print(f"::error::executable not found: {exe}")
        return 1

    with tempfile.TemporaryDirectory() as td:
        code, vtext = run(exe, ["--version"], Path(td) / "version.txt", 120.0)
    print(f"$ {exe.name} --version  → exit {code}\n{vtext.strip()}")
    ok = code == 0 and "Macropad Configurator" in vtext and "(frozen" in vtext
    if a.expect_version and f"Configurator {a.expect_version} " not in vtext:
        print(f"::error::--version does not report {a.expect_version}")
        ok = False

    code, text = run(exe, ["--self-test"], report, a.timeout)
    print(f"$ {exe.name} --self-test → exit {code}\n{text.strip()}")
    report.write_text(vtext.strip() + "\n" + text, encoding="utf-8")
    if code != 0 or "SELF-TEST OK" not in text:
        print(f"::error::self-test failed (exit {code})")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
