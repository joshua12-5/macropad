"""Device page: connection + GET_INFO, uploads, backup / restore, firmware update help.

The page owns no device I/O. Its buttons are bound to the main window's
QActions (so feature gates and their tooltips apply here too) or emit
:pyattr:`backupRequested` / :pyattr:`restoreRequested`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from .. import version as app_version
from ..ui import theme
from ..ui.widgets import EmptyState, icon_button, label
from ..widgets.info_panels import DeviceInfoPanel
from .common import ScrollPage, action_button

REPO_URL = "https://github.com/joshua12-5/macropad"
UPDATE_GUIDE_URL = f"{REPO_URL}/blob/main/docs/USER_GUIDE.md#updating-the-firmware"
RELEASES_URL = f"{REPO_URL}/releases"


class DevicePage(ScrollPage):
    backupRequested = Signal()
    restoreRequested = Signal()

    def __init__(self, actions: dict[str, QAction], parent: QWidget | None = None) -> None:
        super().__init__("devicePage", parent)
        self._acts = actions
        self.info: dict | None = None

        # --- connection ----------------------------------------------------------
        conn = self.section("Connection", first=True)
        self.empty = EmptyState(
            "plug",
            "No device connected",
            "Plug the macropad in over USB, then connect. Uploads, backup and Save device state "
            "need a connection; everything else works offline.",
            action_text="Connect",
        )
        self.empty.setObjectName("deviceEmptyState")
        self.empty.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.empty.activated.connect(actions["connect"].trigger)
        self.info_panel = DeviceInfoPanel()
        conn.addWidget(self.empty)
        conn.addWidget(self.info_panel)
        refresh_row = QHBoxLayout()
        self.refresh_btn = action_button(actions["connect"], text="Refresh")
        self.refresh_btn.setObjectName("deviceRefresh")
        refresh_row.addWidget(self.refresh_btn)
        refresh_row.addStretch(1)
        self.refresh_row = QWidget()
        self.refresh_row.setLayout(refresh_row)
        refresh_row.setContentsMargins(0, 0, 0, 0)
        self.refresh_row.hide()
        conn.addWidget(self.refresh_row)

        # --- send to device -------------------------------------------------------
        send = self.section(
            "Send to device",
            "Profiles and macros are edited on this computer, then uploaded. Uploads take effect "
            "immediately and are saved to the device's flash.",
        )
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE["sm"])
        for key, text in (
            ("upload", "Upload profile…"),
            ("upload_macros", "Upload macros…"),
            ("save_device", "Save device state"),
        ):
            row.addWidget(action_button(actions[key], text=text))
        row.addStretch(1)
        send.addLayout(row)
        as_row = QHBoxLayout()
        self.autoswitch_btn = QToolButton()
        self.autoswitch_btn.setObjectName("autoswitchToggle")
        self.autoswitch_btn.setDefaultAction(actions["autoswitch"])
        self.autoswitch_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.autoswitch_btn.setProperty("outlined", True)
        as_row.addWidget(self.autoswitch_btn)
        as_row.addWidget(
            label("Switch profiles by foreground app (rules on the Auto-switch page).", "caption")
        )
        as_row.addStretch(1)
        send.addLayout(as_row)

        # --- backup / restore ---------------------------------------------------
        backup = self.section(
            "Backup & restore",
            "Back up reads every profile slot, the macro bank, the active slot and the idle "
            "settings from the device into a .mpbackup.json file. Restore writes a backup to "
            "this or another macropad and saves it to flash. Animation frames are not included "
            "(keep your .mpanim project).",
        )
        brow = QHBoxLayout()
        brow.setSpacing(theme.SPACE["sm"])
        self.backup_btn = icon_button(
            "download", "Read everything from the device into a file", text="Back up device…"
        )
        self.backup_btn.setObjectName("backupButton")
        self.backup_btn.setProperty("outlined", True)
        self.backup_btn.clicked.connect(self.backupRequested.emit)
        self.restore_btn = icon_button("upload", "Write a backup file to the device", text="Restore backup…")
        self.restore_btn.setObjectName("restoreButton")
        self.restore_btn.setProperty("outlined", True)
        self.restore_btn.clicked.connect(self.restoreRequested.emit)
        brow.addWidget(self.backup_btn)
        brow.addWidget(self.restore_btn)
        brow.addStretch(1)
        backup.addLayout(brow)
        self.backup_note = label("", "caption", wrap=True)
        backup.addWidget(self.backup_note)

        # --- firmware update -------------------------------------------------------
        fw = self.section("Firmware update")
        self.fw_status = label("", "valueLabel", wrap=True)
        fw.addWidget(self.fw_status)
        fw.addWidget(
            label(
                "1. Download macropad-fw-X.Y.Z.uf2 from the Releases page.\n"
                "2. Hold BOOT while plugging the board in (or hold BOOT and tap RESET); "
                "a drive called RPI-RP2 appears.\n"
                "3. Copy the .uf2 onto RPI-RP2. The board reboots by itself.\n"
                "4. Come back here and press Refresh. Profiles, macros, idle settings and the "
                "animation are kept across updates.",
                "hintLabel",
                wrap=True,
            )
        )
        frow = QHBoxLayout()
        frow.setSpacing(theme.SPACE["sm"])
        guide = icon_button("external-link", f"Open {UPDATE_GUIDE_URL}", text="Update guide")
        guide.setProperty("outlined", True)
        guide.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(UPDATE_GUIDE_URL)))
        rel = icon_button("external-link", f"Open {RELEASES_URL}", text="Releases page")
        rel.setProperty("outlined", True)
        rel.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        frow.addWidget(guide)
        frow.addWidget(rel)
        frow.addStretch(1)
        fw.addLayout(frow)

        self.set_info(None)

    # -- state -------------------------------------------------------------------
    def is_connected(self) -> bool:
        return self.info is not None

    def set_info(self, info: dict | None, proto_ok: bool = True, *, failed: bool = False) -> None:
        self.info = dict(info) if info else None
        expected = f"{app_version.FW_VERSION_MAJOR_EXPECTED}.{app_version.FW_VERSION_MINOR_CURRENT}"
        if info is None:
            self.info_panel.hide()
            self.empty.show()
            self.refresh_row.hide()
            self.empty.set_text(
                "Could not reach the macropad" if failed else "No device connected",
                (
                    "Check the USB cable (data, not charge-only) and that no other app has the "
                    "config interface open, then try again. See TROUBLESHOOTING.md."
                    if failed
                    else "Plug the macropad in over USB, then connect. Uploads, backup and Save device "
                    "state need a connection; everything else works offline."
                ),
            )
            self.fw_status.setText(f"This configurator expects firmware {expected}.")
            self._set_backup(False, "Connect to the device first.")
            return
        self.empty.hide()
        self.info_panel.show()
        self.refresh_row.show()
        self.info_panel.set_info(info, proto_ok)
        major, minor = info.get("fw_major"), info.get("fw_minor")
        have = f"{major}.{minor}"
        if app_version.fw_at_least(major, minor, min_minor=app_version.FW_VERSION_MINOR_CURRENT):
            self.fw_status.setText(f"Firmware {have} is up to date (this configurator expects {expected}).")
        else:
            self.fw_status.setText(
                f"This macropad runs firmware {have}; this configurator expects {expected}. "
                "Update to get every feature."
            )
        if not proto_ok:
            self._set_backup(False, "Protocol mismatch: backup and restore are disabled.")
        elif not app_version.fw_supports_readback(major, minor):
            self._set_backup(
                False, app_version.feature_disabled_tooltip("Backup", app_version.MIN_FW_MINOR_READBACK)
            )
        else:
            self._set_backup(True, "")

    def _set_backup(self, enabled: bool, reason: str) -> None:
        self.backup_btn.setEnabled(enabled)
        self.restore_btn.setEnabled(enabled)
        self.backup_note.setText(reason)
        self.backup_note.setVisible(bool(reason))


__all__ = ["RELEASES_URL", "UPDATE_GUIDE_URL", "DevicePage"]
