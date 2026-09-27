"""QApplication entry for Macropad Configurator.

Command line::

    MacropadConfigurator                 # start the GUI
    MacropadConfigurator --version       # print version info, exit 0
    MacropadConfigurator --self-test [--report FILE]
                                         # headless smoke checks, exit 0/1
    MacropadConfigurator --hil [ARGS]    # run the HIL test tool (hil_test.py)

The same flags work with ``python -m macropad_config``. On Windows the release
build is a GUI-subsystem executable: console output is attached to the parent
console when there is one; ``--report FILE`` always writes a copy to disk.
"""

from __future__ import annotations

import argparse
import sys


def _ensure_console() -> None:
    """Windowed (console-less) builds: attach to the parent console if any."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    if sys.platform.startswith("win"):
        try:
            import ctypes

            if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                sys.stderr = sys.stdout
                return
        except Exception:
            pass
    import os

    null = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = null
    if sys.stderr is None:
        sys.stderr = null if sys.stdout is None else sys.stdout


def version_text() -> str:
    from . import version as v
    from .paths import is_frozen

    kind = "frozen" if is_frozen() else "source"
    return (
        f"Macropad Configurator {v.HOST_APP_VERSION} ({kind}; expects firmware "
        f"{v.FW_VERSION_MAJOR_EXPECTED}.{v.FW_VERSION_MINOR_CURRENT}, "
        f"protocol v{v.PROTO_VER})"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="MacropadConfigurator", description="Macropad Configurator (GUI unless a flag says otherwise)"
    )
    p.add_argument("--version", action="store_true", help="print version and exit")
    p.add_argument(
        "--self-test", action="store_true", help="run headless smoke checks (Qt offscreen) and exit 0/1"
    )
    p.add_argument("--report", metavar="FILE", help="with --self-test/--version: also write output to FILE")
    p.add_argument(
        "--hil",
        nargs=argparse.REMAINDER,
        metavar="ARGS",
        help="run the HIL test tool with ARGS (see --hil --help)",
    )
    return p


class _Tee:
    def __init__(self, *streams) -> None:
        self._s = [s for s in streams if s is not None]

    def write(self, data: str) -> int:
        for s in self._s:
            try:
                s.write(data)
            except Exception:
                pass
        return len(data)

    def flush(self) -> None:
        for s in self._s:
            try:
                s.flush()
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv if argv is None else argv)
    # Qt-style args (-platform, -style …) pass through to QApplication; only
    # intercept our own long options.
    ours = {"--version", "--self-test", "--report", "--hil", "-h", "--help"}
    if any(a.split("=", 1)[0] in ours for a in raw[1:]):
        _ensure_console()
        args = build_parser().parse_args(raw[1:])
        if args.hil is not None:
            from .hil.cli import main as hil_main

            return int(hil_main(args.hil) or 0)
        report = open(args.report, "w", encoding="utf-8") if args.report else None
        out = _Tee(sys.stdout, report)
        try:
            if args.self_test:
                from .selftest import run_self_test

                print(version_text(), file=out)
                return run_self_test(out)
            print(version_text(), file=out)
            return 0
        finally:
            if report is not None:
                report.close()

    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(raw)
    app.setApplicationName("Macropad Configurator")
    app.setOrganizationName("macropad")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
