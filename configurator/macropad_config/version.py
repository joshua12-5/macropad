"""Shared host version and compatibility helpers (Step 21).

Keep in sync with firmware ``FW_VERSION_*`` / ``CFG_PROTO_VERSION`` and the
matrix in ``docs/VERSIONING.md``.
"""

from __future__ import annotations

from typing import Optional, Tuple

# Host configurator semver (About / Connect display).
HOST_APP_VERSION = "0.21.0"

# Must match firmware CFG_PROTO_VERSION and frames.CFG_PROTO_VERSION.
PROTO_VER = 1

# Expected firmware product revision (informational + feature gates).
FW_VERSION_MAJOR_EXPECTED = 0
FW_VERSION_MINOR_CURRENT = 21

# Minimum FW_VERSION_MINOR (same major) for Device menu features.
MIN_FW_MINOR_UPLOAD = 16          # profile BEGIN/DATA/COMMIT
MIN_FW_MINOR_MACRO_UPLOAD = 17    # macro bank sync
MIN_FW_MINOR_AUTOSWITCH = 18      # SET_ACTIVE / GET_ACTIVE
MIN_FW_MINOR_SAVE_ALL = 19        # SAVE_ALL 0x32

# JSON / blob schema versions (host validators).
PROFILE_SCHEMA_VERSION = 1
MACRO_SCHEMA_VERSION = 1
AUTOSWITCH_SCHEMA_VERSION = 1


def fw_version_string(major: int, minor: int) -> str:
    return f"{int(major)}.{int(minor)}"


def check_proto_ver(device_proto_ver: int) -> Tuple[bool, str]:
    """Return (ok, message). ok False → host must warn; do not assume features."""
    try:
        got = int(device_proto_ver)
    except (TypeError, ValueError):
        return False, (
            f"Device protocol version unknown ({device_proto_ver!r}); "
            f"host expects proto_ver={PROTO_VER}."
        )
    if got != PROTO_VER:
        return False, (
            f"Protocol mismatch: device proto_ver={got}, "
            f"host expects {PROTO_VER}. Upgrade firmware or configurator "
            f"so both sides match (see docs/VERSIONING.md)."
        )
    return True, f"proto_ver={got} OK (host {PROTO_VER})"


def _fw_tuple(
    fw_major: Optional[int], fw_minor: Optional[int]
) -> Optional[Tuple[int, int]]:
    if fw_major is None or fw_minor is None:
        return None
    try:
        return int(fw_major), int(fw_minor)
    except (TypeError, ValueError):
        return None


def fw_at_least(
    fw_major: Optional[int],
    fw_minor: Optional[int],
    *,
    min_minor: int,
    expect_major: int = FW_VERSION_MAJOR_EXPECTED,
) -> bool:
    """True if firmware major matches and minor >= min_minor."""
    pair = _fw_tuple(fw_major, fw_minor)
    if pair is None:
        return False
    major, minor = pair
    return major == expect_major and minor >= int(min_minor)


def fw_supports_upload(fw_major: Optional[int], fw_minor: Optional[int]) -> bool:
    return fw_at_least(fw_major, fw_minor, min_minor=MIN_FW_MINOR_UPLOAD)


def fw_supports_macro_upload(
    fw_major: Optional[int], fw_minor: Optional[int]
) -> bool:
    return fw_at_least(fw_major, fw_minor, min_minor=MIN_FW_MINOR_MACRO_UPLOAD)


def fw_supports_autoswitch(
    fw_major: Optional[int], fw_minor: Optional[int]
) -> bool:
    return fw_at_least(fw_major, fw_minor, min_minor=MIN_FW_MINOR_AUTOSWITCH)


def fw_supports_save_all(
    fw_major: Optional[int], fw_minor: Optional[int]
) -> bool:
    return fw_at_least(fw_major, fw_minor, min_minor=MIN_FW_MINOR_SAVE_ALL)


def feature_disabled_tooltip(feature: str, min_minor: int) -> str:
    return (
        f"{feature} requires firmware "
        f"{FW_VERSION_MAJOR_EXPECTED}.{min_minor}+ "
        f"(host {HOST_APP_VERSION}; see docs/VERSIONING.md)."
    )


def compat_summary(info: dict) -> str:
    """One-line status for Connect / status bar."""
    major = info.get("fw_major")
    minor = info.get("fw_minor")
    proto = info.get("proto_ver")
    fw = fw_version_string(major, minor) if major is not None and minor is not None else "?"
    ok, _ = check_proto_ver(proto if proto is not None else -1)
    flag = "OK" if ok else "MISMATCH"
    return (
        f"host {HOST_APP_VERSION} | fw {fw} | proto v{proto} ({flag}) | "
        f"expect proto {PROTO_VER}"
    )
