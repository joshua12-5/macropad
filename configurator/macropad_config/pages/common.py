"""Shared layout helpers for the scrollable form-style pages (Device, Settings)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from ..ui import theme
from ..ui.widgets import divider, label, with_shortcut

CONTENT_MAX_W = 820


class ScrollPage(QScrollArea):
    """Vertically scrolling page with a left-aligned, width-capped content column."""

    def __init__(self, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("pageBody")
        outer = QVBoxLayout(inner)
        S = theme.SPACE
        outer.setContentsMargins(S["xl"], S["lg"], S["xl"], S["xl"])
        self.column = QWidget()
        self.column.setMaximumWidth(CONTENT_MAX_W)
        self.column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.body = QVBoxLayout(self.column)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(S["md"])
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.column, 1)
        row.addStretch(0)
        outer.addLayout(row)
        outer.addStretch(1)
        self.setWidget(inner)

    def section(self, title: str, hint: str = "", *, first: bool = False) -> QVBoxLayout:
        """Append a titled section (divider above unless *first*); returns its layout."""
        if not first:
            self.body.addSpacing(theme.SPACE["sm"])
            self.body.addWidget(divider())
            self.body.addSpacing(theme.SPACE["xs"])
        box = QVBoxLayout()
        box.setSpacing(theme.SPACE["sm"])
        box.addWidget(label(title, "sectionTitle"))
        if hint:
            box.addWidget(label(hint, "hintLabel", wrap=True))
        self.body.addLayout(box)
        return box


def action_button(act: QAction, *, primary: bool = False, text: str = "") -> QToolButton:
    """Text-beside-icon button driven by *act* (enabled state and gate tooltips follow it)."""
    btn = QToolButton()
    btn.setDefaultAction(act)
    # Primary: icon + text; secondary page buttons are text-only (the actions' icons are
    # coloured for the header / menus).
    btn.setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonTextBesideIcon if primary else Qt.ToolButtonStyle.ToolButtonTextOnly
    )
    btn.setIconSize(QSize(16, 16))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        btn.setObjectName("primaryAction")
    else:
        btn.setProperty("outlined", True)

    def sync_tip() -> None:
        if text:
            btn.setText(text)
        btn.setToolTip(with_shortcut(act.toolTip(), act.shortcut()))

    act.changed.connect(sync_tip)
    sync_tip()
    return btn


__all__ = ["CONTENT_MAX_W", "ScrollPage", "action_button"]
