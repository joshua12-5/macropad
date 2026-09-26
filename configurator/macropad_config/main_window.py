"""Main application window — Step 10 shell."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .models.profile import Profile, default_profiles_dir, load_profiles_dir
from .widgets.pad_preview import PadPreview
from .widgets.profile_list import ProfileListWidget

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
    font-size: 14px;
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
}
QPushButton#encoderButton:hover { background-color: #404249; }
QPushButton#encoderButton:checked {
    background-color: #5865f2;
    border-color: #7983f5;
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
QSplitter::handle {
    background-color: #3c3f45;
    width: 2px;
}
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Macropad Configurator")
        self.resize(960, 640)
        self.setStyleSheet(DARK_STYLE)

        self._profiles_dir = default_profiles_dir()
        self._current: Profile | None = None

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
        reload_act.triggered.connect(self.reload_profiles)
        file_menu.addAction(reload_act)

        file_menu.addSeparator()

        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        device_menu = self.menuBar().addMenu("&Device")
        upload_act = QAction("Upload to device", self)
        upload_act.setEnabled(False)
        upload_act.setToolTip("Coming in protocol step")
        upload_act.setStatusTip("Coming in protocol step")
        device_menu.addAction(upload_act)

        help_menu = self.menuBar().addMenu("&Help")
        about_act = QAction("&About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._profile_list = ProfileListWidget()
        self._profile_list.profile_selected.connect(self._on_profile_selected)
        splitter.addWidget(self._profile_list)

        self._pad = PadPreview()
        self._pad.selection_changed.connect(self._on_selection_changed)
        splitter.addWidget(self._pad)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        summary_heading = QLabel("Profile")
        summary_heading.setObjectName("sectionHeading")
        right_layout.addWidget(summary_heading)

        self._summary = QTextEdit()
        self._summary.setObjectName("detailsPanel")
        self._summary.setReadOnly(True)
        self._summary.setMaximumHeight(120)
        right_layout.addWidget(self._summary)

        action_heading = QLabel("Selected action")
        action_heading.setObjectName("sectionHeading")
        right_layout.addWidget(action_heading)

        self._action_view = QTextEdit()
        self._action_view.setObjectName("detailsPanel")
        self._action_view.setReadOnly(True)
        self._action_view.setPlaceholderText("Click a key or encoder slot…")
        right_layout.addWidget(self._action_view)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([200, 480, 280])

        layout.addWidget(splitter)
        self.statusBar().showMessage("Ready")

    def reload_profiles(self) -> None:
        self._profiles_dir = default_profiles_dir()
        profiles, errors = load_profiles_dir(self._profiles_dir)

        # SCHEMA.md is .md; *.json that aren't profiles (none expected) show as errors
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

        if not profiles:
            self._on_profile_selected(None)

    def _on_profile_selected(self, profile: Profile | None) -> None:
        self._current = profile
        self._pad.set_profile(profile)
        self._pad.clear_selection()
        if profile is None:
            self._summary.setPlainText("(no profile selected)")
            self._action_view.clear()
            return
        summary = {
            "id": profile.id,
            "name": profile.name,
            "schema_version": profile.schema_version,
            "oled_title": profile.oled_title,
        }
        self._summary.setPlainText(json.dumps(summary, indent=2))
        self._action_view.setPlainText("(select a key or encoder action)")

    def _on_selection_changed(self, kind: str, selection_id: object) -> None:
        if not kind or self._current is None:
            self._action_view.clear()
            return
        if kind == "key":
            action = self._current.action_for_key(int(selection_id))
            label = f"Key {selection_id}"
        else:
            action = self._current.action_for_encoder(str(selection_id))
            label = f"Encoder.{selection_id}"

        if action is None:
            self._action_view.setPlainText(f"{label}: (missing)")
            return
        payload = {"selection": label, "action": action}
        self._action_view.setPlainText(json.dumps(payload, indent=2))
        self.statusBar().showMessage(f"{label}: {action.get('type', '?')}")

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

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Macropad Configurator",
            (
                "<b>Macropad Configurator</b><br>"
                "Step 10 — PySide6 shell<br><br>"
                "Profile schema version: <b>1</b><br>"
                "Loads JSON from the repo <code>profiles/</code> folder.<br><br>"
                "Action editors (Steps 11–13) and USB upload (Steps 15–16) "
                "are not implemented yet."
            ),
        )
