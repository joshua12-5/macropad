#!/usr/bin/env python3
"""Headless smoke: command palette (Ctrl+K) — fuzzy ranking + keyboard handling.

* fuzzy_score / rank_items unit checks ("k6" → Key 6, "cod" → CODING, "up" → Upload profile…).
* Ctrl+K opens the palette over the window; typing filters; Up/Down/Tab move; Enter runs the
  highlighted page / profile / key / action / theme item; disabled items (device actions while
  not connected) are listed but do not run; Esc and Ctrl+K close it.

Usage:
  cd configurator
  QT_QPA_PLATFORM=offscreen python scripts/smoke_palette.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.TemporaryDirectory()
T = Path(_TMP.name)
shutil.copytree(REPO / "profiles", T / "profiles")
(T / "macros").mkdir()
shutil.copy(REPO / "macros" / "library.json", T / "macros" / "library.json")
os.environ["MACROPAD_PROFILES_DIR"] = str(T / "profiles")
os.environ["MACROPAD_MACROS_PATH"] = str(T / "macros" / "library.json")
(T / "rules.json").write_text('{"schema_version": 1, "enabled": false, "rules": []}', encoding="utf-8")
os.environ["MACROPAD_AUTOSWITCH_PATH"] = str(T / "rules.json")
os.environ["MACROPAD_ANIMATIONS_DIR"] = str(T / "animations")
os.environ.setdefault("MACROPAD_THEME", "dark")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  FAIL: {msg}")


def pump(app, n: int = 6) -> None:
    for _ in range(n):
        app.processEvents()


def unit_checks() -> None:
    from macropad_config.pages.palette import PaletteItem, fuzzy_score, rank_items

    noop = lambda: None  # noqa: E731
    items = [
        PaletteItem("Go to Keys", "Page", noop, keywords="Keys page keys"),
        PaletteItem("Go to Device", "Page", noop, keywords="Device page device"),
        PaletteItem("CODING", "Profile", noop, subtitle="coding · slot 1", keywords="CODING coding profile"),
        PaletteItem("GAMING", "Profile", noop, keywords="GAMING gaming profile"),
        *[PaletteItem(f"Key {n}", "Key", noop, keywords=f"key{n} k{n}") for n in range(1, 13)],
        PaletteItem("Upload profile to device…", "Action", noop, subtitle="Device", enabled=False),
        PaletteItem("Upload macros to device…", "Action", noop, subtitle="Device"),
        PaletteItem("Connect / refresh device", "Action", noop, subtitle="Device"),
        PaletteItem("Toggle dark / light theme", "Action", noop, keywords="theme dark light"),
    ]

    def top(q: str) -> str | None:
        r = rank_items(q, items)
        return r[0].title if r else None

    expect(top("k6") == "Key 6", f"'k6' → {top('k6')}")
    expect(top("key 12") == "Key 12", f"'key 12' → {top('key 12')}")
    expect(top("key 1") == "Key 1", f"'key 1' → {top('key 1')}")
    expect(top("cod") == "CODING", f"'cod' → {top('cod')}")
    expect(top("gam") == "GAMING", f"'gam' → {top('gam')}")
    expect(top("upload mac") == "Upload macros to device…", f"'upload mac' → {top('upload mac')}")
    expect(top("up") and top("up").startswith("Upload"), f"'up' → {top('up')}")
    expect(top("theme") == "Toggle dark / light theme", f"'theme' → {top('theme')}")
    expect(top("dev") == "Go to Device", f"'dev' → {top('dev')}")
    expect(top("zzqx") is None, "no match → empty")
    expect(fuzzy_score("", "anything") == 0.0, "empty query scores 0")
    expect(fuzzy_score("gtk", "Go to Keys") is not None, "subsequence match")
    expect(fuzzy_score("xyz", "Go to Keys") is None, "non-subsequence rejected")
    expect(
        (fuzzy_score("key", "Key 6") or 0) > (fuzzy_score("key", "Monkey business") or 0),
        "word-start beats mid-word",
    )
    blank = rank_items("", items)
    expect([it.category for it in blank][:2] == ["Page", "Page"], "empty query lists pages first")
    expect(top("slot 1") == "CODING", "subtitle matches count")
    # disabled items rank just below an equal enabled one
    up = [it.title for it in rank_items("upload", items)]
    expect(
        up.index("Upload macros to device…") < up.index("Upload profile to device…"),
        f"disabled ranks lower {up}",
    )


def ui_checks(app) -> None:
    from macropad_config.main_window import MainWindow

    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    win.activateWindow()
    pump(app, 10)

    items = win.palette_items()
    cats = {c: sum(1 for it in items if it.category == c) for c in ("Page", "Profile", "Key", "Action")}
    n_prof = len(win._profile_list.profiles())
    expect(cats["Page"] == 6, f"6 page items ({cats})")
    expect(cats["Profile"] == n_prof, f"{n_prof} profile items ({cats})")
    expect(cats["Key"] == 12 + 3, f"12 keys + 3 encoder slots ({cats})")
    expect(cats["Action"] >= 20, f"menu actions listed ({cats})")
    titles = [it.title for it in items]
    expect(len(titles) == len(set(titles)), "no duplicate palette titles")
    expect(not any("Hold" in t for t in titles), "no encoder Hold item")
    upl = next(it for it in items if it.title.startswith("Upload profile"))
    expect(
        not upl.enabled and upl.disabled_reason, "Upload profile disabled (with reason) while not connected"
    )
    expect(upl.shortcut == "Ctrl+Shift+U", f"palette shows the shortcut ({upl.shortcut!r})")

    # Ctrl+K opens
    QTest.keyClick(win, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    pump(app)
    pal = win._palette
    expect(pal is not None and pal.isVisible(), "Ctrl+K opens the palette")
    expect(pal.input.hasFocus() or QApplication.focusWidget() is pal.input, "search box focused")
    expect(pal.results()[0].category == "Page", "blank query starts with pages")

    # Esc closes
    QTest.keyClick(pal.input, Qt.Key.Key_Escape)
    pump(app)
    expect(not pal.isVisible(), "Esc closes the palette")
    expect(win.current_page_key() == "keys", "Esc does not navigate")

    # type → Enter runs a page item
    win.open_palette()
    QTest.keyClicks(pal.input, "macros page")
    pump(app)
    expect(pal.current_item() and pal.current_item().title == "Go to Macros", f"top = {pal.current_item()}")
    QTest.keyClick(pal.input, Qt.Key.Key_Return)
    pump(app)
    expect(not pal.isVisible() and win.current_page_key() == "macros", "Enter ran 'Go to Macros'")

    # profile item (from another page → Keys + profile selected)
    win.open_palette("gaming")
    pump(app)
    QTest.keyClick(pal.input, Qt.Key.Key_Enter)
    pump(app)
    expect(
        win.current_page_key() == "keys" and win._current.id == "gaming", f"profile item → {win._current.id}"
    )

    # key item
    win.open_palette("k6")
    pump(app)
    QTest.keyClick(pal.input, Qt.Key.Key_Return)
    pump(app)
    expect(win._pad.selection() == ("key", 6), f"'k6' selects Key 6 ({win._pad.selection()})")
    expect(win.breadcrumb().endswith("› Key 6"), f"breadcrumb {win.breadcrumb()!r}")

    # Up / Down / Tab move the highlight (wrapping)
    win.open_palette("key")
    pump(app)
    r0 = pal.list.currentRow()
    QTest.keyClick(pal.input, Qt.Key.Key_Down)
    expect(pal.list.currentRow() == r0 + 1, "Down moves")
    QTest.keyClick(pal.input, Qt.Key.Key_Tab)
    expect(pal.list.currentRow() == r0 + 2, "Tab moves")
    QTest.keyClick(pal.input, Qt.Key.Key_Up)
    QTest.keyClick(pal.input, Qt.Key.Key_Up)
    QTest.keyClick(pal.input, Qt.Key.Key_Up)
    expect(pal.list.currentRow() == len(pal.results()) - 1, "Up wraps to the bottom")
    # Ctrl+K toggles closed
    QTest.keyClick(pal.input, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    pump(app)
    expect(not pal.isVisible(), "Ctrl+K closes the palette")

    # disabled action: listed, highlighted, but Enter does nothing
    win.open_palette("upload profile")
    pump(app)
    cur = pal.current_item()
    expect(
        cur is not None and cur.title.startswith("Upload profile") and not cur.enabled,
        f"disabled item listed ({cur})",
    )
    expect(not pal.run_current(), "disabled item does not run")
    expect(pal.isVisible(), "palette stays open on a disabled item")
    pal.close()

    # no matches → empty label
    win.open_palette("zzqxv")
    pump(app)
    expect(not pal.results() and pal.empty.isVisibleTo(pal), "'No matches' state")
    expect(not pal.run_current(), "nothing to run")
    pal.close()

    # theme action
    from macropad_config.ui import theme as th

    before = th.manager().scheme
    win.open_palette("theme")
    pump(app)
    ran: list[str] = []
    pal.executed.connect(ran.append)
    QTest.keyClick(pal.input, Qt.Key.Key_Return)
    pump(app)
    expect(ran == ["Toggle dark / light theme"], f"executed signal {ran}")
    expect(th.manager().scheme != before, f"theme toggled ({before} → {th.manager().scheme})")
    win._toggle_theme()
    expect(th.manager().scheme == before, "theme toggled back")

    # connect via palette (mock device) enables device actions in the palette
    from macropad_config.hil.mock import MockFirmware, MockHidModule

    win._hid_module = MockHidModule(MockFirmware())
    win.open_palette("connect")
    pump(app)
    QTest.keyClick(pal.input, Qt.Key.Key_Return)
    pump(app, 10)
    expect(win.current_page_key() == "device", "Connect via palette shows the Device page")
    upl = next(it for it in win.palette_items() if it.title.startswith("Upload profile"))
    expect(upl.enabled, "Upload profile enabled after connecting")
    win.close()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    unit_checks()
    ui_checks(app)
    if FAILS:
        print(f"smoke_palette: {len(FAILS)} FAIL(S)")
        return 1
    print("smoke_palette: fuzzy ranking, Ctrl+K open/close, keyboard nav, run/disabled items OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
