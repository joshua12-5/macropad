"""Ctrl+K command palette: fuzzy search over pages, profiles, keys and actions.

Items are plain :class:`PaletteItem` records built by the main window each
time the palette opens (so profile names, key legends and enabled states are
current). Matching is a case-insensitive subsequence match scored by
:func:`fuzzy_score`: consecutive runs, word starts and prefixes rank higher,
so "up" finds "Upload profile…", "k6" finds "Key 6" and "cod" finds CODING.

Keys: type to filter, Up/Down (or Ctrl+N / Ctrl+P) to move, Enter to run,
Esc (or clicking outside) to close.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..ui import theme
from ..ui.widgets import label

MAX_RESULTS = 60
_ROLE_ITEM = Qt.ItemDataRole.UserRole
_ROW_H = 40

# Category order when scores tie (and the order of the unfiltered list).
CATEGORY_ORDER = ("Page", "Profile", "Key", "Action")


@dataclass
class PaletteItem:
    title: str
    category: str  # Page / Profile / Key / Action
    run: Callable[[], None]
    subtitle: str = ""
    shortcut: str = ""
    enabled: bool = True
    keywords: str = ""  # extra search text (not shown)
    disabled_reason: str = ""
    order: int = field(default=0, compare=False)

    def haystack(self) -> str:
        return f"{self.title} {self.keywords}".strip()


def _substring_score(needle: str, t: str) -> float | None:
    """Contiguous match: earliest word-start occurrence wins, else the earliest one."""
    pos = t.find(needle)
    if pos < 0:
        return None
    best = pos
    while pos >= 0:
        if pos == 0 or not t[pos - 1].isalnum():
            best = pos
            break
        pos = t.find(needle, pos + 1)
    bonus = 5.0 if best == 0 else 3.0 if not t[best - 1].isalnum() else 0.0
    return 10.0 + 2.5 * len(needle) + bonus - best * 0.02


def fuzzy_score(query: str, text: str) -> float | None:
    """Score *text* for *query* (higher is better); None when it does not match.

    A contiguous match (query as typed, or with spaces removed) scores highest,
    preferring word starts. Otherwise every query character (spaces ignored)
    must appear in order; word starts, consecutive runs and position 0 earn
    bonuses and gaps cost a little. Shorter texts win ties.
    """
    raw = query.lower().strip()
    q = "".join(raw.split())
    if not q:
        return 0.0
    t = text.lower()
    best = _substring_score(raw, t)
    if best is None and q != raw:
        best = _substring_score(q, t)
    if best is None:
        score = 0.0
        ti = 0
        prev = -2
        for ch in q:
            idx = t.find(ch, ti)
            if idx < 0:
                return None
            bonus = 1.0
            if idx == 0:
                bonus += 3.0
            elif not t[idx - 1].isalnum():
                bonus += 2.0  # word start
            if idx == prev + 1:
                bonus += 1.5  # consecutive
            score += bonus - min(idx - ti, 10) * 0.05  # small penalty for gaps
            prev = idx
            ti = idx + 1
        best = score
    return best - len(t) * 0.01


def rank_items(query: str, items: list[PaletteItem], limit: int = MAX_RESULTS) -> list[PaletteItem]:
    """Filter + sort *items* for *query* (stable within equal scores)."""
    for i, it in enumerate(items):
        it.order = i
    if not query.strip():
        return sorted(items, key=lambda it: (_cat_rank(it.category), it.order))[:limit]
    scored = []
    for it in items:
        s = fuzzy_score(query, it.haystack())
        if s is None and it.subtitle:
            s2 = fuzzy_score(query, it.subtitle)
            s = None if s2 is None else s2 - 6.0  # subtitle matches rank below title matches
        if s is not None:
            if not it.enabled:
                s -= 1.0
            scored.append((s, it))
    scored.sort(key=lambda pair: (-pair[0], _cat_rank(pair[1].category), pair[1].order))
    return [it for _s, it in scored[:limit]]


def _cat_rank(cat: str) -> int:
    return CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else len(CATEGORY_ORDER)


class _ItemDelegate(QStyledItemDelegate):
    """Title (+ muted subtitle) on the left; category and shortcut on the right."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), _ROW_H)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        it: PaletteItem | None = index.data(_ROLE_ITEM)
        if it is None:
            return
        c = {k: theme.qcolor(v) for k, v in theme.palette().items()}
        r = QRectF(option.rect).adjusted(6, 1, -6, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c["selected"])
            p.drawRoundedRect(r, 6, 6)
            p.setBrush(c["accent"])
            p.drawRoundedRect(QRectF(r.left(), r.top() + 10, 3, r.height() - 20), 1.5, 1.5)
        base = QFont(option.font)
        base.setPixelSize(theme.FONT_PX["body"])
        small = QFont(base)
        small.setPixelSize(theme.FONT_PX["small"])
        right = r.right() - 10
        if it.shortcut:
            mono = theme.mono_font(theme.FONT_PX["small"])
            fm = QFontMetrics(mono)
            w = fm.horizontalAdvance(it.shortcut) + 12
            box = QRectF(right - w, r.center().y() - 10, w, 20)
            p.setPen(c["border_strong"])
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
            p.setFont(mono)
            p.setPen(c["text_muted"])
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, it.shortcut)
            right = box.left() - 10
        p.setFont(small)
        fm_s = QFontMetrics(small)
        cw = fm_s.horizontalAdvance(it.category)
        p.setPen(c["text_faint"])
        p.drawText(
            QRectF(right - cw, r.top(), cw, r.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            it.category,
        )
        right -= cw + 14
        left = r.left() + 14
        f_title = QFont(base)
        f_title.setWeight(QFont.Weight.Medium)
        fm_t = QFontMetrics(f_title)
        avail = max(10.0, right - left)
        title = fm_t.elidedText(it.title, Qt.TextElideMode.ElideRight, int(avail))
        p.setFont(f_title)
        p.setPen(c["text"] if it.enabled else c["text_faint"])
        tw = fm_t.horizontalAdvance(title)
        p.drawText(QRectF(left, r.top(), tw + 2, r.height()), Qt.AlignmentFlag.AlignVCenter, title)
        sub = it.subtitle if it.enabled else (it.disabled_reason or it.subtitle)
        if sub and tw + 24 < avail:
            p.setFont(small)
            p.setPen(c["text_faint"] if it.enabled else c["warning"])
            x = left + tw + 10
            p.drawText(
                QRectF(x, r.top(), right - x, r.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                fm_s.elidedText(sub, Qt.TextElideMode.ElideRight, int(right - x)),
            )
        p.restore()


class CommandPalette(QFrame):
    """Popup search box. ``open_with(items)`` shows it centred near the top of the parent."""

    executed = Signal(str)  # title of the item that ran

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("commandPalette")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._items: list[PaletteItem] = []
        self._shown: list[PaletteItem] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.input = QLineEdit()
        self.input.setObjectName("paletteInput")
        self.input.setPlaceholderText("Search pages, profiles, keys and actions…")
        self.input.setClearButtonEnabled(True)
        theme.bind_icon(
            self.input.addAction(theme.icon("search"), QLineEdit.ActionPosition.LeadingPosition), "search"
        )
        self.input.textChanged.connect(self._refilter)
        self.input.installEventFilter(self)
        lay.addWidget(self.input)
        self.list = QListWidget()
        self.list.setObjectName("paletteList")
        self.list.setItemDelegate(_ItemDelegate(self.list))
        self.list.setUniformItemSizes(True)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemActivated.connect(lambda _i: self.run_current())
        self.list.itemClicked.connect(lambda _i: self.run_current())
        lay.addWidget(self.list, 1)
        self.hint = label("↑↓ to move · Enter to run · Esc to close", "caption")
        self.empty = label("No matches", "hintLabel")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.hide()
        lay.addWidget(self.empty)
        lay.addWidget(self.hint)

    # -- public ------------------------------------------------------------------
    def open_with(self, items: list[PaletteItem], query: str = "") -> None:
        self._items = list(items)
        parent = self.parentWidget()
        w = min(640, max(420, parent.width() - 160)) if parent else 560
        h = min(460, max(260, (parent.height() - 140) if parent else 420))
        self.resize(w, h)
        if parent is not None:
            top_left = parent.mapToGlobal(QPoint((parent.width() - w) // 2, 64))
            self.move(top_left)
        self.input.blockSignals(True)
        self.input.setText(query)
        self.input.blockSignals(False)
        self._refilter(query)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus(Qt.FocusReason.PopupFocusReason)

    def results(self) -> list[PaletteItem]:
        return list(self._shown)

    def current_item(self) -> PaletteItem | None:
        row = self.list.currentRow()
        return self._shown[row] if 0 <= row < len(self._shown) else None

    def run_current(self) -> bool:
        it = self.current_item()
        if it is None or not it.enabled:
            return False
        self.close()
        # Run after the popup has closed so dialogs / focus changes behave.
        QTimer.singleShot(0, it.run)
        self.executed.emit(it.title)
        return True

    # -- internals ---------------------------------------------------------------
    def _refilter(self, text: str) -> None:
        self._shown = rank_items(text, self._items)
        self.list.clear()
        for it in self._shown:
            li = QListWidgetItem(it.title)
            li.setData(_ROLE_ITEM, it)
            tip = it.subtitle if it.enabled else (it.disabled_reason or "Not available right now")
            if tip:
                li.setToolTip(tip)
            li.setSizeHint(QSize(0, _ROW_H))
            self.list.addItem(li)
        self.empty.setVisible(not self._shown)
        self.list.setVisible(bool(self._shown))
        if self._shown:
            first = next((i for i, it in enumerate(self._shown) if it.enabled), 0)
            self.list.setCurrentRow(first)

    def _move(self, delta: int) -> None:
        n = len(self._shown)
        if not n:
            return
        row = (self.list.currentRow() + delta) % n
        self.list.setCurrentRow(row)
        self.list.scrollToItem(self.list.item(row))

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.input and ev.type() == QEvent.Type.KeyPress:
            return self._handle_key(ev)
        return super().eventFilter(obj, ev)

    def _handle_key(self, ev: QKeyEvent) -> bool:
        key, mods = ev.key(), ev.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Tab) or (ctrl and key == Qt.Key.Key_N):
            self._move(1)
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Backtab) or (ctrl and key == Qt.Key.Key_P):
            self._move(-1)
            return True
        if key == Qt.Key.Key_PageDown:
            self._move(8)
            return True
        if key == Qt.Key.Key_PageUp:
            self._move(-8)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.run_current()
            return True
        if key == Qt.Key.Key_Escape or (ctrl and key == Qt.Key.Key_K):
            self.close()
            return True
        return False

    def keyPressEvent(self, ev) -> None:
        if not self._handle_key(ev):
            super().keyPressEvent(ev)


__all__ = ["CATEGORY_ORDER", "CommandPalette", "PaletteItem", "fuzzy_score", "rank_items"]
