"""Left navigation rail and the page header (title, breadcrumb, unsaved dot).

The rail holds one checkable button per page (icon over a short label). A page
with unsaved edits gets an accent dot on its icon; the header repeats that as
"• Unsaved" next to the page title and breadcrumb (e.g. ``CODING › Key 6``).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..ui import theme
from ..ui.widgets import label, with_shortcut

BREADCRUMB_SEP = " › "


@dataclass(frozen=True)
class PageSpec:
    key: str  # stable id: keys, macros, idle, autoswitch, device, settings
    title: str  # header title / palette entry
    rail_text: str  # short rail label
    icon: str
    shortcut: str  # "Ctrl+1" …
    hint: str  # tooltip / palette subtitle


PAGES: tuple[PageSpec, ...] = (
    PageSpec("keys", "Keys", "Keys", "keyboard", "Ctrl+1", "Profiles, keys and encoder actions"),
    PageSpec("macros", "Macros", "Macros", "list-ordered", "Ctrl+2", "Macro library (macros/library.json)"),
    PageSpec("idle", "Idle animation", "Idle", "film", "Ctrl+3", "OLED idle animation editor and upload"),
    PageSpec(
        "autoswitch", "Auto-switch", "Auto-switch", "repeat", "Ctrl+4", "Switch profiles by foreground app"
    ),
    PageSpec("device", "Device", "Device", "cpu", "Ctrl+5", "Connect, info, upload, backup and firmware"),
    PageSpec(
        "settings", "Settings", "Settings", "settings", "Ctrl+6", "Theme, data folders, shortcuts, about"
    ),
)
PAGE_INDEX = {p.key: i for i, p in enumerate(PAGES)}


class RailButton(QToolButton):
    """Rail entry; paints an accent dot on the icon when its page has unsaved edits."""

    def __init__(self, spec: PageSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self._dirty = False
        self.setObjectName("railButton")
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setText(spec.rail_text)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(20, 20))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(56)
        theme.bind_icon(self, spec.icon, "text_muted", checked_role="accent")
        self._set_tip()

    def _set_tip(self) -> None:
        tip = with_shortcut(f"{self.spec.title} — {self.spec.hint}", self.spec.shortcut)
        if self._dirty:
            tip += "\nUnsaved changes"
        self.setToolTip(tip)
        self.setAccessibleName(self.spec.title + (" (unsaved changes)" if self._dirty else ""))

    def set_dirty(self, dirty: bool) -> None:
        if dirty != self._dirty:
            self._dirty = dirty
            self._set_tip()
            self.update()

    def is_dirty(self) -> bool:
        return self._dirty

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        if not self._dirty:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2 + 11
        p.setPen(QPen(theme.color("panel"), 2))
        p.setBrush(theme.color("accent"))
        p.drawEllipse(QRectF(cx - 4, 7, 8, 8))
        p.end()


class NavRail(QWidget):
    """Vertical page switcher. Emits :pyattr:`pageRequested` with the page index."""

    pageRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(84)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, theme.SPACE["sm"], 6, theme.SPACE["sm"])
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: list[RailButton] = []
        for i, spec in enumerate(PAGES):
            if spec.key == "settings":
                lay.addStretch(1)
            btn = RailButton(spec, self)
            self._group.addButton(btn, i)
            btn.clicked.connect(lambda _c=False, idx=i: self.pageRequested.emit(idx))
            lay.addWidget(btn)
            self.buttons.append(btn)

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)

    def current(self) -> int:
        return self._group.checkedId()

    def set_dirty(self, index: int, dirty: bool) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].set_dirty(dirty)


class DirtyBadge(QWidget):
    """ "• Unsaved" marker in the page header."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("unsavedBadge")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._dot = QWidget()
        self._dot.setObjectName("unsavedDot")
        self._dot.setFixedSize(7, 7)
        lay.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.text = label("Unsaved", "unsavedLabel")
        lay.addWidget(self.text, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setToolTip(with_shortcut("This page has unsaved changes", "Ctrl+S"))


class ElidedLabel(QLabel):
    """Single-line label that shrinks with an ellipsis instead of forcing the layout wider."""

    def minimumSizeHint(self) -> QSize:
        return QSize(24, super().minimumSizeHint().height())

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        r = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle, r.width())
        p.drawText(r, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        p.end()


class PageHeader(QWidget):
    """Title + breadcrumb + unsaved badge on the left, page actions on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(56)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.SPACE["lg"], 0, theme.SPACE["lg"], 0)
        lay.setSpacing(theme.SPACE["md"])
        self.title = label("", "pageTitle")
        lay.addWidget(self.title, 0, Qt.AlignmentFlag.AlignVCenter)
        self.crumb = ElidedLabel("")
        self.crumb.setObjectName("breadcrumb")
        self.crumb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.crumb, 0, Qt.AlignmentFlag.AlignVCenter)
        self.badge = DirtyBadge()
        self.badge.hide()
        lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        self.actions_layout = QHBoxLayout()
        self.actions_layout.setSpacing(theme.SPACE["sm"])
        lay.addLayout(self.actions_layout)

    def set_location(self, title: str, crumbs: list[str], dirty: bool) -> None:
        self.title.setText(title)
        parts = [c for c in crumbs if c]
        text = BREADCRUMB_SEP.join(parts)
        self.crumb.setText(text)
        self.crumb.setToolTip(text)
        self.badge.setVisible(dirty)

    def breadcrumb(self) -> str:
        return self.crumb.text()


__all__ = [
    "BREADCRUMB_SEP",
    "PAGES",
    "PAGE_INDEX",
    "DirtyBadge",
    "ElidedLabel",
    "NavRail",
    "PageHeader",
    "PageSpec",
    "RailButton",
]
