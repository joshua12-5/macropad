"""Headless self-test for source and frozen builds (Step 24).

``MacropadConfigurator --self-test`` (or ``python -m macropad_config
--self-test``) imports every module, exercises the protocol / blob code,
loads the bundled data files, checks the hidapi binding actually loads its
native library, runs the HIL suite against the in-process mock device (no
flash writes, no hardware) and finally builds the main window on Qt's
``offscreen`` platform. Exit code 0 = all checks passed.

Release CI runs this on every packaged artifact before publishing.
"""

from __future__ import annotations

import importlib
import os
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable, TextIO

# Every module shipped in the package; importing them catches PyInstaller
# hidden-import misses that a lazy import would only hit at runtime.
MODULES = (
    "macropad_config",
    "macropad_config.app",
    "macropad_config.paths",
    "macropad_config.version",
    "macropad_config.main_window",
    "macropad_config.models.profile",
    "macropad_config.models.macro",
    "macropad_config.models.schema",
    "macropad_config.protocol.frames",
    "macropad_config.protocol.device",
    "macropad_config.protocol.profile_blob",
    "macropad_config.protocol.macro_blob",
    "macropad_config.autoswitch.rules",
    "macropad_config.autoswitch.matcher",
    "macropad_config.autoswitch.foreground",
    "macropad_config.autoswitch.service",
    "macropad_config.hil.suite",
    "macropad_config.hil.mock",
    "macropad_config.hil.cli",
    "macropad_config.widgets.action_editor",
    "macropad_config.widgets.autoswitch_dialog",
    "macropad_config.widgets.macro_library_dialog",
    "macropad_config.widgets.pad_preview",
    "macropad_config.widgets.profile_dialog",
    "macropad_config.widgets.profile_list",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
)


def _chk_version() -> str:
    from . import version as v

    return (f"host {v.HOST_APP_VERSION}, expects fw "
            f"{v.FW_VERSION_MAJOR_EXPECTED}.{v.FW_VERSION_MINOR_CURRENT}, proto {v.PROTO_VER}")


def _chk_imports() -> str:
    for name in MODULES:
        importlib.import_module(name)
    import PySide6

    return f"{len(MODULES)} modules, PySide6 {PySide6.__version__}"


def _chk_frames() -> str:
    from .protocol import frames as F

    assert F.crc32(b"123456789") == 0xCBF43926, "crc32 check value"
    raw = F.pack_frame(F.CFG_CMD_PING, seq=7, payload=b"\x01\x02\x03")
    fr = F.unpack_frame(raw)
    assert fr.cmd == F.CFG_CMD_PING and fr.seq == 7 and bytes(fr.payload) == b"\x01\x02\x03"
    return f"crc32 + frame roundtrip ({len(raw)} B report)"


def _chk_data() -> str:
    from .autoswitch.rules import default_rules_path, load_rules
    from .models.macro import default_macros_path, load_library
    from .models.profile import default_profiles_dir, load_profiles_dir
    from .protocol.macro_blob import pack_macro, unpack_macro
    from .protocol.profile_blob import pack_profile_dict, unpack_profile_dict

    profiles, errors = load_profiles_dir(default_profiles_dir())
    assert profiles, f"no profiles in {default_profiles_dir()}"
    assert not errors, f"profile load errors: {[str(e) for e in errors]}"
    for p in profiles:
        blob = pack_profile_dict(p.to_dict())
        unpack_profile_dict(blob)
    lib = load_library(default_macros_path())
    assert lib.macros, "macro library empty"
    for m in lib.macros:
        unpack_macro(pack_macro(m), macro_id=m.id)
    rules = load_rules(default_rules_path())
    return (f"{len(profiles)} profiles, {len(lib.macros)} macros, "
            f"{len(rules.rules)} autoswitch rules (from {default_profiles_dir().parent})")


def _chk_hid() -> str:
    from .paths import is_frozen
    from .protocol.device import USB_PID, USB_VID, DeviceError, _import_hid, hid_binding_info

    try:
        mod = _import_hid()
    except DeviceError as exc:
        if is_frozen():
            raise  # release bundles must ship a working binding
        return f"WARN: no hid binding in this environment ({exc})"
    info = hid_binding_info(mod)
    # enumerate() forces the native library to load (pyhidapi loads lazily).
    n = len(list(mod.enumerate(USB_VID, USB_PID)))
    return f"{info['module']} ({info['api']}), enumerate ok, {n} macropad(s) attached"


def _chk_hil_mock() -> str:
    from .hil.mock import MockFirmware, MockHidModule
    from .hil.suite import HilOptions, run_suite

    counts = {}
    for api in ("cython", "pyhidapi"):
        mod = MockHidModule(MockFirmware(), api=api)
        rep = run_suite(HilOptions(pings=5, allow_flash_write=False, timeout_ms=200),
                        hid_module=mod, mock=True)
        c = rep.counts
        bad = [f"{r.id}: {r.detail}" for r in rep.results if r.status == "FAIL"]
        assert not bad, f"{api}: " + "; ".join(bad)
        counts[api] = c
    c = counts["cython"]
    return f"mock HIL suite x2 APIs: {c['PASS']} pass / {c['SKIP']} skip / {c['FAIL']} fail each"


def _chk_qt() -> str:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication.instance() or QApplication([sys.argv[0], "-platform",
                                                   os.environ["QT_QPA_PLATFORM"]])
    win = MainWindow()
    win.show()
    for _ in range(5):
        app.processEvents()
    title = win.windowTitle()
    win.close()
    app.processEvents()
    return f"MainWindow ok on '{app.platformName()}' ({title})"


CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("version", _chk_version),
    ("imports", _chk_imports),
    ("frames", _chk_frames),
    ("data", _chk_data),
    ("hid", _chk_hid),
    ("hil_mock", _chk_hil_mock),
    ("qt", _chk_qt),
)


def run_self_test(out: TextIO) -> int:
    from .paths import is_frozen, resource_root

    # Never touch the real user profile dir from a self-test.
    tmp = tempfile.TemporaryDirectory(prefix="macropad-selftest-")
    os.environ.setdefault("MACROPAD_USER_DATA", tmp.name)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    print(f"Macropad Configurator self-test — python {platform.python_version()} "
          f"{platform.machine()} on {platform.platform()}", file=out)
    print(f"  frozen={is_frozen()} resources={resource_root()}", file=out)
    failed = 0
    for name, fn in CHECKS:
        t0 = time.perf_counter()
        try:
            detail = fn()
            status = "WARN" if detail.startswith("WARN") else "PASS"
        except BaseException as exc:  # noqa: BLE001 — report everything
            if isinstance(exc, KeyboardInterrupt):
                raise
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
            failed += 1
            traceback.print_exc(file=out)
        ms = (time.perf_counter() - t0) * 1000.0
        print(f"[{status}] {name:<9} {detail}  ({ms:.0f} ms)", file=out)
        out.flush()
    print(f"SELF-TEST {'FAILED' if failed else 'OK'}: {len(CHECKS) - failed}/{len(CHECKS)} checks passed",
          file=out)
    out.flush()
    try:
        tmp.cleanup()
    except OSError:
        pass
    return 1 if failed else 0


