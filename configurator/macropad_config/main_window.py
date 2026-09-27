"""Main application window.

Layout: a navigation rail on the left (Keys, Macros, Idle animation,
Auto-switch, Device, Settings; Ctrl+1…6), a page header (title, breadcrumb
such as ``CODING › Key 6``, an unsaved-changes badge and the page's main
actions) and the pages in a stack. Ctrl+K opens the command palette. Modal
dialogs are only used for confirmations, choices and file pickers.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QStyleOption,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import version as app_version
from .models.profile import (
    Profile,
    default_profiles_dir,
    delete_profile_file,
    duplicate_profile,
    load_profiles_dir,
    make_blank_profile,
    save_profile,
    suggest_profile_id,
    suggest_profile_path,
)
from .models.schema import SchemaError
from .pages.device_page import REPO_URL, DevicePage
from .pages.nav import PAGE_INDEX, PAGES, NavRail, PageHeader
from .pages.palette import CommandPalette, PaletteItem
from .pages.settings_page import SettingsPage, open_in_file_manager
from .ui import theme
from .ui.widgets import EmptyState, StatusPill, divider, label, style_form, with_shortcut
from .widgets.action_editor import INSPECTOR_LABEL_W, ActionEditor
from .widgets.autoswitch_dialog import AutoswitchDialog
from .widgets.macro_library_dialog import MacroLibraryDialog
from .widgets.pad_preview import ENCODER_SLOT_LABELS, ENCODER_SLOTS, PadPreview, action_summary
from .widgets.profile_dialog import ProfileNameIdDialog
from .widgets.profile_list import ProfileListWidget

ARCHITECTURE_URL = f"{REPO_URL}/blob/main/docs/ARCHITECTURE.md"
USER_GUIDE_URL = f"{REPO_URL}/blob/main/docs/USER_GUIDE.md"


class _FitScroll(QScrollArea):
    """Scroll wrapper for a big page; asks it to fit its content to the viewport on resize."""

    def __init__(self, page: QWidget) -> None:
        super().__init__()
        self.setObjectName("pageScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setWidget(page)
        self._page = page

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        fit = getattr(self._page, "fit_zoom", None)
        if fit is not None:
            vp = self.viewport().size()
            fit(vp.width(), vp.height())


class _StatusBar(QStatusBar):
    """Status bar whose transient message sits on the 16 px content margin."""

    def paintEvent(self, ev) -> None:
        msg = self.currentMessage()
        if not msg:
            super().paintEvent(ev)
            return
        p = QPainter(self)
        opt = QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_PanelStatusBar, opt, p, self)
        right = self.width() - theme.SPACE["lg"]
        for w in self.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if w.isVisible() and w.x() > self.width() // 3:
                right = min(right, w.x() - theme.SPACE["sm"])
        rect = QRect(theme.SPACE["lg"], 0, max(0, right - theme.SPACE["lg"]), self.height())
        p.setPen(theme.color("text_muted"))
        text = self.fontMetrics().elidedText(msg, Qt.TextElideMode.ElideRight, rect.width())
        p.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        p.end()


# Stock firmware slot layout (the upload dialog's default slot; sidebar badges).
BUILTIN_SLOTS = {"default": 0, "gaming": 1, "coding": 2, "browser": 3, "photoshop": 4}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Macropad Configurator")
        self.resize(1280, 800)
        theme.ensure_theme(QApplication.instance())

        self._profiles_dir = default_profiles_dir()
        self._current: Profile | None = None
        self._selection: tuple[str, object] | None = None
        self._dirty_ids: set[str] = set()
        self._meta_loading = False
        self._applying = False
        self._last_device_info: dict | None = None
        self._autoswitch = None
        self._autoswitch_connected = False
        self._slot_by_id: dict[str, int] = dict(BUILTIN_SLOTS)
        # hid module for ConfigDevice / connect_and_info (None = real hidapi; tests inject a mock)
        self._hid_module = None
        self._page_actions: list[QAction] = []

        self._build_menus()
        self._build_ui()
        self._build_status_bar()
        self.reload_profiles()
        self.go_to_page("keys")

    # ======================================================================
    # Menus
    # ======================================================================
    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_act = QAction("Open profiles &folder", self)
        open_act.setShortcut(QKeySequence("Ctrl+O"))
        open_act.triggered.connect(self._open_profiles_folder)
        file_menu.addAction(open_act)
        self._open_folder_act = open_act

        reload_act = QAction("&Reload profiles", self)
        reload_act.setShortcut(QKeySequence("Ctrl+R"))
        reload_act.triggered.connect(self._reload_with_prompt)
        file_menu.addAction(reload_act)
        self._reload_act = reload_act

        file_menu.addSeparator()

        self._save_act = QAction("&Save", self)
        self._save_act.setShortcut(QKeySequence.StandardKey.Save)
        self._save_act.setStatusTip("Save the current page (profile, macro library, animation or rules)")
        self._save_act.triggered.connect(self._save_page)
        self._save_act.setEnabled(False)
        file_menu.addAction(self._save_act)

        self._save_all_act = QAction("Save &all profiles", self)
        self._save_all_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._save_all_act.triggered.connect(self._save_all)
        self._save_all_act.setEnabled(False)
        file_menu.addAction(self._save_all_act)

        file_menu.addSeparator()

        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        profile_menu = self.menuBar().addMenu("&Profile")

        self._new_profile_act = QAction("&New…", self)
        self._new_profile_act.setShortcut(QKeySequence("Ctrl+N"))
        self._new_profile_act.triggered.connect(self._new_profile)
        profile_menu.addAction(self._new_profile_act)

        self._dup_profile_act = QAction("&Duplicate…", self)
        self._dup_profile_act.setShortcut(QKeySequence("Ctrl+D"))
        self._dup_profile_act.triggered.connect(self._duplicate_profile)
        profile_menu.addAction(self._dup_profile_act)

        self._del_profile_act = QAction("De&lete…", self)
        self._del_profile_act.triggered.connect(self._delete_profile)
        profile_menu.addAction(self._del_profile_act)

        profile_menu.addSeparator()

        self._next_profile_act = QAction("Ne&xt profile", self)
        self._next_profile_act.setShortcut(QKeySequence("Ctrl+Tab"))
        self._next_profile_act.triggered.connect(lambda: self._cycle_profile(1))
        profile_menu.addAction(self._next_profile_act)

        self._prev_profile_act = QAction("P&revious profile", self)
        self._prev_profile_act.setShortcut(QKeySequence("Ctrl+Shift+Tab"))
        self._prev_profile_act.triggered.connect(lambda: self._cycle_profile(-1))
        profile_menu.addAction(self._prev_profile_act)

        profile_menu.addSeparator()

        self._macro_lib_act = QAction("Macro &library", self)
        self._macro_lib_act.setShortcut(QKeySequence("Ctrl+2"))
        self._macro_lib_act.setStatusTip("Go to the Macros page")
        self._macro_lib_act.triggered.connect(self._open_macro_library)
        profile_menu.addAction(self._macro_lib_act)

        self._build_view_menu()

        device_menu = self.menuBar().addMenu("&Device")

        self._connect_act = QAction("&Connect / Get device info", self)
        self._connect_act.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self._connect_act.setStatusTip("PING + GET_INFO over vendor HID; shows the result on the Device page")
        self._connect_act.triggered.connect(self._device_connect_info)
        device_menu.addAction(self._connect_act)

        self._upload_act = QAction("&Upload profile to device…", self)
        self._upload_act.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self._upload_act.setStatusTip("Pack selected profile and upload into a device slot (0–4)")
        self._upload_act.triggered.connect(self._device_upload_profile)
        device_menu.addAction(self._upload_act)

        self._upload_macros_act = QAction("Upload &macros to device…", self)
        self._upload_macros_act.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self._upload_macros_act.setStatusTip("Upload host macro library ids 0–4 to the device flash bank")
        self._upload_macros_act.triggered.connect(self._device_upload_macros)
        device_menu.addAction(self._upload_macros_act)

        self._save_device_act = QAction("&Save device state", self)
        self._save_device_act.setStatusTip(
            "SAVE_ALL (0x32): rewrite flash with current RAM profiles+macros+active"
        )
        self._save_device_act.setEnabled(False)
        self._save_device_act.triggered.connect(self._device_save_all)
        device_menu.addAction(self._save_device_act)

        device_menu.addSeparator()

        self._backup_act = QAction("&Back up device…", self)
        self._backup_act.setStatusTip("Read all profile slots, macros and idle settings into a backup file")
        self._backup_act.triggered.connect(self._device_backup)
        device_menu.addAction(self._backup_act)

        self._restore_act = QAction("&Restore backup…", self)
        self._restore_act.setStatusTip("Write a backup file to the connected macropad")
        self._restore_act.triggered.connect(self._device_restore)
        device_menu.addAction(self._restore_act)

        device_menu.addSeparator()

        self._autoswitch_act = QAction("Auto-switch &enabled", self)
        self._autoswitch_act.setCheckable(True)
        self._autoswitch_act.setChecked(False)
        self._autoswitch_act.setEnabled(False)
        self._autoswitch_act.setStatusTip(
            "Poll foreground app and SET_ACTIVE on the device (needs connection)"
        )
        self._autoswitch_act.toggled.connect(self._on_autoswitch_toggled)
        device_menu.addAction(self._autoswitch_act)

        tools_menu = self.menuBar().addMenu("&Tools")
        self._autoswitch_dlg_act = QAction("&Auto-switch rules", self)
        self._autoswitch_dlg_act.setShortcut(QKeySequence("Ctrl+4"))
        self._autoswitch_dlg_act.setStatusTip("Go to the Auto-switch page (rules: host → device)")
        self._autoswitch_dlg_act.triggered.connect(self._open_autoswitch_dialog)
        tools_menu.addAction(self._autoswitch_dlg_act)

        # OLED idle animation editor (authoring works offline; device
        # actions inside are gated on GET_INFO flag bit3 / fw 0.25+).
        self._anim_act = QAction("&Idle animation", self)
        self._anim_act.setShortcut(QKeySequence("Ctrl+3"))
        self._anim_act.setStatusTip(
            "Go to the Idle animation page: design, import GIFs, upload to the macropad (fw 0.25+)"
        )
        self._anim_act.triggered.connect(self._open_anim_editor)
        tools_menu.addAction(self._anim_act)

        help_menu = self.menuBar().addMenu("&Help")
        self._guide_act = QAction("&User guide", self)
        self._guide_act.setShortcut(QKeySequence("F1"))
        self._guide_act.setStatusTip(f"Open {USER_GUIDE_URL}")
        self._guide_act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(USER_GUIDE_URL)))
        help_menu.addAction(self._guide_act)
        arch_help = QAction("&Architecture doc", self)
        arch_help.setStatusTip(f"Open {ARCHITECTURE_URL} (layers, flash vs RAM, protocol)")
        arch_help.triggered.connect(self._show_architecture_tip)
        help_menu.addAction(arch_help)
        help_menu.addSeparator()
        self._about_act = QAction("&About", self)
        self._about_act.setStatusTip("Settings page → About")
        self._about_act.triggered.connect(self._show_about)
        help_menu.addAction(self._about_act)

        self._palette_menus = {
            "File": file_menu,
            "Profile": profile_menu,
            "Device": device_menu,
            "Tools": tools_menu,
            "Help": help_menu,
        }

    def _build_view_menu(self) -> None:
        view_menu = self.menuBar().addMenu("&View")
        go_menu = QMenu("&Go to", self)
        view_menu.addMenu(go_menu)
        self._go_menu = go_menu
        self._page_acts: list[QAction] = []
        for i, spec in enumerate(PAGES):
            act = QAction(f"&{i + 1}  {spec.title}", self)
            act.setShortcut(QKeySequence(spec.shortcut))
            act.setStatusTip(spec.hint)
            act.setData(spec.key)
            act.triggered.connect(lambda _c=False, k=spec.key: self.go_to_page(k))
            go_menu.addAction(act)
            self._page_acts.append(act)
        # The Tools / Profile page actions carry Ctrl+2/3/4 in their menus; keep one owner per key.
        for key in ("macros", "idle", "autoswitch"):
            self._page_acts[PAGE_INDEX[key]].setShortcut(QKeySequence())
            self._page_acts[PAGE_INDEX[key]].setText(
                self._page_acts[PAGE_INDEX[key]].text() + "\t" + PAGES[PAGE_INDEX[key]].shortcut
            )
        self._palette_act = QAction("&Command palette…", self)
        self._palette_act.setShortcut(QKeySequence("Ctrl+K"))
        self._palette_act.setStatusTip("Search pages, profiles, keys and actions")
        self._palette_act.triggered.connect(self.open_palette)
        view_menu.addAction(self._palette_act)
        view_menu.addSeparator()
        theme_menu = QMenu("&Theme", self)
        view_menu.addMenu(theme_menu)
        self._theme_menu = theme_menu
        group = QActionGroup(self)
        group.setExclusive(True)
        self._theme_acts: dict[str, QAction] = {}
        for mode, text in (("system", "Match &system"), ("dark", "&Dark"), ("light", "&Light")):
            act = QAction(text, self)
            act.setCheckable(True)
            act.setData(mode)
            act.triggered.connect(lambda _checked=False, m=mode: self._set_theme_mode(m))
            group.addAction(act)
            theme_menu.addAction(act)
            self._theme_acts[mode] = act
        self._toggle_theme_act = QAction("Toggle &dark / light", self)
        self._toggle_theme_act.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self._toggle_theme_act.triggered.connect(self._toggle_theme)
        view_menu.addAction(self._toggle_theme_act)
        self._view_menu = view_menu
        theme.manager().changed.connect(self._on_theme_changed)
        self._sync_theme_actions()

    def _set_theme_mode(self, mode: str) -> None:
        theme.apply_theme(QApplication.instance(), mode, persist=True)
        self._sync_theme_actions()

    def _toggle_theme(self) -> None:
        self._set_theme_mode("light" if theme.manager().scheme == "dark" else "dark")

    def _sync_theme_actions(self) -> None:
        mode = theme.manager().mode
        for m, act in getattr(self, "_theme_acts", {}).items():
            act.setChecked(m == mode)

    def _on_theme_changed(self, scheme: str) -> None:
        btn = getattr(self, "_theme_btn", None)
        if btn is not None:
            btn.setIcon(theme.icon("sun" if scheme == "dark" else "moon", "text_muted", mode=scheme))
            btn.setToolTip(
                with_shortcut(
                    "Switch to light theme" if scheme == "dark" else "Switch to dark theme", "Ctrl+Shift+L"
                )
            )
        self._sync_theme_actions()
        settings = getattr(self, "_settings_page", None)
        if settings is not None:
            settings.sync_theme()

    # ======================================================================
    # Layout: rail | header + pages
    # ======================================================================
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("appShell")
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.setCentralWidget(central)

        self._rail = NavRail()
        self._rail.pageRequested.connect(self.go_to_page)
        shell.addWidget(self._rail)
        # quick theme toggle just above Settings at the bottom of the rail
        self._theme_btn = QToolButton()
        self._theme_btn.setObjectName("themeToggle")
        self._theme_btn.setAutoRaise(True)
        self._theme_btn.setIconSize(QSize(18, 18))
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        rail_lay = self._rail.layout()
        rail_lay.insertWidget(
            rail_lay.indexOf(self._rail.buttons[PAGE_INDEX["settings"]]),
            self._theme_btn,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        self._on_theme_changed(theme.manager().scheme)

        column = QWidget()
        column.setObjectName("pageColumn")
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self._header = PageHeader()
        col.addWidget(self._header)
        col.addWidget(divider())
        self._stack = QStackedWidget()
        self._stack.setObjectName("pageStack")
        col.addWidget(self._stack, 1)
        shell.addWidget(column, 1)
        self._build_header_actions()

        self._keys_page = self._build_keys_page()
        self._macros_page = MacroLibraryDialog(embedded=True)
        self._macros_page.dirtyChanged.connect(lambda _d: self._refresh_dirty_ui())
        self._macros_page.currentMacroChanged.connect(lambda _n: self._update_header())
        self._macros_page.saved.connect(self._on_macros_saved)
        self._anim_page = self._build_anim_page()
        self._autoswitch_page = self._build_autoswitch_page()
        self._device_page = DevicePage(
            {
                "connect": self._connect_act,
                "upload": self._upload_act,
                "upload_macros": self._upload_macros_act,
                "save_device": self._save_device_act,
                "autoswitch": self._autoswitch_act,
            }
        )
        self._device_page.backupRequested.connect(self._device_backup)
        self._device_page.restoreRequested.connect(self._device_restore)
        self._settings_page = self._build_settings_page()
        self._pages = {
            "keys": self._keys_page,
            "macros": self._macros_page,
            "idle": self._anim_page,
            "autoswitch": self._autoswitch_page,
            "device": self._device_page,
            "settings": self._settings_page,
        }
        for spec in PAGES:
            page = self._pages[spec.key]
            self._stack.addWidget(_FitScroll(page) if spec.key == "idle" else page)
        self._apply_device_feature_gates(None)

    def _build_header_actions(self) -> None:
        acts = self._header.actions_layout
        self._palette_btn = QPushButton("Search…")
        self._palette_btn.setObjectName("paletteButton")
        theme.bind_icon(self._palette_btn, "search", "text_faint")
        self._palette_btn.setIconSize(QSize(14, 14))
        self._palette_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._palette_btn.setToolTip(with_shortcut("Search pages, profiles, keys and actions", "Ctrl+K"))
        self._palette_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._palette_btn.clicked.connect(self.open_palette)
        hint = QLabel("Ctrl+K")
        hint.setObjectName("paletteHint")
        hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        hint_lay = QHBoxLayout(self._palette_btn)
        hint_lay.setContentsMargins(0, 0, 8, 0)
        hint_lay.addStretch(1)
        hint_lay.addWidget(hint, 0, Qt.AlignmentFlag.AlignVCenter)
        self._palette_hint = hint
        acts.addWidget(self._palette_btn)

        theme.bind_icon(self._save_act, "save")
        theme.bind_icon(self._macro_lib_act, "list-ordered")
        theme.bind_icon(self._anim_act, "film")
        theme.bind_icon(self._autoswitch_dlg_act, "repeat")
        theme.bind_icon(self._connect_act, "plug")
        theme.bind_icon(self._upload_act, "upload", "accent_text")
        theme.bind_icon(self._upload_macros_act, "upload")
        theme.bind_icon(self._backup_act, "download")
        theme.bind_icon(self._palette_act, "search")
        theme.bind_icon(self._guide_act, "external-link")

        def tool(act: QAction, text: str, *, primary: bool = False) -> QToolButton:
            btn = QToolButton()
            btn.setDefaultAction(act)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setIconSize(QSize(16, 16))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if primary:
                btn.setObjectName("primaryAction")
            else:
                btn.setProperty("textBeside", True)

            def sync() -> None:
                btn.setText(text)
                btn.setToolTip(with_shortcut(act.toolTip(), act.shortcut()))

            act.changed.connect(sync)
            sync()
            acts.addWidget(btn)
            return btn

        self._save_btn = tool(self._save_act, "Save")
        self._connect_btn = tool(self._connect_act, "Connect")
        self._upload_btn = tool(self._upload_act, "Upload", primary=True)
        self._upload_macros_btn = tool(self._upload_macros_act, "Upload macros", primary=True)
        theme.bind_icon(self._upload_macros_act, "upload", "accent_text")

    def _build_keys_page(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        # Left: profiles
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self._profile_list = ProfileListWidget()
        self._profile_list.profile_selected.connect(self._on_profile_selected)
        self._profile_list.new_requested.connect(self._new_profile)
        self._profile_list.duplicate_requested.connect(self._duplicate_profile)
        self._profile_list.delete_requested.connect(self._delete_profile)
        self._profile_list.set_slot_map(self._slot_by_id)
        side_layout.addWidget(self._profile_list)
        sidebar.setMinimumWidth(200)
        splitter.addWidget(sidebar)

        # Center: the device (or an empty state when there are no profiles)
        canvas = QWidget()
        canvas.setObjectName("canvasArea")
        canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(
            theme.SPACE["lg"], theme.SPACE["lg"], theme.SPACE["lg"], theme.SPACE["lg"]
        )
        self._pad = PadPreview()
        self._pad.setToolTip("")
        self._pad.selection_changed.connect(self._on_selection_changed)
        self._keys_empty = EmptyState(
            "keyboard",
            "No profiles yet",
            "A profile holds the 12 key actions and the encoder's turn / press actions. "
            "Create one, or put profile JSON files in the profiles folder and reload (Ctrl+R).",
            action_text="New profile",
        )
        self._keys_empty.setObjectName("keysEmptyState")
        self._keys_empty.activated.connect(self._new_profile)
        self._canvas_stack = QStackedWidget()
        self._canvas_stack.addWidget(self._pad)
        self._canvas_stack.addWidget(self._keys_empty)
        canvas_layout.addWidget(self._canvas_stack, 1)
        self._pad_hint = label(
            "Click a key or encoder slot · arrow keys move · Ctrl+Tab next profile · Ctrl+K search",
            "caption",
        )
        self._pad_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        canvas_layout.addWidget(self._pad_hint)
        splitter.addWidget(canvas)

        # Right: inspector
        inspector = QWidget()
        inspector.setObjectName("inspector")
        inspector.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        right_layout = QVBoxLayout(inspector)
        pad = theme.SPACE["lg"]
        right_layout.setContentsMargins(pad, theme.SPACE["md"], pad, pad)
        right_layout.setSpacing(theme.SPACE["md"])

        meta_heading = label("Profile", "sectionTitle")
        meta_heading.setFixedHeight(28)  # same header height as the sidebar (icon buttons)
        right_layout.addWidget(meta_heading)
        meta_form = QFormLayout()
        meta_form.setContentsMargins(0, 0, 0, 0)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Profile name")
        self._name_edit.textChanged.connect(self._on_meta_changed)
        self._oled_edit = QLineEdit()
        self._oled_edit.setPlaceholderText("Shown on the device display")
        self._oled_edit.textChanged.connect(self._on_meta_changed)
        meta_form.addRow("Name", self._name_edit)
        meta_form.addRow("OLED title", self._oled_edit)
        style_form(meta_form, label_width=INSPECTOR_LABEL_W)
        right_layout.addLayout(meta_form)

        right_layout.addSpacing(theme.SPACE["xs"])
        right_layout.addWidget(divider())
        right_layout.addSpacing(theme.SPACE["xs"])

        sel_head = QVBoxLayout()
        sel_head.setSpacing(2)
        self._selection_title = label("No selection", "panelTitle")
        self._selection_hint = label(
            "Select a key or the encoder to edit its action.", "hintLabel", wrap=True
        )
        sel_head.addWidget(self._selection_title)
        sel_head.addWidget(self._selection_hint)
        right_layout.addLayout(sel_head)

        self._action_editor = ActionEditor()
        self._action_editor.actionChanged.connect(self._on_action_changed)
        right_layout.addWidget(self._action_editor)

        right_layout.addSpacing(theme.SPACE["xs"])
        right_layout.addWidget(divider())
        right_layout.addSpacing(theme.SPACE["xs"])
        right_layout.addWidget(label("Action JSON", "sectionTitle"))
        self._action_view = QTextEdit()
        self._action_view.setObjectName("detailsPanel")
        self._action_view.setReadOnly(True)
        self._action_view.setMinimumHeight(96)
        self._action_view.setMaximumHeight(280)
        self._action_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._action_view.document().contentsChanged.connect(self._fit_json_height)
        self._action_view.setPlaceholderText("Select a key or encoder slot")
        self._action_view.setFont(theme.mono_font())
        right_layout.addWidget(self._action_view)
        right_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("inspectorScroll")
        scroll.setWidget(inspector)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(320)
        splitter.addWidget(scroll)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([240, 600, 360])
        splitter.setObjectName("keysPage")
        return splitter

    def _build_anim_page(self):
        from .widgets.anim_editor import AnimationEditorDialog

        page = AnimationEditorDialog(
            device_factory=self._make_device, device_info=self._last_device_info, embedded=True
        )
        page.dirtyChanged.connect(lambda _d: self._refresh_dirty_ui())
        page.projectChanged.connect(lambda _n: self._update_header())
        return page

    def _build_autoswitch_page(self) -> AutoswitchDialog:
        rules = self._load_autoswitch_rules()
        page = AutoswitchDialog(rules, profile_ids=None, embedded=True)
        page.dirtyChanged.connect(lambda _d: self._refresh_dirty_ui())
        page.saved.connect(self._on_autoswitch_saved)
        return page

    def _build_settings_page(self) -> SettingsPage:
        from .animation.project import animations_dir
        from .autoswitch.rules import default_rules_path
        from .models.macro import default_macros_path

        paths = [
            ("Profiles", default_profiles_dir()),
            ("Macro library", default_macros_path()),
            ("Auto-switch rules", default_rules_path()),
            ("Animation projects", animations_dir(create=False)),
        ]
        return SettingsPage(set_theme=self._set_theme_mode, data_paths=paths, shortcuts=self.shortcut_list())

    def shortcut_list(self) -> list[tuple[str, str]]:
        """(keys, description) rows for Settings → Keyboard shortcuts."""
        rows = [
            ("Ctrl+K", "Command palette"),
            ("Ctrl+1 … Ctrl+6", "Go to page (Keys … Settings)"),
            ("Ctrl+Tab", "Next profile"),
            ("Ctrl+Shift+Tab", "Previous profile"),
            ("Arrow keys", "Move around the device view"),
        ]
        for act, text in (
            (self._save_act, "Save the current page"),
            (self._save_all_act, "Save all profiles"),
            (self._new_profile_act, "New profile"),
            (self._dup_profile_act, "Duplicate profile"),
            (self._reload_act, "Reload profiles"),
            (self._open_folder_act, "Open profiles folder"),
            (self._connect_act, "Connect / device info"),
            (self._upload_act, "Upload profile"),
            (self._upload_macros_act, "Upload macros"),
            (self._toggle_theme_act, "Toggle dark / light"),
            (self._guide_act, "User guide"),
        ):
            rows.append((act.shortcut().toString(QKeySequence.SequenceFormat.NativeText), text))
        return rows

    def _fit_json_height(self) -> None:
        """Size the JSON panel to its content (96–280 px) instead of a fixed box."""
        view = self._action_view
        doc = view.document()
        doc.setTextWidth(max(50, view.viewport().width()))
        # document height (incl. its 4 px margin) + 8 px QSS padding and 1 px border per side
        h = int(doc.size().height()) + 2 * (8 + 1) + 4
        view.setFixedHeight(max(96, min(280, h)))

    def _build_status_bar(self) -> None:
        sb = _StatusBar(self)
        self.setStatusBar(sb)
        sb.setSizeGripEnabled(False)
        self._conn_pill = StatusPill("Not connected", "neutral")
        self._conn_pill.setToolTip(with_shortcut("Device page", "Ctrl+5"))
        self._conn_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self._conn_pill.mousePressEvent = lambda _ev: self.go_to_page("device")
        self._fw_label = QLabel("Firmware —")
        self._fw_label.setObjectName("statusMeta")
        self._proto_label = QLabel(f"Protocol v{app_version.PROTO_VER} (host)")
        self._proto_label.setObjectName("statusMeta")
        self._proto_label.setToolTip(
            f"Host protocol v{app_version.PROTO_VER}; host app {app_version.HOST_APP_VERSION}"
        )
        sb.addPermanentWidget(self._fw_label)
        sb.addPermanentWidget(self._proto_label)
        sb.addPermanentWidget(self._conn_pill)
        spacer = QWidget()
        spacer.setFixedWidth(theme.SPACE["sm"])
        sb.addPermanentWidget(spacer)
        sb.showMessage("Ready")

    # ======================================================================
    # Pages, header, unsaved markers
    # ======================================================================
    def current_page_key(self) -> str:
        return PAGES[self._stack.currentIndex()].key

    def page_widget(self, key: str) -> QWidget:
        return self._pages[key]

    def go_to_page(self, page: str | int) -> None:
        idx = PAGE_INDEX[page] if isinstance(page, str) else int(page)
        if not 0 <= idx < len(PAGES):
            return
        self._stack.setCurrentIndex(idx)
        self._rail.set_current(idx)
        key = PAGES[idx].key
        on_keys = key == "keys"
        # Ctrl+D duplicates a profile on the Keys page and a frame on the Idle animation page.
        self._dup_profile_act.setShortcut(QKeySequence("Ctrl+D") if key != "idle" else QKeySequence())
        self._save_btn.setVisible(on_keys)
        self._upload_btn.setVisible(on_keys)
        self._upload_macros_btn.setVisible(key == "macros")
        self._connect_btn.setVisible(key != "device")
        for i, act in enumerate(self._page_acts):
            act.setCheckable(True)
            act.setChecked(i == idx)
        if key == "autoswitch" and not self._autoswitch_page.is_dirty():
            # refresh the fallback-profile choices with the profiles loaded now
            ids = [p.id for p in self._profile_list.profiles()]
            self._autoswitch_page.set_rules(self._autoswitch_page.result_rules(), ids or None)
        self._refresh_dirty_ui()
        focus = {"keys": self._pad, "macros": self._macros_page._list}.get(key)
        if focus is not None and focus.isVisible():
            focus.setFocus(Qt.FocusReason.OtherFocusReason)

    def _page_dirty(self, key: str) -> bool:
        if key == "keys":
            return bool(self._dirty_ids)
        if key == "macros":
            return self._macros_page.is_dirty()
        if key == "idle":
            return self._anim_page.is_dirty()
        if key == "autoswitch":
            return self._autoswitch_page.is_dirty()
        return False

    def dirty_pages(self) -> list[str]:
        return [spec.key for spec in PAGES if self._page_dirty(spec.key)]

    def _refresh_dirty_ui(self) -> None:
        if not hasattr(self, "_pages"):
            return
        for i, spec in enumerate(PAGES):
            self._rail.set_dirty(i, self._page_dirty(spec.key))
        self._profile_list.set_dirty_ids(self._dirty_ids)
        self._update_save_actions()
        self._update_header()

    def breadcrumb_parts(self) -> list[str]:
        key = self.current_page_key()
        if key == "keys":
            if self._current is None:
                return ["No profile"]
            parts = [self._current.oled_title or self._current.name]
            if self._selection is not None:
                kind, sid = self._selection
                if kind == "key":
                    parts.append(f"Key {sid}")
                else:
                    parts.append(f"Encoder · {ENCODER_SLOT_LABELS.get(str(sid), str(sid))}")
            return parts
        if key == "macros":
            name = self._macros_page.current_macro_name()
            return ["Library", name] if name else ["Library"]
        if key == "idle":
            return [self._anim_page.project_name()]
        if key == "autoswitch":
            n = self._autoswitch_page.rule_count()
            state = "running" if self._autoswitch_act.isChecked() else "off"
            return [f"{n} rule{'s' if n != 1 else ''}", f"auto-switch {state}"]
        if key == "device":
            info = self._last_device_info
            if info is None:
                return ["Not connected"]
            return [
                str(info.get("product_tag") or "Macropad"),
                f"fw {info.get('fw_major', '?')}.{info.get('fw_minor', '?')}",
            ]
        return ["Appearance, data, shortcuts, about"]

    def breadcrumb(self) -> str:
        return self._header.breadcrumb()

    def _update_header(self) -> None:
        if not hasattr(self, "_pages"):
            return
        key = self.current_page_key()
        spec = PAGES[PAGE_INDEX[key]]
        dirty = self._page_dirty(key)
        if key == "keys":  # the badge is about the profile being shown
            dirty = bool(self._current and self._current.id in self._dirty_ids)
        self._header.set_location(spec.title, self.breadcrumb_parts(), dirty)

    def _cycle_profile(self, delta: int) -> None:
        prof = self._profile_list.select_offset(delta)
        if prof is None:
            return
        if self.current_page_key() != "keys":
            self.go_to_page("keys")
        self.statusBar().showMessage(f"Profile: {prof.name} ({prof.id})", 4000)

    def _save_page(self) -> None:
        """File → Save / Ctrl+S: save whatever the current page edits."""
        key = self.current_page_key()
        if key == "macros":
            self._macros_page.save()
        elif key == "idle":
            self._anim_page.save_project()
        elif key == "autoswitch":
            self._autoswitch_page.save()
        else:
            self._save_current()
        self._refresh_dirty_ui()

    def _on_macros_saved(self) -> None:
        self._pad.reload_macro_names()
        self._update_selection_header()
        self.statusBar().showMessage("Macro library saved", 5000)
        self._refresh_dirty_ui()

    # ======================================================================
    # Command palette
    # ======================================================================
    def open_palette(self, query: str = "") -> CommandPalette:
        pal = getattr(self, "_palette", None)
        if pal is None:
            pal = CommandPalette(self)
            pal.executed.connect(lambda t: self.statusBar().showMessage(f"Ran: {t}", 3000))
            self._palette = pal
        pal.open_with(self.palette_items(), query if isinstance(query, str) else "")
        return pal

    def palette_items(self) -> list[PaletteItem]:
        items: list[PaletteItem] = []
        cur = self.current_page_key()
        for spec in PAGES:
            items.append(
                PaletteItem(
                    title=f"Go to {spec.title}",
                    category="Page",
                    run=lambda k=spec.key: self.go_to_page(k),
                    subtitle=spec.hint + (" (current)" if spec.key == cur else ""),
                    shortcut=spec.shortcut,
                    keywords=f"{spec.title} page {spec.key}",
                )
            )
        for prof in self._profile_list.profiles():
            slot = self._slot_by_id.get(prof.id)
            sub = prof.id + (f" · slot {slot}" if slot is not None else "")
            if prof.id in self._dirty_ids:
                sub += " · unsaved"
            items.append(
                PaletteItem(
                    title=prof.oled_title or prof.name,
                    category="Profile",
                    run=lambda pid=prof.id: self._palette_select_profile(pid),
                    subtitle=sub,
                    keywords=f"{prof.name} {prof.id} profile",
                )
            )
        macros = self._pad._macros
        for num in range(1, 13):
            act = self._current.action_for_key(num) if self._current else None
            items.append(
                PaletteItem(
                    title=f"Key {num}",
                    category="Key",
                    run=lambda n=num: self._palette_select("key", n),
                    subtitle=action_summary(act, macros) if self._current else "",
                    enabled=self._current is not None,
                    disabled_reason="Select a profile first",
                    keywords=f"key{num} k{num}",
                )
            )
        for slot in ENCODER_SLOTS:
            act = self._current.action_for_encoder(slot) if self._current else None
            items.append(
                PaletteItem(
                    title=f"Encoder · {ENCODER_SLOT_LABELS[slot]}",
                    category="Key",
                    run=lambda s=slot: self._palette_select("encoder", s),
                    subtitle=action_summary(act, macros) if self._current else "",
                    enabled=self._current is not None,
                    disabled_reason="Select a profile first",
                    keywords="knob encoder",
                )
            )
        seen: set[int] = set()
        for menu_name, menu in self._palette_menus.items():
            for act in self._walk_actions(menu):
                if id(act) in seen or act.isSeparator() or act.menu() is not None:
                    continue
                seen.add(id(act))
                title = act.text().replace("&", "").split("\t")[0]
                if act is self._save_act:
                    title = f"Save ({PAGES[PAGE_INDEX[cur]].title})"
                items.append(
                    PaletteItem(
                        title=title,
                        category="Action",
                        run=act.trigger,
                        subtitle=menu_name,
                        shortcut=act.shortcut().toString(QKeySequence.SequenceFormat.NativeText),
                        enabled=act.isEnabled(),
                        disabled_reason=act.toolTip() if not act.isEnabled() else "",
                        keywords=act.statusTip(),
                    )
                )
        items.append(
            PaletteItem(
                title="Toggle dark / light theme",
                category="Action",
                run=self._toggle_theme,
                subtitle="View",
                shortcut="Ctrl+Shift+L",
                keywords="theme dark light appearance",
            )
        )
        return items

    @staticmethod
    def _walk_actions(menu: QMenu):
        for act in menu.actions():
            if act.menu() is not None:
                yield from MainWindow._walk_actions(act.menu())
            else:
                yield act

    def _palette_select_profile(self, pid: str) -> None:
        self.go_to_page("keys")
        self._profile_list.select_by_id(pid)

    def _palette_select(self, kind: str, sid: object) -> None:
        self.go_to_page("keys")
        self._pad.select(kind, sid)
        self._pad.setFocus(Qt.FocusReason.OtherFocusReason)

    def _set_device_status(self, info: dict | None, *, failed: bool = False) -> None:
        """Status-bar pill + firmware/protocol text, Device page and slot badges."""
        if info is None:
            self._conn_pill.set_state(
                "No device" if failed else "Not connected", "danger" if failed else "neutral"
            )
            if hasattr(self, "_device_page") and self._last_device_info is None:
                self._device_page.set_info(None, failed=failed)
            self._update_header()
            return
        fw = f"{info.get('fw_major', '?')}.{info.get('fw_minor', '?')}"
        proto = info.get("proto_ver", "?")
        ok, _ = app_version.check_proto_ver(info.get("proto_ver", -1))
        self._conn_pill.set_state("Connected" if ok else "Protocol mismatch", "success" if ok else "warning")
        self._fw_label.setText(f"Firmware {fw}")
        self._proto_label.setText(f"Protocol v{proto}")
        self._proto_label.setToolTip(f"Device protocol v{proto}; host expects v{app_version.PROTO_VER}")
        try:
            active = int(info.get("active_slot"))
        except (TypeError, ValueError):
            active = None
        self._profile_list.set_active_slot(active)
        self._device_page.set_info(info, ok)
        self._anim_page.set_device_info(info)
        self._update_header()

    def _update_selection_header(self) -> None:
        sel = self._selection
        if sel is None or self._current is None:
            self._selection_title.setText("No selection")
            self._selection_hint.setText(
                "Select a key or the encoder to edit its action." if self._current else "No profile selected."
            )
            self._update_header()
            return
        kind, sid = sel
        if kind == "key":
            self._selection_title.setText(f"Key {sid}")
            action = self._current.action_for_key(int(sid))
        else:
            self._selection_title.setText(f"Encoder · {ENCODER_SLOT_LABELS.get(str(sid), str(sid))}")
            action = self._current.action_for_encoder(str(sid))
        self._selection_hint.setText(action_summary(action, self._pad._macros))
        self._update_header()

    # --- dirty tracking -------------------------------------------------

    def _mark_dirty(self, profile: Profile | None = None) -> None:
        profile = profile or self._current
        if profile is None:
            return
        self._dirty_ids.add(profile.id)
        self._refresh_dirty_ui()
        self.statusBar().showMessage(f"Modified: {profile.name} ({profile.id})")

    def _clear_dirty(self, profile_id: str | None = None) -> None:
        if profile_id is None:
            self._dirty_ids.clear()
        else:
            self._dirty_ids.discard(profile_id)
        self._refresh_dirty_ui()

    def _update_save_actions(self) -> None:
        cur_dirty = bool(self._current and self._current.id in self._dirty_ids)
        if hasattr(self, "_pages"):
            key = self.current_page_key()
            page_dirty = cur_dirty if key == "keys" else self._page_dirty(key)
            self._save_act.setEnabled(page_dirty)
        else:
            self._save_act.setEnabled(cur_dirty)
        self._save_all_act.setEnabled(bool(self._dirty_ids))
        title = "Macropad Configurator"
        if self._dirty_ids or (hasattr(self, "_pages") and self.dirty_pages()):
            title += " *"
        self.setWindowTitle(title)

    def _confirm_discard_dirty(self, reason: str) -> bool:
        if not self._dirty_ids:
            return True
        names = ", ".join(sorted(self._dirty_ids))
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            f"{reason}\n\nUnsaved profiles: {names}\n\nDiscard changes?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Discard

    # --- load / save ----------------------------------------------------
    def _reload_with_prompt(self) -> None:
        if not self._confirm_discard_dirty("Reload will discard unsaved edits."):
            return
        self._clear_dirty()
        self.reload_profiles()

    def reload_profiles(self) -> None:
        self._profiles_dir = default_profiles_dir()
        profiles, errors = load_profiles_dir(self._profiles_dir)
        keep_id = self._current.id if self._current else None

        self._profile_list.set_profiles(profiles)

        if errors:
            messages = "; ".join(f"{e.path.name}: {e.message}" for e in errors)
            self.statusBar().showMessage(f"Load errors: {messages}", 15000)
        elif not profiles:
            self.statusBar().showMessage(f"No profiles found in {self._profiles_dir}", 10000)
        else:
            self.statusBar().showMessage(f"Loaded {len(profiles)} profile(s) from {self._profiles_dir}")

        if keep_id:
            self._profile_list.select_by_id(keep_id)
        if not profiles:
            self._on_profile_selected(None)

    def _path_for_save(self, profile: Profile) -> Path:
        if profile.source_path is not None:
            return Path(profile.source_path)
        return suggest_profile_path(profile.name, profile.id, self._profiles_dir)

    def _save_current(self) -> None:
        if self._current is None:
            return
        try:
            path = save_profile(self._current, self._path_for_save(self._current))
        except (OSError, ValueError, SchemaError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._clear_dirty(self._current.id)
        self._profile_list.refresh_labels()
        self.statusBar().showMessage(f"Saved {path}")

    def _save_all(self) -> None:
        saved = 0
        for profile in self._profile_list.profiles():
            if profile.id not in self._dirty_ids:
                continue
            try:
                save_profile(profile, self._path_for_save(profile))
                self._dirty_ids.discard(profile.id)
                saved += 1
            except (OSError, ValueError, SchemaError) as exc:
                QMessageBox.critical(self, "Save failed", f"{profile.id}: {exc}")
                break
        self._profile_list.refresh_labels()
        self._update_save_actions()
        self.statusBar().showMessage(f"Saved {saved} profile(s)")

    # --- profile / selection --------------------------------------------

    def _on_profile_selected(self, profile: Profile | None) -> None:
        self._current = profile
        self._selection = None
        self._pad.set_profile(profile)
        self._pad.clear_selection()
        has_profiles = bool(self._profile_list.profiles())
        self._canvas_stack.setCurrentIndex(0 if has_profiles else 1)
        self._pad_hint.setVisible(has_profiles)
        self._meta_loading = True
        try:
            if profile is None:
                self._name_edit.clear()
                self._oled_edit.clear()
                self._name_edit.setEnabled(False)
                self._oled_edit.setEnabled(False)
                self._action_editor.set_action(None)
                self._action_editor.set_enabled(False)
                self._action_view.clear()
            else:
                self._name_edit.setEnabled(True)
                self._oled_edit.setEnabled(True)
                self._name_edit.setText(profile.name)
                self._oled_edit.setText(profile.oled_title)
                self._action_editor.set_action(None)
                self._action_editor.set_enabled(False)
                self._action_view.setPlainText("(select a key or encoder action)")
        finally:
            self._meta_loading = False
        self._update_save_actions()
        has = profile is not None
        self._dup_profile_act.setEnabled(has)
        self._del_profile_act.setEnabled(has)
        many = len(self._profile_list.profiles()) > 1
        self._next_profile_act.setEnabled(many)
        self._prev_profile_act.setEnabled(many)
        self._update_selection_header()

    def _on_selection_changed(self, kind: str, selection_id: object) -> None:
        if not kind or self._current is None:
            self._selection = None
            self._action_editor.set_enabled(False)
            self._action_editor.set_action(None)
            self._action_view.clear()
            self._update_selection_header()
            return

        self._selection = (kind, selection_id)
        if kind == "key":
            action = self._current.action_for_key(int(selection_id))
            label = f"Key {selection_id}"
        else:
            action = self._current.action_for_encoder(str(selection_id))
            label = f"Encoder.{selection_id}"

        self._action_editor.set_enabled(True)
        self._action_editor.set_action(dict(action) if action else {"type": "DISABLED"})
        self._refresh_action_json(label)
        self._update_selection_header()
        if action:
            self.statusBar().showMessage(f"{label}: {action.get('type', '?')}")

    def _on_meta_changed(self, *_args: object) -> None:
        if self._meta_loading or self._current is None:
            return
        name = self._name_edit.text().strip()
        title = self._oled_edit.text()
        if name and name != self._current.name:
            try:
                self._current.set_name(name)
            except ValueError:
                return
        if title != self._current.oled_title:
            self._current.set_oled_title(title)
            self._pad.set_oled_title(title)
        self._profile_list.refresh_labels()
        self._mark_dirty()

    def _on_action_changed(self) -> None:
        if self._applying or self._current is None or self._selection is None:
            return
        kind, selection_id = self._selection
        try:
            action = self._action_editor.get_action()
        except SchemaError:
            # Keep JSON preview showing last good attempt / form dump
            self._refresh_action_json_raw()
            return

        self._applying = True
        try:
            if kind == "key":
                self._current.set_key_action(int(selection_id), action)
                label = f"Key {selection_id}"
            else:
                self._current.set_encoder_action(str(selection_id), action)
                label = f"Encoder.{selection_id}"
            self._pad.refresh_captions()
            self._mark_dirty()
            self._refresh_action_json(label)
            self._update_selection_header()
        finally:
            self._applying = False

    def _refresh_action_json(self, label: str) -> None:
        try:
            action = self._action_editor.get_action()
        except SchemaError as exc:
            self._action_view.setPlainText(f"{label}: invalid — {exc}")
            return
        payload = {"selection": label, "action": action}
        self._action_view.setPlainText(json.dumps(payload, indent=2))

    def _refresh_action_json_raw(self) -> None:
        if self._selection is None:
            return
        kind, selection_id = self._selection
        label = f"Key {selection_id}" if kind == "key" else f"Encoder.{selection_id}"
        self._refresh_action_json(label)

    # --- profile CRUD -----------------------------------------
    def _new_profile(self) -> None:
        existing = self._profile_list.existing_ids()
        dlg = ProfileNameIdDialog(
            title="New profile",
            existing_ids=existing,
            initial_name="",
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        name = dlg.profile_name()
        pid = dlg.profile_id()
        try:
            profile = make_blank_profile(pid, name)
        except ValueError as exc:
            QMessageBox.warning(self, "New profile", str(exc))
            return
        self._profile_list.add_profile(profile, select=True)
        self._mark_dirty(profile)
        self.statusBar().showMessage(f"Created profile {name} ({pid}) — unsaved")

    def _duplicate_profile(self) -> None:
        src = self._current or self._profile_list.current_profile()
        if src is None:
            return
        existing = self._profile_list.existing_ids()
        suggested_name = f"{src.name} Copy"
        suggested_id = suggest_profile_id(suggested_name, existing)
        dlg = ProfileNameIdDialog(
            title="Duplicate profile",
            existing_ids=existing,
            initial_name=suggested_name,
            initial_id=suggested_id,
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        name = dlg.profile_name()
        pid = dlg.profile_id()
        try:
            profile = duplicate_profile(src, pid, name)
        except ValueError as exc:
            QMessageBox.warning(self, "Duplicate profile", str(exc))
            return
        self._profile_list.add_profile(profile, select=True)
        self._mark_dirty(profile)
        self.statusBar().showMessage(f"Duplicated {src.id} → {pid} — unsaved")

    def _delete_profile(self) -> None:
        profile = self._current or self._profile_list.current_profile()
        if profile is None:
            return

        remaining = len(self._profile_list.profiles()) - 1
        warn = ""
        if remaining <= 0:
            warn = (
                "\n\nThis is the last profile. You can delete it, "
                "but the list will be empty until you create a new one."
            )
        on_disk = profile.source_path is not None and Path(profile.source_path).is_file()
        disk_note = (
            f"\n\nFile on disk will be removed:\n{profile.source_path}"
            if on_disk
            else "\n\n(Not yet saved to disk — will only drop from memory.)"
        )
        reply = QMessageBox.question(
            self,
            "Delete profile",
            (f"Delete profile {profile.name!r} ({profile.id})?{disk_note}{warn}"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        pid = profile.id
        try:
            if on_disk:
                delete_profile_file(profile)
        except OSError as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return

        self._dirty_ids.discard(pid)
        self._profile_list.remove_profile(pid)
        self._update_save_actions()
        self.statusBar().showMessage(f"Deleted profile {pid}")

    def _open_profiles_folder(self) -> None:
        path = self._profiles_dir
        if not path.exists():
            QMessageBox.warning(self, "Profiles folder", f"Not found:\n{path}")
            return
        try:
            open_in_file_manager(path)
            self.statusBar().showMessage(f"Opened {path}")
        except OSError as exc:
            self.statusBar().showMessage(
                f"Profiles folder: {path} (could not open file manager: {exc})", 10000
            )

    def closeEvent(self, event) -> None:
        pending = []
        if self._dirty_ids:
            pending.append("Profiles: " + ", ".join(sorted(self._dirty_ids)))
        if self._macros_page.is_dirty():
            pending.append("Macro library")
        if self._autoswitch_page.is_dirty():
            pending.append("Auto-switch rules")
        if self._anim_page.is_dirty():
            pending.append(f"Idle animation ({self._anim_page.project_name()})")
        if pending:
            reply = QMessageBox.question(
                self,
                "Unsaved changes",
                "Quit with unsaved changes?\n\n" + "\n".join(pending) + "\n\nDiscard them?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        self._anim_page.set_playing(False)
        event.accept()

    # --- pages that used to be dialogs (menu actions keep working) ------

    def _open_macro_library(self) -> None:
        self.go_to_page("macros")

    def _open_anim_editor(self) -> None:
        self.go_to_page("idle")

    def _open_autoswitch_dialog(self) -> None:
        self.go_to_page("autoswitch")

    def _show_about(self) -> None:
        self.go_to_page("settings")
        page = self._settings_page
        page.ensureWidgetVisible(page.about, 0, 0)

    def _show_architecture_tip(self) -> None:
        QDesktopServices.openUrl(QUrl(ARCHITECTURE_URL))
        self.statusBar().showMessage(f"Architecture: {ARCHITECTURE_URL}", 12000)

    # ======================================================================
    # Device
    # ======================================================================
    def _make_device(self, timeout_ms: int | None = None):
        from .protocol.device import DEFAULT_TIMEOUT_MS, ConfigDevice

        return ConfigDevice(timeout_ms=timeout_ms or DEFAULT_TIMEOUT_MS, hid_module=self._hid_module)

    def _apply_device_feature_gates(self, info: dict | None) -> None:
        """Enable/disable upload / autoswitch / SAVE_ALL / backup from GET_INFO fw."""
        if not info:
            tip_u = app_version.feature_disabled_tooltip("Upload profile", app_version.MIN_FW_MINOR_UPLOAD)
            tip_m = app_version.feature_disabled_tooltip(
                "Upload macros", app_version.MIN_FW_MINOR_MACRO_UPLOAD
            )
            tip_a = app_version.feature_disabled_tooltip("Auto-switch", app_version.MIN_FW_MINOR_AUTOSWITCH)
            tip_s = app_version.feature_disabled_tooltip(
                "Save device state", app_version.MIN_FW_MINOR_SAVE_ALL
            )
            tip_b = app_version.feature_disabled_tooltip(
                "Backup / restore", app_version.MIN_FW_MINOR_READBACK
            )
            for act, tip in (
                (self._upload_act, tip_u),
                (self._upload_macros_act, tip_m),
                (self._autoswitch_act, tip_a),
                (self._save_device_act, tip_s),
                (self._backup_act, tip_b),
                (self._restore_act, tip_b),
            ):
                act.setEnabled(False)
                act.setToolTip(tip)
            return

        major = info.get("fw_major")
        minor = info.get("fw_minor")
        proto_ok, _ = app_version.check_proto_ver(info.get("proto_ver", -1))

        def gate(act, supported: bool, feature: str, min_minor: int, base_tip: str) -> None:
            if proto_ok and supported:
                act.setEnabled(True)
                act.setToolTip(base_tip)
                act.setStatusTip(base_tip)
            else:
                act.setEnabled(False)
                if not proto_ok:
                    tip = (
                        f"{feature} disabled: protocol mismatch "
                        f"(host expects proto_ver={app_version.PROTO_VER})."
                    )
                else:
                    tip = app_version.feature_disabled_tooltip(feature, min_minor)
                act.setToolTip(tip)
                act.setStatusTip(tip)

        gate(
            self._upload_act,
            app_version.fw_supports_upload(major, minor),
            "Upload profile",
            app_version.MIN_FW_MINOR_UPLOAD,
            "Pack selected profile and upload into a device slot (0–4)",
        )
        gate(
            self._upload_macros_act,
            app_version.fw_supports_macro_upload(major, minor),
            "Upload macros",
            app_version.MIN_FW_MINOR_MACRO_UPLOAD,
            "Upload host macro library ids 0–4 to the device flash bank",
        )
        # Autoswitch also needs a prior successful connect flag.
        as_ok = proto_ok and app_version.fw_supports_autoswitch(major, minor)
        if as_ok and self._autoswitch_connected:
            self._autoswitch_act.setEnabled(True)
            tip = "Poll foreground app and SET_ACTIVE on the device (needs connection)"
            self._autoswitch_act.setToolTip(tip)
            self._autoswitch_act.setStatusTip(tip)
        else:
            self._autoswitch_act.setEnabled(False)
            if self._autoswitch_act.isChecked():
                self._autoswitch_act.blockSignals(True)
                self._autoswitch_act.setChecked(False)
                self._autoswitch_act.blockSignals(False)
            if not proto_ok:
                tip = (
                    "Auto-switch disabled: protocol mismatch "
                    f"(host expects proto_ver={app_version.PROTO_VER})."
                )
            elif not app_version.fw_supports_autoswitch(major, minor):
                tip = app_version.feature_disabled_tooltip("Auto-switch", app_version.MIN_FW_MINOR_AUTOSWITCH)
            else:
                tip = "Connect to a device first to enable auto-switch."
            self._autoswitch_act.setToolTip(tip)
            self._autoswitch_act.setStatusTip(tip)

        gate(
            self._save_device_act,
            app_version.fw_supports_save_all(major, minor),
            "Save device state",
            app_version.MIN_FW_MINOR_SAVE_ALL,
            "SAVE_ALL (0x32): rewrite flash with current RAM profiles+macros+active",
        )
        for act, base in (
            (self._backup_act, "Read all profile slots, macros and idle settings into a backup file"),
            (self._restore_act, "Write a backup file to the connected macropad"),
        ):
            gate(
                act,
                app_version.fw_supports_readback(major, minor),
                "Backup / restore",
                app_version.MIN_FW_MINOR_READBACK,
                base,
            )

    def _warn_proto_if_needed(self, info: dict) -> bool:
        """Warn on proto mismatch. Returns True if proto matches."""
        ok, msg = app_version.check_proto_ver(info.get("proto_ver", -1))
        if ok:
            return True
        self.statusBar().showMessage(f"Protocol mismatch — {msg}", 20000)
        QMessageBox.warning(
            self,
            "Protocol version mismatch",
            (
                f"{msg}\n\n"
                f"Host app: {app_version.HOST_APP_VERSION}\n"
                f"Device fw: {info.get('fw_major', '?')}.{info.get('fw_minor', '?')}\n\n"
                "Upload / autoswitch / SAVE_ALL are disabled until versions match.\n"
                "See docs/VERSIONING.md."
            ),
        )
        return False

    def _device_connect_info(self) -> None:
        """Open vendor HID, PING + GET_INFO; show the result on the Device page."""
        try:
            from .protocol.device import DeviceError, connect_and_info
        except Exception as exc:
            QMessageBox.warning(self, "Device", f"Protocol module unavailable:\n{exc}")
            return

        self.statusBar().showMessage("Connecting to device…")
        try:
            info = connect_and_info(hid_module=self._hid_module)
        except DeviceError as exc:
            self._last_device_info = None
            self.statusBar().showMessage(f"No device / connect failed: {exc}", 10000)
            self._set_device_status(None, failed=True)
            self.go_to_page("device")
            return
        except Exception as exc:
            self.statusBar().showMessage(f"Device error: {exc}", 10000)
            self._set_device_status(None, failed=True)
            self.go_to_page("device")
            return

        self._last_device_info = info
        self._autoswitch_connected = True
        self._set_device_status(info)
        self._apply_device_feature_gates(info)
        self.go_to_page("device")
        proto_ok = self._warn_proto_if_needed(info)

        fw = f"{info.get('fw_major', '?')}.{info.get('fw_minor', '?')}"
        proto = info.get("proto_ver", "?")
        status = (
            f"Device {'WARN' if not proto_ok else 'OK'} — fw {fw}  "
            f"proto v{proto}  "
            f"active_slot {info.get('active_slot')}/{info.get('slot_count')}  "
            f"host {app_version.HOST_APP_VERSION}"
        )
        self.statusBar().showMessage(status, 15000)

    def _device_upload_profile(self) -> None:
        """Pack the selected profile and upload into a chosen device slot."""
        if self._current is None:
            self.go_to_page("keys")
            self.statusBar().showMessage("Select a profile to upload.", 6000)
            return

        default_slot = 0
        if self._last_device_info is not None:
            try:
                default_slot = int(self._last_device_info.get("active_slot", 0))
            except (TypeError, ValueError):
                default_slot = 0
        if self._current.id in BUILTIN_SLOTS:
            default_slot = BUILTIN_SLOTS[self._current.id]

        slot, ok = QInputDialog.getInt(
            self,
            "Upload to device",
            (f"Upload profile {self._current.name!r} ({self._current.id})\ninto device slot (0–4):"),
            default_slot,
            0,
            4,
            1,
        )
        if not ok:
            return
        self.upload_profile_to_slot(slot)

    def upload_profile_to_slot(self, slot: int) -> bool:
        """Upload the current profile into *slot* (no prompts on success)."""
        from .protocol.device import DeviceError
        from .protocol.profile_blob import PROFILE_BLOB_V1_SIZE, pack_profile

        if self._current is None:
            return False
        try:
            blob = pack_profile(self._current)
        except Exception as exc:
            QMessageBox.critical(self, "Upload", f"Pack failed:\n{exc}")
            return False
        if len(blob) != PROFILE_BLOB_V1_SIZE:
            QMessageBox.critical(
                self,
                "Upload",
                f"Unexpected blob size {len(blob)} (expected {PROFILE_BLOB_V1_SIZE})",
            )
            return False

        self.statusBar().showMessage(f"Uploading {self._current.id} → slot {slot}…")
        try:
            with self._make_device(2000) as dev:
                try:
                    self._last_device_info = dev.get_info()
                except DeviceError:
                    pass
                dev.upload_profile(slot, blob)
        except Exception as exc:
            self.statusBar().showMessage("Upload failed", 8000)
            QMessageBox.warning(self, "Upload failed", str(exc))
            return False

        msg = f"Uploaded {self._current.name} ({self._current.id}) into device slot {slot}."
        self.statusBar().showMessage(msg, 15000)
        # Sidebar badge: this profile now lives in `slot` (display only).
        self._slot_by_id = {k: v for k, v in self._slot_by_id.items() if v != slot}
        self._slot_by_id[self._current.id] = slot
        self._profile_list.set_slot_map(self._slot_by_id)
        if self._last_device_info is not None:
            self._set_device_status(self._last_device_info)
        return True

    def _device_save_all(self) -> None:
        """SAVE_ALL (0x32) — immediate device flash rewrite."""
        try:
            from .protocol.device import DeviceError
        except Exception as exc:
            QMessageBox.warning(self, "Save device state", f"Protocol module unavailable:\n{exc}")
            return

        self.statusBar().showMessage("Saving device state (SAVE_ALL)…")
        try:
            with self._make_device(3000) as dev:
                try:
                    self._last_device_info = dev.get_info()
                except DeviceError:
                    pass
                dev.save_all()
        except Exception as exc:
            self.statusBar().showMessage("Save device state failed", 8000)
            QMessageBox.warning(self, "Save device state failed", str(exc))
            return

        self._autoswitch_connected = True
        if self._last_device_info is not None:
            self._apply_device_feature_gates(self._last_device_info)
            self._set_device_status(self._last_device_info)
        else:
            self._autoswitch_act.setEnabled(True)
            self._save_device_act.setEnabled(True)
        self.statusBar().showMessage("Device state saved (profiles + macros + active_slot).", 10000)

    # --- backup / restore ------------------------------------------------

    def _device_backup(self) -> None:
        from .device_backup import BACKUP_SUFFIX

        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        start = Path.home() / f"macropad-backup-{stamp}{BACKUP_SUFFIX}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Back up device", str(start), f"Macropad backup (*{BACKUP_SUFFIX});;JSON (*.json)"
        )
        if path:
            self.backup_to(path)

    def backup_to(self, path: str | Path) -> dict | None:
        """Read the connected device into a backup file. Returns the backup dict."""
        from .device_backup import BackupError, read_backup, write_backup_file

        self.statusBar().showMessage("Reading device for backup…")
        try:
            with self._make_device(2000) as dev:
                info = dev.get_info()
                data = read_backup(dev, info)
            write_backup_file(data, path)
        except (BackupError, OSError) as exc:
            self.statusBar().showMessage("Backup failed", 8000)
            QMessageBox.warning(self, "Backup failed", str(exc))
            return None
        except Exception as exc:
            self.statusBar().showMessage("Backup failed", 8000)
            QMessageBox.warning(self, "Backup failed", str(exc))
            return None
        self._last_device_info = info
        self._set_device_status(info)
        self.statusBar().showMessage(
            f"Backed up {len(data['profiles'])} profile slots and {len(data['macros'])} macros to {path}",
            15000,
        )
        return data

    def _device_restore(self) -> None:
        from .device_backup import BACKUP_SUFFIX, BackupError, load_backup_file

        path, _ = QFileDialog.getOpenFileName(
            self, "Restore backup", str(Path.home()), f"Macropad backup (*{BACKUP_SUFFIX} *.json)"
        )
        if not path:
            return
        try:
            data = load_backup_file(path)
        except BackupError as exc:
            QMessageBox.warning(self, "Restore backup", str(exc))
            return
        what = f"{len(data['profiles'])} profile slots, {len(data['macros'])} macros"
        if data.get("idle"):
            what += ", idle settings"
        reply = QMessageBox.question(
            self,
            "Restore backup",
            f"Overwrite {what} and the active slot on the connected macropad with this backup?\n\n"
            f"{Path(path).name}\nCreated {data.get('created', '?')} from firmware {data.get('firmware', '?')}.\n\n"
            "The device saves it to flash right away. This cannot be undone "
            "(back up first if unsure).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.restore_from(data)

    def restore_from(self, data: dict) -> list[str] | None:
        """Write a validated backup to the device (no confirmation; see _device_restore)."""
        from .device_backup import BackupError, restore_backup

        self.statusBar().showMessage("Restoring backup…")
        try:
            with self._make_device(3000) as dev:
                info = dev.get_info()
                done = restore_backup(dev, info, data)
                info = dev.get_info()
        except BackupError as exc:
            self.statusBar().showMessage("Restore failed", 8000)
            QMessageBox.warning(self, "Restore failed", str(exc))
            return None
        except Exception as exc:
            self.statusBar().showMessage("Restore failed", 8000)
            QMessageBox.warning(self, "Restore failed", str(exc))
            return None
        self._last_device_info = info
        self._autoswitch_connected = True
        self._apply_device_feature_gates(info)
        self._set_device_status(info)
        self.statusBar().showMessage("Restored: " + ", ".join(done), 15000)
        return done

    # --- auto-switch -----------------------------------------------------

    def _ensure_autoswitch(self):
        if self._autoswitch is not None:
            return self._autoswitch
        from .autoswitch.service import AutoswitchService

        try:
            ids = [p.id for p in self._profile_list.profiles()]
        except Exception:
            ids = []
        if not ids:
            ids = ["default", "gaming", "coding", "browser", "photoshop"]
        svc = AutoswitchService(
            self,
            on_status=lambda msg: self.statusBar().showMessage(msg, 8000),
            on_stopped=self._on_autoswitch_stopped,
            host_profile_ids=ids,
        )
        try:
            svc.load()
        except Exception:
            pass
        self._autoswitch = svc
        return svc

    def _load_autoswitch_rules(self):
        svc = self._ensure_autoswitch()
        try:
            rules = svc.rules
            if rules.schema_version != 1 or not rules.rules:
                from .autoswitch.rules import load_rules

                rules = load_rules()
                svc.set_rules(rules)
        except Exception as exc:
            print(f"[autoswitch] could not load rules: {exc}")
            from .autoswitch.rules import validate_rules

            rules = validate_rules({"schema_version": 1, "enabled": False, "rules": []})
        return rules

    def _on_autoswitch_saved(self, updated) -> None:
        svc = self._ensure_autoswitch()
        svc.set_rules(updated)
        # Sync checkable menu with saved enabled flag only if connected
        if self._autoswitch_connected and updated.enabled:
            self._autoswitch_act.blockSignals(True)
            self._autoswitch_act.setChecked(True)
            self._autoswitch_act.blockSignals(False)
            svc.set_enabled(True)
        elif not updated.enabled:
            self._autoswitch_act.blockSignals(True)
            self._autoswitch_act.setChecked(False)
            self._autoswitch_act.blockSignals(False)
            svc.set_enabled(False)
        self.statusBar().showMessage("Auto-switch rules saved", 5000)
        self._refresh_dirty_ui()

    def _on_autoswitch_stopped(self) -> None:
        """Menu sync when service stops after device disconnect."""
        self._autoswitch_act.blockSignals(True)
        self._autoswitch_act.setChecked(False)
        self._autoswitch_act.blockSignals(False)
        self._update_header()

    def _on_autoswitch_toggled(self, checked: bool) -> None:
        if checked and not self._autoswitch_connected:
            self._autoswitch_act.blockSignals(True)
            self._autoswitch_act.setChecked(False)
            self._autoswitch_act.blockSignals(False)
            self.statusBar().showMessage("Auto-switch: connect to the device first (Ctrl+Shift+I).", 8000)
            return
        svc = self._ensure_autoswitch()
        # Keep rules.enabled in sync when toggling from menu
        rules = svc.rules
        rules.enabled = bool(checked)
        svc.set_rules(rules)
        svc.set_enabled(bool(checked))
        self._autoswitch_page.set_enabled_checked(bool(checked))
        self._update_header()

    def _device_upload_macros(self) -> None:
        """Upload host macro library ids 0–4 to the device."""
        try:
            from .models.macro import load_library
            from .protocol.device import DeviceError
            from .protocol.macro_blob import MACRO_BLOB_V1_SIZE, pack_macro
        except Exception as exc:
            QMessageBox.warning(self, "Upload macros", f"Module unavailable:\n{exc}")
            return

        if self._macros_page.is_dirty():
            reply = QMessageBox.question(
                self,
                "Upload macros",
                "The macro library has unsaved changes. Uploads use the saved library.\n\n"
                "Save the library first?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Ignore
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save and not self._macros_page.save():
                return
        try:
            library = load_library()
        except Exception as exc:
            QMessageBox.warning(self, "Upload macros", f"Could not load library:\n{exc}")
            return

        by_id = {m.id: m for m in library.macros}
        to_upload = [(i, by_id[i]) for i in range(5) if i in by_id]
        if not to_upload:
            self.statusBar().showMessage("Upload macros: no macros with ids 0–4 in the library.", 8000)
            return

        reply = QMessageBox.question(
            self,
            "Upload macros",
            f"Upload {len(to_upload)} macro(s) (ids 0–4) to the device flash bank?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.statusBar().showMessage("Uploading macros…")
        uploaded = 0
        try:
            with self._make_device(2000) as dev:
                try:
                    self._last_device_info = dev.get_info()
                    self._autoswitch_connected = True
                    self._autoswitch_act.setEnabled(True)
                    self._save_device_act.setEnabled(True)
                except DeviceError:
                    pass
                for mid, macro in to_upload:
                    blob = pack_macro(macro)
                    if len(blob) != MACRO_BLOB_V1_SIZE:
                        raise DeviceError(f"macro {mid} blob size {len(blob)} != {MACRO_BLOB_V1_SIZE}")
                    dev.upload_macro(mid, blob)
                    uploaded += 1
        except DeviceError as exc:
            self.statusBar().showMessage("Macro upload failed", 8000)
            QMessageBox.warning(self, "Upload macros failed", str(exc))
            return
        except Exception as exc:
            self.statusBar().showMessage("Macro upload failed", 8000)
            QMessageBox.warning(self, "Upload macros failed", str(exc))
            return

        if self._last_device_info is not None:
            self._set_device_status(self._last_device_info)
        self.statusBar().showMessage(f"Uploaded {uploaded} macro(s) to device.", 15000)
