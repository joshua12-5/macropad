"""Editable form for a single profile action dict (Step 11)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..models.schema import ActionType, SchemaError, validate_action

# Common HID key names matching firmware JSON style.
COMMON_KEYS = [
    *[chr(c) for c in range(ord("A"), ord("Z") + 1)],
    *[str(d) for d in range(10)],
    *[f"F{i}" for i in range(1, 13)],
    "ENTER",
    "SPACE",
    "TAB",
    "ESC",
    "BACKSPACE",
    "DELETE",
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
    "/",
    "-",
    "=",
    "[",
    "]",
    "\\",
    ";",
    "'",
    ",",
    ".",
    "`",
]

MACRO_LABELS = {
    0: "hello",
    1: "sel+cpy",
    2: "undo/redo",
    3: "git st",
    4: "alt-tab",
}

TEXT_LABELS = {
    0: "Hello",
    1: "github macropad URL",
    2: "git status\\n",
    3: "console.log(",
    4: "notepad",
    5: "calc",
    6: "Hello, World!",
    7: "ls -la\\n",
}

MEDIA_CODES = [
    "PLAY_PAUSE",
    "NEXT",
    "PREV",
    "STOP",
    "MUTE",
    "SCAN_NEXT",
    "SCAN_PREV",
    "VOLUME_UP",
    "VOLUME_DOWN",
]

VOLUME_DIRS = ["up", "down", "mute"]


class ActionEditor(QWidget):
    """Edit one action dict with type-dependent fields."""

    actionChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._build_ui()
        self._update_field_visibility()
        self.set_enabled(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        self._type = QComboBox()
        for at in ActionType:
            self._type.addItem(at.value, at.value)
        self._type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Type", self._type)

        # KEY / SHORTCUT key
        self._key_combo = QComboBox()
        self._key_combo.setEditable(True)
        self._key_combo.addItems(COMMON_KEYS)
        self._key_combo.currentTextChanged.connect(self._emit_changed)
        self._key_combo.lineEdit().editingFinished.connect(self._emit_changed)
        self._key_row = QWidget()
        key_row_layout = QHBoxLayout(self._key_row)
        key_row_layout.setContentsMargins(0, 0, 0, 0)
        key_row_layout.addWidget(self._key_combo)
        form.addRow("Key", self._key_row)

        # SHORTCUT mods
        self._mods_row = QWidget()
        mods_layout = QHBoxLayout(self._mods_row)
        mods_layout.setContentsMargins(0, 0, 0, 0)
        self._mod_boxes: dict[str, QCheckBox] = {}
        for name in ("CTRL", "SHIFT", "ALT", "GUI"):
            box = QCheckBox(name)
            box.stateChanged.connect(self._emit_changed)
            mods_layout.addWidget(box)
            self._mod_boxes[name] = box
        mods_layout.addStretch(1)
        form.addRow("Mods", self._mods_row)

        # MACRO
        self._macro_spin = QSpinBox()
        self._macro_spin.setRange(0, 4)
        self._macro_spin.valueChanged.connect(self._on_macro_changed)
        self._macro_label = QLabel("")
        self._macro_label.setObjectName("hintLabel")
        macro_wrap = QWidget()
        macro_layout = QHBoxLayout(macro_wrap)
        macro_layout.setContentsMargins(0, 0, 0, 0)
        macro_layout.addWidget(self._macro_spin)
        macro_layout.addWidget(self._macro_label, stretch=1)
        self._macro_row = macro_wrap
        form.addRow("Macro id", self._macro_row)

        # TEXT / URL / APP text_id
        self._text_spin = QSpinBox()
        self._text_spin.setRange(0, 7)
        self._text_spin.valueChanged.connect(self._on_text_changed)
        self._text_label = QLabel("")
        self._text_label.setObjectName("hintLabel")
        text_wrap = QWidget()
        text_layout = QHBoxLayout(text_wrap)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(self._text_spin)
        text_layout.addWidget(self._text_label, stretch=1)
        self._text_row = text_wrap
        form.addRow("Text id", self._text_row)

        # MEDIA
        self._media_combo = QComboBox()
        self._media_combo.setEditable(True)
        self._media_combo.addItems(MEDIA_CODES)
        self._media_combo.currentTextChanged.connect(self._emit_changed)
        self._media_combo.lineEdit().editingFinished.connect(self._emit_changed)
        self._usage_edit = QLineEdit()
        self._usage_edit.setPlaceholderText("optional usage hex e.g. 0x00B5")
        self._usage_edit.textChanged.connect(self._emit_changed)
        media_wrap = QWidget()
        media_layout = QVBoxLayout(media_wrap)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(4)
        media_layout.addWidget(self._media_combo)
        media_layout.addWidget(self._usage_edit)
        self._media_row = media_wrap
        form.addRow("Media", self._media_row)

        # VOLUME
        self._volume_combo = QComboBox()
        self._volume_combo.addItems(VOLUME_DIRS)
        self._volume_combo.currentIndexChanged.connect(self._emit_changed)
        self._volume_row = self._volume_combo
        form.addRow("Volume", self._volume_row)

        # PROFILE
        self._slot_spin = QSpinBox()
        self._slot_spin.setRange(0, 4)
        self._slot_spin.valueChanged.connect(self._emit_changed)
        self._profile_id_edit = QLineEdit()
        self._profile_id_edit.setPlaceholderText("optional profile_id")
        self._profile_id_edit.textChanged.connect(self._emit_changed)
        profile_wrap = QWidget()
        profile_layout = QVBoxLayout(profile_wrap)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setSpacing(4)
        slot_line = QHBoxLayout()
        slot_line.addWidget(QLabel("Slot"))
        slot_line.addWidget(self._slot_spin)
        slot_line.addStretch(1)
        profile_layout.addLayout(slot_line)
        profile_layout.addWidget(self._profile_id_edit)
        self._profile_row = profile_wrap
        form.addRow("Profile", self._profile_row)

        root.addLayout(form)

        self._error = QLabel("")
        self._error.setObjectName("validationError")
        self._error.setWordWrap(True)
        self._error.hide()
        root.addWidget(self._error)

        self._on_macro_changed(self._macro_spin.value())
        self._on_text_changed(self._text_spin.value())

    def set_enabled(self, enabled: bool) -> None:  # noqa: FBT001
        super().setEnabled(enabled)
        if not enabled:
            self._error.hide()

    def set_action(self, action: dict[str, Any] | None) -> None:
        """Populate the form from an action dict (or clear if None)."""
        self._loading = True
        try:
            if action is None:
                self._type.setCurrentText(ActionType.DISABLED.value)
                self._clear_fields()
                self._update_field_visibility()
                self._error.hide()
                return

            atype = str(action.get("type", ActionType.DISABLED.value))
            idx = self._type.findData(atype)
            if idx < 0:
                idx = self._type.findData(ActionType.DISABLED.value)
            self._type.setCurrentIndex(max(0, idx))

            key = str(action.get("key", "A"))
            self._set_combo_text(self._key_combo, key)

            mods = action.get("mods") or []
            if not isinstance(mods, list):
                mods = []
            mod_set = {str(m).upper() for m in mods}
            # Map WIN/CMD → GUI checkbox
            if "WIN" in mod_set or "CMD" in mod_set:
                mod_set.add("GUI")
            for name, box in self._mod_boxes.items():
                box.setChecked(name in mod_set)

            self._macro_spin.setValue(int(action.get("macro_id", 0)))
            text_id = action.get("text_id", action.get("app_id", 0))
            self._text_spin.setValue(int(text_id) if text_id is not None else 0)

            code = str(action.get("code", "PLAY_PAUSE"))
            self._set_combo_text(self._media_combo, code)
            usage = action.get("usage", "")
            self._usage_edit.setText(str(usage) if usage else "")

            direction = str(action.get("dir", "up"))
            vol_idx = self._volume_combo.findText(direction)
            self._volume_combo.setCurrentIndex(vol_idx if vol_idx >= 0 else 0)

            self._slot_spin.setValue(int(action.get("slot", 0)))
            pid = action.get("profile_id", "")
            self._profile_id_edit.setText(str(pid) if pid else "")

            self._update_field_visibility()
            self._on_macro_changed(self._macro_spin.value())
            self._on_text_changed(self._text_spin.value())
            self._show_validation(None)
        finally:
            self._loading = False

    def get_action(self) -> dict[str, Any]:
        """Build and validate the current action dict. Raises SchemaError."""
        atype = self._type.currentData()
        action: dict[str, Any] = {"type": atype}

        if atype == ActionType.DISABLED.value:
            pass
        elif atype == ActionType.KEY.value:
            action["key"] = self._key_combo.currentText().strip() or "A"
        elif atype == ActionType.SHORTCUT.value:
            action["key"] = self._key_combo.currentText().strip() or "A"
            mods = [name for name, box in self._mod_boxes.items() if box.isChecked()]
            action["mods"] = mods
        elif atype == ActionType.MACRO.value:
            action["macro_id"] = self._macro_spin.value()
        elif atype in (ActionType.TEXT.value, ActionType.URL.value):
            action["text_id"] = self._text_spin.value()
        elif atype == ActionType.APP.value:
            action["text_id"] = self._text_spin.value()
        elif atype == ActionType.MEDIA.value:
            code = self._media_combo.currentText().strip()
            usage = self._usage_edit.text().strip()
            if code:
                action["code"] = code
            if usage:
                action["usage"] = usage
            if "code" not in action and "usage" not in action:
                action["code"] = "PLAY_PAUSE"
        elif atype == ActionType.VOLUME.value:
            action["dir"] = self._volume_combo.currentText()
        elif atype == ActionType.PROFILE.value:
            action["slot"] = self._slot_spin.value()
            pid = self._profile_id_edit.text().strip()
            if pid:
                action["profile_id"] = pid

        return validate_action(action)

    def _clear_fields(self) -> None:
        self._set_combo_text(self._key_combo, "A")
        for box in self._mod_boxes.values():
            box.setChecked(False)
        self._macro_spin.setValue(0)
        self._text_spin.setValue(0)
        self._set_combo_text(self._media_combo, "PLAY_PAUSE")
        self._usage_edit.clear()
        self._volume_combo.setCurrentIndex(0)
        self._slot_spin.setValue(0)
        self._profile_id_edit.clear()

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str) -> None:
        idx = combo.findText(text)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setEditText(text)

    def _on_type_changed(self, _index: int = 0) -> None:
        self._update_field_visibility()
        self._emit_changed()

    def _update_field_visibility(self) -> None:
        atype = self._type.currentData() or ActionType.DISABLED.value
        show_key = atype in (ActionType.KEY.value, ActionType.SHORTCUT.value)
        show_mods = atype == ActionType.SHORTCUT.value
        show_macro = atype == ActionType.MACRO.value
        show_text = atype in (
            ActionType.TEXT.value,
            ActionType.URL.value,
            ActionType.APP.value,
        )
        show_media = atype == ActionType.MEDIA.value
        show_volume = atype == ActionType.VOLUME.value
        show_profile = atype == ActionType.PROFILE.value

        self._key_row.setVisible(show_key)
        self._mods_row.setVisible(show_mods)
        self._macro_row.setVisible(show_macro)
        self._text_row.setVisible(show_text)
        self._media_row.setVisible(show_media)
        self._volume_row.setVisible(show_volume)
        self._profile_row.setVisible(show_profile)

        # Hide form labels for invisible rows via parent form — labels stay;
        # visibility on the field widgets is enough for usability.

    def _on_macro_changed(self, value: int) -> None:
        name = MACRO_LABELS.get(value, "?")
        self._macro_label.setText(name)
        self._emit_changed()

    def _on_text_changed(self, value: int) -> None:
        name = TEXT_LABELS.get(value, "")
        self._text_label.setText(name)
        self._emit_changed()

    def _emit_changed(self, *_args: object) -> None:
        if self._loading:
            return
        try:
            validate_action(self.get_action())
            self._show_validation(None)
        except SchemaError as exc:
            self._show_validation(str(exc))
        except Exception as exc:  # noqa: BLE001 — surface any build error
            self._show_validation(str(exc))
        self.actionChanged.emit()

    def _show_validation(self, message: str | None) -> None:
        if message:
            self._error.setText(message)
            self._error.show()
        else:
            self._error.clear()
            self._error.hide()


__all__ = ["ActionEditor"]
