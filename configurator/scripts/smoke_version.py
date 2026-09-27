#!/usr/bin/env python3
"""Headless smoke: version module imports + compat helpers.

Usage:
  cd configurator
  python scripts/smoke_version.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def expect(cond: bool, msg: str = "assertion failed") -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    from macropad_config import version as ver
    from macropad_config.autoswitch import rules as as_rules
    from macropad_config.models.macro import MACRO_SCHEMA_VERSION
    from macropad_config.models.schema import SCHEMA_VERSION
    from macropad_config.protocol import frames

    print("smoke_version: imports OK")

    expect(ver.HOST_APP_VERSION == "0.25.0", f"HOST_APP={ver.HOST_APP_VERSION}")
    expect(ver.PROTO_VER == 1, f"PROTO_VER={ver.PROTO_VER}")
    expect(ver.FW_VERSION_MINOR_CURRENT == 25, "FW minor current")
    expect(ver.PROTO_VER == frames.CFG_PROTO_VERSION, "PROTO vs frames")
    expect(ver.PROFILE_SCHEMA_VERSION == SCHEMA_VERSION == 1)
    expect(ver.MACRO_SCHEMA_VERSION == MACRO_SCHEMA_VERSION == 1)
    expect(ver.AUTOSWITCH_SCHEMA_VERSION == as_rules.SCHEMA_VERSION == 1)

    ok, msg = ver.check_proto_ver(1)
    expect(ok, msg)
    bad, bmsg = ver.check_proto_ver(99)
    expect(not bad, "proto 99 should fail")
    expect("mismatch" in bmsg.lower() or "expects" in bmsg.lower(), bmsg)

    # Feature gates: current fw unlocks all; old minors gate correctly.
    expect(ver.fw_supports_upload(0, 24))
    expect(ver.fw_supports_macro_upload(0, 24))
    expect(ver.fw_supports_autoswitch(0, 24))
    expect(ver.fw_supports_save_all(0, 24))

    expect(ver.fw_supports_upload(0, 16))
    expect(not ver.fw_supports_upload(0, 15))
    expect(not ver.fw_supports_macro_upload(0, 16))
    expect(ver.fw_supports_macro_upload(0, 17))
    expect(not ver.fw_supports_autoswitch(0, 17))
    expect(ver.fw_supports_autoswitch(0, 18))
    expect(not ver.fw_supports_save_all(0, 18))
    expect(ver.fw_supports_save_all(0, 19))
    expect(ver.MIN_FW_MINOR_READBACK == 23)
    expect(ver.fw_supports_readback(0, 23))
    expect(ver.fw_supports_readback(0, 24))
    expect(not ver.fw_supports_readback(0, 22))
    expect(ver.MIN_FW_MINOR_ANIM == 25)
    expect(ver.fw_supports_anim(0, 25))
    expect(not ver.fw_supports_anim(0, 24))
    expect(frames.CFG_INFO_FLAG_ANIM == 0x08)
    expect(frames.CFG_CMD_ANIM_BEGIN == 0x40 and frames.CFG_CMD_ANIM_PREVIEW == 0x48)

    # Wrong major never unlocks.
    expect(not ver.fw_supports_upload(1, 99))
    expect(not ver.fw_supports_autoswitch(None, 24))

    tip = ver.feature_disabled_tooltip("Upload", ver.MIN_FW_MINOR_UPLOAD)
    expect("0.16+" in tip or "0.16" in tip, tip)

    summary = ver.compat_summary({"fw_major": 0, "fw_minor": 25, "proto_ver": 1})
    expect("0.25.0" in summary and "OK" in summary, summary)
    bad_sum = ver.compat_summary({"fw_major": 0, "fw_minor": 24, "proto_ver": 2})
    expect("MISMATCH" in bad_sum, bad_sum)

    print(f"  HOST_APP_VERSION={ver.HOST_APP_VERSION}")
    print(f"  PROTO_VER={ver.PROTO_VER}  frames.CFG_PROTO_VERSION={frames.CFG_PROTO_VERSION}")
    print(f"  FW current={ver.FW_VERSION_MAJOR_EXPECTED}.{ver.FW_VERSION_MINOR_CURRENT}")
    print("  schemas profile/macro/autoswitch=1/1/1")
    print(f"  compat_summary: {summary}")
    print("smoke_version: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"smoke_version: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
