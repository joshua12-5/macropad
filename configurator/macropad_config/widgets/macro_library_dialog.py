"""Macro library editor: the Macros page of the main window (``embedded=True``)
or a stand-alone dialog (tests, scripts)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models.macro import (
    MACRO_OPS,
    Macro,
    MacroLibrary,
    MacroLoadError,
    MacroStep,
    default_macros_path,
    load_library,
    save_library,
)
from ..models.schema import SchemaError
from ..ui import theme
from ..ui.widgets import (
    EmptyState,
    dialog_margins,
    divider,
    icon_button,
    label,
    polish_table,
    style_form,
    with_shortcut,
)
from .action_editor import COMMON_KEYS, MOD_LABELS, TEXT_LABELS

# Consumer usage presets (label, value).
CONSUMER_PRESETS: list[tuple[str, int]] = [
    ("(custom)", -1),
    ("PLAY_PAUSE 0x00CD", 0x00CD),
    ("NEXT 0x00B5", 0x00B5),
    ("PREV 0x00B6", 0x00B6),
    ("STOP 0x00B7", 0x00B7),
    ("MUTE 0x00E2", 0x00E2),
    ("VOLUME_UP 0x00E9", 0x00E9),
    ("VOLUME_DOWN 0x00EA", 0x00EA),
]


class MacroLibraryDialog(QDialog):
    """Edit macros/library.json: list + step table + Save/Cancel.

    With ``embedded=True`` it is a plain page widget: Save keeps it open,
    Cancel becomes Revert (reload from disk), Esc / Enter do nothing special,
    and :pyattr:`dirtyChanged` / :pyattr:`saved` report state to the window.
    """

    dirtyChanged = Signal(bool)
    saved = Signal()
    currentMacroChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, embedded: bool = False) -> None:
        super().__init__(parent)
        self._embedded = embedded
        self.__dirty = False
        self.setWindowTitle("Macro library")
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setObjectName("macrosPage")
        else:
            self.resize(900, 560)
            self.setModal(True)

        self._path = default_macros_path()
        self._library: MacroLibrary | None = None
        self._loading = False
        self._dirty = False
        self._current_id: int | None = None
        # Index of the step currently shown in the step editor (-1 = none). Edits are
        # written back only to this step, and only when they actually change it.
        self._editor_idx = -1

        self._build_ui()
        self._load_or_empty()

    # --- dirty state -----------------------------------------------------
    @property
    def _dirty(self) -> bool:
        return self.__dirty

    @_dirty.setter
    def _dirty(self, value: bool) -> None:
        value = bool(value)
        if value != self.__dirty:
            self.__dirty = value
            self.dirtyChanged.emit(value)

    def is_dirty(self) -> bool:
        return self.__dirty

    def current_macro_name(self) -> str:
        m = self._current_macro()
        return m.name if m is not None else ""

    def _build_ui(self) -> None:
        S = theme.SPACE
        root = dialog_margins(QVBoxLayout(self))
        if self._embedded:
            root.setContentsMargins(S["lg"], S["md"], S["lg"], S["md"])

        body = QHBoxLayout()
        body.setSpacing(S["lg"])

        # --- left: macro list + CRUD ---
        left = QVBoxLayout()
        left.setSpacing(S["sm"])
        head = QHBoxLayout()
        head.setSpacing(2)
        head.addWidget(label("Macros", "sectionTitle"))
        head.addStretch(1)
        self._btn_new = icon_button("plus", "New macro")
        self._btn_new.setObjectName("profileToolButton")
        self._btn_new.clicked.connect(self._new_macro)
        self._btn_dup = icon_button("copy", "Duplicate macro")
        self._btn_dup.setObjectName("profileToolButton")
        self._btn_dup.clicked.connect(self._duplicate_macro)
        self._btn_del = icon_button("trash", "Delete macro")
        self._btn_del.setObjectName("profileToolButton")
        self._btn_del.clicked.connect(self._delete_macro)
        for b in (self._btn_new, self._btn_dup, self._btn_del):
            head.addWidget(b)
        left.addLayout(head)
        self._list = QListWidget()
        self._list.setObjectName("profileList")
        self._list.currentRowChanged.connect(self._on_macro_selected)
        left.addWidget(self._list, stretch=1)
        left_w = QWidget()
        left_w.setLayout(left)
        left.setContentsMargins(0, 0, 0, 0)
        left_w.setMinimumWidth(220)
        left_w.setMaximumWidth(280)
        body.addWidget(left_w, stretch=1)
        body.addWidget(divider(vertical=True))

        # --- right: name + steps ---
        right = QVBoxLayout()
        right.setSpacing(S["sm"])
        form = QFormLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Macro name")
        self._name_edit.textChanged.connect(self._on_name_changed)
        self._id_label = QLabel("—")
        self._id_label.setObjectName("hintLabel")
        form.addRow("Id", self._id_label)
        form.addRow("Name", self._name_edit)
        style_form(form, label_width=64)
        right.addLayout(form)
        right.addSpacing(S["sm"])

        steps_head = QHBoxLayout()
        steps_head.setSpacing(2)
        steps_head.addWidget(label("Steps", "sectionTitle"))
        steps_head.addStretch(1)
        self._btn_add_step = icon_button("plus", "Add a step after the selected one", text="Add step")
        self._btn_add_step.setObjectName("profileToolButton")
        self._btn_add_step.clicked.connect(self._add_step)
        self._btn_rm_step = icon_button("minus", "Remove the selected step", text="Remove step")
        self._btn_rm_step.setObjectName("profileToolButton")
        self._btn_rm_step.clicked.connect(self._remove_step)
        self._btn_up = icon_button("arrow-up", "Move the selected step up")
        self._btn_up.setObjectName("profileToolButton")
        self._btn_up.clicked.connect(lambda: self._move_step(-1))
        self._btn_down = icon_button("arrow-down", "Move the selected step down")
        self._btn_down.setObjectName("profileToolButton")
        self._btn_down.clicked.connect(lambda: self._move_step(1))
        for b in (self._btn_add_step, self._btn_rm_step, self._btn_up, self._btn_down):
            steps_head.addWidget(b)
        right.addLayout(steps_head)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Op", "Mods", "Key", "Arg"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.itemSelectionChanged.connect(self._on_step_selected)
        polish_table(self._table)
        self._table.setFrameShape(QFrame.Shape.StyledPanel)
        right.addWidget(self._table, stretch=1)
        right.addSpacing(S["sm"])
        right.addWidget(label("Selected step", "sectionTitle"))

        # Step editor panel
        editor_box = QWidget()
        editor_layout = QFormLayout(editor_box)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_form = editor_layout

        self._op_combo = QComboBox()
        self._op_combo.addItems(list(MACRO_OPS))
        self._op_combo.currentTextChanged.connect(self._on_op_changed)
        editor_layout.addRow("Op", self._op_combo)

        self._mods_row = QWidget()
        mods_layout = QHBoxLayout(self._mods_row)
        mods_layout.setContentsMargins(0, 0, 0, 0)
        mods_layout.setSpacing(S["xs"] + 2)
        self._mod_boxes: dict[str, QCheckBox] = {}
        for name in ("CTRL", "SHIFT", "ALT", "GUI"):
            box = QCheckBox(MOD_LABELS[name])
            box.setObjectName("chip")
            box.setToolTip(f"{name} modifier")
            box.stateChanged.connect(self._apply_step_editor)
            mods_layout.addWidget(box)
            self._mod_boxes[name] = box
        mods_layout.addStretch(1)
        editor_layout.addRow("Mods", self._mods_row)

        self._key_combo = QComboBox()
        self._key_combo.setEditable(True)
        self._key_combo.addItem("")  # empty = keycode 0
        self._key_combo.addItems(COMMON_KEYS)
        self._key_combo.currentTextChanged.connect(self._apply_step_editor)
        self._key_combo.lineEdit().editingFinished.connect(self._apply_step_editor)
        editor_layout.addRow("Key", self._key_combo)

        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(0, 65535)
        self._delay_spin.setSuffix(" ms")
        self._delay_spin.valueChanged.connect(self._apply_step_editor)
        editor_layout.addRow("Delay", self._delay_spin)

        self._text_spin = QSpinBox()
        self._text_spin.setRange(0, 7)
        self._text_spin.valueChanged.connect(self._on_text_id_changed)
        self._text_hint = QLabel("")
        self._text_hint.setObjectName("hintLabel")
        text_wrap = QWidget()
        text_layout = QHBoxLayout(text_wrap)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(self._text_spin)
        text_layout.addWidget(self._text_hint, stretch=1)
        editor_layout.addRow("Text id", text_wrap)

        self._consumer_combo = QComboBox()
        for preset_label, _val in CONSUMER_PRESETS:
            self._consumer_combo.addItem(preset_label)
        self._consumer_combo.currentIndexChanged.connect(self._on_consumer_preset)
        self._consumer_edit = QLineEdit()
        self._consumer_edit.setPlaceholderText("usage hex e.g. 0x00CD")
        self._consumer_edit.textChanged.connect(self._apply_step_editor)
        consumer_wrap = QWidget()
        consumer_layout = QVBoxLayout(consumer_wrap)
        consumer_layout.setContentsMargins(0, 0, 0, 0)
        consumer_layout.setSpacing(S["sm"])
        consumer_layout.addWidget(self._consumer_combo)
        consumer_layout.addWidget(self._consumer_edit)
        editor_layout.addRow("Consumer", consumer_wrap)

        style_form(editor_layout, label_width=64)
        right.addWidget(editor_box)
        self._editor_box = editor_box
        self._editor_rows = {
            "mods": self._mods_row,
            "key": self._key_combo,
            "delay": self._delay_spin,
            "text": text_wrap,
            "consumer": consumer_wrap,
        }

        editor = QWidget()
        editor.setLayout(right)
        right.setContentsMargins(0, 0, 0, 0)
        self._empty = EmptyState(
            "list-ordered",
            "No macros yet",
            "A macro is a short sequence of taps, delays, text snippets and media keys. "
            "Create one here, then assign it to a key with the MACRO action.",
            action_text="New macro",
        )
        self._empty.activated.connect(self._new_macro)
        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(editor)
        self._right_stack.addWidget(self._empty)
        body.addWidget(self._right_stack, stretch=3)
        root.addLayout(body, stretch=1)

        self._error = QLabel("")
        self._error.setObjectName("validationError")
        self._error.setWordWrap(True)
        self._error.hide()
        root.addWidget(self._error)

        root.addWidget(divider())
        footer = QHBoxLayout()
        path_label = label(str(self._path), "caption")
        path_label.setToolTip(f"Macro library file: {self._path}")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        footer.addWidget(path_label, 1)
        if self._embedded:
            self._revert_btn = QPushButton("Revert")
            self._revert_btn.setToolTip("Discard unsaved edits and reload macros/library.json")
            self._revert_btn.clicked.connect(self.revert)
            self._save_btn = QPushButton("Save")
            self._save_btn.setToolTip(with_shortcut("Save the macro library", "Ctrl+S"))
            theme.set_primary(self._save_btn)
            self._save_btn.clicked.connect(self._on_save)
            for b in (self._revert_btn, self._save_btn):
                b.setAutoDefault(False)
                footer.addWidget(b)
            self.dirtyChanged.connect(self._sync_page_buttons)
            self._sync_page_buttons(False)
        else:
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(self._on_save)
            buttons.rejected.connect(self.reject)
            footer.addWidget(buttons)
        root.addLayout(footer)

        self._set_editor_enabled(False)
        self._update_op_fields()
        self._list.setFocus()

    # --- load / save ----------------------------------------------------

    def _load_or_empty(self) -> None:
        try:
            if self._path.is_file():
                self._library = load_library(self._path)
            else:
                self._library = MacroLibrary(schema_version=1, macros=[], source_path=self._path)
        except MacroLoadError as exc:
            QMessageBox.warning(
                self,
                "Macro library",
                f"Could not load library:\n{exc}\n\nStarting empty.",
            )
            self._library = MacroLibrary(schema_version=1, macros=[], source_path=self._path)
        self._dirty = False
        self._refresh_list()
        if self._library.macros:
            self._list.setCurrentRow(0)
        else:
            self._clear_editor()

    def _on_save(self) -> None:
        if self._library is None:
            return
        # Flush current step editor into model
        self._apply_step_editor()
        self._sync_name_from_edit()
        try:
            save_library(self._library, self._path)
        except (OSError, SchemaError, ValueError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._dirty = False
        self._error.hide()
        self.saved.emit()
        if not self._embedded:
            self.accept()

    def save(self) -> bool:
        """Save (page mode / Ctrl+S). Returns True when the library is clean afterwards."""
        self._on_save()
        return not self._dirty

    def revert(self, *, confirm: bool = True) -> None:
        """Reload macros/library.json, discarding edits (asks first when dirty)."""
        if confirm and self._dirty:
            reply = QMessageBox.question(
                self,
                "Revert macros",
                "Discard unsaved changes to the macro library and reload it from disk?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Discard:
                return
        self._current_id = None
        self._load_or_empty()

    def _sync_page_buttons(self, dirty: bool) -> None:
        self._save_btn.setEnabled(dirty)
        self._revert_btn.setEnabled(dirty)

    # Page mode: never close/hide, and let Esc / Enter reach the focused widget.
    def done(self, r: int) -> None:
        if not self._embedded:
            super().done(r)

    def keyPressEvent(self, ev) -> None:
        if self._embedded:
            QWidget.keyPressEvent(self, ev)
        else:
            super().keyPressEvent(ev)

    def library(self) -> MacroLibrary | None:
        return self._library

    # --- list -----------------------------------------------------------

    def _refresh_list(self, keep_id: int | None = None) -> None:
        if self._library is None:
            return
        keep = keep_id if keep_id is not None else self._current_id
        self._list.blockSignals(True)
        self._list.clear()
        for macro in sorted(self._library.macros, key=lambda m: m.id):
            item = QListWidgetItem(f"{macro.id}: {macro.name}")
            item.setData(Qt.ItemDataRole.UserRole, macro.id)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._right_stack.setCurrentIndex(0 if self._library.macros else 1)
        if not self._library.macros:
            self.currentMacroChanged.emit("")
        if keep is not None:
            for row in range(self._list.count()):
                item = self._list.item(row)
                if item and item.data(Qt.ItemDataRole.UserRole) == keep:
                    self._list.setCurrentRow(row)
                    return
        if self._list.count():
            self._list.setCurrentRow(0)

    def _current_macro(self) -> Macro | None:
        if self._library is None or self._current_id is None:
            return None
        return self._library.macro_by_id(self._current_id)

    def _on_macro_selected(self, row: int) -> None:
        self._apply_step_editor()
        self._sync_name_from_edit()
        if row < 0 or self._library is None:
            self._current_id = None
            self._clear_editor()
            return
        item = self._list.item(row)
        if item is None:
            return
        mid = int(item.data(Qt.ItemDataRole.UserRole))
        self._current_id = mid
        macro = self._library.macro_by_id(mid)
        if macro is None:
            self._clear_editor()
            return
        self._loading = True
        try:
            self._id_label.setText(str(macro.id))
            self._name_edit.setText(macro.name)
            self._name_edit.setEnabled(True)
            self._populate_table(macro)
            self._set_editor_enabled(True)
            if macro.steps:
                self._table.selectRow(0)
        finally:
            self._loading = False
        # Load the editor for the selected row *after* the guarded block: the selection
        # signal above is ignored while loading, and a stale editor used to be flushed
        # back into step 0 on the next selection.
        if macro.steps:
            self._load_step_editor(macro.steps[0], 0)
        else:
            self._clear_step_editor()
        self._btn_dup.setEnabled(True)
        self._btn_del.setEnabled(True)
        self.currentMacroChanged.emit(macro.name)

    def _clear_editor(self) -> None:
        self._loading = True
        try:
            self._id_label.setText("—")
            self._name_edit.clear()
            self._name_edit.setEnabled(False)
            self._table.setRowCount(0)
            self._clear_step_editor()
            self._set_editor_enabled(False)
        finally:
            self._loading = False
        self._btn_dup.setEnabled(False)
        self._btn_del.setEnabled(False)

    def _set_editor_enabled(self, enabled: bool) -> None:
        self._btn_add_step.setEnabled(enabled)
        self._btn_rm_step.setEnabled(enabled)
        self._btn_up.setEnabled(enabled)
        self._btn_down.setEnabled(enabled)
        self._editor_box.setEnabled(enabled)
        self._table.setEnabled(enabled)

    # --- macro CRUD -----------------------------------------------------

    def _new_macro(self) -> None:
        if self._library is None:
            return
        self._apply_step_editor()
        self._sync_name_from_edit()
        macro = self._library.add_macro("new macro")
        self._dirty = True
        self._refresh_list(keep_id=macro.id)

    def _duplicate_macro(self) -> None:
        src = self._current_macro()
        if src is None or self._library is None:
            return
        self._apply_step_editor()
        self._sync_name_from_edit()
        macro = self._library.duplicate_macro(src)
        self._dirty = True
        self._refresh_list(keep_id=macro.id)

    def _delete_macro(self) -> None:
        macro = self._current_macro()
        if macro is None or self._library is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete macro",
            f"Delete macro {macro.id}: {macro.name!r}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._library.remove_macro(macro.id)
        self._current_id = None
        self._dirty = True
        self._refresh_list()
        if not self._library.macros:
            self._clear_editor()

    def _on_name_changed(self, text: str) -> None:
        if self._loading:
            return
        macro = self._current_macro()
        if macro is None:
            return
        name = text.strip() or macro.name
        macro.name = name
        self._dirty = True
        # Update list label without reselection churn
        row = self._list.currentRow()
        item = self._list.item(row)
        if item is not None:
            item.setText(f"{macro.id}: {macro.name}")
        self.currentMacroChanged.emit(macro.name)

    def _sync_name_from_edit(self) -> None:
        macro = self._current_macro()
        if macro is None:
            return
        name = self._name_edit.text().strip()
        if name:
            macro.name = name

    # --- steps table ----------------------------------------------------

    def _populate_table(self, macro: Macro) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for step in macro.steps:
            self._append_table_row(step)
        self._table.blockSignals(False)

    def _append_table_row(self, step: MacroStep) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._set_table_row(row, step)

    def _set_table_row(self, row: int, step: MacroStep) -> None:
        mods = "+".join(step.mods) if step.mods else ""
        key = step.key if step.op in ("TAP", "KEY_DOWN", "KEY_UP") else ""
        if step.op == "DELAY_MS":
            arg = str(step.arg)
        elif step.op == "TEXT":
            arg = str(step.arg)
        elif step.op == "CONSUMER":
            arg = f"0x{step.arg:04X}"
        else:
            arg = ""
        values = [step.op, mods, key, arg]
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, col, item)

    def _selected_step_index(self) -> int:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return -1
        return rows[0].row()

    def _on_step_selected(self) -> None:
        if self._loading:
            return
        # Flush previous editor before switching
        # (skip when loading table)
        idx = self._selected_step_index()
        macro = self._current_macro()
        if macro is None or idx < 0 or idx >= len(macro.steps):
            self._clear_step_editor()
            return
        self._load_step_editor(macro.steps[idx], idx)

    def _clear_step_editor(self) -> None:
        self._editor_idx = -1
        self._loading = True
        try:
            self._op_combo.setCurrentText("END")
            for box in self._mod_boxes.values():
                box.setChecked(False)
            self._key_combo.setCurrentIndex(0)
            self._delay_spin.setValue(0)
            self._text_spin.setValue(0)
            self._text_hint.setText(TEXT_LABELS.get(0, ""))
            self._consumer_combo.setCurrentIndex(0)
            self._consumer_edit.clear()
            self._update_op_fields()
            self._editor_box.setEnabled(False)
        finally:
            self._loading = False

    def _load_step_editor(self, step: MacroStep, idx: int) -> None:
        self._editor_idx = idx
        self._loading = True
        try:
            self._editor_box.setEnabled(True)
            self._op_combo.setCurrentText(step.op)
            for name, box in self._mod_boxes.items():
                box.setChecked(name in step.mods)
            # key
            key = step.key or ""
            kidx = self._key_combo.findText(key)
            if kidx >= 0:
                self._key_combo.setCurrentIndex(kidx)
            else:
                self._key_combo.setEditText(key)
            self._delay_spin.setValue(step.arg if step.op == "DELAY_MS" else 0)
            if step.op == "TEXT":
                self._text_spin.setValue(step.arg)
                self._text_hint.setText(TEXT_LABELS.get(step.arg, ""))
            else:
                self._text_spin.setValue(0)
                self._text_hint.setText(TEXT_LABELS.get(0, ""))
            if step.op == "CONSUMER":
                self._consumer_edit.setText(f"0x{step.arg:04X}")
                matched = 0
                for i, (_label, val) in enumerate(CONSUMER_PRESETS):
                    if val == step.arg:
                        matched = i
                        break
                self._consumer_combo.setCurrentIndex(matched)
            else:
                self._consumer_combo.setCurrentIndex(0)
                self._consumer_edit.clear()
            self._update_op_fields()
        finally:
            self._loading = False

    def _on_op_changed(self, _text: str = "") -> None:
        self._update_op_fields()
        self._apply_step_editor()

    def _update_op_fields(self) -> None:
        op = self._op_combo.currentText()
        show_key = op in ("TAP", "KEY_DOWN", "KEY_UP")
        show_delay = op == "DELAY_MS"
        show_text = op == "TEXT"
        show_consumer = op == "CONSUMER"
        # Hide label + field together so e.g. a TAP step shows no Delay / Text id / Consumer labels.
        for key, show in (
            ("mods", show_key),
            ("key", show_key),
            ("delay", show_delay),
            ("text", show_text),
            ("consumer", show_consumer),
        ):
            self._editor_form.setRowVisible(self._editor_rows[key], show)

    def visible_step_labels(self) -> list[str]:
        """Labels of the step-editor rows currently shown (used by smokes / screenshots)."""
        form = self._editor_form
        out: list[str] = []
        for i in range(form.rowCount()):
            lab = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
            if lab is not None and lab.widget() is not None and form.isRowVisible(i):
                out.append(lab.widget().text())
        return out

    def _on_text_id_changed(self, value: int) -> None:
        self._text_hint.setText(TEXT_LABELS.get(value, ""))
        self._apply_step_editor()

    def _on_consumer_preset(self, index: int) -> None:
        if self._loading:
            return
        if 0 <= index < len(CONSUMER_PRESETS):
            _label, val = CONSUMER_PRESETS[index]
            if val >= 0:
                self._loading = True
                try:
                    self._consumer_edit.setText(f"0x{val:04X}")
                finally:
                    self._loading = False
        self._apply_step_editor()

    def _apply_step_editor(self, *_args: object) -> None:
        if self._loading:
            return
        macro = self._current_macro()
        idx = self._editor_idx
        if macro is None or idx < 0 or idx >= len(macro.steps) or idx != self._selected_step_index():
            return
        op = self._op_combo.currentText()
        mods = [n for n, b in self._mod_boxes.items() if b.isChecked()]
        key = self._key_combo.currentText()
        arg = 0
        if op == "DELAY_MS":
            arg = self._delay_spin.value()
        elif op == "TEXT":
            arg = self._text_spin.value()
        elif op == "CONSUMER":
            text = self._consumer_edit.text().strip()
            if text:
                try:
                    arg = int(text, 16) if text.lower().startswith("0x") else int(text)
                except ValueError:
                    self._error.setText(f"Invalid consumer arg: {text}")
                    self._error.show()
                    return
        try:
            step = MacroStep.from_dict(
                {"op": op, "mods": mods, "key": key, "arg": arg},
                path="step",
            )
        except SchemaError as exc:
            self._error.setText(str(exc))
            self._error.show()
            return
        self._error.hide()
        if step.to_dict() == macro.steps[idx].to_dict():
            return  # no real edit (selection change, focus-out, programmatic update)
        macro.steps[idx] = step
        self._loading = True
        try:
            self._set_table_row(idx, step)
        finally:
            self._loading = False
        self._dirty = True

    def _add_step(self) -> None:
        macro = self._current_macro()
        if macro is None:
            return
        self._apply_step_editor()
        # Insert before final END if present, else append END then new TAP before it
        new_step = MacroStep(op="TAP", mods=[], key="A")
        if macro.steps and macro.steps[-1].op == "END":
            insert_at = len(macro.steps) - 1
            macro.steps.insert(insert_at, new_step)
        else:
            macro.steps.append(new_step)
            macro.steps.append(MacroStep(op="END"))
            insert_at = len(macro.steps) - 2
        self._dirty = True
        self._populate_table(macro)
        self._table.selectRow(insert_at)

    def _remove_step(self) -> None:
        macro = self._current_macro()
        idx = self._selected_step_index()
        if macro is None or idx < 0 or idx >= len(macro.steps):
            return
        if macro.steps[idx].op == "END" and idx == len(macro.steps) - 1:
            QMessageBox.information(self, "Remove step", "Cannot remove the trailing END step.")
            return
        del macro.steps[idx]
        if not macro.steps or macro.steps[-1].op != "END":
            macro.steps.append(MacroStep(op="END"))
        self._dirty = True
        self._populate_table(macro)
        new_idx = min(idx, len(macro.steps) - 1)
        if new_idx >= 0:
            self._table.selectRow(new_idx)

    def _move_step(self, delta: int) -> None:
        macro = self._current_macro()
        idx = self._selected_step_index()
        if macro is None or idx < 0:
            return
        self._apply_step_editor()
        # Don't move trailing END
        end_idx = len(macro.steps) - 1
        if macro.steps and macro.steps[-1].op == "END":
            movable_max = end_idx - 1
        else:
            movable_max = end_idx
        if idx > movable_max:
            return
        new_idx = idx + delta
        if new_idx < 0 or new_idx > movable_max:
            return
        macro.steps[idx], macro.steps[new_idx] = macro.steps[new_idx], macro.steps[idx]
        self._dirty = True
        self._populate_table(macro)
        self._table.selectRow(new_idx)

    def reject(self) -> None:
        if self._embedded:
            return
        if self._dirty:
            reply = QMessageBox.question(
                self,
                "Unsaved changes",
                "Discard changes to the macro library?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Discard:
                return
        super().reject()


__all__ = ["MacroLibraryDialog"]
