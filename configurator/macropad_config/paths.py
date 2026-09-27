"""Filesystem locations for bundled defaults and user data.

Two run modes:

* **Source checkout** (``python -m macropad_config``): everything lives in the
  repository — ``profiles/``, ``macros/library.json``, ``autoswitch/rules.json``
  at the repo root. Behaviour is unchanged from earlier steps.
* **Frozen build** (PyInstaller, ``sys.frozen``): read-only defaults are
  bundled under ``<bundle>/data``. On first run they are copied (never
  overwritten) into a per-user writable directory:

  - Windows: ``%APPDATA%\\MacropadConfigurator``
  - macOS:   ``~/Library/Application Support/MacropadConfigurator``
  - Linux:   ``$XDG_DATA_HOME/macropad-configurator`` (``~/.local/share/...``)

``MACROPAD_USER_DATA`` overrides the user directory; the older per-file
variables (``MACROPAD_PROFILES_DIR``, ``MACROPAD_MACROS_PATH``,
``MACROPAD_AUTOSWITCH_PATH``) still win over both.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_DIRNAME = "MacropadConfigurator"
APP_DIRNAME_XDG = "macropad-configurator"

# Relative paths (under resource_root) seeded into the user data dir.
SEED_ITEMS = ("profiles", "macros/library.json", "autoswitch/rules.json")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Directory holding read-only defaults (profiles/, macros/, autoswitch/)."""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
        return Path(base) / "data"
    # macropad_config/paths.py → parents[2] = repo root
    return Path(__file__).resolve().parents[2]


def user_data_dir() -> Path:
    env = os.environ.get("MACROPAD_USER_DATA")
    if env:
        return Path(env).expanduser()
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIRNAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIRNAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIRNAME_XDG


def seed_user_data(dest: Path | None = None, src: Path | None = None) -> Path:
    """Copy bundled defaults into *dest* without overwriting existing files."""
    dest = Path(dest) if dest else user_data_dir()
    src = Path(src) if src else resource_root()
    for rel in SEED_ITEMS:
        s = src / rel
        d = dest / rel
        if s.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            # Only seed an empty profiles dir: a user who deleted a stock
            # profile should not see it resurrected on every launch.
            if any(d.glob("*.json")):
                continue
            for f in sorted(s.glob("*.json")):
                shutil.copy2(f, d / f.name)
        elif s.is_file() and not d.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
    return dest


def data_root() -> Path:
    """Read/write root for profiles/, macros/, autoswitch/."""
    if is_frozen():
        try:
            return seed_user_data()
        except OSError:
            # Read-only home (kiosk / sandbox): fall back to bundled defaults.
            return resource_root()
    return resource_root()
