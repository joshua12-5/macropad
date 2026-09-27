"""Small shared building blocks for the themed UI (dividers, titles, pills, tables)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QLabel,
    QLayout,
    QTableView,
    QToolButton,
    QWidget,
)

from . import theme

CONTROL_H = 32  # line edits, combo boxes, buttons (20 px text + 2×5 padding + 2×1 border)


def divider(vertical: bool = False) -> QFrame:
    """1 px hairline used instead of group-box frames."""
    line = QFrame()
    line.setObjectName("vdivider" if vertical else "divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


def label(text: str = "", role: str = "", *, wrap: bool = False, selectable: bool = False) -> QLabel:
    """QLabel with a theme role: sectionTitle, panelTitle, pageTitle, hintLabel, caption, overline …"""
    lab = QLabel(text)
    if role:
        lab.setObjectName(role)
    lab.setWordWrap(wrap)
    if selectable:
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def section_title(text: str) -> QLabel:
    return label(text, "sectionTitle")


def style_form(form: QFormLayout, *, muted_labels: bool = True, label_width: int = 0) -> QFormLayout:
    """Consistent form rhythm: 8 px rows, 12 px label gap, left-aligned muted labels."""
    form.setHorizontalSpacing(theme.SPACE["md"])
    form.setVerticalSpacing(theme.SPACE["sm"])
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
    if muted_labels:
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            w = item.widget() if item is not None else None
            if isinstance(w, QLabel) and not w.objectName():
                w.setObjectName("formLabel")
            if isinstance(w, QLabel) and label_width:
                w.setMinimumWidth(label_width)
            if isinstance(w, QLabel) and w.text():
                # Same height as a 32 px control so the text centres on the field's text.
                w.setMinimumHeight(CONTROL_H)
                w.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return form


def dialog_margins(layout: QLayout, spacing: int | None = None) -> QLayout:
    """Standard dialog padding (16 px) and spacing (12 px)."""
    m = theme.SPACE["lg"]
    layout.setContentsMargins(m, m, m, m)
    layout.setSpacing(theme.SPACE["md"] if spacing is None else spacing)
    return layout


def polish_table(view: QTableView, row_height: int = 32, *, alternating: bool = False) -> QTableView:
    """Comfortable rows, no grid, quiet headers."""
    view.setShowGrid(False)
    view.setAlternatingRowColors(alternating)
    view.verticalHeader().setDefaultSectionSize(row_height)
    view.verticalHeader().setMinimumSectionSize(row_height)
    view.horizontalHeader().setHighlightSections(False)
    view.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    view.horizontalHeader().setMinimumHeight(32)
    view.setWordWrap(False)
    view.setFrameShape(QFrame.Shape.NoFrame)
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    return view


def icon_button(
    name: str, tooltip: str, *, text: str = "", checkable: bool = False, role: str = "text_muted"
) -> QToolButton:
    """Flat toolbar-style button with a themed Lucide icon (text beside when given)."""
    btn = QToolButton()
    theme.bind_icon(btn, name, role)
    btn.setIconSize(QSize(16, 16))
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip)
    btn.setCheckable(checkable)
    btn.setAutoRaise(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if text:
        btn.setText(text)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setProperty("textBeside", True)
    else:
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    return btn


class StatusPill(QWidget):
    """Quiet status indicator: coloured dot + text in a hairline pill."""

    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._tone = tone
        self.setObjectName("statusPill")
        theme.manager().changed.connect(lambda _s: self.update())

    def set_state(self, text: str, tone: str = "neutral") -> None:
        self._text = text
        self._tone = tone
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def tone(self) -> str:
        return self._tone

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self._font())
        return QSize(fm.horizontalAdvance(self._text) + 8 + 6 + 8 + 10, 20)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _font(self):
        f = self.font()
        f.setPixelSize(theme.FONT_PX["small"])
        return f

    def paintEvent(self, _ev) -> None:
        pal = theme.palette()
        tone_color = {
            "success": pal["success"],
            "warning": pal["warning"],
            "danger": pal["danger"],
            "accent": pal["accent"],
        }.get(self._tone, pal["text_faint"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(theme.qcolor(pal["border_strong"]))
        p.setBrush(theme.qcolor(pal["raised"]))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.qcolor(tone_color)))
        cy = r.center().y()
        p.drawEllipse(QRectF(r.left() + 8, cy - 3, 6, 6))
        p.setPen(theme.qcolor(pal["text_muted"]))
        p.setFont(self._font())
        p.drawText(
            r.adjusted(8 + 6 + 6, 0, -8, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._text,
        )
        p.end()
