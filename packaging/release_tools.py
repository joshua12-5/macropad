#!/usr/bin/env python3
"""Release helpers used by .github/workflows/release.yml.

Stdlib only; run from anywhere::

    python packaging/release_tools.py versions            # JSON: host / fw / changelog
    python packaging/release_tools.py check v0.24.0       # tag == host == fw? (exit 1 if not)
    python packaging/release_tools.py notes v0.24.0 [-o notes.md]
    python packaging/release_tools.py sha256sums DIR [-o DIR/SHA256SUMS.txt]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION_PY = REPO / "configurator" / "macropad_config" / "version.py"
INIT_PY = REPO / "configurator" / "macropad_config" / "__init__.py"
FW_HEADER = REPO / "firmware" / "include" / "config_protocol.h"
CHANGELOG = REPO / "CHANGELOG.md"

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SECTION_RE = re.compile(r"^## \[(?P<ver>[^\]]+)\](?P<rest>.*)$")


class ReleaseError(Exception):
    pass


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def host_version(repo: Path = REPO) -> str:
    m = re.search(r'^HOST_APP_VERSION\s*=\s*"([^"]+)"', _read(repo / VERSION_PY.relative_to(REPO)), re.M)
    if not m:
        raise ReleaseError("HOST_APP_VERSION not found in version.py")
    return m.group(1)


def package_version(repo: Path = REPO) -> str | None:
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', _read(repo / INIT_PY.relative_to(REPO)), re.M)
    return m.group(1) if m else None


def fw_version(repo: Path = REPO) -> tuple[int, int]:
    text = _read(repo / FW_HEADER.relative_to(REPO))
    maj = re.search(r"^#define\s+FW_VERSION_MAJOR\s+(\d+)u?", text, re.M)
    mino = re.search(r"^#define\s+FW_VERSION_MINOR\s+(\d+)u?", text, re.M)
    if not (maj and mino):
        raise ReleaseError("FW_VERSION_MAJOR/MINOR not found in config_protocol.h")
    return int(maj.group(1)), int(mino.group(1))


def host_fw_expected(repo: Path = REPO) -> tuple[int, int]:
    text = _read(repo / VERSION_PY.relative_to(REPO))
    maj = re.search(r"^FW_VERSION_MAJOR_EXPECTED\s*=\s*(\d+)", text, re.M)
    mino = re.search(r"^FW_VERSION_MINOR_CURRENT\s*=\s*(\d+)", text, re.M)
    if not (maj and mino):
        raise ReleaseError("FW_VERSION_*_EXPECTED/CURRENT not found in version.py")
    return int(maj.group(1)), int(mino.group(1))


def changelog_section(version: str, text: str | None = None) -> str:
    """Body of ``## [version] …`` up to the next ``## [`` heading (stripped)."""
    text = _read(CHANGELOG) if text is None else text
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            if inside:
                break
            inside = m.group("ver").strip() == version
            continue
        if inside:
            if re.match(r"^\[[^\]]+\]:\s*\S+", line):  # link-reference footer
                break
            out.append(line)
    if not inside and not out:
        raise ReleaseError(f"CHANGELOG.md has no '## [{version}]' section")
    body = "\n".join(out).strip()
    if not body:
        raise ReleaseError(f"CHANGELOG.md section [{version}] is empty")
    return body


def check(tag: str, repo: Path = REPO) -> list[str]:
    """Return a list of problems (empty = tag consistent with sources)."""
    problems: list[str] = []
    m = TAG_RE.match(tag)
    if not m:
        return [f"tag {tag!r} is not vMAJOR.MINOR.PATCH"]
    ver = tag[1:]
    major, minor = int(m.group(1)), int(m.group(2))
    host = host_version(repo)
    if host != ver:
        problems.append(f"version.py HOST_APP_VERSION {host} != tag {ver}")
    pkg = package_version(repo)
    if pkg is not None and pkg != ver:
        problems.append(f"macropad_config.__version__ {pkg} != tag {ver}")
    fw = fw_version(repo)
    if fw != (major, minor):
        problems.append(f"firmware FW_VERSION {fw[0]}.{fw[1]} != tag {major}.{minor}")
    exp = host_fw_expected(repo)
    if exp != (major, minor):
        problems.append(f"version.py expects firmware {exp[0]}.{exp[1]} != tag {major}.{minor}")
    try:
        changelog_section(ver, _read(repo / CHANGELOG.relative_to(REPO)))
    except ReleaseError as exc:
        problems.append(str(exc))
    return problems


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256sums(directory: Path, output: Path | None = None) -> str:
    output = output or directory / "SHA256SUMS.txt"
    lines = []
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.name != output.name and not p.name.endswith(".sha256"):
            lines.append(f"{sha256_file(p)}  {p.name}")
    text = "\n".join(lines) + "\n"
    output.write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("versions")
    c = sub.add_parser("check")
    c.add_argument("tag")
    n = sub.add_parser("notes")
    n.add_argument("tag")
    n.add_argument("-o", "--output")
    s = sub.add_parser("sha256sums")
    s.add_argument("directory")
    s.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "versions":
            fw = fw_version()
            print(
                json.dumps(
                    {
                        "host": host_version(),
                        "package": package_version(),
                        "fw": f"{fw[0]}.{fw[1]}",
                        "tag": f"v{host_version()}",
                    }
                )
            )
            return 0
        if args.cmd == "check":
            problems = check(args.tag)
            for p in problems:
                print(f"::error::{p}")
            if not problems:
                print(f"OK: {args.tag} matches version.py, __init__.py, FW_VERSION and CHANGELOG")
            return 1 if problems else 0
        if args.cmd == "notes":
            ver = args.tag[1:] if args.tag.startswith("v") else args.tag
            body = changelog_section(ver)
            if args.output:
                Path(args.output).write_text(body + "\n", encoding="utf-8")
            else:
                print(body)
            return 0
        if args.cmd == "sha256sums":
            d = Path(args.directory)
            print(sha256sums(d, Path(args.output) if args.output else None), end="")
            return 0
    except ReleaseError as exc:
        print(f"::error::{exc}")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
