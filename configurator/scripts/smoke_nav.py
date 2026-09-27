#!/usr/bin/env python3
"""Headless smoke: main-window page navigation (Qt offscreen).

* Rail + Ctrl+1…6 + View → Go to switch pages; old menu actions (Macro library, Idle
  animation, Auto-switch rules, About, Connect) land on their pages instead of dialogs.
* Header title + breadcrumb ("CODING › Key 6", "Library › hello", …).
* Unsaved-changes markers: rail dot, header badge, profile-row dot, window title; page-aware
  Ctrl+S (profile / macro library / auto-switch rules); quit prompt lists every dirty page.
* Empty states: Device (not connected), Keys (no profiles), Macros (no macros), Auto-switch (no rules).
* Ctrl+Tab / Ctrl+Shift+Tab cycle profiles; arrow keys on the device view; the encoder Hold
  slot is gone from the view (reserved in the format) but still round-trips in the model.
* Device page with the mock macropad: connect shows GET_INFO inline; backup → file → restore.
* Tooltips carry shortcuts.

Usage:
  cd configurator
  QT_QPA_PLATFORM=offscreen python scripts/smoke_nav.py
"""

from __future__ import annotations

import json
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
(T / "autoswitch").mkdir()
shutil.copy(REPO / "autoswitch" / "rules.json", T / "autoswitch" / "rules.json")
os.environ["MACROPAD_PROFILES_DIR"] = str(T / "profiles")
os.environ["MACROPAD_MACROS_PATH"] = str(T / "macros" / "library.json")
os.environ["MACROPAD_AUTOSWITCH_PATH"] = str(T / "autoswitch" / "rules.json")
os.environ["MACROPAD_ANIMATIONS_DIR"] = str(T / "animations")
os.environ.setdefault("MACROPAD_THEME", "dark")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  FAIL: {msg}")


def pump(app, n: int = 5) -> None:
    for _ in range(n):
        app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from macropad_config.hil.mock import MockFirmware, MockHidModule
    from macropad_config.main_window import MainWindow
    from macropad_config.pages.nav import PAGES
    from macropad_config.widgets import pad_preview as pp
    from macropad_config.widgets.profile_list import _ROLE_DIRTY

    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    win.activateWindow()
    pump(app, 10)

    # --- pages via shortcuts / rail / menus ---------------------------------------------
    expect(win.current_page_key() == "keys", "starts on the Keys page")
    expect(
        [s.key for s in PAGES] == ["keys", "macros", "idle", "autoswitch", "device", "settings"], "page order"
    )
    for i, spec in enumerate(PAGES):
        QTest.keyClick(win, Qt.Key(Qt.Key.Key_1 + i), Qt.KeyboardModifier.ControlModifier)
        pump(app)
        expect(
            win.current_page_key() == spec.key, f"Ctrl+{i + 1} → {spec.key} (got {win.current_page_key()})"
        )
        expect(win._header.title.text() == spec.title, f"header title {win._header.title.text()!r}")
        expect(win._rail.buttons[i].isChecked(), f"rail button {spec.key} checked")
    win._rail.buttons[1].click()
    pump(app)
    expect(win.current_page_key() == "macros", "rail click → macros")
    for act, key in (
        (win._macro_lib_act, "macros"),
        (win._anim_act, "idle"),
        (win._autoswitch_dlg_act, "autoswitch"),
        (win._about_act, "settings"),
    ):
        win.go_to_page("keys")
        act.trigger()
        pump(app)
        expect(win.current_page_key() == key, f"menu {act.text()!r} → {key} (got {win.current_page_key()})")
    for i, act in enumerate(win._page_acts):
        act.trigger()
        pump(app)
        expect(win.current_page_key() == PAGES[i].key, f"View → Go to {PAGES[i].title}")
    win.go_to_page("idle")
    expect(win._dup_profile_act.shortcut().isEmpty(), "Ctrl+D handed to the frame editor on the Idle page")
    win.go_to_page("keys")
    expect(win._dup_profile_act.shortcut().toString() == "Ctrl+D", "Ctrl+D duplicates a profile on Keys")

    # --- tooltips show shortcuts ---------------------------------------------------------------
    for i, b in enumerate(win._rail.buttons):
        expect(f"Ctrl+{i + 1}" in b.toolTip(), f"rail tooltip shortcut: {b.toolTip()!r}")
    expect("Ctrl+K" in win._palette_btn.toolTip(), "search button tooltip has Ctrl+K")
    expect("Ctrl+Shift+U" in win._upload_btn.toolTip(), f"upload tooltip {win._upload_btn.toolTip()!r}")
    expect("Ctrl+Shift+I" in win._connect_btn.toolTip(), "connect tooltip shortcut")

    # --- breadcrumb ----------------------------------------------------------------------------------
    win._profile_list.select_by_id("coding")
    pump(app)
    expect(win.breadcrumb() == "CODING", f"breadcrumb profile only {win.breadcrumb()!r}")
    win._pad.select("key", 6)
    expect(win.breadcrumb() == "CODING › Key 6", f"breadcrumb {win.breadcrumb()!r}")
    win._pad.select("encoder", "press")
    expect(win.breadcrumb() == "CODING › Encoder · Press", f"breadcrumb {win.breadcrumb()!r}")
    win.go_to_page("macros")
    win._macros_page._list.setCurrentRow(0)
    pump(app)
    expect(win.breadcrumb().startswith("Library › "), f"macros breadcrumb {win.breadcrumb()!r}")
    win.go_to_page("device")
    expect(win.breadcrumb() == "Not connected", f"device breadcrumb {win.breadcrumb()!r}")

    # --- empty state: device ------------------------------------------------------------------------
    expect(win._device_page.empty.isVisibleTo(win._device_page), "Device page empty state before connecting")
    expect(not win._device_page.backup_btn.isEnabled(), "backup disabled when not connected")

    # --- profile cycling + arrow keys -------------------------------------------------------------
    win.go_to_page("keys")
    ids = [p.id for p in win._profile_list.profiles()]
    start = win._current.id
    QTest.keyClick(win, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    pump(app)
    expect(win._current.id == ids[(ids.index(start) + 1) % len(ids)], f"Ctrl+Tab → next ({win._current.id})")
    QTest.keyClick(
        win, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    )
    pump(app)
    expect(win._current.id == start, f"Ctrl+Shift+Tab → previous ({win._current.id})")
    win._profile_list.select_by_id(ids[-1])
    win._cycle_profile(1)
    expect(win._current.id == ids[0], "profile cycling wraps")
    win.go_to_page("device")
    win._cycle_profile(1)
    expect(win.current_page_key() == "keys", "cycling a profile from another page shows Keys")

    win._profile_list.select_by_id("coding")
    pump(app)
    win._pad.setFocus()
    win._pad.select("key", 1)
    for key, want in (
        (Qt.Key.Key_Right, ("key", 2)),
        (Qt.Key.Key_Down, ("key", 6)),
        (Qt.Key.Key_Down, ("key", 10)),
        (Qt.Key.Key_Down, ("encoder", "cw")),
        (Qt.Key.Key_Right, ("encoder", "press")),
        (Qt.Key.Key_Right, ("encoder", "press")),
        (Qt.Key.Key_Up, ("key", 12)),
    ):
        QTest.keyClick(win._pad, key)
        expect(win._pad.selection() == want, f"arrow {key.name} → {want} (got {win._pad.selection()})")

    # --- encoder Hold slot reserved -----------------------------------------------------------------
    expect(pp.ENCODER_SLOTS == ("ccw", "cw", "press"), f"encoder slots in the view {pp.ENCODER_SLOTS}")
    expect("long_press" not in pp.ENCODER_SLOT_LABELS, "no Hold label")
    expect(win._current.action_for_encoder("long_press") is not None, "long_press still in the model")
    win._pad.select("encoder", "long_press")
    expect(win._pad.selection() is None, "long_press cannot be selected")

    # --- dirty markers + page-aware save ----------------------------------------------------------
    win._pad.select("key", 6)
    win._oled_edit.setText("CODING2")
    pump(app)
    expect(win._rail.buttons[0].is_dirty(), "Keys rail dot after an edit")
    expect(win._header.badge.isVisibleTo(win._header), "header Unsaved badge")
    row = [p.id for p in win._profile_list.profiles()].index("coding")
    expect(bool(win._profile_list._list.item(row).data(_ROLE_DIRTY)), "profile row dot")
    expect(win.windowTitle().endswith("*"), "window title *")
    expect(win.breadcrumb() == "CODING2 › Key 6", f"breadcrumb follows the OLED title {win.breadcrumb()!r}")
    QTest.keyClick(win, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    pump(app)
    expect(not win._dirty_ids, "Ctrl+S saved the profile")
    expect(
        not win._rail.buttons[0].is_dirty() and not win._header.badge.isVisibleTo(win._header),
        "markers cleared",
    )
    saved = json.loads(Path(win._current.source_path).read_text(encoding="utf-8"))
    expect(saved.get("oled", {}).get("title") == "CODING2", "profile written to disk")

    win.go_to_page("macros")
    mp = win._macros_page
    n_before = len(mp.library().macros)
    mp._new_macro()
    pump(app)
    expect(
        win._rail.buttons[1].is_dirty() and win._header.badge.isVisibleTo(win._header), "macros dirty markers"
    )
    expect(win._save_act.isEnabled(), "File → Save enabled for the macro page")
    win._save_page()
    lib = json.loads((T / "macros" / "library.json").read_text(encoding="utf-8"))
    expect(len(lib["macros"]) == n_before + 1 and not mp.is_dirty(), "macro library saved via Ctrl+S")
    expect(not win._rail.buttons[1].is_dirty(), "macros dot cleared")

    win.go_to_page("autoswitch")
    ap = win._autoswitch_page
    ap._add_row()
    pump(app)
    expect(win._rail.buttons[3].is_dirty(), "auto-switch dirty after Add rule")
    ap.revert(confirm=False)
    expect(not ap.is_dirty() and not win._rail.buttons[3].is_dirty(), "auto-switch revert clears the dot")

    # quit prompt lists dirty pages (answer Cancel)
    asked: list[str] = []
    orig_q = QMessageBox.question
    QMessageBox.question = staticmethod(
        lambda *a, **k: (asked.append(a[2]), QMessageBox.StandardButton.Cancel)[1]
    )
    try:
        mp._new_macro()
        win._oled_edit.setText("CODING3")
        expect(not win.close(), "close refused while pages are dirty")
        expect(
            asked and "Macro library" in asked[-1] and "coding" in asked[-1], f"quit prompt {asked[-1:]!r}"
        )
    finally:
        QMessageBox.question = orig_q
    mp.revert(confirm=False)
    win._dirty_ids.clear()
    win._refresh_dirty_ui()
    expect(not win.dirty_pages(), f"all clean {win.dirty_pages()}")

    # --- Device page with the mock macropad: connect, backup, restore -------------------------------
    fw = MockFirmware()
    win._hid_module = MockHidModule(fw)
    win.go_to_page("keys")
    win._connect_act.trigger()
    pump(app)
    expect(win.current_page_key() == "device", "Connect shows the Device page")
    expect(win._device_page.info_panel.isVisibleTo(win._device_page), "GET_INFO shown inline")
    expect(win.breadcrumb().endswith("fw 0.26"), f"device breadcrumb {win.breadcrumb()!r}")
    expect(win._device_page.backup_btn.isEnabled(), "backup enabled on fw 0.26")
    expect(win._upload_act.isEnabled() and win._backup_act.isEnabled(), "device actions gated on")
    bpath = T / "dev.mpbackup.json"
    data = win.backup_to(bpath)
    expect(data is not None and bpath.is_file(), "backup file written")
    orig_profiles = [bytes(p) for p in fw.profiles]
    from macropad_config.device_backup import load_backup_file

    loaded = load_backup_file(bpath)
    fw.profiles[0] = bytes(fw.profiles[1])  # simulate a change on the device
    fw.active = 4
    done = win.restore_from(loaded)
    expect(done is not None and "saved to flash" in done, f"restore summary {done}")
    expect([bytes(p) for p in fw.profiles] == orig_profiles, "profiles restored")
    expect(fw.active == data["active_slot"], f"active slot restored ({fw.active})")
    bad = dict(json.loads(bpath.read_text()))
    bad["profiles"][0] = "00" * 10
    try:
        from macropad_config.device_backup import BackupError, validate_backup

        validate_backup(bad)
        expect(False, "short blob accepted")
    except BackupError:
        pass

    # --- empty states for Keys / Macros / Auto-switch -----------------------------------------------
    win.close()
    empty = T / "empty"
    (empty / "profiles").mkdir(parents=True)
    os.environ["MACROPAD_PROFILES_DIR"] = str(empty / "profiles")
    os.environ["MACROPAD_MACROS_PATH"] = str(empty / "library.json")
    (empty / "rules.json").write_text(json.dumps({"schema_version": 1, "enabled": False, "rules": []}))
    os.environ["MACROPAD_AUTOSWITCH_PATH"] = str(empty / "rules.json")
    w2 = MainWindow()
    w2.show()
    pump(app)
    expect(w2._canvas_stack.currentWidget() is w2._keys_empty, "Keys empty state with no profiles")
    expect(w2.breadcrumb() == "No profile", f"empty breadcrumb {w2.breadcrumb()!r}")
    w2.go_to_page("macros")
    expect(w2._macros_page._right_stack.currentIndex() == 1, "Macros empty state")
    w2.go_to_page("autoswitch")
    expect(w2._autoswitch_page._table_stack.currentIndex() == 1, "Auto-switch empty state")
    w2._autoswitch_page._empty.button.click()
    expect(w2._autoswitch_page.rule_count() == 1 and w2._autoswitch_page.is_dirty(), "empty-state Add rule")
    w2._autoswitch_page.revert(confirm=False)
    w2.close()

    if FAILS:
        print(f"smoke_nav: {len(FAILS)} FAIL(S)")
        return 1
    print("smoke_nav: pages, shortcuts, breadcrumbs, unsaved markers, empty states, backup/restore OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
