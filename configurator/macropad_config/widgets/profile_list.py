"""Left-panel list of loaded profiles with New / Duplicate / Delete."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models.profile import Profile


class ProfileListWidget(QWidget):
    """List showing profile display names; emits selection and CRUD requests."""

    profile_selected = Signal(object)  # Profile | None
    new_requested = Signal()
    duplicate_requested = Signal()
    delete_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profiles: list[Profile] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        heading = QLabel("Profiles")
        heading.setObjectName("sectionHeading")
        layout.addWidget(heading)

        self._list = QListWidget()
        self._list.setObjectName("profileList")
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        self._new_btn = QPushButton("New…")
        self._new_btn.setObjectName("profileToolButton")
        self._new_btn.setToolTip("Create a blank profile")
        self._new_btn.clicked.connect(self.new_requested.emit)
        toolbar.addWidget(self._new_btn)

        self._dup_btn = QPushButton("Duplicate…")
        self._dup_btn.setObjectName("profileToolButton")
        self._dup_btn.setToolTip("Duplicate the selected profile")
        self._dup_btn.clicked.connect(self.duplicate_requested.emit)
        toolbar.addWidget(self._dup_btn)

        self._del_btn = QPushButton("Delete…")
        self._del_btn.setObjectName("profileToolButton")
        self._del_btn.setToolTip("Delete the selected profile")
        self._del_btn.clicked.connect(self.delete_requested.emit)
        toolbar.addWidget(self._del_btn)

        layout.addLayout(toolbar)
        self._update_button_states()

    def set_profiles(self, profiles: list[Profile]) -> None:
        keep_id = None
        row = self._list.currentRow()
        if 0 <= row < len(self._profiles):
            keep_id = self._profiles[row].id

        self._profiles = list(profiles)
        self._list.blockSignals(True)
        self._list.clear()
        for profile in self._profiles:
            item = QListWidgetItem(self._label_for(profile))
            item.setToolTip(str(profile.source_path) if profile.source_path else "(unsaved)")
            self._list.addItem(item)
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
        item = QListWidgetItem(self._label_for(profile))
        item.setToolTip(str(profile.source_path) if profile.source_path else "(unsaved)")
        self._list.addItem(item)
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
                item.setText(self._label_for(profile))
                item.setToolTip(str(profile.source_path) if profile.source_path else "(unsaved)")

    @staticmethod
    def _label_for(profile: Profile) -> str:
        return f"{profile.name}  ({profile.id})"

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
