#!/usr/bin/env python3
"""Headless smoke: type-dependent form rows + macro-library dirty tracking (Qt offscreen).

* ActionEditor: for every action type only the applicable rows are shown, and hidden rows hide
  their *label* too (no orphan "Key" / "Mods" / "Text id" … labels, e.g. for MACRO).
* MacroLibraryDialog step editor: same for TAP / DELAY_MS / TEXT / CONSUMER / END steps.
* MacroLibraryDialog dirty tracking: selecting macros / steps must not mark the library dirty or
  change any step (regression: step 0 of each visited macro was overwritten with END), closing
  after mere browsing must not ask "Discard changes?", a real edit must mark dirty and prompt.

Usage:
  cd configurator
  QT_QPA_PLATFORM=offscreen python scripts/smoke_editor_forms.py
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
LIB = Path(_TMP.name) / "library.json"
shutil.copy(REPO / "macros" / "library.json", LIB)
os.environ["MACROPAD_MACROS_PATH"] = str(LIB)

from PySide6.QtWidgets import QApplication, QFormLayout, QMessageBox

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  FAIL: {msg}")


def shown_labels(form: QFormLayout) -> list[str]:
    """Label texts whose label widget is actually visible (independent of helper methods)."""
    out = []
    for i in range(form.rowCount()):
        item = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
        if item is not None and item.widget() is not None and item.widget().isVisible():
            out.append(item.widget().text())
    return out


ACTIONS = {
    "DISABLED": ({"type": "DISABLED"}, ["Type"]),
    "KEY": ({"type": "KEY", "key": "A"}, ["Type", "Key"]),
    "SHORTCUT": ({"type": "SHORTCUT", "mods": ["CTRL"], "key": "C"}, ["Type", "Key", "Mods"]),
    "MACRO": ({"type": "MACRO", "macro_id": 1}, ["Type", "Macro"]),
    "TEXT": ({"type": "TEXT", "text_id": 0}, ["Type", "Text id"]),
    "URL": ({"type": "URL", "text_id": 1}, ["Type", "Text id"]),
    "APP": ({"type": "APP", "text_id": 4}, ["Type", "Text id"]),
    "MEDIA": ({"type": "MEDIA", "code": "PLAY_PAUSE"}, ["Type", "Media"]),
    "VOLUME": ({"type": "VOLUME", "dir": "up"}, ["Type", "Volume"]),
    "PROFILE": ({"type": "PROFILE", "profile_id": "gaming"}, ["Type", "Profile"]),
}


def check_action_editor(app: QApplication) -> None:
    from macropad_config.widgets.action_editor import ActionEditor

    print("smoke_editor_forms: action editor rows per type")
    ed = ActionEditor()
    ed.show()
    for name, (action, want) in ACTIONS.items():
        ed.set_action(action)
        app.processEvents()
        got = shown_labels(ed._form)
        expect(got == want, f"ActionEditor {name}: visible labels {got}, want {want}")
        expect(ed.visible_field_labels() == want, f"ActionEditor {name}: helper {ed.visible_field_labels()}")
    # switching type via the combo updates rows too
    ed.set_action({"type": "MACRO", "macro_id": 0})
    ed._type.setCurrentIndex(ed._type.findData("SHORTCUT"))
    app.processEvents()
    expect(shown_labels(ed._form) == ["Type", "Key", "Mods"], f"combo switch: {shown_labels(ed._form)}")
    ed.close()


STEP_LABELS = {
    "TAP": ["Op", "Mods", "Key"],
    "KEY_DOWN": ["Op", "Mods", "Key"],
    "DELAY_MS": ["Op", "Delay"],
    "TEXT": ["Op", "Text id"],
    "CONSUMER": ["Op", "Consumer"],
    "END": ["Op"],
}


def snapshot(dlg) -> list:
    return [[s.to_dict() for s in m.steps] + [m.name] for m in dlg.library().macros]


def check_macro_dialog(app: QApplication) -> None:
    from macropad_config.widgets import macro_library_dialog as mld

    print("smoke_editor_forms: macro library dirty tracking + step rows")
    asked: list[str] = []

    def fake_question(*args, **kwargs):
        asked.append(str(args[2]) if len(args) > 2 else "?")
        return QMessageBox.StandardButton.Cancel

    orig_q = mld.QMessageBox.question
    mld.QMessageBox.question = staticmethod(fake_question)
    try:
        dlg = mld.MacroLibraryDialog()
        dlg.show()
        app.processEvents()
        before = snapshot(dlg)
        n = len(before)
        expect(n >= 3, f"library has {n} macros")
        # Regression: switching macros without touching the step table used to write the
        # (never loaded) step editor — op END — into step 0 of the macro being left.
        for row in (1, 2, 0):
            dlg._list.setCurrentRow(row)
            app.processEvents()
        expect(snapshot(dlg) == before, "switching macros overwrote step data (step 0 -> END)")
        # Browse: every macro, every step.
        for row in [*range(n), 0, 2, 1]:
            dlg._list.setCurrentRow(row)
            app.processEvents()
            for srow in range(dlg._table.rowCount()):
                dlg._table.selectRow(srow)
                app.processEvents()
        expect(not dlg._dirty, "browsing macros / steps marked the library dirty")
        expect(snapshot(dlg) == before, "browsing macros / steps changed step data")
        # Step editor rows per op (walk all steps seen in the bundled library).
        seen = set()
        for row in range(n):
            dlg._list.setCurrentRow(row)
            app.processEvents()
            macro = dlg._current_macro()
            for srow, step in enumerate(macro.steps):
                dlg._table.selectRow(srow)
                app.processEvents()
                if step.op in STEP_LABELS:
                    seen.add(step.op)
                    got = shown_labels(dlg._editor_form)
                    expect(got == STEP_LABELS[step.op], f"step {step.op}: labels {got}")
                    expect(dlg.visible_step_labels() == STEP_LABELS[step.op], f"step {step.op}: helper")
        expect({"TAP", "DELAY_MS", "END"} <= seen, f"library covers TAP/DELAY_MS/END steps: {seen}")
        # Changing the op in the editor switches rows (and is a real edit).
        expect(snapshot(dlg) == before and not dlg._dirty, "still clean before the real edit")
        # Close after browsing: no prompt, dialog closes.
        dlg.reject()
        app.processEvents()
        expect(not asked, f"'Discard changes?' asked after browsing only: {asked}")
        expect(not dlg.isVisible(), "dialog did not close after browsing only")

        # Real edit → dirty + prompt.
        dlg2 = mld.MacroLibraryDialog()
        dlg2.show()
        app.processEvents()
        base = snapshot(dlg2)
        target = None
        for row in range(len(base)):
            dlg2._list.setCurrentRow(row)
            app.processEvents()
            for srow, step in enumerate(dlg2._current_macro().steps):
                if step.op == "DELAY_MS":
                    target = (row, srow, step.arg)
                    break
            if target:
                break
        expect(target is not None, "found a DELAY_MS step")
        if target:
            row, srow, arg = target
            dlg2._table.selectRow(srow)
            app.processEvents()
            expect(not dlg2._dirty, "selecting the DELAY_MS step marked dirty")
            dlg2._delay_spin.setValue(arg + 7)
            app.processEvents()
            expect(dlg2._dirty, "editing the delay did not mark dirty")
            expect(dlg2._current_macro().steps[srow].arg == arg + 7, "delay edit not applied")
            others = [m for i, m in enumerate(snapshot(dlg2)) if i != row]
            expect(others == [m for i, m in enumerate(base) if i != row], "edit leaked into other macros")
            # op switch on the same step → rows follow
            dlg2._op_combo.setCurrentText("TEXT")
            app.processEvents()
            expect(shown_labels(dlg2._editor_form) == ["Op", "Text id"], "op switch rows")
        dlg2.reject()
        app.processEvents()
        expect(len(asked) == 1, f"real edit should ask once on close, asked {asked}")
        expect(dlg2.isVisible(), "Cancel on the prompt must keep the dialog open")
        dlg2._dirty = False
        dlg2.reject()
        # the library file on disk is untouched (no save happened)
        expect(LIB.read_bytes() == (REPO / "macros" / "library.json").read_bytes(), "library file modified")
    finally:
        mld.QMessageBox.question = orig_q


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    check_action_editor(app)
    check_macro_dialog(app)
    if FAILS:
        print(f"smoke_editor_forms: FAIL ({len(FAILS)})")
        return 1
    print("smoke_editor_forms: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
