#!/usr/bin/env python3
"""Headless smoke: HIL suite against the in-process mock macropad (Step 23).

Runs ``hil_test`` end-to-end through the real ConfigDevice / frames code with
``macropad_config.hil.mock`` standing in for hidapi + firmware, and checks the
suite also *catches* seeded firmware bugs.

Usage:
  cd configurator
  python scripts/smoke_hil_mock.py
"""

from __future__ import annotations

import io
import json
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macropad_config.hil import cli  # noqa: E402
from macropad_config.hil.mock import (  # noqa: E402
    MockFirmware,
    MockHidModule,
    fw_macro_canon,
    fw_profile_canon,
)
from macropad_config.hil.suite import test_macro_blob, test_profile_blob  # noqa: E402
from macropad_config.protocol import frames as F  # noqa: E402
from macropad_config.protocol.macro_blob import pack_macro  # noqa: E402
from macropad_config.protocol.profile_blob import pack_profile_dict  # noqa: E402

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  FAIL: {msg}")


def run(argv, *, fw=None, api="pyhidapi", prompt=None, present=True):
    fw = fw or MockFirmware()
    mod = MockHidModule(fw, api=api, present=present)
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        jpath = Path(td) / "r.json"
        code = cli.main(list(argv) + ["--json", str(jpath), "--pings", "5"],
                        hid_module=mod, prompt=prompt, stream=buf)
        data = json.loads(jpath.read_text()) if jpath.exists() else {}
    status = {r["id"]: r["status"] for r in data.get("results", [])}
    return code, status, data, fw, buf.getvalue()


def main() -> int:
    print("smoke_hil_mock: canonical blobs")
    import glob

    for p in sorted(glob.glob(str(ROOT.parent / "profiles" / "*.json"))):
        blob = pack_profile_dict(json.loads(Path(p).read_text()))
        expect(fw_profile_canon(blob) == blob, f"host profile pack not canonical: {p}")
    lib = json.loads((ROOT.parent / "macros" / "library.json").read_text())
    for m in lib["macros"]:
        blob = pack_macro(m)
        expect(fw_macro_canon(blob) == blob, f"host macro pack not canonical: {m.get('name')}")
    expect(fw_profile_canon(test_profile_blob()) == test_profile_blob(), "test profile blob canonical")
    expect(fw_macro_canon(test_macro_blob()) == test_macro_blob(), "test macro blob canonical")
    # Host fix: steps after the first END are dropped (firmware truncates there).
    trailing = pack_macro({"name": "t", "steps": [{"op": "TAP", "key": "A"}, {"op": "END"},
                                                  {"op": "TAP", "key": "B"}]})
    expect(trailing[16] == 2 and fw_macro_canon(trailing) == trailing, "pack_macro truncates at END")
    # Firmware quirks mirrored: 16-char names lose the last char, bad schema/count rejected.
    raw = bytearray(test_profile_blob()); raw[2:18] = b"ABCDEFGHIJKLMNOP"
    expect(fw_profile_canon(bytes(raw))[2:18] == b"ABCDEFGHIJKLMNO\x00", "name NUL at [15]")
    raw[0] = 2
    expect(fw_profile_canon(bytes(raw)) is None, "schema 2 rejected")
    m = bytearray(test_macro_blob()); m[16] = 25
    expect(fw_macro_canon(bytes(m)) is None, "step_count 25 rejected")

    print("smoke_hil_mock: default (flash-free) run, fw 0.23")
    code, st, data, fw, out = run(["--mock"])
    expect(code == 0, f"default exit {code}\n{out}")
    expect(data["summary"]["FAIL"] == 0, f"failures: {data['summary']}")
    for tid in ("enumerate", "ping", "info", "echo", "malformed", "profile", "macro", "active",
                "restore_check"):
        expect(st.get(tid) == "PASS", f"{tid} = {st.get(tid)}")
    for tid in ("profile_roundtrip", "macro_roundtrip", "save_all", "interactive"):
        expect(st.get(tid) == "SKIP", f"{tid} should SKIP without flags, got {st.get(tid)}")
    fw.advance(5.0)  # let the SET_ACTIVE debounce fire
    expect(fw.flash_writes == 0, f"flash-free run wrote flash {fw.flash_writes}x")
    expect("stor debounce skip (unchanged)" in fw.log, "debounce skip not exercised")
    ping = next(r for r in data["results"] if r["id"] == "ping")
    expect({"min_ms", "avg_ms", "max_ms"} <= set(ping["metrics"]), "latency metrics")

    print("smoke_hil_mock: --allow-flash-write, both hid APIs")
    for api in ("pyhidapi", "cython"):
        code, st, data, fw, out = run(["--mock", "--allow-flash-write"], api=api)
        expect(code == 0 and data["summary"]["FAIL"] == 0, f"{api}: flash run failed\n{out}")
        expect(st.get("profile_roundtrip") == "PASS" and st.get("macro_roundtrip") == "PASS"
               and st.get("save_all") == "PASS", f"{api}: roundtrips {st}")
        expect(fw.flash_writes == 5, f"{api}: expected 5 flash writes, got {fw.flash_writes}")
        expect(fw.flash_image_valid_v2(), "flash image invalid after run")
        expect(fw.upload_kind == 0, "upload left open")

    print("smoke_hil_mock: Step 22 firmware (no readback)")
    code, st, data, fw, out = run(["--mock"], fw=MockFirmware(fw_minor=22))
    expect(code == 0, f"fw22 exit {code}\n{out}")
    expect(st.get("active") == "SKIP", "fw22 active should SKIP without flash flag")
    expect("WARN fw 0.22" in out, "fw22 version warning missing")
    code, st, _d, _fw, _o = run(["--mock", "--strict-version"], fw=MockFirmware(fw_minor=22))
    expect(code == 1 and st.get("info") == "FAIL", "--strict-version should FAIL fw22")
    fw22 = MockFirmware(fw_minor=22)
    code, st, _d, fw22, out = run(["--mock", "--only", "active", "--allow-flash-write"], fw=fw22)
    fw22.advance(5.0)
    expect(code == 0 and fw22.flash_writes == 1, f"fw22 debounced persist writes={fw22.flash_writes}")

    print("smoke_hil_mock: interactive checklist")
    answers = iter(["y"] * 15)
    code, st, _d, _fw, _o = run(["--mock", "--only", "interactive", "--interactive"],
                                prompt=lambda _q: next(answers))
    expect(code == 0 and st.get("interactive") == "PASS", f"interactive all-yes {st}")
    answers = iter(["y", "n"] + ["y"] * 13)
    code, st, _d, _fw, _o = run(["--mock", "--only", "interactive", "--interactive"],
                                prompt=lambda _q: next(answers))
    expect(code == 1 and st.get("interactive") == "FAIL", "interactive 'n' should FAIL")

    print("smoke_hil_mock: suite catches seeded firmware bugs")

    class BadMagicNak(MockFirmware):
        def _validate(self, buf):
            err = super()._validate(buf)
            return F.CFG_ERR_EINVAL if err == F.CFG_ERR_EBADMSG and buf[0] != 0x50 else err

    code, st, _d, _fw, _o = run(["--mock"], fw=BadMagicNak())
    expect(code == 1 and st.get("malformed") == "FAIL", f"bad-magic NAK bug not caught {st}")

    class NoBusy(MockFirmware):
        def handle(self, req):
            if req[4] == F.CFG_CMD_MACRO_BEGIN and self.upload_kind == 1:
                self.upload_kind = 0  # bug: silently drops the profile upload
            return super().handle(req)

    code, st, _d, _fw, _o = run(["--mock"], fw=NoBusy())
    expect(code == 1 and st.get("macro") == "FAIL", f"EBUSY bug not caught {st}")

    class Lossy(MockFirmware):
        def _upload_commit(self, kind):
            err = super()._upload_commit(kind)
            if err == 0 and kind == 1:
                p = bytearray(self.profiles[self.upload_slot]); p[146] ^= 1
                self.profiles[self.upload_slot] = bytes(p)
            return err

    code, st, _d, _fw, _o = run(["--mock", "--allow-flash-write"], fw=Lossy())
    expect(st.get("profile_roundtrip") == "FAIL", f"lossy commit not caught {st}")

    class NoResp(MockFirmware):
        def handle(self, req):
            return None if req[4] == F.CFG_CMD_GET_ACTIVE else super().handle(req)

    code, st, _d, _fw, _o = run(["--mock"], fw=NoResp())
    expect(code == 1 and st.get("active") == "FAIL", f"missing response not caught {st}")

    print("smoke_hil_mock: no device / --list")
    code, st, data, _fw, _o = run(["--mock"], present=False)
    expect(code == 2 and st.get("enumerate") == "FAIL", f"no-device exit {code}")
    expect(all(s == "SKIP" for k, s in st.items() if k != "enumerate"), "tests after no-device SKIP")
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        lcode = cli.main(["--mock", "--list"], hid_module=MockHidModule())
    finally:
        sys.stdout = old
    expect(lcode == 0 and "CONFIG" in buf.getvalue() and "0xff00" in buf.getvalue(), "--list output")

    # Short OUT report path (config_protocol_on_host_report len < 64).
    fw = MockFirmware()
    resp = fw.on_host_report(F.pack_frame(F.CFG_CMD_PING, 9)[:20])
    frame = F.unpack_frame(resp)
    expect(frame.cmd == F.CFG_CMD_NAK and frame.payload == bytes([F.CFG_ERR_EBADMSG]) and frame.seq == 9,
           "short report → NAK EBADMSG")
    expect(fw.on_host_report(b"\x01\x02") is None, "<6 byte report → no reply")
    _ = struct  # keep import for readers poking at frames

    if FAILS:
        print(f"smoke_hil_mock: {len(FAILS)} FAILURE(S)")
        return 1
    print("smoke_hil_mock: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
