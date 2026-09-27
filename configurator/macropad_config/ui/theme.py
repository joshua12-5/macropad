"""Hand-built light/dark theme for the configurator.

Everything visual lives here and in ``theme.qss`` (a template whose
``{{token}}`` placeholders are filled from :data:`PALETTES`):

* **Palette** – neutral graphite (dark) / off-white (light) surfaces, one
  accent colour (amber) reserved for selection and primary actions.
* **Type** – the platform UI font (Segoe UI Variable / SF Pro / Inter /
  Cantarell …) at 13 px; semibold section titles; muted secondary text.
* **Spacing** – 8 px grid (:data:`SPACE`), radii 6–8 px, 1 px dividers.
* **Icons** – monochrome Lucide SVGs (ISC, see ``icons/LICENSE``) recoloured
  per theme. :func:`icon` returns a QIcon; :func:`bind_icon` keeps a
  widget/action icon in sync when the theme changes.

Mode: ``"system"`` (follow the OS colour scheme), ``"dark"`` or ``"light"``.
The choice is stored in QSettings (``appearance/theme``);
``MACROPAD_THEME`` overrides it (handy for screenshots and tests).
"""

from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import tempfile
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, QObject, QRectF, QSettings, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QComboBox, QListView, QProxyStyle, QStyle, QStyleFactory, QWidget

UI_DIR = Path(__file__).resolve().parent
ICON_DIR = UI_DIR / "icons"
QSS_TEMPLATE = UI_DIR / "theme.qss"

MODES = ("system", "dark", "light")
SETTINGS_KEY = "appearance/theme"
ENV_OVERRIDE = "MACROPAD_THEME"

# 8 px grid. Use these instead of ad-hoc numbers in layouts.
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
RADIUS = {"sm": 6, "md": 8}
FONT_PX = {"caption": 11, "small": 12, "body": 13, "title": 15, "display": 18}

# fmt: off
PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "window":        "#111214",   # app background / canvas
        "panel":         "#17181b",   # sidebar, inspector
        "raised":        "#1d1e21",   # inputs, buttons, lists
        "hover":         "#26272b",
        "pressed":       "#2e2f34",
        "border":        "#25262a",   # 1 px dividers
        "border_strong": "#34353a",   # control outlines
        "border_hover":  "#45464c",
        "text":          "#e7e7ea",
        "text_muted":    "#9d9ea5",
        "text_faint":    "#65666d",
        "accent":        "#f0913a",
        "accent_hover":  "#f5a257",
        "accent_pressed": "#d97f2c",
        "accent_text":   "#1c1206",
        "accent_soft":   "rgba(240, 145, 58, 0.14)",
        "accent_line":   "rgba(240, 145, 58, 0.55)",
        "selection":     "rgba(240, 145, 58, 0.30)",
        "alt_row":       "#1a1b1e",
        "selected":      "#2a2b30",   # neutral selection (lists, tables)
        "scroll":        "#34353a",
        "scroll_hover":  "#4a4b51",
        "tooltip_bg":    "#26272b",
        "tooltip_text":  "#e7e7ea",
        "success":       "#4cb782",
        "warning":       "#e2b340",
        "danger":        "#eb5a5a",
        # device illustration
        "device_body":   "#1b1c1f",
        "device_edge":   "#2c2d31",
        "cap_skirt":     "#222326",
        "cap_top":       "#2a2b2f",
        "cap_top_hover": "#303136",
        "cap_edge":      "#37383d",
        "cap_legend":    "#e7e7ea",
        "knob":          "#26272b",
        "knob_edge":     "#3b3c42",
        "oled_bg":       "#050506",
        "oled_fg":       "#e9f1ff",
    },
    "light": {
        "window":        "#f6f6f4",
        "panel":         "#fbfbfa",
        "raised":        "#ffffff",
        "hover":         "#efefec",
        "pressed":       "#e6e6e2",
        "border":        "#e5e5e1",
        "border_strong": "#d4d4cf",
        "border_hover":  "#bdbdb7",
        "text":          "#1b1b1d",
        "text_muted":    "#65656b",
        "text_faint":    "#9d9da3",
        "accent":        "#b8520f",
        "accent_hover":  "#a64a0d",
        "accent_pressed": "#914009",
        "accent_text":   "#ffffff",
        "accent_soft":   "rgba(184, 82, 15, 0.10)",
        "accent_line":   "rgba(184, 82, 15, 0.55)",
        "selection":     "rgba(184, 82, 15, 0.22)",
        "alt_row":       "#fafaf8",
        "selected":      "#e8e8e4",
        "scroll":        "#d4d4cf",
        "scroll_hover":  "#b5b5af",
        "tooltip_bg":    "#1f1f22",
        "tooltip_text":  "#f2f2f3",
        "success":       "#2f8f5b",
        "warning":       "#a87a0c",
        "danger":        "#c93c3c",
        "device_body":   "#ecece8",
        "device_edge":   "#d6d6d0",
        "cap_skirt":     "#dcdcd7",
        "cap_top":       "#ffffff",
        "cap_top_hover": "#f7f7f5",
        "cap_edge":      "#cfcfc9",
        "cap_legend":    "#1b1b1d",
        "knob":          "#f4f4f1",
        "knob_edge":     "#c9c9c3",
        "oled_bg":       "#050506",
        "oled_fg":       "#e9f1ff",
    },
}
# fmt: on

UI_FONT_CANDIDATES = (
    "Segoe UI Variable Text",
    "Segoe UI Variable",
    "Segoe UI",
    "SF Pro Text",
    "SF Pro",
    "Inter",
    "Cantarell",
    "Noto Sans",
)
MONO_FONT_CANDIDATES = (
    "Cascadia Mono",
    "SF Mono",
    "Menlo",
    "JetBrains Mono",
    "Consolas",
    "IBM Plex Mono",
    "DejaVu Sans Mono",
)

_TOKEN_RE = re.compile(r"\{\{\s*([a-z_:\-0-9]+)\s*\}\}")


def qcolor(value: str) -> QColor:
    """Parse ``#rrggbb`` or ``rgba(r, g, b, a<=1)`` into a QColor."""
    value = value.strip()
    m = re.fullmatch(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)", value)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        return QColor(r, g, b, round(float(m.group(4)) * 255))
    return QColor(value)


def _pick_family(candidates: tuple[str, ...]) -> Optional[str]:
    families = {f.lower(): f for f in QFontDatabase.families()}
    for name in candidates:
        hit = families.get(name.lower())
        if hit:
            return hit
    return None


def ui_font() -> QFont:
    """The application font: platform UI family at the body size (13 px)."""
    font = QFont(QGuiApplication.font())
    if sys.platform != "darwin":  # macOS already defaults to SF Pro
        family = _pick_family(UI_FONT_CANDIDATES)
        if family:
            font.setFamily(family)
    font.setPixelSize(FONT_PX["body"])
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def mono_font(px: int | None = None) -> QFont:
    family = _pick_family(MONO_FONT_CANDIDATES)
    font = QFont(family) if family else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(px or FONT_PX["small"])
    return font


# --------------------------------------------------------------------------
# Icons
# --------------------------------------------------------------------------


def icon_names() -> list[str]:
    return sorted(p.stem for p in ICON_DIR.glob("*.svg"))


def icon_path(name: str) -> Path:
    return ICON_DIR / f"{name}.svg"


# Names requested so far (lets the theme smoke verify every vendored icon is used).
REQUESTED_ICONS: set[str] = set()


def _svg_bytes(name: str, color: str) -> bytes:
    REQUESTED_ICONS.add(name)
    path = icon_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"icon not found: {path}")
    c = qcolor(color)
    svg = path.read_text(encoding="utf-8").replace("currentColor", c.name(QColor.NameFormat.HexRgb))
    if c.alpha() < 255:
        svg = svg.replace("<svg ", f'<svg opacity="{c.alphaF():.3f}" ', 1)
    return svg.encode("utf-8")


def render_icon(name: str, color: str, px: int, dpr: float = 1.0) -> QPixmap:
    """Render icon *name* recoloured to *color* as a (px × px logical) pixmap."""
    phys = max(1, round(px * dpr))
    img = QImage(phys, phys, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(_svg_bytes(name, color)))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, phys, phys))
    p.end()
    pix = QPixmap.fromImage(img)
    pix.setDevicePixelRatio(dpr)
    return pix


def icon(
    name: str, role: str = "text_muted", *, checked_role: str | None = None, mode: str | None = None
) -> QIcon:
    """QIcon for Lucide icon *name* in palette colour *role* (plus disabled/checked states)."""
    pal = palette(mode)
    out = QIcon()
    for px in (16, 18, 20, 24, 32):
        for dpr in (1.0, 2.0):
            out.addPixmap(render_icon(name, pal[role], px, dpr), QIcon.Mode.Normal, QIcon.State.Off)
            out.addPixmap(render_icon(name, pal["text"], px, dpr), QIcon.Mode.Active, QIcon.State.Off)
            out.addPixmap(render_icon(name, pal["text_faint"], px, dpr), QIcon.Mode.Disabled, QIcon.State.Off)
            on = pal[checked_role or "accent"]
            out.addPixmap(render_icon(name, on, px, dpr), QIcon.Mode.Normal, QIcon.State.On)
            out.addPixmap(render_icon(name, on, px, dpr), QIcon.Mode.Active, QIcon.State.On)
    return out


# --------------------------------------------------------------------------
# Theme manager
# --------------------------------------------------------------------------


_MSG_ICONS = {
    QStyle.StandardPixmap.SP_MessageBoxInformation: ("info", "text_muted"),
    QStyle.StandardPixmap.SP_MessageBoxWarning: ("triangle-alert", "warning"),
    QStyle.StandardPixmap.SP_MessageBoxCritical: ("circle-x", "danger"),
    QStyle.StandardPixmap.SP_MessageBoxQuestion: ("circle-question-mark", "text_muted"),
}


class _ThemeStyle(QProxyStyle):
    """Fusion with a few product-level tweaks (no icons on dialog buttons, themed message icons)."""

    def __init__(self) -> None:
        super().__init__(QStyleFactory.create("Fusion"))

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_DialogButtonBox_ButtonsHaveIcons:
            return 0
        if hint == QStyle.StyleHint.SH_ItemView_ShowDecorationSelected:
            return 1
        if hint == QStyle.StyleHint.SH_UnderlineShortcut:
            return 0
        return super().styleHint(hint, option, widget, returnData)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_ToolBarIconSize:
            return 18
        if metric == QStyle.PixelMetric.PM_MessageBoxIconSize:
            return 28
        if metric in (QStyle.PixelMetric.PM_SmallIconSize, QStyle.PixelMetric.PM_ButtonIconSize):
            return 16
        if metric in (
            QStyle.PixelMetric.PM_LayoutLeftMargin,
            QStyle.PixelMetric.PM_LayoutTopMargin,
            QStyle.PixelMetric.PM_LayoutRightMargin,
            QStyle.PixelMetric.PM_LayoutBottomMargin,
        ):
            return SPACE["lg"]
        if metric in (
            QStyle.PixelMetric.PM_LayoutHorizontalSpacing,
            QStyle.PixelMetric.PM_LayoutVerticalSpacing,
        ):
            return SPACE["sm"]
        return super().pixelMetric(metric, option, widget)

    def standardIcon(self, standardIcon, option=None, widget=None):
        spec = _MSG_ICONS.get(standardIcon)
        if spec is not None:
            name, role = spec
            return icon(name, role)
        return super().standardIcon(standardIcon, option, widget)

    def polish(self, arg):
        if isinstance(arg, QComboBox) and not arg.property("_themedView"):
            # A QListView popup honours ::item QSS (height, padding, radius);
            # the default QComboBox delegate ignores it.
            arg.setProperty("_themedView", True)
            arg.setView(QListView(arg))
        return super().polish(arg)


class ThemeManager(QObject):
    """Owns the current mode and (re)applies palette + stylesheet to the app."""

    changed = Signal(str)  # resolved scheme: "dark" | "light"

    def __init__(self) -> None:
        super().__init__()
        self.mode = "system"
        self.scheme = "dark"
        self._bound: list[tuple[weakref.ref, str, str, Optional[str]]] = []
        self._cache_dir: Optional[Path] = None
        self._style: Optional[_ThemeStyle] = None
        self._hooked = False

    # -- resolution -------------------------------------------------------
    @staticmethod
    def system_scheme() -> str:
        try:
            scheme = QGuiApplication.styleHints().colorScheme()
        except Exception:
            return "dark"
        if scheme == Qt.ColorScheme.Light:
            return "light"
        return "dark"  # Dark or Unknown

    def resolve(self, mode: str | None = None) -> str:
        mode = mode or self.mode
        return self.system_scheme() if mode == "system" else mode

    # -- persistence --------------------------------------------------------
    @staticmethod
    def saved_mode() -> str:
        env = os.environ.get(ENV_OVERRIDE, "").strip().lower()
        if env in MODES:
            return env
        try:
            val = str(QSettings("macropad", "Macropad Configurator").value(SETTINGS_KEY, "system"))
        except Exception:
            val = "system"
        return val if val in MODES else "system"

    @staticmethod
    def save_mode(mode: str) -> None:
        QSettings("macropad", "Macropad Configurator").setValue(SETTINGS_KEY, mode)

    # -- application --------------------------------------------------------
    def apply(
        self, app: QApplication | None = None, mode: str | None = None, *, persist: bool = False
    ) -> str:
        app = app or QApplication.instance()
        if app is None:
            raise RuntimeError("apply_theme needs a QApplication")
        if mode is not None:
            if mode not in MODES:
                raise ValueError(f"unknown theme mode {mode!r}")
            self.mode = mode
            if persist:
                self.save_mode(mode)
        scheme = self.resolve()
        self.scheme = scheme
        pal = PALETTES[scheme]

        if self._style is None:
            self._style = _ThemeStyle()
            app.setStyle(self._style)
            app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, True)
        app.setFont(ui_font())
        app.setPalette(self._qpalette(pal))
        app.setStyleSheet(self.stylesheet(scheme))
        if not self._hooked:
            self._hooked = True
            try:
                QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme)
            except Exception:
                pass
        self._refresh_bound()
        self.changed.emit(scheme)
        return scheme

    def _on_system_scheme(self, *_args) -> None:
        if self.mode == "system" and self.resolve() != self.scheme:
            self.apply()

    def stylesheet(self, scheme: str) -> str:
        pal = PALETTES[scheme]
        template = re.sub(r"/\*.*?\*/", "", QSS_TEMPLATE.read_text(encoding="utf-8"), flags=re.S)

        def sub(m: re.Match) -> str:
            key = m.group(1)
            if key.startswith("icon:"):
                _, name, role = key.split(":")
                return self._icon_file(name, pal[role], scheme, role)
            if key == "mono":
                return mono_font().family()
            if key in pal:
                return pal[key]
            raise KeyError(f"theme.qss: unknown token {key!r}")

        return _TOKEN_RE.sub(sub, template)

    def _icon_file(self, name: str, color: str, scheme: str, role: str) -> str:
        """PNG (+@2x/@3x) of a recoloured icon for QSS ``image: url(...)``."""
        if self._cache_dir is None:
            self._cache_dir = Path(tempfile.mkdtemp(prefix="macropad-theme-"))
            atexit.register(shutil.rmtree, self._cache_dir, True)
        base = self._cache_dir / f"{name}-{scheme}-{role}"
        target = base.with_suffix(".png")
        if not target.exists():
            for dpr, suffix in ((1.0, ""), (2.0, "@2x"), (3.0, "@3x")):
                pix = render_icon(name, color, 16, dpr)
                pix.toImage().save(str(base) + suffix + ".png")
        return target.as_posix()

    @staticmethod
    def _qpalette(pal: dict[str, str]) -> QPalette:
        c = {k: qcolor(v) for k, v in pal.items()}
        p = QPalette()
        R = QPalette.ColorRole
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            p.setColor(group, R.Window, c["window"])
            p.setColor(group, R.WindowText, c["text"])
            p.setColor(group, R.Base, c["raised"])
            p.setColor(group, R.AlternateBase, c["alt_row"])
            p.setColor(group, R.Text, c["text"])
            p.setColor(group, R.Button, c["raised"])
            p.setColor(group, R.ButtonText, c["text"])
            p.setColor(group, R.BrightText, c["accent_text"])
            p.setColor(group, R.Highlight, c["accent"])
            p.setColor(group, R.HighlightedText, c["accent_text"])
            p.setColor(group, R.ToolTipBase, c["tooltip_bg"])
            p.setColor(group, R.ToolTipText, c["tooltip_text"])
            p.setColor(group, R.PlaceholderText, c["text_faint"])
            p.setColor(group, R.Link, c["accent"])
            p.setColor(group, R.Light, c["hover"])
            p.setColor(group, R.Midlight, c["border_strong"])
            p.setColor(group, R.Mid, c["border"])
            p.setColor(group, R.Dark, c["window"])
            p.setColor(group, R.Shadow, QColor(0, 0, 0, 90))
        g = QPalette.ColorGroup.Disabled
        for role in (R.WindowText, R.Text, R.ButtonText):
            p.setColor(g, role, c["text_faint"])
        p.setColor(g, R.Base, c["window"])
        p.setColor(g, R.Button, c["window"])
        p.setColor(g, R.Window, c["window"])
        p.setColor(g, R.Highlight, c["border_strong"])
        return p

    # -- icons that follow the theme -------------------------------------------
    def bind_icon(
        self, target: QObject, name: str, role: str = "text_muted", checked_role: str | None = None
    ):
        """Set *target*'s icon now and whenever the theme changes (QAction / button)."""
        target.setIcon(icon(name, role, checked_role=checked_role, mode=self.scheme))
        self._bound.append((weakref.ref(target), name, role, checked_role))
        return target

    def _refresh_bound(self) -> None:
        alive = []
        for ref, name, role, checked_role in self._bound:
            obj = ref()
            if obj is None:
                continue
            try:
                obj.setIcon(icon(name, role, checked_role=checked_role, mode=self.scheme))
            except RuntimeError:  # C++ object already deleted
                continue
            alive.append((ref, name, role, checked_role))
        self._bound = alive

    def on_change(self, fn: Callable[[str], None]) -> None:
        self.changed.connect(fn)


_manager: Optional[ThemeManager] = None


def manager() -> ThemeManager:
    global _manager
    if _manager is None:
        _manager = ThemeManager()
    return _manager


def palette(mode: str | None = None) -> dict[str, str]:
    """Token dict for *mode* (``dark``/``light``) or the active scheme."""
    if mode in ("dark", "light"):
        return PALETTES[mode]
    return PALETTES[manager().scheme]


def color(token: str) -> QColor:
    return qcolor(palette()[token])


def apply_theme(app: QApplication | None = None, mode: str | None = None, *, persist: bool = False) -> str:
    """Apply the theme app-wide; returns the resolved scheme (``dark``/``light``)."""
    return manager().apply(app, mode, persist=persist)


def ensure_theme(app: QApplication | None = None) -> str:
    """Apply the saved/system theme once (no-op when already applied)."""
    m = manager()
    if m._style is None:
        return m.apply(app, m.saved_mode())
    return m.scheme


def bind_icon(target: QObject, name: str, role: str = "text_muted", checked_role: str | None = None):
    return manager().bind_icon(target, name, role, checked_role)


def set_primary(widget: QWidget, primary: bool = True) -> QWidget:
    """Mark a button as the primary action (accent fill)."""
    widget.setProperty("primary", primary)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


def icon_size(px: int = 16) -> QSize:
    return QSize(px, px)
