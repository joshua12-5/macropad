"""Device backup / restore (Device page → Back up… / Restore…).

A backup is a small JSON file holding what the device keeps in its flash
image: every profile slot and macro-bank blob (read back with PROFILE_READ /
MACRO_READ, fw 0.23+), the active slot and, on fw 0.25+, the idle-animation
settings. Animation *frames* are not included (keep the ``.mpanim`` project;
the Idle animation page can upload it again).

Restore uploads every blob, restores the idle settings and active slot, then
issues SAVE_ALL so flash matches immediately. Blobs are validated (size and
the blob's own CRC via the unpackers) before anything is sent.

Pure protocol code, no Qt: ``ConfigDevice``-compatible object in, dict out.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import version as app_version
from .protocol.macro_blob import MACRO_BLOB_V1_SIZE, unpack_macro
from .protocol.profile_blob import PROFILE_BLOB_V1_SIZE, unpack_profile_dict

BACKUP_FORMAT = "macropad-device-backup"
BACKUP_VERSION = 1
BACKUP_SUFFIX = ".mpbackup.json"
MACRO_BANK_SIZE = 5


class BackupError(ValueError):
    """Unsupported firmware, malformed backup file, or a blob that fails validation."""


def _fw(info: dict) -> tuple[int | None, int | None]:
    return info.get("fw_major"), info.get("fw_minor")


def read_backup(dev, info: dict) -> dict:
    """Read every profile slot, macro and setting from an open device."""
    if not app_version.fw_supports_readback(*_fw(info)):
        raise BackupError(
            app_version.feature_disabled_tooltip("Device backup", app_version.MIN_FW_MINOR_READBACK)
        )
    slots = int(info.get("slot_count") or 5)
    profiles = [dev.profile_read(i).hex() for i in range(slots)]
    macros = [dev.macro_read(i).hex() for i in range(MACRO_BANK_SIZE)]
    try:
        active = int(dev.get_active_slot())
    except Exception:
        active = int(info.get("active_slot") or 0)
    data: dict = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host_app": app_version.HOST_APP_VERSION,
        "firmware": f"{info.get('fw_major', '?')}.{info.get('fw_minor', '?')}",
        "active_slot": active,
        "profiles": profiles,
        "macros": macros,
    }
    if app_version.fw_supports_anim(*_fw(info)):
        s = dev.anim_settings_get()
        data["idle"] = {
            "enabled": bool(s["enabled"]),
            "idle_timeout_s": int(s["idle_timeout_s"]),
            "blank_timeout_s": int(s["blank_timeout_s"]),
        }
    return data


def validate_backup(data: object) -> dict:
    """Check structure, sizes and blob CRCs; returns the dict with ``bytes`` blobs added."""
    if not isinstance(data, dict) or data.get("format") != BACKUP_FORMAT:
        raise BackupError("Not a macropad device backup (missing format marker).")
    if data.get("version") != BACKUP_VERSION:
        raise BackupError(f"Unsupported backup version {data.get('version')!r} (expected {BACKUP_VERSION}).")
    out = dict(data)
    for key, size, unpack in (
        ("profiles", PROFILE_BLOB_V1_SIZE, unpack_profile_dict),
        ("macros", MACRO_BLOB_V1_SIZE, unpack_macro),
    ):
        items = data.get(key)
        if not isinstance(items, list) or not items:
            raise BackupError(f"Backup has no {key}.")
        blobs = []
        for i, h in enumerate(items):
            try:
                blob = bytes.fromhex(str(h))
            except ValueError as exc:
                raise BackupError(f"{key}[{i}]: not hex ({exc})") from None
            if len(blob) != size:
                raise BackupError(f"{key}[{i}]: {len(blob)} bytes, expected {size}")
            try:
                unpack(blob)
            except Exception as exc:
                raise BackupError(f"{key}[{i}]: {exc}") from None
            blobs.append(blob)
        out[f"_{key}_bytes"] = blobs
    active = data.get("active_slot", 0)
    if not isinstance(active, int) or not 0 <= active < len(out["_profiles_bytes"]):
        raise BackupError(f"active_slot {active!r} out of range")
    idle = data.get("idle")
    if idle is not None and not (
        isinstance(idle, dict) and {"enabled", "idle_timeout_s", "blank_timeout_s"} <= set(idle)
    ):
        raise BackupError("idle settings incomplete")
    return out


def restore_backup(dev, info: dict, data: dict) -> list[str]:
    """Upload a validated backup to an open device. Returns a list of what was restored."""
    data = validate_backup(data)
    if not app_version.fw_supports_upload(*_fw(info)):
        raise BackupError(app_version.feature_disabled_tooltip("Restore", app_version.MIN_FW_MINOR_UPLOAD))
    slots = int(info.get("slot_count") or 5)
    done: list[str] = []
    profiles = data["_profiles_bytes"][:slots]
    for slot, blob in enumerate(profiles):
        dev.upload_profile(slot, blob)
    done.append(f"{len(profiles)} profile slot(s)")
    if app_version.fw_supports_macro_upload(*_fw(info)):
        for mid, blob in enumerate(data["_macros_bytes"][:MACRO_BANK_SIZE]):
            dev.upload_macro(mid, blob)
        done.append(f"{min(MACRO_BANK_SIZE, len(data['_macros_bytes']))} macro(s)")
    idle = data.get("idle")
    if idle and app_version.fw_supports_anim(*_fw(info)):
        dev.anim_settings_set(
            enabled=bool(idle["enabled"]),
            idle_timeout_s=int(idle["idle_timeout_s"]),
            blank_timeout_s=int(idle["blank_timeout_s"]),
        )
        done.append("idle settings")
    active = int(data.get("active_slot", 0))
    if app_version.fw_supports_autoswitch(*_fw(info)) and active < slots:
        dev.set_active_slot(active)
        done.append(f"active slot {active}")
    if app_version.fw_supports_save_all(*_fw(info)):
        dev.save_all()
        done.append("saved to flash")
    return done


def write_backup_file(data: dict, path: Path | str) -> Path:
    path = Path(path)
    clean = {k: v for k, v in data.items() if not k.startswith("_")}
    path.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    return path


def load_backup_file(path: Path | str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError(f"Could not read {path}: {exc}") from None
    return validate_backup(data)


__all__ = [
    "BACKUP_FORMAT",
    "BACKUP_SUFFIX",
    "BACKUP_VERSION",
    "BackupError",
    "load_backup_file",
    "read_backup",
    "restore_backup",
    "validate_backup",
    "write_backup_file",
]
