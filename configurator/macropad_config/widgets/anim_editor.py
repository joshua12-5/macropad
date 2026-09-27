"""Tools → Idle animation… — OLED idle-animation editor.

Author 128x64 1bpp animations for the macropad's SSD1306:

* frame strip with thumbnails (add / duplicate / delete / reorder, drag to move);
* pixel canvas: pen / eraser (right mouse = opposite), brush size, invert,
  clear, shift (wraps), onion skin of the previous frame, grid, undo/redo;
* live preview at the chosen fps, loop flag;
* presets (starfield, bouncing text, scrolling text, pulse) generated in Python;
* import GIF / PNG sequence / single image with fit + threshold or
  Floyd–Steinberg dithering + invert (live preview);
* project files (*.mpanim.json) in the user data folder, GIF / .mpan export;
* device: upload (progress), read back, preview on device, idle settings.
  Device actions are gated on GET_INFO flag bit3 (firmware 0.25+).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from .. import version as app_version
from ..animation import codec as A
from ..animation import presets as P
from ..animation.gifwriter import write_oled_gif
from ..animation.project import SUFFIX, AnimationProject, ProjectError, animations_dir, blob_name
from ..ui import theme
from ..ui.theme import set_primary
from ..ui.widgets import dialog_margins, divider, icon_button, label, style_form

OLED_ON = QColor(0xE6, 0xF3, 0xFF)
OLED_OFF = QColor(0x06, 0x08, 0x0E)
ONION = QColor(0x6A, 0x43, 0x1E)  # dimmed accent: previous frame
GRID = QColor(0x1A, 0x1B, 0x1E)
PAGE_LINE = QColor(0x33, 0x34, 0x39)
W, H = A.WIDTH, A.HEIGHT
UNDO_LIMIT = 60


def frame_qimage(frame: bytes, onion: Optional[bytes] = None) -> QImage:
    """Page-order frame → 128x64 indexed QImage (0 off, 1 on, 2 onion)."""
    bits = A.frame_to_bits(frame)
    if onion is not None:
        ob = A.frame_to_bits(onion)
        data = bytes(b if b else (2 if o else 0) for b, o in zip(bits, ob, strict=True))
    else:
        data = bytes(bits)
    img = QImage(data, W, H, W, QImage.Format_Indexed8)
    img.setColorTable([OLED_OFF.rgb(), OLED_ON.rgb(), ONION.rgb()])
    return img.copy()  # detach from the Python buffer


def frame_pixmap(frame: bytes, scale: int = 1) -> QPixmap:
    img = frame_qimage(frame)
    if scale != 1:
        img = img.scaled(W * scale, H * scale, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    return QPixmap.fromImage(img)


# --------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------


class OledView(QWidget):
    """Static OLED look-alike showing one frame (bezel + pixels)."""

    def __init__(self, scale: int = 2, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._img: Optional[QImage] = None
        self.setFixedSize(W * scale + 16, H * scale + 16)

    def set_frame(self, frame: Optional[bytes]) -> None:
        self._img = frame_qimage(frame) if frame is not None else None
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(theme.color("device_edge"), 1))
        p.setBrush(theme.color("device_body"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.setRenderHint(QPainter.Antialiasing, False)
        target = self.rect().adjusted(8, 8, -8, -8)
        p.fillRect(target, OLED_OFF)
        if self._img is not None:
            p.drawImage(target, self._img)
        p.end()


class _FrameDelegate(QStyledItemDelegate):
    """Frame strip row: number gutter + framed 128×64 thumbnail."""

    GUTTER = 28

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(self.GUTTER + W + 16, H + 12)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        pal = theme.palette()
        c = {k: theme.qcolor(v) for k, v in pal.items()}
        r = QRectF(option.rect).adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if selected or hover:
            p.setPen(Qt.NoPen)
            p.setBrush(c["selected"] if selected else c["hover"])
            p.drawRoundedRect(r, 6, 6)
        num = QRectF(r.left(), r.top(), self.GUTTER - 6, r.height())
        f = QFont(option.font)
        f.setPixelSize(theme.FONT_PX["caption"])
        f.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(c["text"] if selected else c["text_faint"])
        p.drawText(num, Qt.AlignRight | Qt.AlignVCenter, str(index.row() + 1))
        thumb = QRectF(r.left() + self.GUTTER, r.center().y() - H / 2, W, H)
        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon):
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            p.drawPixmap(thumb.toRect(), icon.pixmap(QSize(W, H)))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(c["accent"] if selected else c["border_strong"], 1.5 if selected else 1))
        p.drawRoundedRect(thumb.adjusted(-1.5, -1.5, 1.5, 1.5), 3, 3)
        p.restore()


class PixelCanvas(QWidget):
    """Zoomed 128x64 pixel editor operating on a page-order frame."""

    strokeStarted = Signal()
    edited = Signal()
    hover = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame = A.blank_frame()
        self._onion: Optional[bytes] = None
        self._zoom = 6
        self._grid = True
        self._tool_draw = True
        self._brush = 1
        self._stroke_value: Optional[bool] = None
        self._last: Optional[tuple[int, int]] = None
        self._img: Optional[QImage] = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self._resize()

    # -- api -----------------------------------------------------------------
    def set_frame(self, frame: bytes, onion: Optional[bytes] = None) -> None:
        self._frame = bytearray(frame)
        self._onion = bytes(onion) if onion is not None else None
        self._refresh()

    def frame(self) -> bytes:
        return bytes(self._frame)

    def set_zoom(self, z: int) -> None:
        self._zoom = max(2, min(12, int(z)))
        self._resize()
        self.update()

    def set_grid(self, on: bool) -> None:
        self._grid = bool(on)
        self.update()

    def set_draw_mode(self, draw: bool) -> None:
        self._tool_draw = bool(draw)

    def set_brush(self, n: int) -> None:
        self._brush = max(1, min(8, int(n)))

    def _resize(self) -> None:
        self.setFixedSize(W * self._zoom + 1, H * self._zoom + 1)

    def _refresh(self) -> None:
        self._img = frame_qimage(bytes(self._frame), self._onion)
        self.update()

    # -- painting --------------------------------------------------------------
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        z = self._zoom
        if self._img is None:
            self._refresh()
        p.drawImage(self.rect().adjusted(0, 0, -1, -1), self._img)
        if self._grid and z >= 4:
            p.setPen(QPen(GRID, 1))
            for x in range(0, W + 1):
                if x % 8:
                    p.drawLine(x * z, 0, x * z, H * z)
            for y in range(0, H + 1):
                if y % 8:
                    p.drawLine(0, y * z, W * z, y * z)
            p.setPen(QPen(PAGE_LINE, 1))
            for x in range(0, W + 1, 8):
                p.drawLine(x * z, 0, x * z, H * z)
            for y in range(0, H + 1, 8):
                p.drawLine(0, y * z, W * z, y * z)
        p.end()

    # -- mouse -------------------------------------------------------------------
    def _cell(self, ev) -> tuple[int, int]:
        pos = ev.position()
        return int(pos.x()) // self._zoom, int(pos.y()) // self._zoom

    def _plot(self, x: int, y: int, on: bool) -> None:
        b = self._brush
        off = (b - 1) // 2
        for dy in range(b):
            for dx in range(b):
                A.set_pixel(self._frame, x - off + dx, y - off + dy, on)

    def _line(self, x0: int, y0: int, x1: int, y1: int, on: bool) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self._plot(x0, y0, on)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def mousePressEvent(self, ev) -> None:
        if ev.button() not in (Qt.LeftButton, Qt.RightButton):
            return
        self.strokeStarted.emit()
        draw = self._tool_draw
        if ev.button() == Qt.RightButton:
            draw = not draw
        self._stroke_value = draw
        x, y = self._cell(ev)
        self._plot(x, y, draw)
        self._last = (x, y)
        self._refresh()

    def mouseMoveEvent(self, ev) -> None:
        x, y = self._cell(ev)
        if 0 <= x < W and 0 <= y < H:
            self.hover.emit(x, y)
        if self._stroke_value is None or self._last is None:
            return
        self._line(self._last[0], self._last[1], x, y, self._stroke_value)
        self._last = (x, y)
        self._refresh()

    def mouseReleaseEvent(self, _ev) -> None:
        if self._stroke_value is not None:
            self._stroke_value = None
            self._last = None
            self.edited.emit()


# --------------------------------------------------------------------------
# Import dialog
# --------------------------------------------------------------------------


class ImportDialog(QDialog):
    """Preview + options for GIF / image / sequence import."""

    def __init__(self, paths: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from ..animation import imaging as IM

        self._IM = IM
        self.setWindowTitle("Import images → OLED frames")
        self._paths = list(paths)
        if len(paths) == 1:
            self._images, self.fps_guess = IM.read_image_frames(paths[0])
        else:
            self._images, self.fps_guess = [], None
            for pth in IM.sort_sequence(paths):
                self._images.append(IM.read_image_frames(pth)[0][0])
        self._gray_cache: dict = {}

        lay = dialog_margins(QVBoxLayout(self))
        src = Path(paths[0]).name + (f" (+{len(paths) - 1} more)" if len(paths) > 1 else "")
        size = self._images[0].size()
        info = QLabel(
            f"<b>{src}</b> — {len(self._images)} frame(s), {size.width()}×{size.height()} px"
            + (f", ~{self.fps_guess} fps" if self.fps_guess else "")
        )
        lay.addWidget(info)

        row = QHBoxLayout()
        self._src_view = QLabel()
        self._src_view.setFixedSize(W * 2 + 16, H * 2 + 16)
        self._src_view.setAlignment(Qt.AlignCenter)
        self._src_view.setObjectName("imagePreview")
        self._view = OledView(2)
        row.addWidget(self._labeled("Source", self._src_view))
        row.addWidget(self._labeled("OLED result", self._view))
        lay.addLayout(row)

        self._scrub = QSlider(Qt.Horizontal)
        self._scrub.setRange(0, len(self._images) - 1)
        self._scrub.setEnabled(len(self._images) > 1)
        self._scrub.valueChanged.connect(self._update_preview)
        lay.addWidget(self._scrub)

        form = QFormLayout()
        self._dither = QComboBox()
        self._dither.addItem("Floyd–Steinberg dithering", IM.DITHER_FLOYD)
        self._dither.addItem("Threshold", IM.DITHER_THRESHOLD)
        self._dither.currentIndexChanged.connect(self._opts_changed)
        form.addRow("Conversion", self._dither)
        th_row = QHBoxLayout()
        self._threshold = QSlider(Qt.Horizontal)
        self._threshold.setRange(1, 254)
        self._threshold.setValue(128)
        self._threshold_lbl = QLabel("128")
        self._threshold.valueChanged.connect(
            lambda v: (self._threshold_lbl.setText(str(v)), self._opts_changed())
        )
        th_row.addWidget(self._threshold)
        th_row.addWidget(self._threshold_lbl)
        form.addRow("Threshold", th_row)
        self._fit = QComboBox()
        self._fit.addItem("Fit (keep aspect, centred)", "contain")
        self._fit.addItem("Stretch to 128×64", "stretch")
        self._fit.currentIndexChanged.connect(self._opts_changed)
        form.addRow("Resize", self._fit)
        self._invert = QCheckBox("Invert (light background artwork)")
        self._invert.toggled.connect(self._opts_changed)
        form.addRow("", self._invert)
        self._bg_white = QCheckBox("Transparent areas are white")
        self._bg_white.toggled.connect(self._opts_changed)
        form.addRow("", self._bg_white)
        mode_row = QHBoxLayout()
        self._mode_replace = QRadioButton("Replace all frames")
        self._mode_append = QRadioButton("Append")
        self._mode_insert = QRadioButton("Insert after current")
        self._mode_replace.setChecked(True)
        for b in (self._mode_replace, self._mode_append, self._mode_insert):
            mode_row.addWidget(b)
        form.addRow("Mode", mode_row)
        self._use_fps = QCheckBox(
            "Use the GIF's frame rate" + (f" ({self.fps_guess} fps)" if self.fps_guess else "")
        )
        self._use_fps.setChecked(bool(self.fps_guess))
        self._use_fps.setEnabled(bool(self.fps_guess))
        form.addRow("", self._use_fps)
        style_form(form)
        lay.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(f"Import {len(self._images)} frame(s)")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._opts_changed()

    @staticmethod
    def _labeled(title: str, w: QWidget) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.SPACE["xs"])
        v.addWidget(label(title, "formLabel"))
        v.addWidget(w)
        return box

    def options(self):
        return self._IM.ImportOptions(
            dither=self._dither.currentData(),
            threshold=self._threshold.value(),
            invert=self._invert.isChecked(),
            fit=self._fit.currentData(),
            background_white=self._bg_white.isChecked(),
        )

    def _opts_changed(self, *_a) -> None:
        self._threshold.setEnabled(self._dither.currentData() == self._IM.DITHER_THRESHOLD)
        self._gray_cache.clear()
        self._update_preview()

    def _gray(self, i: int):
        o = self.options()
        key = (i, o.fit, o.background_white)
        if key not in self._gray_cache:
            self._gray_cache[key] = self._IM.image_to_gray(self._images[i], o)
        return self._gray_cache[key]

    def _update_preview(self, *_a) -> None:
        i = self._scrub.value()
        img = self._images[i]
        self._src_view.setPixmap(
            QPixmap.fromImage(img).scaled(W * 2, H * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self._view.set_frame(self._IM.gray_to_frame(self._gray(i), self.options()))

    @property
    def mode(self) -> str:
        if self._mode_append.isChecked():
            return "append"
        if self._mode_insert.isChecked():
            return "insert"
        return "replace"

    @property
    def use_fps(self) -> bool:
        return self._use_fps.isChecked() and bool(self.fps_guess)

    def frames(self) -> list[bytes]:
        o = self.options()
        return [self._IM.gray_to_frame(self._gray(i), o) for i in range(len(self._images))]


# --------------------------------------------------------------------------
# Main editor dialog
# --------------------------------------------------------------------------


def _default_device_factory():
    from ..protocol.device import ConfigDevice

    return ConfigDevice(timeout_ms=3000)


class AnimationEditorDialog(QDialog):
    """Idle-animation editor: the Idle animation page (``embedded=True``) or a dialog."""

    dirtyChanged = Signal(bool)
    projectChanged = Signal(str)  # file name ("untitled" when unsaved)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        device_factory: Optional[Callable[[], object]] = None,
        device_info: Optional[dict] = None,
        embedded: bool = False,
    ) -> None:
        super().__init__(parent)
        self._embedded = embedded
        self._dirty = False
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setObjectName("animPage")
        self.setWindowTitle("Idle animation editor")
        self._device_factory = device_factory or _default_device_factory
        self._device_info = device_info
        self.frames: list[bytearray] = [A.blank_frame()]
        self.cur = 0
        self.path: Optional[Path] = None
        self.dirty = False
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._play_idx = 0
        self._playing = False
        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.setInterval(250)
        self._stats_timer.timeout.connect(self._update_stats)
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._play_tick)
        self._build()
        self._load_project(AnimationProject(), mark_clean=True)

    # ======================================================================
    # UI
    # ======================================================================
    @property
    def dirty(self) -> bool:
        return self._dirty

    @dirty.setter
    def dirty(self, value: bool) -> None:
        value = bool(value)
        if value != self._dirty:
            self._dirty = value
            self.dirtyChanged.emit(value)

    def is_dirty(self) -> bool:
        return self._dirty

    def project_name(self) -> str:
        return self.path.name if self.path else "untitled"

    def set_device_info(self, info: Optional[dict]) -> None:
        """Latest GET_INFO from the main window (device actions still re-check on use)."""
        self._device_info = info
        if info and not app_version.fw_supports_anim(info.get("fw_major"), info.get("fw_minor")):
            self.dev_status.setText(
                app_version.feature_disabled_tooltip("Idle animation upload", app_version.MIN_FW_MINOR_ANIM)
            )

    def _set_zoom(self, z: int) -> None:
        self._setting_zoom = True
        try:
            self.zoom.setValue(int(z))
        finally:
            self._setting_zoom = False

    def _on_zoom_changed(self, _z: int) -> None:
        if not self._setting_zoom:
            self._zoom_auto = False

    def fit_zoom(self, avail_w: int, avail_h: int) -> None:
        """Page mode: pick the largest canvas zoom (2–8) that fits *avail* without scrolling."""
        if not self._zoom_auto:
            return
        minh = self.minimumSizeHint()
        over_w = minh.width() - self._center_layout.minimumSize().width()
        over_h = minh.height() - self.canvas.height()
        z = min((avail_w - over_w - 1) // W, (avail_h - over_h - 1) // H)
        z = max(2, min(8, z))
        if z != self.zoom.value():
            self._set_zoom(z)

    def maybe_save(self) -> bool:
        """Ask to save unsaved edits; False when the user cancels."""
        return self._maybe_save()

    def _build(self) -> None:
        S = theme.SPACE
        root = QVBoxLayout(self)
        if self._embedded:
            root.setContentsMargins(S["lg"], S["md"], S["lg"], S["md"])
        else:
            root.setContentsMargins(S["lg"], S["lg"], S["lg"], S["md"])
        root.setSpacing(S["md"])
        body = QHBoxLayout()
        body.setSpacing(S["md"] if self._embedded else S["lg"])
        root.addLayout(body, 1)

        # ---- frame strip ----------------------------------------------------
        left = QVBoxLayout()
        left.setSpacing(S["sm"])
        left.addWidget(label("Frames", "sectionTitle"))
        self.frame_list = QListWidget()
        self.frame_list.setObjectName("frameStrip")
        self.frame_list.setIconSize(QSize(W, H))
        self.frame_list.setViewMode(QListWidget.ListMode)
        self.frame_list.setItemDelegate(_FrameDelegate(self.frame_list))
        self.frame_list.setUniformItemSizes(True)
        self.frame_list.setFixedWidth(W + 72)
        self.frame_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.frame_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.frame_list.setDefaultDropAction(Qt.MoveAction)
        self.frame_list.currentRowChanged.connect(self._on_row_changed)
        self.frame_list.model().rowsMoved.connect(self._on_rows_moved)
        left.addWidget(self.frame_list, 1)
        frame_btns = QHBoxLayout()
        frame_btns.setSpacing(2)
        self.btn_add = icon_button("plus", "Insert a blank frame after the current one")
        self.btn_dup = icon_button("copy", "Duplicate the current frame (Ctrl+D)")
        self.btn_del = icon_button("trash", "Delete the current frame")
        self.btn_up = icon_button("arrow-up", "Move the frame earlier")
        self.btn_down = icon_button("arrow-down", "Move the frame later")
        self.btn_add.clicked.connect(self.add_frame)
        self.btn_dup.clicked.connect(self.duplicate_frame)
        self.btn_del.clicked.connect(self.delete_frame)
        self.btn_up.clicked.connect(lambda: self.move_frame(-1))
        self.btn_down.clicked.connect(lambda: self.move_frame(1))
        for b in (self.btn_add, self.btn_dup, self.btn_del):
            frame_btns.addWidget(b)
        frame_btns.addStretch(1)
        frame_btns.addWidget(self.btn_up)
        frame_btns.addWidget(self.btn_down)
        left.addLayout(frame_btns)
        body.addLayout(left)
        body.addWidget(divider(vertical=True))

        # ---- canvas + tools --------------------------------------------------
        center = QVBoxLayout()
        center.setSpacing(S["sm"])
        self._center_layout = center
        tools = QHBoxLayout()
        tools.setSpacing(S["xs"])
        gap = S["xs"] if self._embedded else S["sm"]
        self.tool_pen = icon_button(
            "pencil", "Draw (P). Right mouse button erases.", text="Pen", checkable=True
        )
        self.tool_erase = icon_button(
            "eraser", "Erase (E). Right mouse button draws.", text="Eraser", checkable=True
        )
        self.tool_pen.setChecked(True)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(self.tool_pen)
        grp.addButton(self.tool_erase)
        self.tool_pen.toggled.connect(lambda on: self.canvas.set_draw_mode(on))
        tools.addWidget(self.tool_pen)
        tools.addWidget(self.tool_erase)
        tools.addSpacing(gap)
        tools.addWidget(label("Brush", "formLabel"))
        self.brush = QSpinBox()
        self.brush.setRange(1, 8)
        self.brush.setSuffix(" px")
        tools.addWidget(self.brush)
        tools.addSpacing(gap)
        tools.addWidget(divider(vertical=True))
        tools.addSpacing(gap)
        self.btn_invert = icon_button("contrast", "Invert the frame (I)", text="Invert")
        self.btn_clear = icon_button("x", "Clear the frame", text="Clear")
        self.btn_invert.clicked.connect(self.invert_frame)
        self.btn_clear.clicked.connect(self.clear_frame)
        tools.addWidget(self.btn_invert)
        tools.addWidget(self.btn_clear)
        tools.addSpacing(gap)
        tools.addWidget(divider(vertical=True))
        tools.addSpacing(gap)
        tools.addWidget(label("Shift", "formLabel"))
        for name, dx, dy, tip in (
            ("arrow-left", -1, 0, "left"),
            ("arrow-right", 1, 0, "right"),
            ("arrow-up", 0, -1, "up"),
            ("arrow-down", 0, 1, "down"),
        ):
            b = icon_button(name, f"Shift frame {tip} by 1 px (wraps around)")
            b.clicked.connect(lambda _=False, a=dx, c=dy: self.shift_frame(a, c))
            tools.addWidget(b)
        tools.addStretch(1)
        if self._embedded:  # compact tool row as a page (names stay in the tooltips)
            for b in (self.tool_pen, self.tool_erase, self.btn_invert, self.btn_clear):
                b.setText("")
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                b.setProperty("textBeside", False)
        self.btn_undo = icon_button("undo-2", "Undo (Ctrl+Z)")
        self.btn_redo = icon_button("redo-2", "Redo (Ctrl+Y)")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo.clicked.connect(self.redo)
        tools.addWidget(self.btn_undo)
        tools.addWidget(self.btn_redo)
        center.addLayout(tools)

        opts = QHBoxLayout()
        opts.setSpacing(S["lg"])
        self.onion = QCheckBox("Onion skin (previous frame)")
        self.onion.setChecked(True)
        self.onion.toggled.connect(lambda _: self._show_current())
        self.grid_cb = QCheckBox("Grid")
        self.grid_cb.setChecked(True)
        self.grid_cb.toggled.connect(lambda on: self.canvas.set_grid(on))
        opts.addWidget(self.onion)
        opts.addWidget(self.grid_cb)
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(S["sm"])
        zoom_row.addWidget(label("Zoom", "formLabel"))
        self.zoom = QSpinBox()
        self.zoom.setRange(2, 12)
        self.zoom.setValue(6)
        self.zoom.setSuffix("×")
        zoom_row.addWidget(self.zoom)
        opts.addLayout(zoom_row)
        opts.addStretch(1)
        center.addLayout(opts)

        self.canvas = PixelCanvas()
        self.canvas.strokeStarted.connect(self._push_undo)
        self.canvas.edited.connect(self._on_canvas_edited)
        self.canvas.hover.connect(
            lambda x, y: self.pos_label.setText(f"x {x:3d}  y {y:2d}  page {y // 8}  byte {x + (y // 8) * W}")
        )
        self.brush.valueChanged.connect(self.canvas.set_brush)
        self.zoom.valueChanged.connect(self.canvas.set_zoom)
        self.zoom.valueChanged.connect(self._on_zoom_changed)
        self._zoom_auto = self._embedded  # page mode: fit the canvas until the user picks a zoom
        self._setting_zoom = False
        if self._embedded:
            self._set_zoom(4)
        center.addSpacing(S["xs"])
        center.addWidget(self.canvas, 0, Qt.AlignLeft | Qt.AlignTop)
        info_row = QHBoxLayout()
        self.frame_label = label("", "hintLabel")
        self.pos_label = label(" ", "monoLabel")
        info_row.addWidget(self.frame_label)
        info_row.addStretch(1)
        info_row.addWidget(self.pos_label)
        center.addLayout(info_row)
        center.addSpacing(S["sm"])
        center.addWidget(divider())
        center.addSpacing(S["xs"])

        center.addWidget(label("Presets & import", "sectionTitle"))
        pl = QGridLayout()
        pl.setHorizontalSpacing(S["sm"])
        pl.setVerticalSpacing(S["sm"])
        self.preset_combo = QComboBox()
        for key, pr in P.PRESETS.items():
            self.preset_combo.addItem(pr.label, key)
        self.preset_text = QLineEdit()
        self.preset_text.setPlaceholderText("Text for text presets")
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        self.btn_preset = QPushButton("Load preset")
        self.btn_preset.clicked.connect(self.load_preset)
        self.btn_import = QPushButton("Import GIF / images…")
        theme.bind_icon(self.btn_import, "image-plus")
        self.btn_import.clicked.connect(self.import_images)
        pl.addWidget(label("Preset", "formLabel"), 0, 0)
        pl.addWidget(self.preset_combo, 0, 1)
        pl.addWidget(self.preset_text, 0, 2)
        pl.addWidget(self.btn_preset, 0, 3)
        pl.addWidget(
            label(
                "GIF, PNG sequence (multi-select) or single image; resized to fit 128×64, threshold or dithering.",
                "hintLabel",
                wrap=True,
            ),
            1,
            1,
            1,
            2,
        )
        pl.addWidget(self.btn_import, 1, 3)
        pl.setColumnStretch(2, 1)
        center.addLayout(pl)
        center.addStretch(1)
        body.addLayout(center, 1)
        body.addWidget(divider(vertical=True))

        # ---- right column: preview, settings, device ----------------------------
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(S["sm"])
        right.addWidget(label("Preview", "sectionTitle"))
        self.preview = OledView(2)
        right.addWidget(self.preview, 0, Qt.AlignLeft)
        prow = QHBoxLayout()
        prow.setSpacing(S["sm"])
        self.btn_play = QPushButton("Play")
        self.btn_play.setCheckable(True)
        theme.bind_icon(self.btn_play, "play", "text", checked_role="text")
        self.btn_play.toggled.connect(self.set_playing)
        self.play_label = label("", "hintLabel")
        prow.addWidget(self.btn_play)
        prow.addWidget(self.play_label, 1)
        right.addLayout(prow)
        right.addSpacing(S["sm"])
        right.addWidget(divider())
        right.addSpacing(S["xs"])

        right.addWidget(label("Animation", "sectionTitle"))
        sf = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(8)
        self.name_edit.setToolTip("Stored in the device header (max 8 ASCII characters)")
        self.name_edit.textEdited.connect(lambda _: self._mark_dirty())
        self.fps = QSpinBox()
        self.fps.setRange(1, A.MAX_FPS)
        self.fps.setSuffix(" fps")
        self.fps.valueChanged.connect(self._on_fps_changed)
        self.loop = QCheckBox("Loop")
        self.loop.toggled.connect(lambda _: self._mark_dirty())
        sf.addRow("Name", self.name_edit)
        sf.addRow("Speed", self.fps)
        sf.addRow("", self.loop)
        style_form(sf)
        right.addLayout(sf)
        right.addSpacing(S["sm"])
        right.addWidget(divider())
        right.addSpacing(S["xs"])

        right.addWidget(label("Idle behaviour (device)", "sectionTitle"))
        idf = QFormLayout()
        self.idle_enabled = QCheckBox("Play animation when idle")
        self.idle_timeout = QSpinBox()
        self.idle_timeout.setRange(0, 65535)
        self.idle_timeout.setSuffix(" s")
        self.idle_timeout.setSpecialValueText("off")
        self.idle_timeout.setToolTip(
            "Seconds without key/encoder input before the animation starts (0 = off)"
        )
        self.blank_timeout = QSpinBox()
        self.blank_timeout.setRange(0, 65535)
        self.blank_timeout.setSuffix(" s")
        self.blank_timeout.setSpecialValueText("never")
        self.blank_timeout.setToolTip(
            "Seconds without input before the display is switched off (burn-in protection, 0 = never)"
        )
        for w in (self.idle_timeout, self.blank_timeout):
            w.valueChanged.connect(lambda _: self._mark_dirty())
        self.idle_enabled.toggled.connect(lambda _: self._mark_dirty())
        idf.addRow("", self.idle_enabled)
        idf.addRow("Start after", self.idle_timeout)
        idf.addRow("Screen off after", self.blank_timeout)
        style_form(idf)
        right.addLayout(idf)
        right.addWidget(
            label(
                "Any key or encoder input wakes the display; the waking input is not sent to the PC.",
                "caption",
                wrap=True,
            )
        )
        right.addSpacing(S["sm"])
        right.addWidget(divider())
        right.addSpacing(S["xs"])

        self.stats = QLabel()
        self.stats.setObjectName("hintLabel")
        self.stats.setWordWrap(True)
        self.stats.setTextFormat(Qt.RichText)
        right.addWidget(self.stats)
        right.addSpacing(S["sm"])
        right.addWidget(divider())
        right.addSpacing(S["xs"])

        right.addWidget(label("Device", "sectionTitle"))
        dl = QGridLayout()
        dl.setHorizontalSpacing(S["sm"])
        dl.setVerticalSpacing(S["sm"])
        self.btn_upload = QPushButton("Upload to device")
        self.btn_upload.setToolTip("Write the animation to the macropad's flash (ANIM_BEGIN/DATA/COMMIT)")
        theme.bind_icon(self.btn_upload, "upload", "accent_text")
        set_primary(self.btn_upload)
        self.btn_upload.clicked.connect(self.upload_to_device)
        self.btn_dev_preview = QPushButton("Preview on device")
        self.btn_dev_preview.clicked.connect(lambda: self.device_preview(A.PREVIEW_PLAY))
        self.btn_dev_stop = QPushButton("Stop preview")
        self.btn_dev_stop.clicked.connect(lambda: self.device_preview(A.PREVIEW_STOP))
        self.btn_push = QPushButton("Push idle settings")
        self.btn_push.clicked.connect(self.push_settings)
        self.btn_readback = QPushButton("Read from device")
        self.btn_readback.clicked.connect(self.read_from_device)
        self.btn_builtin = QPushButton("Built-in demo")
        self.btn_builtin.setToolTip("Play the firmware's built-in starfield on the device")
        self.btn_builtin.clicked.connect(lambda: self.device_preview(A.PREVIEW_BUILTIN))
        self.push_with_upload = QCheckBox("Also push idle settings on upload")
        self.push_with_upload.setChecked(True)
        dl.addWidget(self.btn_upload, 0, 0, 1, 2)
        dl.addWidget(self.push_with_upload, 1, 0, 1, 2)
        dl.addWidget(self.btn_dev_preview, 2, 0)
        dl.addWidget(self.btn_dev_stop, 2, 1)
        dl.addWidget(self.btn_push, 3, 0)
        dl.addWidget(self.btn_readback, 3, 1)
        dl.addWidget(self.btn_builtin, 4, 0)
        right.addLayout(dl)
        self.dev_status = label("Firmware 0.25+ required for device actions.", "caption", wrap=True)
        right.addWidget(self.dev_status)
        right.addStretch(1)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(W * 2 + 88)
        if self._embedded:
            # As a page the side panel scrolls on its own, so its height never forces the window taller.
            rscroll = QScrollArea()
            rscroll.setObjectName("animSidePanel")
            rscroll.setFrameShape(QFrame.Shape.NoFrame)
            rscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            rscroll.setWidgetResizable(True)
            rscroll.setWidget(rw)
            rscroll.setFixedWidth(W * 2 + 88 + 12)
            body.addWidget(rscroll)
        else:
            body.addWidget(rw)

        # ---- bottom bar -------------------------------------------------------------
        root.addWidget(divider())
        bottom = QHBoxLayout()
        bottom.setSpacing(S["sm"])
        self.btn_new = QPushButton("New")
        self.btn_open = QPushButton("Open…")
        self.btn_save = QPushButton("Save")
        self.btn_save_as = QPushButton("Save as…")
        self.btn_export_gif = QPushButton("Export GIF…")
        self.btn_export_bin = QPushButton("Export .mpan…")
        self.btn_new.clicked.connect(self.new_project)
        self.btn_open.clicked.connect(self.open_project)
        self.btn_save.clicked.connect(self.save_project)
        self.btn_save_as.clicked.connect(lambda: self.save_project(ask=True))
        self.btn_export_gif.clicked.connect(self.export_gif)
        self.btn_export_bin.clicked.connect(self.export_blob)
        for b in (self.btn_new, self.btn_open, self.btn_save, self.btn_save_as):
            bottom.addWidget(b)
        bottom.addSpacing(S["sm"])
        bottom.addWidget(self.btn_export_gif)
        bottom.addWidget(self.btn_export_bin)
        bottom.addSpacing(S["sm"])
        self.path_label = label("", "caption")
        self.path_label.setMinimumWidth(40)
        bottom.addWidget(self.path_label, 1)
        if not self._embedded:
            close = QPushButton("Close")
            close.clicked.connect(self.close)
            bottom.addWidget(close)
        root.addLayout(bottom)

        # shortcuts (as a page, Ctrl+S is the window's page-aware File → Save)
        for seq, fn in (
            (QKeySequence.Undo, self.undo),
            (QKeySequence.Redo, self.redo),
            (QKeySequence("Ctrl+Y"), self.redo),
            (QKeySequence.Save, None if self._embedded else self.save_project),
            (QKeySequence("Ctrl+D"), self.duplicate_frame),
            (QKeySequence("P"), lambda: self.tool_pen.setChecked(True)),
            (QKeySequence("E"), lambda: self.tool_erase.setChecked(True)),
            (QKeySequence("I"), self.invert_frame),
            (QKeySequence("["), lambda: self.select_frame(self.cur - 1)),
            (QKeySequence("]"), lambda: self.select_frame(self.cur + 1)),
            (QKeySequence("Space"), lambda: self.btn_play.toggle()),
        ):
            if fn is not None:
                QShortcut(seq, self, activated=fn)
        self._preset_changed()
        if not self._embedded:
            self.resize(1320, 880)

    # ======================================================================
    # Model helpers
    # ======================================================================
    def project(self) -> AnimationProject:
        return AnimationProject(
            frames=[bytes(f) for f in self.frames],
            fps=self.fps.value(),
            loop=self.loop.isChecked(),
            name=self.name_edit.text() or "custom",
            idle_enabled=self.idle_enabled.isChecked(),
            idle_timeout_s=self.idle_timeout.value(),
            blank_timeout_s=self.blank_timeout.value(),
        )

    def _load_project(self, proj: AnimationProject, *, mark_clean: bool) -> None:
        self.set_playing(False)
        self.frames = [bytearray(f) for f in proj.frames] or [A.blank_frame()]
        for w, v in (
            (self.fps, proj.fps),
            (self.idle_timeout, proj.idle_timeout_s),
            (self.blank_timeout, proj.blank_timeout_s),
        ):
            w.blockSignals(True)
            w.setValue(int(v))
            w.blockSignals(False)
        for w, v in ((self.loop, proj.loop), (self.idle_enabled, proj.idle_enabled)):
            w.blockSignals(True)
            w.setChecked(bool(v))
            w.blockSignals(False)
        self.name_edit.setText(blob_name(proj.name))
        self._undo.clear()
        self._redo.clear()
        self._rebuild_list(0)
        if mark_clean:
            self.dirty = False
        else:
            self._mark_dirty()
        self._update_title()

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._update_title()
        self._stats_timer.start()

    def _update_title(self) -> None:
        name = self.path.name if self.path else "untitled"
        self.setWindowTitle(f"Idle animation editor — {name}{' *' if self.dirty else ''}")
        self.projectChanged.emit(name)
        self.path_label.setText(str(self.path) if self.path else f"Projects: {animations_dir(create=False)}")

    def _snapshot(self) -> tuple:
        return ([bytes(f) for f in self.frames], self.cur)

    def _push_undo(self) -> None:
        self._undo.append(self._snapshot())
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()

    def _restore(self, snap: tuple) -> None:
        frames, cur = snap
        self.frames = [bytearray(f) for f in frames]
        self._rebuild_list(min(cur, len(self.frames) - 1))
        self._mark_dirty()

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self._snapshot())
            self._restore(self._undo.pop())

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self._snapshot())
            self._restore(self._redo.pop())

    # ======================================================================
    # Frame list
    # ======================================================================
    def _item_for(self, i: int) -> QListWidgetItem:
        it = QListWidgetItem(QIcon(frame_pixmap(bytes(self.frames[i]))), f"{i + 1}")
        it.setSizeHint(QSize(W + 60, H + 8))
        return it

    def _rebuild_list(self, select: int) -> None:
        self.frame_list.blockSignals(True)
        self.frame_list.clear()
        for i in range(len(self.frames)):
            self.frame_list.addItem(self._item_for(i))
        self.frame_list.blockSignals(False)
        self.select_frame(select)
        self._stats_timer.start()

    def _refresh_thumb(self, i: int) -> None:
        it = self.frame_list.item(i)
        if it is not None:
            it.setIcon(QIcon(frame_pixmap(bytes(self.frames[i]))))

    def select_frame(self, i: int) -> None:
        if not self.frames:
            return
        i = max(0, min(len(self.frames) - 1, int(i)))
        self.cur = i
        self.frame_list.blockSignals(True)
        self.frame_list.setCurrentRow(i)
        self.frame_list.blockSignals(False)
        self._show_current()

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self.frames):
            self.cur = row
            self._show_current()

    def _on_rows_moved(self, _parent, start, end, _dest, row) -> None:
        # Drag-and-drop reorder inside the list widget.
        self._push_undo()
        block = self.frames[start : end + 1]
        del self.frames[start : end + 1]
        insert_at = row if row < start else row - (end - start + 1)
        self.frames[insert_at:insert_at] = block
        QTimer.singleShot(0, lambda: self._rebuild_list(insert_at))
        self._mark_dirty()

    def _show_current(self) -> None:
        f = bytes(self.frames[self.cur])
        onion = None
        if self.onion.isChecked() and len(self.frames) > 1:
            prev = self.cur - 1 if self.cur > 0 else (len(self.frames) - 1 if self.loop.isChecked() else None)
            if prev is not None and prev != self.cur:
                onion = bytes(self.frames[prev])
        self.canvas.set_frame(f, onion)
        self.frame_label.setText(
            f"Frame {self.cur + 1} / {len(self.frames)}   ·   {A.frame_pixel_count(f)} px lit"
        )
        if not self._playing:
            self.preview.set_frame(f)

    def _on_canvas_edited(self) -> None:
        self.frames[self.cur] = bytearray(self.canvas.frame())
        self._refresh_thumb(self.cur)
        self._show_current()
        self._mark_dirty()

    def _apply_to_current(self, fn) -> None:
        self._push_undo()
        self.frames[self.cur] = bytearray(fn(bytes(self.frames[self.cur])))
        self._refresh_thumb(self.cur)
        self._show_current()
        self._mark_dirty()

    def invert_frame(self) -> None:
        self._apply_to_current(A.invert_frame)

    def clear_frame(self) -> None:
        self._apply_to_current(lambda f: bytes(A.FRAME_BYTES))

    def shift_frame(self, dx: int, dy: int) -> None:
        self._apply_to_current(lambda f: A.shift_frame(f, dx, dy))

    def add_frame(self) -> None:
        if len(self.frames) >= A.MAX_FRAMES:
            return
        self._push_undo()
        self.frames.insert(self.cur + 1, A.blank_frame())
        self._rebuild_list(self.cur + 1)
        self._mark_dirty()

    def duplicate_frame(self) -> None:
        if len(self.frames) >= A.MAX_FRAMES:
            return
        self._push_undo()
        self.frames.insert(self.cur + 1, bytearray(self.frames[self.cur]))
        self._rebuild_list(self.cur + 1)
        self._mark_dirty()

    def delete_frame(self) -> None:
        self._push_undo()
        if len(self.frames) == 1:
            self.frames[0] = A.blank_frame()
        else:
            del self.frames[self.cur]
        self._rebuild_list(min(self.cur, len(self.frames) - 1))
        self._mark_dirty()

    def move_frame(self, delta: int) -> None:
        j = self.cur + delta
        if not 0 <= j < len(self.frames):
            return
        self._push_undo()
        self.frames[self.cur], self.frames[j] = self.frames[j], self.frames[self.cur]
        self._rebuild_list(j)
        self._mark_dirty()

    # ======================================================================
    # Preview
    # ======================================================================
    def _on_fps_changed(self, v: int) -> None:
        if self._playing:
            self._play_timer.setInterval(max(1, round(1000 / v)))
        self._mark_dirty()

    def set_playing(self, on: bool) -> None:
        on = bool(on)
        self._playing = on
        if self.btn_play.isChecked() != on:
            self.btn_play.blockSignals(True)
            self.btn_play.setChecked(on)
            self.btn_play.blockSignals(False)
        self.btn_play.setText("Pause" if on else "Play")
        theme.bind_icon(self.btn_play, "pause" if on else "play", "text", checked_role="text")
        if on:
            self._play_idx = 0
            self._play_timer.start(max(1, round(1000 / self.fps.value())))
            self._play_tick()
        else:
            self._play_timer.stop()
            self.play_label.setText("")
            if self.frames:
                self.preview.set_frame(bytes(self.frames[self.cur]))

    def _play_tick(self) -> None:
        if not self.frames:
            return
        if self._play_idx >= len(self.frames):
            if self.loop.isChecked():
                self._play_idx = 0
            else:
                self.set_playing(False)
                return
        self.preview.set_frame(bytes(self.frames[self._play_idx]))
        self.play_label.setText(f"{self._play_idx + 1}/{len(self.frames)} @ {self.fps.value()} fps")
        self._play_idx += 1

    # ======================================================================
    # Stats
    # ======================================================================
    def _update_stats(self) -> None:
        try:
            blob = self.project().to_blob()
            st = A.blob_stats(blob)
        except (ProjectError, A.AnimFormatError) as exc:
            self.stats.setText(f"<span style='color:{theme.palette()['danger']}'>{exc}</span>")
            return
        pct = 100.0 * st["total_len"] / A.REGION_SIZE
        enc = st["encodings"]
        dur = len(self.frames) / max(1, self.fps.value())
        pal = theme.palette()
        color = pal["success"] if st["fits"] else pal["danger"]
        warn = (
            ""
            if st["fits"]
            else f"<br><b style='color:{pal['danger']}'>Too large for the device region — remove frames or simplify.</b>"
        )
        self.stats.setText(
            f"<span style='color:{pal['text']}'><b>{len(self.frames)}</b> frames · {dur:.1f} s per loop</span><br>"
            f"Encoded <b style='color:{color}'>{st['total_len']:,} B</b> of {A.REGION_SIZE // 1024} KiB "
            f"({pct:.1f} %) · raw {st['raw_len']:,} B<br>"
            f"RLE {enc['RLE']} · delta {enc['DELTA']} · raw {enc['RAW']}{warn}"
        )

    # ======================================================================
    # Presets / import
    # ======================================================================
    def _preset_changed(self, *_a) -> None:
        pr = P.PRESETS[self.preset_combo.currentData()]
        self.preset_text.setEnabled(pr.takes_text)
        if pr.takes_text and not self.preset_text.text():
            self.preset_text.setText(pr.default_text)
        if not pr.takes_text:
            self.preset_text.clear()
            self.preset_text.setPlaceholderText("(no text for this preset)")
        else:
            self.preset_text.setPlaceholderText("Text for text presets")

    def _confirm_replace(self, what: str) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(
            self,
            "Replace animation",
            f"{what} replaces the current frames. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        return r == QMessageBox.Yes

    def load_preset(self, key: Optional[str] = None, *, confirm: bool = True) -> None:
        if key is not None:
            idx = self.preset_combo.findData(key)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        key = self.preset_combo.currentData()
        pr = P.PRESETS[key]
        if confirm and not self._confirm_replace(f"Preset '{pr.label}'"):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            frames, fps = P.generate(key, self.preset_text.text() if pr.takes_text else None)
        finally:
            QApplication.restoreOverrideCursor()
        self._push_undo()
        self.frames = [bytearray(f) for f in frames]
        self.fps.blockSignals(True)
        self.fps.setValue(fps)
        self.fps.blockSignals(False)
        self.loop.setChecked(True)
        self.name_edit.setText(blob_name(key))
        self._rebuild_list(0)
        self._mark_dirty()

    def import_images(self, paths: Optional[list[str]] = None) -> Optional[ImportDialog]:
        if not paths:
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                "Import GIF / images",
                str(Path.home()),
                "Images (*.gif *.png *.jpg *.jpeg *.bmp *.webp);;All files (*)",
            )
        if not paths:
            return None
        try:
            dlg = ImportDialog(list(paths), self)
        except Exception as exc:
            QMessageBox.warning(self, "Import", f"Could not read the image(s):\n{exc}")
            return None
        if dlg.exec() != QDialog.Accepted:
            return dlg
        self.apply_import(dlg)
        return dlg

    def apply_import(self, dlg: ImportDialog) -> None:
        new = [bytearray(f) for f in dlg.frames()]
        self._push_undo()
        if dlg.mode == "replace":
            self.frames = new
            sel = 0
            self.name_edit.setText(blob_name(Path(dlg._paths[0]).stem))
        elif dlg.mode == "append":
            sel = len(self.frames)
            self.frames.extend(new)
        else:
            sel = self.cur + 1
            self.frames[sel:sel] = new
        self.frames = self.frames[: A.MAX_FRAMES]
        if dlg.use_fps:
            self.fps.setValue(int(dlg.fps_guess))
        self._rebuild_list(min(sel, len(self.frames) - 1))
        self._mark_dirty()

    # ======================================================================
    # Files
    # ======================================================================
    def _maybe_save(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(
            self,
            "Unsaved animation",
            "Save changes to this animation?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            return self.save_project()
        return True

    def new_project(self) -> None:
        if not self._maybe_save():
            return
        self.path = None
        self._load_project(AnimationProject(), mark_clean=True)

    def open_project(self, path: Optional[str] = None) -> None:
        if not path:
            if not self._maybe_save():
                return
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Open animation",
                str(animations_dir()),
                f"Animation projects (*{SUFFIX});;Device blobs (*.mpan);;All files (*)",
            )
        if not path:
            return
        try:
            if str(path).endswith(".mpan"):
                proj = AnimationProject.from_blob(Path(path).read_bytes(), Path(path).stem)
                self.path = None
            else:
                proj = AnimationProject.load(path)
                self.path = Path(path)
        except (ProjectError, A.AnimFormatError, OSError) as exc:
            QMessageBox.warning(self, "Open animation", str(exc))
            return
        self._load_project(proj, mark_clean=self.path is not None)

    def save_project(self, ask: bool = False) -> bool:
        path = self.path
        if ask or path is None:
            default = animations_dir() / f"{self.name_edit.text() or 'animation'}{SUFFIX}"
            fn, _ = QFileDialog.getSaveFileName(
                self, "Save animation", str(default), f"Animation projects (*{SUFFIX})"
            )
            if not fn:
                return False
            if not fn.endswith(SUFFIX):
                fn += SUFFIX
            path = Path(fn)
        try:
            self.project().save(path)
        except (ProjectError, OSError) as exc:
            QMessageBox.warning(self, "Save animation", str(exc))
            return False
        self.path = path
        self.dirty = False
        self._update_title()
        return True

    def export_gif(self, path: Optional[str] = None, scale: int = 3) -> None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export GIF", str(animations_dir() / "animation.gif"), "GIF (*.gif)"
            )
        if path:
            write_oled_gif(
                path,
                [bytes(f) for f in self.frames],
                self.fps.value(),
                scale=scale,
                loop=self.loop.isChecked(),
            )

    def export_blob(self, path: Optional[str] = None) -> None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export device blob", str(animations_dir() / "animation.mpan"), "Device blob (*.mpan)"
            )
        if path:
            try:
                Path(path).write_bytes(self.project().to_blob())
            except (ProjectError, A.AnimFormatError, OSError) as exc:
                QMessageBox.warning(self, "Export", str(exc))

    def closeEvent(self, ev) -> None:
        if self._embedded:  # the main window asks via maybe_save() on quit
            self.set_playing(False)
            ev.accept()
            return
        if self._maybe_save():
            self.set_playing(False)
            ev.accept()
        else:
            ev.ignore()

    def reject(self) -> None:  # Esc
        if not self._embedded:
            self.close()

    def done(self, r: int) -> None:
        if not self._embedded:
            super().done(r)

    def keyPressEvent(self, ev) -> None:
        if self._embedded:
            QWidget.keyPressEvent(self, ev)
        else:
            super().keyPressEvent(ev)

    def hideEvent(self, ev) -> None:
        if self._embedded:  # leaving the page stops the preview
            self.set_playing(False)
        super().hideEvent(ev)

    # ======================================================================
    # Device
    # ======================================================================
    def _open_device(self):
        """Open + GET_INFO + feature gate. Returns an open device or None."""
        try:
            from ..protocol.device import DeviceError
        except Exception as exc:
            QMessageBox.warning(self, "Device", f"Protocol module unavailable:\n{exc}")
            return None
        try:
            dev = self._device_factory()
            dev.open()
            info = dev.get_info()
        except DeviceError as exc:
            QMessageBox.information(self, "Device", f"Could not talk to the macropad.\n\n{exc}")
            return None
        except Exception as exc:
            QMessageBox.warning(self, "Device", str(exc))
            return None
        self._device_info = info
        from ..protocol.frames import CFG_INFO_FLAG_ANIM

        ok_proto, msg = app_version.check_proto_ver(info.get("proto_ver", -1))
        has_flag = bool(int(info.get("flags", 0)) & CFG_INFO_FLAG_ANIM)
        fw_ok = app_version.fw_supports_anim(info.get("fw_major"), info.get("fw_minor"))
        if not ok_proto or not (has_flag and fw_ok):
            dev.close()
            fw = f"{info.get('fw_major', '?')}.{info.get('fw_minor', '?')}"
            text = (
                msg
                if not ok_proto
                else f"This macropad runs firmware {fw}, which has no OLED idle-animation support.\n\n"
                f"Flash firmware {app_version.FW_VERSION_MAJOR_EXPECTED}."
                f"{app_version.MIN_FW_MINOR_ANIM}+ (macropad-fw-X.Y.Z.uf2 from the Releases page) to upload "
                "animations and change idle settings.\n\nYou can still design, save and export "
                "animations here."
            )
            self.dev_status.setText(f"Firmware {fw}: idle animations not supported.")
            QMessageBox.information(self, "Idle animation not supported", text)
            return None
        return dev

    def _refresh_dev_status(self, dev) -> None:
        try:
            info = dev.anim_info()
        except Exception as exc:
            self.dev_status.setText(f"ANIM_INFO failed: {exc}")
            return
        fw = f"{self._device_info.get('fw_major')}.{self._device_info.get('fw_minor')}"
        if info["stored_valid"]:
            stored = (
                f"stored '{info['name']}': {info['frame_count']} frames @ {info['fps']} fps, "
                f"{info['total_len']:,} B"
            )
        else:
            stored = "no stored animation (built-in starfield is used)"
        state = "blanked" if info["blanked"] else "playing" if info["playing"] else "normal UI"
        timing = ""
        if info["last_frame_bus_us"]:
            timing = (
                f" · last frame push {info['last_frame_bus_us'] / 1000:.1f} ms bus / "
                f"{info['last_frame_wall_us'] / 1000:.1f} ms wall"
            )
        self.dev_status.setText(f"fw {fw} · {stored} · display: {state}{timing}")

    def upload_to_device(self) -> bool:
        try:
            blob = self.project().to_blob()
        except (ProjectError, A.AnimFormatError) as exc:
            QMessageBox.warning(self, "Upload", str(exc))
            return False
        if len(blob) > A.REGION_SIZE:
            QMessageBox.warning(
                self,
                "Upload",
                f"Encoded animation is {len(blob):,} B; the device region holds "
                f"{A.REGION_SIZE:,} B. Remove frames or simplify the artwork.",
            )
            return False
        dev = self._open_device()
        if dev is None:
            return False
        prog = QProgressDialog("Uploading animation…", "Cancel", 0, len(blob), self)
        prog.setWindowTitle("Upload animation")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)

        def cb(done: int, total: int):
            prog.setValue(done)
            prog.setLabelText(f"Uploading animation… {done:,} / {total:,} B")
            QApplication.processEvents()
            return not prog.wasCanceled()

        try:
            dev.anim_upload(blob, cb)
            if self.push_with_upload.isChecked():
                dev.anim_settings_set(
                    enabled=self.idle_enabled.isChecked(),
                    idle_timeout_s=self.idle_timeout.value(),
                    blank_timeout_s=self.blank_timeout.value(),
                )
            readback = dev.anim_download()
            self._refresh_dev_status(dev)
        except Exception as exc:
            prog.close()
            QMessageBox.warning(self, "Upload failed", str(exc))
            dev.close()
            return False
        prog.setValue(len(blob))
        prog.close()
        dev.close()
        if readback != blob:
            QMessageBox.warning(self, "Upload", "Upload finished but the read-back does not match.")
            return False
        self.dev_status.setText(self.dev_status.text() + " · verified ✓")
        return True

    def device_preview(self, mode: int) -> None:
        dev = self._open_device()
        if dev is None:
            return
        try:
            dev.anim_preview(mode)
            self._refresh_dev_status(dev)
        except Exception as exc:
            QMessageBox.warning(self, "Device preview", str(exc))
        finally:
            dev.close()

    def push_settings(self) -> None:
        dev = self._open_device()
        if dev is None:
            return
        try:
            got = dev.anim_settings_set(
                enabled=self.idle_enabled.isChecked(),
                idle_timeout_s=self.idle_timeout.value(),
                blank_timeout_s=self.blank_timeout.value(),
            )
            self._refresh_dev_status(dev)
            self.dev_status.setText(
                self.dev_status.text() + f" · settings saved (idle {got['idle_timeout_s']} s, "
                f"off {got['blank_timeout_s']} s, "
                f"{'on' if got['enabled'] else 'disabled'})"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Idle settings", str(exc))
        finally:
            dev.close()

    def read_from_device(self) -> None:
        dev = self._open_device()
        if dev is None:
            return
        try:
            blob = dev.anim_download()
            settings = dev.anim_settings_get()
            self._refresh_dev_status(dev)
        except Exception as exc:
            QMessageBox.warning(self, "Read from device", str(exc))
            return
        finally:
            dev.close()
        if blob is None:
            QMessageBox.information(
                self,
                "Read from device",
                "The device has no stored animation (it plays the built-in "
                "starfield). Idle settings were loaded.",
            )
            proj = self.project()
        else:
            if not self._confirm_replace("Reading the device animation"):
                return
            proj = AnimationProject.from_blob(blob)
        proj.idle_enabled = settings["enabled"]
        proj.idle_timeout_s = settings["idle_timeout_s"]
        proj.blank_timeout_s = settings["blank_timeout_s"]
        self.path = None
        self._load_project(proj, mark_clean=False)
