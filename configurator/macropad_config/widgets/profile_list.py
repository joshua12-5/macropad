"""Left-panel list of loaded profiles."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget, QLabel

from ..models.profile import Profile


class ProfileListWidget(QWidget):
    """Simple list showing profile display names; emits selection changes."""

    profile_selected = Signal(object)  # Profile | None

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

    def set_profiles(self, profiles: list[Profile]) -> None:
        self._profiles = list(profiles)
        self._list.blockSignals(True)
        self._list.clear()
        for profile in self._profiles:
            item = QListWidgetItem(f"{profile.name}  ({profile.id})")
            item.setToolTip(str(profile.source_path) if profile.source_path else profile.id)
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self._profiles:
            self._list.setCurrentRow(0)
        else:
            self.profile_selected.emit(None)

    def profiles(self) -> list[Profile]:
        return list(self._profiles)

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

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._profiles):
            self.profile_selected.emit(self._profiles[row])
        else:
            self.profile_selected.emit(None)
