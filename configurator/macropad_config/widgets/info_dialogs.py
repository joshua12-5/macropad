"""Device info and About dialogs (read-only, themed key/value layouts)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import version as app_version
from ..ui import theme
from ..ui.widgets import StatusPill, dialog_margins, divider, label

_FLAG_NAMES = (
    (0, "Flash storage"),
    (1, "Macro bank"),
    (2, "Readback"),
    (3, "Idle animation"),
)


def describe_flags(flags: int) -> str:
    names = [name for bit, name in _FLAG_NAMES if flags >> bit & 1]
    return f"0x{flags:02X} · " + (", ".join(names) if names else "none")


def _kv_grid(rows: list[tuple[str, str]]) -> QGridLayout:
    grid = QGridLayout()
    grid.setHorizontalSpacing(theme.SPACE["xl"])
    grid.setVerticalSpacing(theme.SPACE["sm"])
    for r, (key, value) in enumerate(rows):
        k = label(key, "formLabel")
        v = label(value, "valueLabel", selectable=True)
        grid.addWidget(k, r, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addWidget(v, r, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    grid.setColumnStretch(1, 1)
    return grid


class DeviceInfoDialog(QDialog):
    """Result of Device → Connect / Get device info."""

    def __init__(self, info: dict, proto_ok: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Device info")
        self.setObjectName("deviceInfoDialog")
        self.setMinimumWidth(460)
        self.info = dict(info)
        lay = dialog_margins(QVBoxLayout(self), spacing=theme.SPACE["lg"])

        fw = f"{info.get('fw_major', '?')}.{info.get('fw_minor', '?')}"
        proto = info.get("proto_ver", "?")

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE["md"])
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(str(info.get("product_tag", "Macropad")) or "Macropad", "panelTitle"))
        titles.addWidget(label(f"Firmware {fw} · protocol v{proto}", "hintLabel"))
        head.addLayout(titles, 1)
        self.pill = StatusPill(
            "Connected" if proto_ok else "Protocol mismatch", "success" if proto_ok else "warning"
        )
        head.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        lay.addWidget(divider())

        flags = int(info.get("flags", 0) or 0)
        rows = [
            ("Firmware", f"{fw}  (major.minor)"),
            ("Protocol", f"v{proto}  (host expects v{app_version.PROTO_VER})"),
            ("Host app", app_version.HOST_APP_VERSION),
            ("Active slot", f"{info.get('active_slot', '?')} of {info.get('slot_count', '?')}"),
            ("Features", describe_flags(flags)),
            ("PING", repr(info.get("ping_payload", ""))),
        ]
        lay.addLayout(_kv_grid(rows))
        if not proto_ok:
            warn = label(
                "Protocol mismatch: upload, auto-switch and Save device state stay disabled until the "
                "host and firmware versions match. See docs/VERSIONING.md.",
                "validationError",
                wrap=True,
            )
            lay.addWidget(warn)
        lay.addWidget(divider())
        summary = label(app_version.compat_summary(info), "monoLabel", wrap=True, selectable=True)
        lay.addWidget(summary)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class AboutDialog(QDialog):
    """Help → About."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Macropad Configurator")
        self.setObjectName("aboutDialog")
        self.setMinimumWidth(440)
        lay = dialog_margins(QVBoxLayout(self), spacing=theme.SPACE["lg"])

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label("Macropad Configurator", "pageTitle"))
        head.addWidget(label(f"Version {app_version.HOST_APP_VERSION}", "hintLabel"))
        lay.addLayout(head)
        lay.addWidget(
            label(
                "Desktop configurator for the RP2040 macropad: key and encoder actions, "
                "macros, auto-switch rules and OLED idle animations.",
                wrap=True,
            )
        )
        lay.addWidget(divider())
        rows = [
            ("Protocol (host)", f"v{app_version.PROTO_VER}"),
            (
                "Expected firmware",
                f"{app_version.FW_VERSION_MAJOR_EXPECTED}.{app_version.FW_VERSION_MINOR_CURRENT}",
            ),
            (
                "Schemas",
                f"profile {app_version.PROFILE_SCHEMA_VERSION} · macro {app_version.MACRO_SCHEMA_VERSION} · "
                f"auto-switch {app_version.AUTOSWITCH_SCHEMA_VERSION}",
            ),
            ("Data", "profiles/, macros/library.json, autoswitch/rules.json"),
            ("Docs", "docs/USER_GUIDE.md · docs/VERSIONING.md · docs/ARCHITECTURE.md"),
        ]
        lay.addLayout(_kv_grid(rows))
        lay.addWidget(divider())
        foot = QLabel(f"{app_version.COPYRIGHT} · MIT License · Icons: Lucide (ISC)")
        foot.setObjectName("caption")
        lay.addWidget(foot)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
