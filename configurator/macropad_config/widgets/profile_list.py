"""Left sidebar: loaded profiles (name, id, device slot) with New / Duplicate / Delete."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..models.profile import Profile
from ..ui import theme
from ..ui.widgets import icon_button, label

_ROLE_ID = Qt.ItemDataRole.UserRole
_ROLE_SLOT = Qt.ItemDataRole.UserRole + 1
_ROLE_ACTIVE = Qt.ItemDataRole.UserRole + 2
_ROW_H = 48


class _ProfileDelegate(QStyledItemDelegate):
    """Two-line row: name + id, with a device-slot badge on the right."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), _ROW_H)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        c = {k: theme.qcolor(v) for k, v in theme.palette().items()}
        r = QRectF(option.rect).adjusted(8, 2, -8, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if selected or hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c["selected"] if selected else c["hover"])
            p.drawRoundedRect(r, 6, 6)
        if selected:
            p.setBrush(c["accent"])
            p.drawRoundedRect(QRectF(r.left(), r.top() + 10, 3, r.height() - 20), 1.5, 1.5)

        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        pid = str(index.data(_ROLE_ID) or "")
        slot = index.data(_ROLE_SLOT)
        active = bool(index.data(_ROLE_ACTIVE))

        base = QFont(option.font)
        base.setPixelSize(theme.FONT_PX["body"])
        f_name = QFont(base)
        f_name.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Medium)
        f_id = QFont(base)
        f_id.setPixelSize(theme.FONT_PX["caption"])

        right = r.right() - 10
        if slot is not None:
            f_badge = QFont(f_id)
            f_badge.setWeight(QFont.Weight.DemiBold)
            text = f"Slot {slot}"
            fm = QFontMetrics(f_badge)
            bw = fm.horizontalAdvance(text) + 14 + (10 if active else 0)
            badge = QRectF(right - bw, r.center().y() - 9, bw, 18)
            p.setPen(QPen(c["accent_line"] if active else c["border_strong"], 1))
            p.setBrush(c["accent_soft"] if active else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(badge.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            tx = badge.adjusted(7, 0, -7, 0)
            if active:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c["accent"])
                p.drawEllipse(QRectF(tx.left(), badge.center().y() - 3, 6, 6))
                tx.setLeft(tx.left() + 10)
            p.setFont(f_badge)
            p.setPen(c["text"] if active else c["text_muted"])
            p.drawText(tx, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            right = badge.left() - 8

        left = r.left() + 14
        width = max(10.0, right - left)
        p.setFont(f_name)
        p.setPen(c["text"])
        fm = QFontMetrics(f_name)
        p.drawText(
            QRectF(left, r.top() + 6, width, r.height() / 2 - 4),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(name, Qt.TextElideMode.ElideRight, int(width)),
        )
        p.setFont(f_id)
        p.setPen(c["text_faint"])
        fm2 = QFontMetrics(f_id)
        p.drawText(
            QRectF(left, r.center().y() + 1, width, r.height() / 2 - 6),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm2.elidedText(pid, Qt.TextElideMode.ElideRight, int(width)),
        )
        p.restore()


class ProfileListWidget(QWidget):
    """Profile list; emits selection and CRUD requests."""

    profile_selected = Signal(object)  # Profile | None
    new_requested = Signal()
    duplicate_requested = Signal()
    delete_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profiles: list[Profile] = []
        self._slot_map: dict[str, int] = {}
        self._active_slot: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, theme.SPACE["md"], 0, theme.SPACE["sm"])
        layout.setSpacing(theme.SPACE["sm"])

        header = QHBoxLayout()
        header.setContentsMargins(theme.SPACE["lg"], 0, theme.SPACE["sm"], 0)
        header.setSpacing(2)
        heading = label("Profiles", "sectionTitle")
        header.addWidget(heading)
        header.addStretch(1)

        self._new_btn = icon_button("plus", "New profile… (Ctrl+N)")
        self._new_btn.setObjectName("profileToolButton")
        self._new_btn.clicked.connect(self.new_requested.emit)
        self._dup_btn = icon_button("copy", "Duplicate profile… (Ctrl+D)")
        self._dup_btn.setObjectName("profileToolButton")
        self._dup_btn.clicked.connect(self.duplicate_requested.emit)
        self._del_btn = icon_button("trash", "Delete profile…")
        self._del_btn.setObjectName("profileToolButton")
        self._del_btn.clicked.connect(self.delete_requested.emit)
        for b in (self._new_btn, self._dup_btn, self._del_btn):
            header.addWidget(b)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setObjectName("sidebarList")
        self._list.setItemDelegate(_ProfileDelegate(self._list))
        self._list.setMouseTracking(True)
        self._list.setUniformItemSizes(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list, 1)

        theme.manager().changed.connect(lambda _s: self._list.viewport().update())
        self._update_button_states()

    # -- device slot badges (display only) ----------------------------------
    def set_slot_map(self, slot_by_id: dict[str, int]) -> None:
        self._slot_map = dict(slot_by_id)
        self.refresh_labels()

    def set_active_slot(self, slot: int | None) -> None:
        self._active_slot = slot
        self.refresh_labels()

    def slot_for(self, profile_id: str) -> int | None:
        return self._slot_map.get(profile_id)

    # -- data ------------------------------------------------------------------
    def set_profiles(self, profiles: list[Profile]) -> None:
        keep_id = None
        row = self._list.currentRow()
        if 0 <= row < len(self._profiles):
            keep_id = self._profiles[row].id

        self._profiles = list(profiles)
        self._list.blockSignals(True)
        self._list.clear()
        for profile in self._profiles:
            self._list.addItem(self._make_item(profile))
        self._list.blockSignals(False)

        if keep_id and any(p.id == keep_id for p in self._profiles):
            self.select_by_id(keep_id)
        elif self._profiles:
            self._list.setCurrentRow(0)
        else:
            self.profile_selected.emit(None)
        self._update_button_states()

    def profiles(self) -> list[Profile]:
        return list(self._profiles)

    def existing_ids(self) -> set[str]:
        return {p.id for p in self._profiles}

    def current_profile(self) -> Profile | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._profiles):
            return self._profiles[row]
        return None

    def select_by_id(self, profile_id: str) -> None:
        for i, profile in enumerate(self._profiles):
            if profile.id == profile_id:
                self._list.setCurrentRow(i)
                return

    def add_profile(self, profile: Profile, *, select: bool = True) -> None:
        self._profiles.append(profile)
        self._list.addItem(self._make_item(profile))
        if select:
            self._list.setCurrentRow(len(self._profiles) - 1)
        self._update_button_states()

    def remove_profile(self, profile_id: str) -> None:
        for i, profile in enumerate(self._profiles):
            if profile.id == profile_id:
                self._profiles.pop(i)
                self._list.takeItem(i)
                break
        if self._profiles:
            row = min(self._list.currentRow(), len(self._profiles) - 1)
            if row < 0:
                row = 0
            self._list.setCurrentRow(row)
        else:
            self.profile_selected.emit(None)
        self._update_button_states()

    def refresh_labels(self) -> None:
        for i, profile in enumerate(self._profiles):
            item = self._list.item(i)
            if item is not None:
                self._fill_item(item, profile)
        self._list.viewport().update()

    @staticmethod
    def _label_for(profile: Profile) -> str:
        return f"{profile.name}  ({profile.id})"

    def _make_item(self, profile: Profile) -> QListWidgetItem:
        item = QListWidgetItem()
        self._fill_item(item, profile)
        return item

    def _fill_item(self, item: QListWidgetItem, profile: Profile) -> None:
        slot = self._slot_map.get(profile.id)
        active = slot is not None and slot == self._active_slot
        item.setText(profile.name)
        item.setData(_ROLE_ID, profile.id)
        item.setData(_ROLE_SLOT, slot)
        item.setData(_ROLE_ACTIVE, active)
        tip = [self._label_for(profile), str(profile.source_path) if profile.source_path else "(unsaved)"]
        if slot is not None:
            tip.append(f"Device slot {slot}" + (" (active on the device)" if active else ""))
        item.setToolTip("\n".join(tip))
        item.setSizeHint(QSize(0, _ROW_H))

    def _update_button_states(self) -> None:
        has = bool(self._profiles) and self._list.currentRow() >= 0
        self._dup_btn.setEnabled(has)
        self._del_btn.setEnabled(has)
        self._new_btn.setEnabled(True)

    def _on_row_changed(self, row: int) -> None:
        self._update_button_states()
        if 0 <= row < len(self._profiles):
            self.profile_selected.emit(self._profiles[row])
        else:
            self.profile_selected.emit(None)
