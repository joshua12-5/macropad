"""Auto-switch rules editor: the Auto-switch page (``embedded=True``) or a dialog."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..autoswitch.rules import (
    AutoswitchRules,
    Rule,
    RulesError,
    clone_rules,
    save_rules,
    validate_rules,
)
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

DEFAULT_PROFILE_IDS = ["default", "gaming", "coding", "browser", "photoshop"]


class AutoswitchDialog(QDialog):
    """Rules table + enabled / poll / fallback.

    ``embedded=True``: page mode (Save keeps it open and emits :pyattr:`saved`
    with the new rules; Cancel becomes Revert; :pyattr:`dirtyChanged` tracks edits).
    """

    dirtyChanged = Signal(bool)
    saved = Signal(object)  # AutoswitchRules

    def __init__(
        self,
        rules: AutoswitchRules,
        parent=None,
        *,
        profile_ids: Optional[list[str]] = None,
        embedded: bool = False,
    ) -> None:
        super().__init__(parent)
        self._embedded = embedded
        self._dirty = False
        self._loading = False
        self.setWindowTitle("Auto-switch")
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setObjectName("autoswitchPage")
        else:
            self.resize(720, 480)
        self._profile_ids = profile_ids or list(DEFAULT_PROFILE_IDS)
        self._rules = clone_rules(rules)

        layout = dialog_margins(QVBoxLayout(self))
        if embedded:
            S = theme.SPACE
            layout.setContentsMargins(S["lg"], S["md"], S["lg"], S["md"])

        hint = QLabel(
            "Host watches the foreground app and sends USB SET_ACTIVE "
            "(instant RAM + OLED switch; the device saves the slot to flash once it has been "
            "stable for 4 s, so rapid switching does not wear flash). Requires the configurator "
            "to be running; the device cannot see host apps."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")
        layout.addWidget(hint)

        form = QFormLayout()
        self._enabled = QCheckBox("Enabled")
        self._enabled.setToolTip(
            "Start switching automatically once a device is connected (also Device → Auto-switch enabled)"
        )
        self._enabled.setChecked(self._rules.enabled)
        form.addRow(self._enabled)

        self._poll = QSpinBox()
        self._poll.setRange(100, 10000)
        self._poll.setSingleStep(50)
        self._poll.setSuffix(" ms")
        self._poll.setValue(self._rules.poll_ms)
        form.addRow("Poll interval", self._poll)

        self._fallback = QComboBox()
        self._fallback.addItem("(none)", None)
        for pid in self._profile_ids:
            self._fallback.addItem(pid, pid)
        if self._rules.fallback_profile_id:
            idx = self._fallback.findData(self._rules.fallback_profile_id)
            if idx >= 0:
                self._fallback.setCurrentIndex(idx)
        form.addRow("Fallback profile", self._fallback)
        style_form(form)
        layout.addLayout(form)
        layout.addSpacing(theme.SPACE["xs"])

        rules_head = QHBoxLayout()
        rules_head.setSpacing(2)
        rules_head.addWidget(label("Rules", "sectionTitle"))
        rules_head.addStretch(1)
        add_btn = icon_button("plus", "Add a rule", text="Add rule")
        add_btn.clicked.connect(self._add_row)
        del_btn = icon_button("minus", "Remove the selected rules", text="Remove selected")
        del_btn.clicked.connect(self._remove_selected)
        rules_head.addWidget(add_btn)
        rules_head.addWidget(del_btn)
        layout.addLayout(rules_head)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["profile_id", "process (comma-separated)", "title_regex", "slot"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 110)
        self._table.setColumnWidth(1, 320)
        self._table.setColumnWidth(2, 140)
        polish_table(self._table)
        self._table.setFrameShape(QFrame.Shape.StyledPanel)
        self._empty = EmptyState(
            "repeat",
            "No rules yet",
            "Add a rule to switch the macropad to a profile when a matching app "
            "(process name or window title) comes to the front.",
            action_text="Add rule",
        )
        self._empty.activated.connect(self._add_row)
        self._table_stack = QStackedWidget()
        self._table_stack.addWidget(self._table)
        self._table_stack.addWidget(self._empty)
        layout.addWidget(self._table_stack, 1)

        self._fill_rules()

        layout.addWidget(divider())
        if embedded:
            foot = QHBoxLayout()
            foot.addWidget(label("autoswitch/rules.json · applied when saved", "caption"), 1)
            self._revert_btn = QPushButton("Revert")
            self._revert_btn.setToolTip("Discard unsaved edits and reload the saved rules")
            self._revert_btn.clicked.connect(self.revert)
            self._save_btn = QPushButton("Save")
            self._save_btn.setToolTip(with_shortcut("Save and apply the rules", "Ctrl+S"))
            theme.set_primary(self._save_btn)
            self._save_btn.clicked.connect(self._on_save)
            for b in (self._revert_btn, self._save_btn):
                b.setAutoDefault(False)
                foot.addWidget(b)
            layout.addLayout(foot)
        else:
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(self._on_save)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

        self._enabled.toggled.connect(self._mark_dirty)
        self._poll.valueChanged.connect(self._mark_dirty)
        self._fallback.currentIndexChanged.connect(self._mark_dirty)
        self._table.itemChanged.connect(self._mark_dirty)
        self._set_dirty(False)

    # --- state ------------------------------------------------------------
    def is_dirty(self) -> bool:
        return self._dirty

    def rule_count(self) -> int:
        return self._table.rowCount()

    def _set_dirty(self, dirty: bool) -> None:
        changed = dirty != self._dirty
        self._dirty = dirty
        if self._embedded:
            self._save_btn.setEnabled(dirty)
            self._revert_btn.setEnabled(dirty)
        if changed:
            self.dirtyChanged.emit(dirty)

    def _mark_dirty(self, *_args) -> None:
        if not self._loading:
            self._set_dirty(True)

    def _sync_empty(self) -> None:
        self._table_stack.setCurrentIndex(0 if self._table.rowCount() else 1)

    def _fill_rules(self) -> None:
        self._loading = True
        try:
            self._table.setRowCount(0)
            for rule in self._rules.rules:
                self._append_rule(rule)
        finally:
            self._loading = False
        self._sync_empty()

    def set_rules(self, rules: AutoswitchRules, profile_ids: Optional[list[str]] = None) -> None:
        """Load *rules* into the editor (clean state)."""
        self._rules = clone_rules(rules)
        if profile_ids:
            self._profile_ids = list(profile_ids)
        self._loading = True
        try:
            self._enabled.setChecked(self._rules.enabled)
            self._poll.setValue(self._rules.poll_ms)
            self._fallback.clear()
            self._fallback.addItem("(none)", None)
            for pid in self._profile_ids:
                self._fallback.addItem(pid, pid)
            idx = self._fallback.findData(self._rules.fallback_profile_id)
            self._fallback.setCurrentIndex(max(0, idx))
        finally:
            self._loading = False
        self._fill_rules()
        self._set_dirty(False)

    def set_enabled_checked(self, enabled: bool) -> None:
        """Mirror the Device-menu toggle without marking the page dirty."""
        self._loading = True
        try:
            self._enabled.setChecked(enabled)
        finally:
            self._loading = False
        self._rules.enabled = bool(enabled)

    def save(self) -> bool:
        self._on_save()
        return not self._dirty

    def revert(self, *, confirm: bool = True) -> None:
        if confirm and self._dirty:
            reply = QMessageBox.question(
                self,
                "Revert auto-switch rules",
                "Discard unsaved changes to the auto-switch rules?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Discard:
                return
        self.set_rules(self._rules)

    def done(self, r: int) -> None:
        if not self._embedded:
            super().done(r)

    def keyPressEvent(self, ev) -> None:
        if self._embedded:
            QWidget.keyPressEvent(self, ev)
        else:
            super().keyPressEvent(ev)

    def _append_rule(self, rule: Rule) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(rule.profile_id))
        self._table.setItem(row, 1, QTableWidgetItem(", ".join(rule.process)))
        self._table.setItem(row, 2, QTableWidgetItem(rule.title_regex or ""))
        self._table.setItem(
            row,
            3,
            QTableWidgetItem("" if rule.slot is None else str(rule.slot)),
        )

    def _add_row(self) -> None:
        self._append_rule(Rule(profile_id="coding", process=["Code"], title_regex=None))
        self._sync_empty()
        self._mark_dirty()

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedIndexes()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)
        self._sync_empty()
        if rows:
            self._mark_dirty()

    def _collect(self) -> AutoswitchRules:
        rules: list[Rule] = []
        for row in range(self._table.rowCount()):
            pid_item = self._table.item(row, 0)
            proc_item = self._table.item(row, 1)
            title_item = self._table.item(row, 2)
            slot_item = self._table.item(row, 3)
            pid = (pid_item.text() if pid_item else "").strip()
            procs_raw = (proc_item.text() if proc_item else "").strip()
            procs = [p.strip() for p in procs_raw.split(",") if p.strip()]
            title = (title_item.text() if title_item else "").strip() or None
            slot_s = (slot_item.text() if slot_item else "").strip()
            slot = int(slot_s) if slot_s else None
            rules.append(
                Rule(
                    profile_id=pid,
                    process=procs,
                    title_regex=title,
                    slot=slot,
                )
            )
        fb = self._fallback.currentData()
        data = {
            "schema_version": 1,
            "enabled": self._enabled.isChecked(),
            "poll_ms": int(self._poll.value()),
            "fallback_profile_id": fb,
            "rules": [
                {
                    "profile_id": r.profile_id,
                    "process": r.process,
                    "title_regex": r.title_regex,
                    **({"slot": r.slot} if r.slot is not None else {}),
                }
                for r in rules
            ],
        }
        return validate_rules(data)

    def _on_save(self) -> None:
        try:
            rules = self._collect()
            save_rules(rules)
        except (RulesError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Auto-switch", f"Could not save:\n{exc}")
            return
        self._rules = rules
        self._set_dirty(False)
        self.saved.emit(rules)
        if not self._embedded:
            self.accept()

    def result_rules(self) -> AutoswitchRules:
        return self._rules
