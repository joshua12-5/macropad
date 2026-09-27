"""Device info and About panels (read-only key/value layouts shown inline on the
Device and Settings pages)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import version as app_version
from ..ui import theme
from ..ui.widgets import StatusPill, divider, label

_FLAG_NAMES = (
    (0, "Flash storage"),
    (1, "Macro bank"),
    (2, "Readback"),
    (3, "Idle animation"),
)


def describe_flags(flags: int) -> str:
    names = [name for bit, name in _FLAG_NAMES if flags >> bit & 1]
    return f"0x{flags:02X} · " + (", ".join(names) if names else "none")


class KeyValueGrid(QGridLayout):
    """Muted keys on the left, selectable values on the right; rows can be replaced."""

    def __init__(self, rows: list[tuple[str, str]] | None = None) -> None:
        super().__init__()
        self.setHorizontalSpacing(theme.SPACE["xl"])
        self.setVerticalSpacing(theme.SPACE["sm"])
        self.setColumnStretch(1, 1)
        self._widgets: list[QLabel] = []
        self.values: dict[str, QLabel] = {}
        if rows:
            self.set_rows(rows)

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        for w in self._widgets:
            self.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()
        self.values.clear()
        for r, (key, value) in enumerate(rows):
            k = label(key, "formLabel")
            v = label(value, "valueLabel", selectable=True)
            v.setWordWrap(True)
            self.addWidget(k, r, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.addWidget(v, r, 1, Qt.AlignmentFlag.AlignTop)
            self._widgets += [k, v]
            self.values[key] = v


def device_info_rows(info: dict) -> list[tuple[str, str]]:
    fw = f"{info.get('fw_major', '?')}.{info.get('fw_minor', '?')}"
    proto = info.get("proto_ver", "?")
    flags = int(info.get("flags", 0) or 0)
    return [
        (
            "Firmware",
            f"{fw}  (host expects {app_version.FW_VERSION_MAJOR_EXPECTED}."
            f"{app_version.FW_VERSION_MINOR_CURRENT})",
        ),
        ("Protocol", f"v{proto}  (host expects v{app_version.PROTO_VER})"),
        ("Host app", app_version.HOST_APP_VERSION),
        ("Active slot", f"{info.get('active_slot', '?')} of {info.get('slot_count', '?')}"),
        ("Features", describe_flags(flags)),
        ("PING", repr(info.get("ping_payload", ""))),
    ]


class DeviceInfoPanel(QWidget):
    """GET_INFO result: product, firmware / protocol, active slot, feature flags."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("deviceInfoPanel")
        self.info: dict = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE["md"])

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE["md"])
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.product = label("Macropad", "panelTitle")
        self.subtitle = label("", "hintLabel")
        titles.addWidget(self.product)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.pill = StatusPill("Not connected", "neutral")
        head.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        self.grid = KeyValueGrid()
        lay.addLayout(self.grid)
        self.warning = label(
            "Protocol mismatch: upload, backup, auto-switch and Save device state stay disabled until "
            "the host and firmware versions match. See docs/VERSIONING.md.",
            "validationError",
            wrap=True,
        )
        self.warning.hide()
        lay.addWidget(self.warning)
        lay.addWidget(divider())
        self.summary = label("", "monoLabel", wrap=True, selectable=True)
        lay.addWidget(self.summary)

    def set_info(self, info: dict, proto_ok: bool) -> None:
        self.info = dict(info)
        fw = f"{info.get('fw_major', '?')}.{info.get('fw_minor', '?')}"
        self.product.setText(str(info.get("product_tag", "Macropad")) or "Macropad")
        self.subtitle.setText(f"Firmware {fw} · protocol v{info.get('proto_ver', '?')}")
        self.pill.set_state(
            "Connected" if proto_ok else "Protocol mismatch", "success" if proto_ok else "warning"
        )
        self.grid.set_rows(device_info_rows(info))
        self.warning.setVisible(not proto_ok)
        self.summary.setText(app_version.compat_summary(info))


class AboutPanel(QWidget):
    """Version, schemas and credits (Settings → About)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("aboutPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE["md"])
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label("Macropad Configurator", "panelTitle"))
        head.addWidget(label(f"Version {app_version.HOST_APP_VERSION}", "hintLabel"))
        lay.addLayout(head)
        lay.addWidget(
            label(
                "Desktop configurator for the RP2040 macropad: key and encoder actions, "
                "macros, auto-switch rules and OLED idle animations.",
                wrap=True,
            )
        )
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
            ("Docs", "docs/USER_GUIDE.md · docs/VERSIONING.md · docs/ARCHITECTURE.md"),
        ]
        lay.addLayout(KeyValueGrid(rows))
        foot = QLabel(f"{app_version.COPYRIGHT} · MIT License · Icons: Lucide (ISC)")
        foot.setObjectName("caption")
        lay.addWidget(foot)


__all__ = ["AboutPanel", "DeviceInfoPanel", "KeyValueGrid", "describe_flags", "device_info_rows"]
