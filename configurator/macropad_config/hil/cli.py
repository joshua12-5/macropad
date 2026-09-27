"""Command line for the HIL suite. See ``--help``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .. import version as ver
from ..protocol.device import CFG_USAGE_PAGE, USB_PID, USB_VID, DeviceError, list_config_devices
from .suite import FAIL, PASS, SKIP, TEST_IDS, HilOptions, run_suite

EPILOG = f"""\
tests (in order): {", ".join(TEST_IDS)}

flash wear: PROFILE/MACRO COMMIT, SAVE_ALL and ANIM_SETTINGS_SET each erase+program
the 4 KiB storage sector and an animation upload rewrites animation-region sectors, so
profile_roundtrip / macro_roundtrip / save_all / anim_settings / anim_roundtrip are
SKIPPED unless --allow-flash-write is given (a full write run costs 7 storage-sector
writes plus a few animation-region sectors). All other tests are flash-free on fw 0.23+.

exit codes: 0 = no FAIL, 1 = at least one FAIL, 2 = no device / cannot open.

examples:
  python scripts/hil_test.py --list
  python scripts/hil_test.py                       # flash-free suite on hardware
  python scripts/hil_test.py --allow-flash-write --json hil.json
  python scripts/hil_test.py --mock --allow-flash-write   # headless / CI
  python scripts/hil_test.py --interactive         # + guided key/encoder checklist
"""

_COLORS = {PASS: "\033[32m", FAIL: "\033[31m", SKIP: "\033[33m"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hil_test.py",
        description="Hardware-in-the-loop tests for the macropad vendor config HID "
        f"interface (VID {USB_VID:#06x} PID {USB_PID:#06x}, usage page "
        f"{CFG_USAGE_PAGE:#06x}). Host {ver.HOST_APP_VERSION}.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--list", action="store_true", help="list matching HID interfaces and exit")
    p.add_argument("--mock", action="store_true", help="run against the in-process mock device")
    p.add_argument(
        "--mock-fw-minor",
        type=int,
        default=ver.FW_VERSION_MINOR_CURRENT,
        metavar="N",
        help="firmware minor the mock reports (default %(default)s)",
    )
    p.add_argument(
        "--mock-api",
        choices=("cython", "pyhidapi"),
        default="pyhidapi",
        help="hid module flavour the mock imitates (default %(default)s)",
    )
    p.add_argument("--path", help="open this hidapi path instead of auto-selecting")
    p.add_argument(
        "--allow-flash-write",
        action="store_true",
        help="enable COMMIT round-trips and SAVE_ALL (writes flash)",
    )
    p.add_argument(
        "--slot",
        type=int,
        choices=range(5),
        metavar="0-4",
        help="profile slot for upload tests (default: active+1)",
    )
    p.add_argument(
        "--macro-id",
        type=int,
        choices=range(5),
        default=4,
        metavar="0-4",
        help="macro id for upload tests (default 4)",
    )
    p.add_argument("--pings", type=int, default=20, metavar="N", help="PING count (default 20)")
    p.add_argument("--seed", type=int, default=23, help="RNG seed for ECHO payloads")
    p.add_argument("--timeout-ms", type=int, default=500, help="per-request timeout (default 500)")
    p.add_argument(
        "--strict-version", action="store_true", help="FAIL (not warn) when fw minor != host-expected minor"
    )
    p.add_argument(
        "--interactive", action="store_true", help="guided key/encoder checklist (prompts on stdin)"
    )
    p.add_argument("--only", metavar="IDS", help="comma-separated test ids to run")
    p.add_argument("--skip", metavar="IDS", help="comma-separated test ids to skip")
    p.add_argument("--json", metavar="FILE", help="write a JSON report ('-' = stdout)")
    p.add_argument("--no-color", action="store_true", help="plain PASS/FAIL/SKIP labels")
    p.add_argument("-q", "--quiet", action="store_true", help="only print the summary")
    return p


def _split(s: Optional[str]) -> Optional[list[str]]:
    if not s:
        return None
    ids = [x.strip() for x in s.split(",") if x.strip()]
    bad = [x for x in ids if x not in TEST_IDS]
    if bad:
        raise SystemExit(f"unknown test id(s): {', '.join(bad)} (choose from {', '.join(TEST_IDS)})")
    return ids


def _make_mock(args):
    from .mock import MockFirmware, MockHidModule

    return MockHidModule(MockFirmware(fw_minor=args.mock_fw_minor), api=args.mock_api)


def cmd_list(hid_module) -> int:
    try:
        devs = list_config_devices(USB_VID, USB_PID, hid_module=hid_module)
    except DeviceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not devs:
        print(f"no HID interfaces for VID {USB_VID:#06x} PID {USB_PID:#06x}")
        return 2
    for d in devs:
        path = d.get("path")
        path_s = path.decode("latin-1") if isinstance(path, bytes) else str(path)
        mark = "CONFIG" if d.get("_match_config") else "      "
        bcd = d.get("release_number")
        print(
            f"{mark}  IF{d.get('interface_number', '?')}  usage {int(d.get('usage_page') or 0):#06x}/"
            f"{int(d.get('usage') or 0):#04x}  bcd {int(bcd or 0):#06x}  "
            f"{d.get('product_string') or ''!s:<24} serial {d.get('serial_number') or '-'}  path {path_s}"
        )
    return 0


def main(argv: Optional[list[str]] = None, *, hid_module=None, prompt=None, stream=None) -> int:
    args = build_parser().parse_args(argv)
    out = stream or sys.stdout
    color = not args.no_color and hasattr(out, "isatty") and out.isatty()
    if args.mock and hid_module is None:
        hid_module = _make_mock(args)

    if args.list:
        return cmd_list(hid_module)

    opts = HilOptions(
        pings=args.pings,
        seed=args.seed,
        allow_flash_write=args.allow_flash_write,
        profile_slot=args.slot,
        macro_id=args.macro_id,
        strict_version=args.strict_version,
        interactive=args.interactive,
        timeout_ms=args.timeout_ms,
        only=_split(args.only),
        skip=_split(args.skip),
        path=args.path.encode("latin-1") if args.path else None,
    )

    def label(status: str) -> str:
        return f"{_COLORS[status]}{status}\033[0m" if color else status

    def on_result(r) -> None:
        if args.quiet:
            return
        print(f"[{label(r.status)}] {r.title}  ({r.duration_ms:.0f} ms)", file=out)
        if r.detail:
            print(f"       {r.detail}", file=out)
        for n in r.notes:
            print(f"       - {n}", file=out)
        out.flush()

    target = "MOCK device" if args.mock else "hardware"
    if not args.quiet:
        print(
            f"hil_test: host {ver.HOST_APP_VERSION}, expects fw "
            f"{ver.FW_VERSION_MAJOR_EXPECTED}.{ver.FW_VERSION_MINOR_CURRENT}; target {target}; "
            f"flash writes {'ENABLED' if args.allow_flash_write else 'disabled'}",
            file=out,
        )
        print("-" * 72, file=out)
    report = run_suite(
        opts,
        hid_module=hid_module,
        mock=args.mock,
        prompt=prompt,
        log=lambda m: print(m, file=out),
        on_result=on_result,
    )
    c = report.counts
    if hasattr(hid_module, "firmware"):
        report.options["mock_flash_writes"] = hid_module.firmware.flash_writes
    print("-" * 72, file=out)
    print(f"SUMMARY  pass={c[PASS]} fail={c[FAIL]} skip={c[SKIP]}  exit={report.exit_code}", file=out)
    for r in report.results:
        if r.status == FAIL:
            print(f"  FAIL {r.id}: {r.detail}", file=out)
    if args.json:
        data = json.dumps(report.to_dict(), indent=2, default=str)
        if args.json == "-":
            print(data, file=out)
        else:
            with open(args.json, "w", encoding="utf-8") as fh:
                fh.write(data + "\n")
            print(f"JSON report → {args.json}", file=out)
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
