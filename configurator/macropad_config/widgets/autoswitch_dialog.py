"""Tools → Auto-switch… rules editor dialog."""

from __future__ import annotations

from typing import Optional

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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
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
from ..ui.widgets import dialog_margins, divider, icon_button, label, polish_table, style_form


class AutoswitchDialog(QDialog):
    def __init__(
        self,
        rules: AutoswitchRules,
        parent=None,
        *,
        profile_ids: Optional[list[str]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Auto-switch")
        self.resize(720, 480)
        self._profile_ids = profile_ids or [
            "default",
            "gaming",
            "coding",
            "browser",
            "photoshop",
        ]
        self._rules = clone_rules(rules)

        layout = dialog_margins(QVBoxLayout(self))

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
        layout.addWidget(self._table, 1)

        for rule in self._rules.rules:
            self._append_rule(rule)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(divider())
        layout.addWidget(buttons)

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

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedIndexes()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)

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
        self.accept()

    def result_rules(self) -> AutoswitchRules:
        return self._rules
