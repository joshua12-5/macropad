"""Main application window — Step 23 HIL test tooling."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFormLayout,
    QInputDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .models.profile import (
    Profile,
    default_profiles_dir,
    delete_profile_file,
    duplicate_profile,
    load_profiles_dir,
    make_blank_profile,
    save_profile,
    suggest_profile_id,
    suggest_profile_path,
)
from .models.schema import SchemaError
from .widgets.action_editor import ActionEditor
from .widgets.macro_library_dialog import MacroLibraryDialog
from .widgets.pad_preview import PadPreview
from .widgets.profile_dialog import ProfileNameIdDialog
from .widgets.autoswitch_dialog import AutoswitchDialog
from .widgets.profile_list import ProfileListWidget
from . import version as app_version

DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #1e1f22;
    color: #e8e8ea;
    font-family: "Segoe UI", "Ubuntu", "Cantarell", sans-serif;
    font-size: 13px;
}
QMenuBar {
    background-color: #2b2d31;
    color: #e8e8ea;
}
QMenuBar::item:selected { background-color: #3c3f45; }
QMenu {
    background-color: #2b2d31;
    color: #e8e8ea;
    border: 1px solid #3c3f45;
}
QMenu::item:selected { background-color: #404249; }
QMenu::item:disabled { color: #6d6f78; }
QStatusBar {
    background-color: #2b2d31;
    color: #b5bac1;
}
QLabel#sectionHeading {
    font-weight: 600;
    color: #b5bac1;
    padding: 4px 2px;
}
QLabel#oledTitle {
    background-color: #0a0a0a;
    color: #9ee493;
    border: 2px solid #3a3a3a;
    border-radius: 4px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 18px;
    font-weight: bold;
    letter-spacing: 2px;
    padding: 8px;
}
QLabel#encoderKnob {
    background-color: #2b2d31;
    border: 3px solid #5865f2;
    border-radius: 36px;
    font-size: 28px;
    color: #c9cdfb;
}
QLabel#hintLabel {
    color: #80848e;
    font-size: 11px;
}
QLabel#validationError {
    color: #f23f43;
    font-size: 11px;
    padding: 2px 0;
}
QFrame#keyGridFrame {
    background-color: #2b2d31;
    border: 1px solid #3c3f45;
    border-radius: 8px;
}
QPushButton#keyButton {
    background-color: #383a40;
    color: #e8e8ea;
    border: 1px solid #4e5058;
    border-radius: 6px;
    font-weight: 600;
    font-size: 11px;
}
QPushButton#keyButton:hover { background-color: #404249; }
QPushButton#keyButton:checked {
    background-color: #5865f2;
    border-color: #7983f5;
    color: #ffffff;
}
QPushButton#encoderButton {
    background-color: #383a40;
    color: #e8e8ea;
    border: 1px solid #4e5058;
    border-radius: 4px;
    padding: 6px;
    font-size: 11px;
}
QPushButton#encoderButton:hover { background-color: #404249; }
QPushButton#encoderButton:checked {
    background-color: #5865f2;
    border-color: #7983f5;
}
QPushButton#profileToolButton {
    background-color: #383a40;
    color: #e8e8ea;
    border: 1px solid #4e5058;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}
QPushButton#profileToolButton:hover { background-color: #404249; }
QPushButton#profileToolButton:disabled {
    color: #6d6f78;
    background-color: #2b2d31;
}
QListWidget#profileList {
    background-color: #2b2d31;
    border: 1px solid #3c3f45;
    border-radius: 6px;
    padding: 4px;
    outline: none;
}
QListWidget#profileList::item {
    padding: 8px 10px;
    border-radius: 4px;
}
QListWidget#profileList::item:selected {
    background-color: #5865f2;
    color: #ffffff;
}
QListWidget#profileList::item:hover:!selected {
    background-color: #35373c;
}
QTextEdit#detailsPanel {
    background-color: #2b2d31;
    border: 1px solid #3c3f45;
    border-radius: 6px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
    color: #dce0e6;
    padding: 6px;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #383a40;
    color: #e8e8ea;
    border: 1px solid #4e5058;
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: #5865f2;
}
QComboBox::drop-down { border: none; }
QCheckBox { spacing: 6px; }
QSplitter::handle {
    background-color: #3c3f45;
    width: 2px;
}
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Macropad Configurator")
        self.resize(1100, 700)
        self.setStyleSheet(DARK_STYLE)

        self._profiles_dir = default_profiles_dir()
        self._current: Profile | None = None
        self._selection: tuple[str, object] | None = None
        self._dirty_ids: set[str] = set()
        self._meta_loading = False
        self._applying = False
        self._last_device_info: dict | None = None
        self._autoswitch = None
        self._autoswitch_connected = False

        self._build_menus()
        self._build_ui()
        self.reload_profiles()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_act = QAction("Open profiles &folder…", self)
        open_act.setShortcut(QKeySequence("Ctrl+O"))
        open_act.triggered.connect(self._open_profiles_folder)
        file_menu.addAction(open_act)

        reload_act = QAction("&Reload", self)
        reload_act.setShortcut(QKeySequence("Ctrl+R"))
        reload_act.triggered.connect(self._reload_with_prompt)
        file_menu.addAction(reload_act)

        file_menu.addSeparator()

        self._save_act = QAction("&Save", self)
        self._save_act.setShortcut(QKeySequence.StandardKey.Save)
        self._save_act.triggered.connect(self._save_current)
        self._save_act.setEnabled(False)
        file_menu.addAction(self._save_act)

        self._save_all_act = QAction("Save &All", self)
        self._save_all_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._save_all_act.triggered.connect(self._save_all)
        self._save_all_act.setEnabled(False)
        file_menu.addAction(self._save_all_act)

        file_menu.addSeparator()

        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        profile_menu = self.menuBar().addMenu("&Profile")

        self._new_profile_act = QAction("&New…", self)
        self._new_profile_act.setShortcut(QKeySequence("Ctrl+N"))
        self._new_profile_act.triggered.connect(self._new_profile)
        profile_menu.addAction(self._new_profile_act)

        self._dup_profile_act = QAction("&Duplicate…", self)
        self._dup_profile_act.setShortcut(QKeySequence("Ctrl+D"))
        self._dup_profile_act.triggered.connect(self._duplicate_profile)
        profile_menu.addAction(self._dup_profile_act)

        self._del_profile_act = QAction("De&lete…", self)
        self._del_profile_act.triggered.connect(self._delete_profile)
        profile_menu.addAction(self._del_profile_act)

        profile_menu.addSeparator()

        macro_lib_act = QAction("Macro &library…", self)
        macro_lib_act.triggered.connect(self._open_macro_library)
        profile_menu.addAction(macro_lib_act)

        device_menu = self.menuBar().addMenu("&Device")

        connect_act = QAction("&Connect / Get device info", self)
        connect_act.setShortcut(QKeySequence("Ctrl+Shift+I"))
        connect_act.setStatusTip("PING + GET_INFO over vendor HID (Step 15)")
        connect_act.triggered.connect(self._device_connect_info)
        device_menu.addAction(connect_act)

        self._upload_act = QAction("&Upload profile to device…", self)
        self._upload_act.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self._upload_act.setStatusTip(
            "Pack selected profile and upload into a device slot (0–4)"
        )
        self._upload_act.triggered.connect(self._device_upload_profile)
        device_menu.addAction(self._upload_act)

        self._upload_macros_act = QAction("Upload &macros to device…", self)
        self._upload_macros_act.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self._upload_macros_act.setStatusTip(
            "Upload host macro library ids 0–4 to the device flash bank"
        )
        self._upload_macros_act.triggered.connect(self._device_upload_macros)
        device_menu.addAction(self._upload_macros_act)

        self._save_device_act = QAction("&Save device state", self)
        self._save_device_act.setStatusTip(
            "SAVE_ALL (0x32): rewrite flash with current RAM profiles+macros+active"
        )
        self._save_device_act.setEnabled(False)
        self._save_device_act.triggered.connect(self._device_save_all)
        device_menu.addAction(self._save_device_act)

        device_menu.addSeparator()

        self._autoswitch_act = QAction("Auto-switch &enabled", self)
        self._autoswitch_act.setCheckable(True)
        self._autoswitch_act.setChecked(False)
        self._autoswitch_act.setEnabled(False)
        self._autoswitch_act.setStatusTip(
            "Poll foreground app and SET_ACTIVE on the device (needs connection)"
        )
        self._autoswitch_act.toggled.connect(self._on_autoswitch_toggled)
        device_menu.addAction(self._autoswitch_act)

        tools_menu = self.menuBar().addMenu("&Tools")
        autoswitch_dlg_act = QAction("&Auto-switch…", self)
        autoswitch_dlg_act.setStatusTip("Edit auto-switch rules (host → device)")
        autoswitch_dlg_act.triggered.connect(self._open_autoswitch_dialog)
        tools_menu.addAction(autoswitch_dlg_act)

        arch_tip_act = QAction("Architecture &overview…", self)
        arch_tip_act.setStatusTip(
            "Stack layers & data flow: docs/ARCHITECTURE.md in the repo"
        )
        arch_tip_act.triggered.connect(self._show_architecture_tip)
        tools_menu.addAction(arch_tip_act)

        help_menu = self.menuBar().addMenu("&Help")
        about_act = QAction("&About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)
        arch_help = QAction("&Architecture doc", self)
        arch_help.setStatusTip(
            "See docs/ARCHITECTURE.md — layers, flash vs RAM, protocol links"
        )
        arch_help.triggered.connect(self._show_architecture_tip)
        help_menu.addAction(arch_help)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._profile_list = ProfileListWidget()
        self._profile_list.profile_selected.connect(self._on_profile_selected)
        self._profile_list.new_requested.connect(self._new_profile)
        self._profile_list.duplicate_requested.connect(self._duplicate_profile)
        self._profile_list.delete_requested.connect(self._delete_profile)
        splitter.addWidget(self._profile_list)

        self._pad = PadPreview()
        self._pad.selection_changed.connect(self._on_selection_changed)
        splitter.addWidget(self._pad)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        meta_heading = QLabel("Profile")
        meta_heading.setObjectName("sectionHeading")
        right_layout.addWidget(meta_heading)

        meta_form = QFormLayout()
        meta_form.setContentsMargins(0, 0, 0, 0)
        meta_form.setSpacing(4)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Profile name")
        self._name_edit.textChanged.connect(self._on_meta_changed)
        self._oled_edit = QLineEdit()
        self._oled_edit.setPlaceholderText("OLED title")
        self._oled_edit.textChanged.connect(self._on_meta_changed)
        meta_form.addRow("Name", self._name_edit)
        meta_form.addRow("OLED", self._oled_edit)
        right_layout.addLayout(meta_form)

        action_heading = QLabel("Selected action")
        action_heading.setObjectName("sectionHeading")
        right_layout.addWidget(action_heading)

        self._action_editor = ActionEditor()
        self._action_editor.actionChanged.connect(self._on_action_changed)
        right_layout.addWidget(self._action_editor)

        json_heading = QLabel("Action JSON")
        json_heading.setObjectName("sectionHeading")
        right_layout.addWidget(json_heading)

        self._action_view = QTextEdit()
        self._action_view.setObjectName("detailsPanel")
        self._action_view.setReadOnly(True)
        self._action_view.setMaximumHeight(160)
        self._action_view.setPlaceholderText("Click a key or encoder slot…")
        right_layout.addWidget(self._action_view)

        right_layout.addStretch(1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([200, 520, 340])

        layout.addWidget(splitter)
        self.statusBar().showMessage("Ready")

    # --- dirty tracking -------------------------------------------------

    def _mark_dirty(self, profile: Profile | None = None) -> None:
        profile = profile or self._current
        if profile is None:
            return
        self._dirty_ids.add(profile.id)
        self._update_save_actions()
        self.statusBar().showMessage(f"Modified: {profile.name} ({profile.id})")

    def _clear_dirty(self, profile_id: str | None = None) -> None:
        if profile_id is None:
            self._dirty_ids.clear()
        else:
            self._dirty_ids.discard(profile_id)
        self._update_save_actions()

    def _update_save_actions(self) -> None:
        cur_dirty = bool(self._current and self._current.id in self._dirty_ids)
        self._save_act.setEnabled(cur_dirty)
        self._save_all_act.setEnabled(bool(self._dirty_ids))
        title = "Macropad Configurator"
        if self._dirty_ids:
            title += " *"
        self.setWindowTitle(title)

    def _confirm_discard_dirty(self, reason: str) -> bool:
        if not self._dirty_ids:
            return True
        names = ", ".join(sorted(self._dirty_ids))
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            f"{reason}\n\nUnsaved profiles: {names}\n\nDiscard changes?",
            QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Discard

    # --- load / save ----------------------------------------------------

    def _reload_with_prompt(self) -> None:
        if not self._confirm_discard_dirty("Reload will discard unsaved edits."):
            return
        self._clear_dirty()
        self.reload_profiles()

    def reload_profiles(self) -> None:
        self._profiles_dir = default_profiles_dir()
        profiles, errors = load_profiles_dir(self._profiles_dir)
        keep_id = self._current.id if self._current else None

        self._profile_list.set_profiles(profiles)

        if errors:
            messages = "; ".join(f"{e.path.name}: {e.message}" for e in errors)
            self.statusBar().showMessage(f"Load errors: {messages}", 15000)
        elif not profiles:
            self.statusBar().showMessage(
                f"No profiles found in {self._profiles_dir}", 10000
            )
        else:
            self.statusBar().showMessage(
                f"Loaded {len(profiles)} profile(s) from {self._profiles_dir}"
            )

        if keep_id:
            self._profile_list.select_by_id(keep_id)
        if not profiles:
            self._on_profile_selected(None)

    def _path_for_save(self, profile: Profile) -> Path:
        if profile.source_path is not None:
            return Path(profile.source_path)
        return suggest_profile_path(profile.name, profile.id, self._profiles_dir)

    def _save_current(self) -> None:
        if self._current is None:
            return
        try:
            path = save_profile(self._current, self._path_for_save(self._current))
        except (OSError, ValueError, SchemaError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._clear_dirty(self._current.id)
        self._profile_list.refresh_labels()
        self.statusBar().showMessage(f"Saved {path}")

    def _save_all(self) -> None:
        saved = 0
        for profile in self._profile_list.profiles():
            if profile.id not in self._dirty_ids:
                continue
            try:
                save_profile(profile, self._path_for_save(profile))
                self._dirty_ids.discard(profile.id)
                saved += 1
            except (OSError, ValueError, SchemaError) as exc:
                QMessageBox.critical(
                    self, "Save failed", f"{profile.id}: {exc}"
                )
                break
        self._profile_list.refresh_labels()
        self._update_save_actions()
        self.statusBar().showMessage(f"Saved {saved} profile(s)")

    # --- profile / selection --------------------------------------------

    def _on_profile_selected(self, profile: Profile | None) -> None:
        self._current = profile
        self._selection = None
        self._pad.set_profile(profile)
        self._pad.clear_selection()
        self._meta_loading = True
        try:
            if profile is None:
                self._name_edit.clear()
                self._oled_edit.clear()
                self._name_edit.setEnabled(False)
                self._oled_edit.setEnabled(False)
                self._action_editor.set_action(None)
                self._action_editor.set_enabled(False)
                self._action_view.clear()
            else:
                self._name_edit.setEnabled(True)
                self._oled_edit.setEnabled(True)
                self._name_edit.setText(profile.name)
                self._oled_edit.setText(profile.oled_title)
                self._action_editor.set_action(None)
                self._action_editor.set_enabled(False)
                self._action_view.setPlainText("(select a key or encoder action)")
        finally:
            self._meta_loading = False
        self._update_save_actions()
        has = profile is not None
        self._dup_profile_act.setEnabled(has)
        self._del_profile_act.setEnabled(has)

    def _on_selection_changed(self, kind: str, selection_id: object) -> None:
        if not kind or self._current is None:
            self._selection = None
            self._action_editor.set_enabled(False)
            self._action_editor.set_action(None)
            self._action_view.clear()
            return

        self._selection = (kind, selection_id)
        if kind == "key":
            action = self._current.action_for_key(int(selection_id))
            label = f"Key {selection_id}"
        else:
            action = self._current.action_for_encoder(str(selection_id))
            label = f"Encoder.{selection_id}"

        self._action_editor.set_enabled(True)
        self._action_editor.set_action(dict(action) if action else {"type": "DISABLED"})
        self._refresh_action_json(label)
        if action:
            self.statusBar().showMessage(f"{label}: {action.get('type', '?')}")

    def _on_meta_changed(self, *_args: object) -> None:
        if self._meta_loading or self._current is None:
            return
        name = self._name_edit.text().strip()
        title = self._oled_edit.text()
        if name and name != self._current.name:
            try:
                self._current.set_name(name)
            except ValueError:
                return
        if title != self._current.oled_title:
            self._current.set_oled_title(title)
            self._pad.set_oled_title(title)
        self._profile_list.refresh_labels()
        self._mark_dirty()

    def _on_action_changed(self) -> None:
        if self._applying or self._current is None or self._selection is None:
            return
        kind, selection_id = self._selection
        try:
            action = self._action_editor.get_action()
        except SchemaError:
            # Keep JSON preview showing last good attempt / form dump
            self._refresh_action_json_raw()
            return

        self._applying = True
        try:
            if kind == "key":
                self._current.set_key_action(int(selection_id), action)
                label = f"Key {selection_id}"
            else:
                self._current.set_encoder_action(str(selection_id), action)
                label = f"Encoder.{selection_id}"
            self._pad.refresh_captions()
            self._mark_dirty()
            self._refresh_action_json(label)
        finally:
            self._applying = False

    def _refresh_action_json(self, label: str) -> None:
        try:
            action = self._action_editor.get_action()
        except SchemaError as exc:
            self._action_view.setPlainText(f"{label}: invalid — {exc}")
            return
        payload = {"selection": label, "action": action}
        self._action_view.setPlainText(json.dumps(payload, indent=2))

    def _refresh_action_json_raw(self) -> None:
        if self._selection is None:
            return
        kind, selection_id = self._selection
        label = (
            f"Key {selection_id}" if kind == "key" else f"Encoder.{selection_id}"
        )
        self._refresh_action_json(label)


    # --- profile CRUD (Step 12) -----------------------------------------

    def _new_profile(self) -> None:
        existing = self._profile_list.existing_ids()
        dlg = ProfileNameIdDialog(
            title="New profile",
            existing_ids=existing,
            initial_name="",
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        name = dlg.profile_name()
        pid = dlg.profile_id()
        try:
            profile = make_blank_profile(pid, name)
        except ValueError as exc:
            QMessageBox.warning(self, "New profile", str(exc))
            return
        self._profile_list.add_profile(profile, select=True)
        self._mark_dirty(profile)
        self.statusBar().showMessage(f"Created profile {name} ({pid}) — unsaved")

    def _duplicate_profile(self) -> None:
        src = self._current or self._profile_list.current_profile()
        if src is None:
            return
        existing = self._profile_list.existing_ids()
        suggested_name = f"{src.name} Copy"
        suggested_id = suggest_profile_id(suggested_name, existing)
        dlg = ProfileNameIdDialog(
            title="Duplicate profile",
            existing_ids=existing,
            initial_name=suggested_name,
            initial_id=suggested_id,
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        name = dlg.profile_name()
        pid = dlg.profile_id()
        try:
            profile = duplicate_profile(src, pid, name)
        except ValueError as exc:
            QMessageBox.warning(self, "Duplicate profile", str(exc))
            return
        self._profile_list.add_profile(profile, select=True)
        self._mark_dirty(profile)
        self.statusBar().showMessage(
            f"Duplicated {src.id} → {pid} — unsaved"
        )

    def _delete_profile(self) -> None:
        profile = self._current or self._profile_list.current_profile()
        if profile is None:
            return

        remaining = len(self._profile_list.profiles()) - 1
        warn = ""
        if remaining <= 0:
            warn = (
                "\n\nThis is the last profile. You can delete it, "
                "but the list will be empty until you create a new one."
            )
        on_disk = (
            profile.source_path is not None
            and Path(profile.source_path).is_file()
        )
        disk_note = (
            f"\n\nFile on disk will be removed:\n{profile.source_path}"
            if on_disk
            else "\n\n(Not yet saved to disk — will only drop from memory.)"
        )
        reply = QMessageBox.question(
            self,
            "Delete profile",
            (
                f"Delete profile {profile.name!r} ({profile.id})?"
                f"{disk_note}{warn}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        pid = profile.id
        try:
            if on_disk:
                delete_profile_file(profile)
        except OSError as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return

        self._dirty_ids.discard(pid)
        self._profile_list.remove_profile(pid)
        self._update_save_actions()
        self.statusBar().showMessage(f"Deleted profile {pid}")

    def _open_profiles_folder(self) -> None:
        path = self._profiles_dir
        if not path.exists():
            QMessageBox.warning(self, "Profiles folder", f"Not found:\n{path}")
            return
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif sys.platform.startswith("win"):
                subprocess.Popen(["explorer", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            self.statusBar().showMessage(f"Opened {path}")
        except OSError as exc:
            QMessageBox.information(
                self,
                "Profiles folder",
                f"Profiles directory:\n{path}\n\n(Could not open file manager: {exc})",
            )

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._confirm_discard_dirty("Quit with unsaved changes?"):
            event.ignore()
            return
        event.accept()


    def _open_macro_library(self) -> None:
        dlg = MacroLibraryDialog(parent=self)
        dlg.exec()


    def _apply_device_feature_gates(self, info: dict | None) -> None:
        """Enable/disable upload / autoswitch / SAVE_ALL from GET_INFO fw."""
        if not info:
            tip_u = app_version.feature_disabled_tooltip(
                "Upload profile", app_version.MIN_FW_MINOR_UPLOAD
            )
            tip_m = app_version.feature_disabled_tooltip(
                "Upload macros", app_version.MIN_FW_MINOR_MACRO_UPLOAD
            )
            tip_a = app_version.feature_disabled_tooltip(
                "Auto-switch", app_version.MIN_FW_MINOR_AUTOSWITCH
            )
            tip_s = app_version.feature_disabled_tooltip(
                "Save device state", app_version.MIN_FW_MINOR_SAVE_ALL
            )
            for act, tip in (
                (self._upload_act, tip_u),
                (self._upload_macros_act, tip_m),
                (self._autoswitch_act, tip_a),
                (self._save_device_act, tip_s),
            ):
                act.setEnabled(False)
                act.setToolTip(tip)
            return

        major = info.get("fw_major")
        minor = info.get("fw_minor")
        proto_ok, _ = app_version.check_proto_ver(info.get("proto_ver", -1))

        def gate(act, supported: bool, feature: str, min_minor: int, base_tip: str) -> None:
            if proto_ok and supported:
                act.setEnabled(True)
                act.setToolTip("")
                act.setStatusTip(base_tip)
            else:
                act.setEnabled(False)
                if not proto_ok:
                    tip = (
                        f"{feature} disabled: protocol mismatch "
                        f"(host expects proto_ver={app_version.PROTO_VER})."
                    )
                else:
                    tip = app_version.feature_disabled_tooltip(feature, min_minor)
                act.setToolTip(tip)
                act.setStatusTip(tip)

        gate(
            self._upload_act,
            app_version.fw_supports_upload(major, minor),
            "Upload profile",
            app_version.MIN_FW_MINOR_UPLOAD,
            "Pack selected profile and upload into a device slot (0–4)",
        )
        gate(
            self._upload_macros_act,
            app_version.fw_supports_macro_upload(major, minor),
            "Upload macros",
            app_version.MIN_FW_MINOR_MACRO_UPLOAD,
            "Upload host macro library ids 0–4 to the device flash bank",
        )
        # Autoswitch also needs a prior successful connect flag.
        as_ok = proto_ok and app_version.fw_supports_autoswitch(major, minor)
        if as_ok and self._autoswitch_connected:
            self._autoswitch_act.setEnabled(True)
            self._autoswitch_act.setToolTip("")
            self._autoswitch_act.setStatusTip(
                "Poll foreground app and SET_ACTIVE on the device (needs connection)"
            )
        else:
            self._autoswitch_act.setEnabled(False)
            if self._autoswitch_act.isChecked():
                self._autoswitch_act.blockSignals(True)
                self._autoswitch_act.setChecked(False)
                self._autoswitch_act.blockSignals(False)
            if not proto_ok:
                tip = (
                    "Auto-switch disabled: protocol mismatch "
                    f"(host expects proto_ver={app_version.PROTO_VER})."
                )
            elif not app_version.fw_supports_autoswitch(major, minor):
                tip = app_version.feature_disabled_tooltip(
                    "Auto-switch", app_version.MIN_FW_MINOR_AUTOSWITCH
                )
            else:
                tip = "Connect to a device first to enable auto-switch."
            self._autoswitch_act.setToolTip(tip)
            self._autoswitch_act.setStatusTip(tip)

        gate(
            self._save_device_act,
            app_version.fw_supports_save_all(major, minor),
            "Save device state",
            app_version.MIN_FW_MINOR_SAVE_ALL,
            "SAVE_ALL (0x32): rewrite flash with current RAM profiles+macros+active",
        )

    def _warn_proto_if_needed(self, info: dict) -> bool:
        """Warn on proto mismatch. Returns True if proto matches."""
        ok, msg = app_version.check_proto_ver(info.get("proto_ver", -1))
        if ok:
            return True
        self.statusBar().showMessage(f"Protocol mismatch — {msg}", 20000)
        QMessageBox.warning(
            self,
            "Protocol version mismatch",
            (
                f"{msg}\n\n"
                f"Host app: {app_version.HOST_APP_VERSION}\n"
                f"Device fw: {info.get('fw_major', '?')}.{info.get('fw_minor', '?')}\n\n"
                "Upload / autoswitch / SAVE_ALL are disabled until versions match.\n"
                "See docs/VERSIONING.md."
            ),
        )
        return False


    def _device_connect_info(self) -> None:
        """Open vendor HID, PING + GET_INFO, show result (Step 15)."""
        try:
            from .protocol.device import DeviceError, connect_and_info
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Device",
                f"Protocol module unavailable:\n{exc}",
            )
            return

        self.statusBar().showMessage("Connecting to device…")
        try:
            info = connect_and_info()
        except DeviceError as exc:
            self.statusBar().showMessage("No device / connect failed", 8000)
            QMessageBox.information(
                self,
                "Device",
                f"Could not talk to the macropad.\n\n{exc}",
            )
            return
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage("Device error", 8000)
            QMessageBox.warning(self, "Device", str(exc))
            return

        self._last_device_info = info
        self._autoswitch_connected = True
        proto_ok = self._warn_proto_if_needed(info)
        self._apply_device_feature_gates(info)

        fw = f"{info.get('fw_major', '?')}.{info.get('fw_minor', '?')}"
        proto = info.get("proto_ver", "?")
        lines = [
            f"Host app: {app_version.HOST_APP_VERSION}",
            f"Firmware: {fw}   (major.minor)",
            f"Protocol: v{proto}  (host expects {app_version.PROTO_VER})",
            "",
            f"Product: {info.get('product_tag', '?')}",
            f"Active slot: {info.get('active_slot', '?')}",
            f"Slot count: {info.get('slot_count', '?')}",
            f"Flags: {info.get('flags', 0)}",
            f"PING: {info.get('ping_payload', '')!r}",
            "",
            app_version.compat_summary(info),
        ]
        if not proto_ok:
            lines.insert(3, "*** PROTOCOL MISMATCH — see warning ***")
        msg = "\n".join(lines)
        status = (
            f"Device {'WARN' if not proto_ok else 'OK'} — fw {fw}  "
            f"proto v{proto}  "
            f"active_slot {info.get('active_slot')}/{info.get('slot_count')}  "
            f"host {app_version.HOST_APP_VERSION}"
        )
        self.statusBar().showMessage(status, 15000)
        QMessageBox.information(self, "Device info", msg)


    def _device_upload_profile(self) -> None:
        """Pack the selected profile and upload into a chosen device slot."""
        if self._current is None:
            QMessageBox.information(
                self, "Upload", "Select a profile to upload."
            )
            return

        try:
            from .protocol.device import ConfigDevice, DeviceError
            from .protocol.profile_blob import (
                PROFILE_BLOB_V1_SIZE,
                pack_profile,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Upload", f"Protocol module unavailable:\n{exc}"
            )
            return

        default_slot = 0
        if self._last_device_info is not None:
            try:
                default_slot = int(self._last_device_info.get("active_slot", 0))
            except (TypeError, ValueError):
                default_slot = 0
        builtin = {
            "default": 0,
            "gaming": 1,
            "coding": 2,
            "browser": 3,
            "photoshop": 4,
        }
        if self._current.id in builtin:
            default_slot = builtin[self._current.id]

        slot, ok = QInputDialog.getInt(
            self,
            "Upload to device",
            (
                f"Upload profile {self._current.name!r} ({self._current.id})\n"
                f"into device slot (0–4):"
            ),
            default_slot,
            0,
            4,
            1,
        )
        if not ok:
            return

        try:
            blob = pack_profile(self._current)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Upload", f"Pack failed:\n{exc}")
            return
        if len(blob) != PROFILE_BLOB_V1_SIZE:
            QMessageBox.critical(
                self,
                "Upload",
                f"Unexpected blob size {len(blob)} (expected {PROFILE_BLOB_V1_SIZE})",
            )
            return

        self.statusBar().showMessage(
            f"Uploading {self._current.id} → slot {slot}…"
        )
        try:
            with ConfigDevice(timeout_ms=2000) as dev:
                try:
                    self._last_device_info = dev.get_info()
                except DeviceError:
                    pass
                dev.upload_profile(slot, blob)
        except DeviceError as exc:
            self.statusBar().showMessage("Upload failed", 8000)
            QMessageBox.warning(self, "Upload failed", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage("Upload failed", 8000)
            QMessageBox.warning(self, "Upload failed", str(exc))
            return

        msg = (
            f"Uploaded {self._current.name} ({self._current.id}) "
            f"into device slot {slot}."
        )
        self.statusBar().showMessage(msg, 15000)
        QMessageBox.information(self, "Upload", msg)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Macropad Configurator",
            (
                "<b>Macropad Configurator</b><br>"
                f"Version <b>{app_version.HOST_APP_VERSION}</b> — Step 23 "
                "hardware-in-the-loop test tooling<br><br>"
                f"Protocol (host): <b>{app_version.PROTO_VER}</b><br>"
                f"Expected firmware: <b>{app_version.FW_VERSION_MAJOR_EXPECTED}."
                f"{app_version.FW_VERSION_MINOR_CURRENT}</b><br>"
                f"Profile / macro / autoswitch schemas: <b>"
                f"{app_version.PROFILE_SCHEMA_VERSION}/"
                f"{app_version.MACRO_SCHEMA_VERSION}/"
                f"{app_version.AUTOSWITCH_SCHEMA_VERSION}</b><br><br>"
                "Loads/saves <code>profiles/</code> and <code>macros/library.json</code>.<br>"
                "Compatibility: <code>docs/VERSIONING.md</code><br>"
                "Architecture: <code>docs/ARCHITECTURE.md</code><br>"
                "Device → Connect shows fw / proto; mismatches warn and gate features."
            ),
        )

    def _show_architecture_tip(self) -> None:
        self.statusBar().showMessage(
            "Architecture: docs/ARCHITECTURE.md (layers, flash vs RAM, protocol links)",
            12000,
        )
        QMessageBox.information(
            self,
            "Architecture",
            (
                "Stack overview lives in the repo at:\n\n"
                "    docs/ARCHITECTURE.md\n\n"
                "It covers layers (pins → matrix → actions → USB/config → "
                "flash v2 → host), data flows, and flash vs RAM."
            ),
        )

    def _device_save_all(self) -> None:
        """SAVE_ALL (0x32) — immediate device flash rewrite."""
        try:
            from .protocol.device import ConfigDevice, DeviceError
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Save device state", f"Protocol module unavailable:\n{exc}"
            )
            return

        self.statusBar().showMessage("Saving device state (SAVE_ALL)…")
        try:
            with ConfigDevice(timeout_ms=3000) as dev:
                try:
                    self._last_device_info = dev.get_info()
                except DeviceError:
                    pass
                dev.save_all()
        except DeviceError as exc:
            self.statusBar().showMessage("Save device state failed", 8000)
            QMessageBox.warning(self, "Save device state failed", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage("Save device state failed", 8000)
            QMessageBox.warning(self, "Save device state failed", str(exc))
            return

        self._autoswitch_connected = True
        if self._last_device_info is not None:
            self._apply_device_feature_gates(self._last_device_info)
        else:
            self._autoswitch_act.setEnabled(True)
            self._save_device_act.setEnabled(True)
        msg = "Device state saved (profiles + macros + active_slot)."
        self.statusBar().showMessage(msg, 10000)
        QMessageBox.information(self, "Save device state", msg)


    def _ensure_autoswitch(self):
        if self._autoswitch is not None:
            return self._autoswitch
        from .autoswitch.service import AutoswitchService

        try:
            ids = [p.id for p in self._profile_list.profiles()]
        except Exception:
            ids = []
        if not ids:
            ids = ["default", "gaming", "coding", "browser", "photoshop"]
        svc = AutoswitchService(
            self,
            on_status=lambda msg: self.statusBar().showMessage(msg, 8000),
            on_stopped=self._on_autoswitch_stopped,
            host_profile_ids=ids,
        )
        try:
            svc.load()
        except Exception:
            pass
        self._autoswitch = svc
        return svc

    def _open_autoswitch_dialog(self) -> None:
        svc = self._ensure_autoswitch()
        try:
            rules = svc.rules
            if rules.schema_version != 1 or not rules.rules:
                from .autoswitch.rules import load_rules
                rules = load_rules()
                svc.set_rules(rules)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Auto-switch", f"Could not load rules:\n{exc}")
            return
        profile_ids = []
        try:
            profile_ids = [p.id for p in self._profile_list.profiles()]
        except Exception:
            profile_ids = ["default", "gaming", "coding", "browser", "photoshop"]
        dlg = AutoswitchDialog(rules, parent=self, profile_ids=profile_ids or None)
        if dlg.exec():
            updated = dlg.result_rules()
            svc.set_rules(updated)
            # Sync checkable menu with saved enabled flag only if connected
            if self._autoswitch_connected and updated.enabled:
                self._autoswitch_act.blockSignals(True)
                self._autoswitch_act.setChecked(True)
                self._autoswitch_act.blockSignals(False)
                svc.set_enabled(True)
            elif not updated.enabled:
                self._autoswitch_act.blockSignals(True)
                self._autoswitch_act.setChecked(False)
                self._autoswitch_act.blockSignals(False)
                svc.set_enabled(False)
            self.statusBar().showMessage("Auto-switch rules saved", 5000)

    def _on_autoswitch_stopped(self) -> None:
        """Menu sync when service stops after device disconnect."""
        self._autoswitch_act.blockSignals(True)
        self._autoswitch_act.setChecked(False)
        self._autoswitch_act.blockSignals(False)

    def _on_autoswitch_toggled(self, checked: bool) -> None:
        if checked and not self._autoswitch_connected:
            self._autoswitch_act.blockSignals(True)
            self._autoswitch_act.setChecked(False)
            self._autoswitch_act.blockSignals(False)
            QMessageBox.information(
                self,
                "Auto-switch",
                "Connect to the device first (Device → Connect / Get device info).",
            )
            return
        svc = self._ensure_autoswitch()
        # Keep rules.enabled in sync when toggling from menu
        rules = svc.rules
        rules.enabled = bool(checked)
        svc.set_rules(rules)
        svc.set_enabled(bool(checked))

    def _device_upload_macros(self) -> None:
        """Upload host macro library ids 0–4 to the device (Step 17)."""
        try:
            from .models.macro import load_library
            from .protocol.device import ConfigDevice, DeviceError
            from .protocol.macro_blob import MACRO_BLOB_V1_SIZE, pack_macro
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Upload macros", f"Module unavailable:\n{exc}"
            )
            return

        try:
            library = load_library()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Upload macros", f"Could not load library:\n{exc}")
            return

        by_id = {m.id: m for m in library.macros}
        to_upload = [(i, by_id[i]) for i in range(5) if i in by_id]
        if not to_upload:
            QMessageBox.information(
                self, "Upload macros", "No macros with ids 0–4 in the library."
            )
            return

        reply = QMessageBox.question(
            self,
            "Upload macros",
            f"Upload {len(to_upload)} macro(s) (ids 0–4) to the device flash bank?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.statusBar().showMessage("Uploading macros…")
        uploaded = 0
        try:
            with ConfigDevice(timeout_ms=2000) as dev:
                try:
                    self._last_device_info = dev.get_info()
                    self._autoswitch_connected = True
                    self._autoswitch_act.setEnabled(True)
                    self._save_device_act.setEnabled(True)
                except DeviceError:
                    pass
                for mid, macro in to_upload:
                    blob = pack_macro(macro)
                    if len(blob) != MACRO_BLOB_V1_SIZE:
                        raise DeviceError(
                            f"macro {mid} blob size {len(blob)} != {MACRO_BLOB_V1_SIZE}"
                        )
                    dev.upload_macro(mid, blob)
                    uploaded += 1
        except DeviceError as exc:
            self.statusBar().showMessage("Macro upload failed", 8000)
            QMessageBox.warning(self, "Upload macros failed", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage("Macro upload failed", 8000)
            QMessageBox.warning(self, "Upload macros failed", str(exc))
            return

        msg = f"Uploaded {uploaded} macro(s) to device."
        self.statusBar().showMessage(msg, 15000)
        QMessageBox.information(self, "Upload macros", msg)
