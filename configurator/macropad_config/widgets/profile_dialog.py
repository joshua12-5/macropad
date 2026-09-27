"""Dialog for creating or duplicating a profile (name + id)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..models.profile import is_valid_profile_id, suggest_profile_id


class ProfileNameIdDialog(QDialog):
    """Collect a display name and unique profile id."""

    def __init__(
        self,
        *,
        title: str,
        existing_ids: set[str],
        initial_name: str = "",
        initial_id: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._existing_ids = set(existing_ids)
        self._id_manual = False

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit(initial_name)
        self._name_edit.setPlaceholderText("Display name")
        self._name_edit.textChanged.connect(self._on_name_changed)
        form.addRow("Name", self._name_edit)

        self._id_edit = QLineEdit(initial_id)
        self._id_edit.setPlaceholderText("unique_id")
        self._id_edit.textChanged.connect(self._on_id_edited)
        form.addRow("Id", self._id_edit)

        layout.addLayout(form)

        self._error = QLabel("")
        self._error.setObjectName("validationError")
        self._error.setWordWrap(True)
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        layout.addWidget(buttons)

        if initial_id:
            self._id_manual = True
        elif initial_name:
            self._id_edit.setText(suggest_profile_id(initial_name, self._existing_ids))
            self._id_manual = False

        self._validate()

    def _on_name_changed(self, text: str) -> None:
        if not self._id_manual:
            suggested = suggest_profile_id(text, self._existing_ids)
            self._id_edit.blockSignals(True)
            self._id_edit.setText(suggested)
            self._id_edit.blockSignals(False)
        self._validate()

    def _on_id_edited(self, _text: str) -> None:
        self._id_manual = True
        self._validate()

    def _validate(self) -> None:
        name = self._name_edit.text().strip()
        pid = self._id_edit.text().strip()
        err = ""
        if not name:
            err = "Name is required."
        elif not pid:
            err = "Id is required."
        elif not is_valid_profile_id(pid):
            err = "Id must match ^[a-z][a-z0-9_]*$."
        elif pid in self._existing_ids:
            err = f"Id {pid!r} is already in use."
        self._error.setText(err)
        self._ok.setEnabled(not err)

    def profile_name(self) -> str:
        return self._name_edit.text().strip()

    def profile_id(self) -> str:
        return self._id_edit.text().strip()

    def accept(self) -> None:
        self._validate()
        if not self._ok.isEnabled():
            return
        super().accept()
