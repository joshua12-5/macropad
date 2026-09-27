"""Settings page: theme, data folders, keyboard shortcuts, About."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QRadioButton,
    QWidget,
)

from ..ui import theme
from ..ui.widgets import icon_button, label
from ..widgets.info_panels import AboutPanel
from .common import ScrollPage

THEME_CHOICES = (("system", "Match system"), ("dark", "Dark"), ("light", "Light"))


def open_in_file_manager(path: Path) -> None:
    """Reveal *path* (a folder, or a file's folder) in the OS file manager."""
    folder = path if path.is_dir() else path.parent
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


class SettingsPage(ScrollPage):
    def __init__(
        self,
        *,
        set_theme: Callable[[str], None],
        data_paths: list[tuple[str, Path]],
        shortcuts: list[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("settingsPage", parent)
        self._set_theme = set_theme

        # --- appearance -----------------------------------------------------------
        app_box = self.section("Appearance", "Match system follows the OS light / dark setting.", first=True)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE["lg"])
        self.theme_group = QButtonGroup(self)
        self.theme_radios: dict[str, QRadioButton] = {}
        for mode, text in THEME_CHOICES:
            rb = QRadioButton(text)
            rb.setObjectName(f"themeRadio_{mode}")
            rb.toggled.connect(lambda on, m=mode: on and self._set_theme(m))
            self.theme_group.addButton(rb)
            self.theme_radios[mode] = rb
            row.addWidget(rb)
        row.addStretch(1)
        app_box.addLayout(row)
        app_box.addWidget(label("Ctrl+Shift+L toggles dark / light from anywhere.", "caption"))
        theme.manager().changed.connect(lambda _s: self.sync_theme())
        self.sync_theme()

        # --- data folders ---------------------------------------------------------------
        data = self.section(
            "Data",
            "Your files on this computer are the master copy. Override the locations with the "
            "MACROPAD_* environment variables (see the user guide).",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE["md"])
        grid.setVerticalSpacing(theme.SPACE["xs"])
        self.path_labels: dict[str, QWidget] = {}
        for r, (name, path) in enumerate(data_paths):
            grid.addWidget(label(name, "formLabel"), r, 0, Qt.AlignmentFlag.AlignVCenter)
            val = label(str(path), "monoLabel", selectable=True)
            val.setToolTip(str(path))
            grid.addWidget(val, r, 1, Qt.AlignmentFlag.AlignVCenter)
            btn = icon_button("folder-open", f"Open {'folder' if path.suffix == '' else 'containing folder'}")
            btn.clicked.connect(lambda _c=False, p=path: self._open(p))
            grid.addWidget(btn, r, 2, Qt.AlignmentFlag.AlignVCenter)
            self.path_labels[name] = val
        grid.setColumnStretch(1, 1)
        data.addLayout(grid)

        # --- shortcuts ---------------------------------------------------------------------
        sc = self.section("Keyboard shortcuts", "Press Ctrl+K anywhere to search everything by name.")
        sgrid = QGridLayout()
        sgrid.setHorizontalSpacing(theme.SPACE["xl"])
        sgrid.setVerticalSpacing(theme.SPACE["xs"])
        half = (len(shortcuts) + 1) // 2
        for i, (keys, what) in enumerate(shortcuts):
            col = 0 if i < half else 2
            r = i if i < half else i - half
            k = label(keys, "shortcutKeys")
            sgrid.addWidget(k, r, col, Qt.AlignmentFlag.AlignLeft)
            sgrid.addWidget(label(what, "hintLabel"), r, col + 1, Qt.AlignmentFlag.AlignLeft)
        sgrid.setColumnStretch(1, 1)
        sgrid.setColumnStretch(3, 1)
        sc.addLayout(sgrid)
        self.shortcut_count = len(shortcuts)

        # --- about -----------------------------------------------------------------------
        about = self.section("About")
        self.about = AboutPanel()
        about.addWidget(self.about)

    def sync_theme(self) -> None:
        mode = theme.manager().mode
        for m, rb in self.theme_radios.items():
            rb.blockSignals(True)
            rb.setChecked(m == mode)
            rb.blockSignals(False)

    def _open(self, path: Path) -> None:
        try:
            open_in_file_manager(path)
        except OSError:
            pass


__all__ = ["THEME_CHOICES", "SettingsPage", "open_in_file_manager"]
