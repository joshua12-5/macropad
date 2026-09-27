"""Center device view: a drawn macropad (OLED, encoder knob, 3×4 keycaps).

Each keycap shows its action's short legend; the four encoder slots sit in a
strip under the device. Clicking a cap, the knob or a slot selects it and
emits :pyattr:`PadPreview.selection_changed` (``"key", 1..12`` or
``"encoder", "ccw" | "cw" | "press"``). Arrow keys move the selection.
Purely presentational: the profile is only read.

The profile format still has an ``encoder.long_press`` slot, but holding the
knob opens the on-device menu (firmware 0.26+), so the slot is reserved and
not shown here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..animation import font5x7
from ..models.macro import BUILTIN_MACRO_NAMES, macro_names
from ..models.profile import Profile
from ..ui import theme
from .action_editor import MOD_LABELS, TEXT_LABELS

# Editable encoder slots, left to right in the strip under the device. ``long_press``
# stays in the profile / blob format but is reserved (hold = on-device menu).
ENCODER_SLOTS = ("ccw", "cw", "press")
ENCODER_SLOT_LABELS = {"ccw": "Turn left", "cw": "Turn right", "press": "Press"}
ENCODER_SLOT_ICONS = {"ccw": "rotate-ccw", "cw": "rotate-cw", "press": "circle-dot"}
# Keycap column under/over each encoder chip for arrow-key navigation.
_CHIP_COL = {"ccw": 0, "cw": 1, "press": 3}
_COL_CHIP = ("ccw", "cw", "cw", "press")

_KEY_NAMES = {
    "ENTER": "Enter",
    "SPACE": "Space",
    "TAB": "Tab",
    "ESC": "Esc",
    "BACKSPACE": "Bksp",
    "DELETE": "Del",
    "UP": "↑",
    "DOWN": "↓",
    "LEFT": "←",
    "RIGHT": "→",
}
_MOD_NAMES = MOD_LABELS
_MEDIA = {
    "PLAY_PAUSE": ("play", "Play/Pause"),
    "NEXT": ("skip-forward", "Next"),
    "PREV": ("skip-back", "Previous"),
    "STOP": ("square", "Stop"),
    "MUTE": ("volume-x", "Mute"),
    "SCAN_NEXT": ("fast-forward", "Scan fwd"),
    "SCAN_PREV": ("rewind", "Scan back"),
    "VOLUME_UP": ("volume-2", "Volume +"),
    "VOLUME_DOWN": ("volume-1", "Volume −"),
}
_VOLUME = {"up": ("volume-2", "Volume +"), "down": ("volume-1", "Volume −"), "mute": ("volume-x", "Mute")}


@dataclass(frozen=True)
class Legend:
    primary: str
    secondary: str = ""
    icon: str | None = None
    disabled: bool = False


def _key_legend(key: str) -> str:
    key = key.strip()
    return _KEY_NAMES.get(key.upper(), key if len(key) <= 1 else key.title() if key.isalpha() else key)


def action_legend(action: dict | None, macros: dict[int, str] | None = None) -> Legend:
    """Short keycap legend for an action dict (primary text / icon + secondary line)."""
    if not action or str(action.get("type", "DISABLED")) == "DISABLED":
        return Legend("—", "", None, True)
    atype = str(action.get("type"))
    if atype == "KEY":
        return Legend(_key_legend(str(action.get("key", "?"))), "Key")
    if atype == "SHORTCUT":
        mods = [_MOD_NAMES.get(str(m).upper(), str(m).title()) for m in (action.get("mods") or [])]
        return Legend(_key_legend(str(action.get("key", "?"))), " + ".join(mods) or "Shortcut")
    if atype == "MACRO":
        mid = action.get("macro_id", "?")
        names = macros if macros is not None else BUILTIN_MACRO_NAMES
        name = names.get(mid) if isinstance(mid, int) else None
        return Legend(name or f"M{mid}", f"Macro {mid}")
    if atype in ("TEXT", "URL", "APP"):
        tid = action.get("text_id", action.get("app_id", 0))
        text = TEXT_LABELS.get(tid, f"#{tid}") if isinstance(tid, int) else f"#{tid}"
        text = text.replace("\\n", " ⏎").strip()
        return Legend(text, {"TEXT": "Text", "URL": "URL", "APP": "App"}[atype] + f" {tid}")
    if atype == "MEDIA":
        code = str(action.get("code", "PLAY_PAUSE")).upper()
        icon_name, label = _MEDIA.get(code, (None, code.title()))
        return Legend(label, "Media", icon_name)
    if atype == "VOLUME":
        icon_name, label = _VOLUME.get(str(action.get("dir", "up")).lower(), (None, "Volume"))
        return Legend(label, "Volume", icon_name)
    if atype == "PROFILE":
        pid = action.get("profile_id") or ""
        slot = action.get("slot", 0)
        return Legend(str(pid) if pid else f"Slot {slot}", f"Profile · slot {slot}")
    return Legend(atype.title(), "")


def action_summary(action: dict | None, macros: dict[int, str] | None = None) -> str:
    """One-line description, e.g. ``Shortcut · Ctrl + Shift + S``."""
    lg = action_legend(action, macros)
    if lg.disabled:
        return "Disabled"
    atype = str((action or {}).get("type", "")).title()
    if atype == "Shortcut":
        return (
            f"Shortcut · {lg.secondary} + {lg.primary}"
            if lg.secondary != "Shortcut"
            else f"Shortcut · {lg.primary}"
        )
    return f"{atype} · {lg.primary}"


def oled_idle_image(title: str) -> QImage:
    """128×64 mono image of the firmware idle screen (MACROPAD + profile title)."""
    img = QImage(128, 64, QImage.Format.Format_Mono)
    img.setColorTable([0xFF000000, 0xFFFFFFFF])
    img.fill(0)

    def draw(y: int, text: str) -> None:
        text = text[:21]
        x = max(0, (128 - len(text) * font5x7.ADVANCE) // 2)
        for ch in text:
            cols = font5x7.glyph(ch)
            for cx, bits in enumerate(cols):
                for cy in range(font5x7.GLYPH_H):
                    if bits >> cy & 1 and 0 <= x + cx < 128:
                        img.setPixel(x + cx, y + cy, 1)
            x += font5x7.ADVANCE

    draw(4, "MACROPAD")
    if title:
        draw(24, title)
    return img


# Base geometry (device-independent units; scaled to the widget).
_P = 22.0  # body padding
_U = 76.0  # keycap
_G = 12.0  # gap
_TOP = 92.0  # OLED / knob row
_ROW_GAP = 20.0
_GRID_W = 4 * _U + 3 * _G
_BODY_W = _GRID_W + 2 * _P
_BODY_H = _P + _TOP + _ROW_GAP + 3 * _U + 2 * _G + _P
_STRIP_GAP = 16.0
_CHIP_H = 52.0
_TOTAL_H = _BODY_H + _STRIP_GAP + _CHIP_H


class PadPreview(QWidget):
    """Drawn macropad; select keys / encoder slots by clicking."""

    # selection_kind: "key" | "encoder", selection_id: int (1-12) or str slot
    selection_changed = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile: Profile | None = None
        self._selected: tuple[str, object] | None = None
        self._hover: tuple[str, object] | None = None
        self._pressed: tuple[str, object] | None = None
        self._oled_title = "—"
        self._oled_img = oled_idle_image("")
        self._macros: dict[int, str] = dict(BUILTIN_MACRO_NAMES)
        self.setObjectName("padPreview")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 420)
        self.setAccessibleName("Macropad layout")
        theme.manager().changed.connect(lambda _s: self.update())
        self.reload_macro_names()

    # -- public API (unchanged) ---------------------------------------------
    def set_profile(self, profile: Profile | None) -> None:
        self._profile = profile
        if profile is None:
            self.set_oled_title("")
            self.clear_selection()
            return
        self.set_oled_title(profile.oled_title)
        self.refresh_captions()
        if self._selected is None:
            return
        kind, sid = self._selected
        if kind == "key":
            self._select_key(int(sid))
        else:
            self._select_encoder(str(sid))

    def refresh_captions(self) -> None:
        self.update()

    def reload_macro_names(self) -> None:
        try:
            names = macro_names()
        except Exception:
            names = {}
        self._macros = names or dict(BUILTIN_MACRO_NAMES)
        self.update()

    def set_oled_title(self, title: str) -> None:
        self._oled_title = title or "—"
        self._oled_img = oled_idle_image(title or "")
        self.update()

    def selection(self) -> tuple[str, object] | None:
        return self._selected

    def legend_for(self, kind: str, sid: object) -> Legend:
        return action_legend(self._action(kind, sid), self._macros)

    def clear_selection(self) -> None:
        self._selected = None
        self.update()
        self.selection_changed.emit("", None)

    def select(self, kind: str, sid: object) -> None:
        """Select ``("key", 1..12)`` or ``("encoder", slot)`` (command palette, tests)."""
        if kind == "key":
            self._select_key(int(sid))
        elif kind == "encoder" and str(sid) in ENCODER_SLOTS:
            self._select_encoder(str(sid))
        else:
            self.clear_selection()

    def _select_key(self, num: int) -> None:
        self._selected = ("key", int(num))
        self.update()
        self.selection_changed.emit("key", int(num))

    def _select_encoder(self, slot: str) -> None:
        self._selected = ("encoder", slot)
        self.update()
        self.selection_changed.emit("encoder", slot)

    # -- geometry ---------------------------------------------------------------
    def sizeHint(self) -> QSize:
        return QSize(int(_BODY_W * 1.3), int(_TOTAL_H * 1.3))

    def _layout(self) -> tuple[float, QPointF]:
        margin = 24.0
        w = max(1.0, self.width() - 2 * margin)
        h = max(1.0, self.height() - 2 * margin)
        s = max(0.55, min(w / _BODY_W, h / _TOTAL_H, 1.9))
        ox = (self.width() - _BODY_W * s) / 2
        oy = (self.height() - _TOTAL_H * s) / 2
        return s, QPointF(ox, oy)

    def _r(self, x: float, y: float, w: float, h: float) -> QRectF:
        s, o = self._layout()
        return QRectF(o.x() + x * s, o.y() + y * s, w * s, h * s)

    def _body_rect(self) -> QRectF:
        return self._r(0, 0, _BODY_W, _BODY_H)

    def _oled_rect(self) -> QRectF:
        return self._r(_P, _P, 3 * _U + 2 * _G, _TOP)

    def _knob_rect(self) -> QRectF:
        d = 70.0
        cx = _P + 3 * (_U + _G) + _U / 2
        cy = _P + _TOP / 2
        return self._r(cx - d / 2, cy - d / 2, d, d)

    def _key_rect(self, num: int) -> QRectF:
        row, col = divmod(num - 1, 4)
        x = _P + col * (_U + _G)
        y = _P + _TOP + _ROW_GAP + row * (_U + _G)
        return self._r(x, y, _U, _U)

    def _chip_rect(self, slot: str) -> QRectF:
        i = ENCODER_SLOTS.index(slot)
        n = len(ENCODER_SLOTS)
        gap = 8.0
        w = (_BODY_W - (n - 1) * gap) / n
        return self._r(i * (w + gap), _BODY_H + _STRIP_GAP, w, _CHIP_H)

    def _hit(self, pos: QPointF) -> tuple[str, object] | None:
        for num in range(1, 13):
            if self._key_rect(num).contains(pos):
                return ("key", num)
        kr = self._knob_rect()
        c = kr.center()
        if (pos.x() - c.x()) ** 2 + (pos.y() - c.y()) ** 2 <= (kr.width() / 2 + 4) ** 2:
            return ("knob", None)
        for slot in ENCODER_SLOTS:
            if self._chip_rect(slot).contains(pos):
                return ("encoder", slot)
        return None

    # -- model helpers -------------------------------------------------------------
    def _action(self, kind: str, sid: object) -> dict | None:
        if self._profile is None:
            return None
        if kind == "key":
            return self._profile.action_for_key(int(sid))
        return self._profile.action_for_encoder(str(sid))

    # -- events ------------------------------------------------------------------------
    def mouseMoveEvent(self, ev) -> None:
        hit = self._hit(ev.position())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _ev) -> None:
        self._hover = None
        self._pressed = None
        self.update()

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        self._pressed = self._hit(ev.position())
        self.update()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._hit(ev.position())
        pressed, self._pressed = self._pressed, None
        if hit is not None and hit == pressed:
            kind, sid = hit
            if kind == "key":
                self._select_key(int(sid))
            elif kind == "knob":
                cur = self._selected
                slot = str(cur[1]) if cur and cur[0] == "encoder" else "press"
                self._select_encoder(slot)
            else:
                self._select_encoder(str(sid))
        self.update()

    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        moves = {
            Qt.Key.Key_Left: (0, -1),
            Qt.Key.Key_Right: (0, 1),
            Qt.Key.Key_Up: (-1, 0),
            Qt.Key.Key_Down: (1, 0),
        }
        if key not in moves or self._profile is None:
            super().keyPressEvent(ev)
            return
        dr, dc = moves[key]
        cur = self._selected
        if cur is None:
            self._select_key(1)
            return
        if cur[0] == "key":
            row, col = divmod(int(cur[1]) - 1, 4)
            if row == 0 and dr == -1:
                self._select_encoder("press" if col == 3 else "ccw")
                return
            if row == 2 and dr == 1:
                self._select_encoder(_COL_CHIP[col])
                return
            row = min(2, max(0, row + dr))
            col = min(3, max(0, col + dc))
            self._select_key(row * 4 + col + 1)
        else:
            i = ENCODER_SLOTS.index(str(cur[1]))
            if dc:
                self._select_encoder(ENCODER_SLOTS[min(len(ENCODER_SLOTS) - 1, max(0, i + dc))])
            elif dr == -1:
                self._select_key(9 + _CHIP_COL[ENCODER_SLOTS[i]])

    def event(self, ev) -> bool:
        if ev.type() == ev.Type.ToolTip:
            hit = self._hit(QPointF(ev.pos()))
            if hit is None or self._profile is None:
                QToolTip.hideText()
                ev.ignore()
                return True
            kind, sid = hit
            if kind == "key":
                name = f"Key {sid}"
            elif kind == "knob":
                name, kind, sid = "Encoder · press", "encoder", "press"
            else:
                name = f"Encoder · {ENCODER_SLOT_LABELS[str(sid)].lower()}"
            QToolTip.showText(
                ev.globalPos(), f"{name}\n{action_summary(self._action(kind, sid), self._macros)}", self
            )
            return True
        return super().event(ev)

    # -- painting ------------------------------------------------------------------------
    def paintEvent(self, _ev) -> None:
        pal = theme.palette()
        c = {k: theme.qcolor(v) for k, v in pal.items()}
        s, _ = self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Body plate
        body = self._body_rect().adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(c["device_edge"], 1))
        p.setBrush(c["device_body"])
        p.drawRoundedRect(body, 14 * s, 14 * s)

        self._paint_oled(p, c, s)
        self._paint_knob(p, c, s)
        for num in range(1, 13):
            self._paint_cap(p, c, s, num)
        for slot in ENCODER_SLOTS:
            self._paint_chip(p, c, s, slot)
        p.end()

    def _font(self, px: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(max(8, round(px)))
        f.setWeight(weight)
        return f

    def _paint_oled(self, p: QPainter, c: dict, s: float) -> None:
        bezel = self._oled_rect()
        p.setPen(QPen(c["device_edge"], 1))
        p.setBrush(c["oled_bg"])
        p.drawRoundedRect(bezel.adjusted(0.5, 0.5, -0.5, -0.5), 6 * s, 6 * s)
        # Integer physical scale keeps the 128×64 pixels crisp.
        dpr = self.devicePixelRatioF()
        avail_w = (bezel.width() - 16 * s) * dpr
        avail_h = (bezel.height() - 12 * s) * dpr
        k = max(1, int(min(avail_w / 128, avail_h / 64)))
        w, h = 128 * k / dpr, 64 * k / dpr
        target = QRectF(bezel.center().x() - w / 2, bezel.center().y() - h / 2, w, h)
        target.moveTo(round(target.x() * dpr) / dpr, round(target.y() * dpr) / dpr)
        img = QImage(self._oled_img)
        img.setColorTable([c["oled_bg"].rgba(), c["oled_fg"].rgba()])
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(target, img)
        p.restore()

    def _paint_knob(self, p: QPainter, c: dict, s: float) -> None:
        r = self._knob_rect()
        sel = self._selected is not None and self._selected[0] == "encoder"
        hover = self._hover is not None and self._hover[0] == "knob"
        if sel:
            p.setPen(QPen(c["accent"], max(1.5, 2 * s)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(-5 * s, -5 * s, 5 * s, 5 * s))
        p.setPen(QPen(c["border_hover"] if hover else c["knob_edge"], 1))
        p.setBrush(c["knob"])
        p.drawEllipse(r)
        # knurling
        center = r.center()
        rad = r.width() / 2
        p.setPen(QPen(c["knob_edge"], max(1.0, 1.2 * s)))
        for i in range(36):
            a = 2 * math.pi * i / 36
            p.drawLine(
                QPointF(center.x() + math.cos(a) * rad * 0.86, center.y() + math.sin(a) * rad * 0.86),
                QPointF(center.x() + math.cos(a) * rad * 0.96, center.y() + math.sin(a) * rad * 0.96),
            )
        inner = QRectF(center.x() - rad * 0.72, center.y() - rad * 0.72, rad * 1.44, rad * 1.44)
        p.setPen(QPen(c["knob_edge"], 1))
        p.setBrush(c["cap_top_hover"] if hover else c["cap_top"])
        p.drawEllipse(inner)
        # indicator
        p.setPen(
            QPen(
                c["accent"] if sel else c["text_muted"],
                max(2.0, 2.4 * s),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        p.drawLine(QPointF(center.x(), center.y() - rad * 0.58), QPointF(center.x(), center.y() - rad * 0.30))

    def _paint_cap(self, p: QPainter, c: dict, s: float, num: int) -> None:
        rect = self._key_rect(num)
        me = ("key", num)
        sel = self._selected == me
        hover = self._hover == me
        pressed = self._pressed == me and hover
        if sel:
            p.setPen(QPen(c["accent"], max(1.5, 2 * s)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(-4 * s, -4 * s, 4 * s, 4 * s), 11 * s, 11 * s)
        p.setPen(QPen(c["cap_edge"], 1))
        p.setBrush(c["cap_skirt"])
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 8 * s, 8 * s)
        dy = 1.5 * s if pressed else 0.0
        top = rect.adjusted(5 * s, 4 * s + dy, -5 * s, -8 * s + dy)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c["cap_top_hover"] if hover else c["cap_top"])
        p.drawRoundedRect(top, 6 * s, 6 * s)

        legend = action_legend(self._action("key", num), self._macros)
        # key number, top-left
        p.setFont(self._font(10 * s))
        p.setPen(c["text_faint"])
        p.drawText(
            top.adjusted(7 * s, 5 * s, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, str(num)
        )
        self._paint_legend(p, c, s, top, legend, size=15)

    def _paint_legend(
        self, p: QPainter, c: dict, s: float, box: QRectF, lg: Legend, *, size: float, top_pad: float = 6
    ) -> None:
        inner = box.adjusted(6 * s, top_pad * s, -6 * s, -4 * s)
        sec_h = 13 * s if lg.secondary else 0
        main = QRectF(inner.left(), inner.top(), inner.width(), inner.height() - sec_h)
        if lg.icon:
            d = size * 1.35 * s
            icon_rect = QRectF(main.center().x() - d / 2, main.center().y() - d / 2 + 2 * s, d, d)
            pix = theme.render_icon(
                lg.icon, theme.palette()["cap_legend"], max(8, round(d)), self.devicePixelRatioF()
            )
            p.drawPixmap(icon_rect.toRect(), pix)
        else:
            f = self._font(size * s * (0.82 if len(lg.primary) > 5 else 1.0), QFont.Weight.DemiBold)
            fm = QFontMetrics(f)
            text = fm.elidedText(lg.primary, Qt.TextElideMode.ElideRight, int(main.width()))
            p.setFont(f)
            p.setPen(c["text_faint"] if lg.disabled else c["cap_legend"])
            p.drawText(main.adjusted(0, 2 * s, 0, 0), Qt.AlignmentFlag.AlignCenter, text)
        if lg.secondary:
            f2 = self._font(10 * s)
            fm2 = QFontMetrics(f2)
            p.setFont(f2)
            p.setPen(c["text_muted"])
            sec = QRectF(inner.left(), inner.bottom() - sec_h, inner.width(), sec_h)
            p.drawText(
                sec,
                Qt.AlignmentFlag.AlignCenter,
                fm2.elidedText(lg.secondary, Qt.TextElideMode.ElideRight, int(sec.width())),
            )

    def _paint_chip(self, p: QPainter, c: dict, s: float, slot: str) -> None:
        rect = self._chip_rect(slot)
        me = ("encoder", slot)
        sel = self._selected == me
        hover = self._hover == me or (
            self._hover is not None and self._hover[0] == "knob" and slot == "press"
        )
        if sel:
            p.setPen(QPen(c["accent"], max(1.5, 2 * s)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(-3 * s, -3 * s, 3 * s, 3 * s), 10 * s, 10 * s)
        p.setPen(QPen(c["border_hover"] if hover else c["border_strong"], 1))
        p.setBrush(c["hover"] if hover else c["raised"])
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 8 * s, 8 * s)

        lg = action_legend(self._action("encoder", slot), self._macros)
        pad = 10 * s
        # caption row: slot icon + name
        cap_font = self._font(10 * s)
        p.setFont(cap_font)
        isz = max(8, round(12 * s))
        pix = theme.render_icon(
            ENCODER_SLOT_ICONS[slot], theme.palette()["text_faint"], isz, self.devicePixelRatioF()
        )
        p.drawPixmap(QPointF(rect.left() + pad, rect.top() + 9 * s), pix)
        p.setPen(c["text_muted"])
        p.drawText(
            QRectF(rect.left() + pad + isz + 5 * s, rect.top() + 7 * s, rect.width() - 2 * pad - isz, 16 * s),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            ENCODER_SLOT_LABELS[slot],
        )
        # value row
        vf = self._font(12.5 * s, QFont.Weight.DemiBold)
        fm = QFontMetrics(vf)
        text = lg.primary
        p.setFont(vf)
        p.setPen(c["text_faint"] if lg.disabled else c["text"])
        p.drawText(
            QRectF(rect.left() + pad, rect.top() + 26 * s, rect.width() - 2 * pad, 18 * s),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width() - 2 * pad)),
        )
