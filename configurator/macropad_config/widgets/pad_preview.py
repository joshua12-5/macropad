"""Center pad preview: OLED title, 3×4 key grid, encoder knob mock."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models.profile import Profile


class PadPreview(QWidget):
    """Visual mock of the macropad faceplate."""

    # selection_kind: "key" | "encoder", selection_id: int (1-12) or str slot
    selection_changed = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile: Profile | None = None
        self._key_buttons: dict[int, QPushButton] = {}
        self._encoder_buttons: dict[str, QPushButton] = {}
        self._selected: tuple[str, object] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        # OLED mock
        self._oled = QLabel("—")
        self._oled.setObjectName("oledTitle")
        self._oled.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._oled.setMinimumHeight(48)
        self._oled.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self._oled)

        # Keys + encoder row
        body = QHBoxLayout()
        body.setSpacing(16)

        grid_frame = QFrame()
        grid_frame.setObjectName("keyGridFrame")
        grid = QGridLayout(grid_frame)
        grid.setSpacing(8)
        grid.setContentsMargins(8, 8, 8, 8)

        for index in range(12):
            num = index + 1
            row, col = divmod(index, 4)
            btn = QPushButton(str(num))
            btn.setObjectName("keyButton")
            btn.setCheckable(True)
            btn.setMinimumSize(56, 48)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            btn.clicked.connect(lambda checked=False, n=num: self._select_key(n))
            grid.addWidget(btn, row, col)
            self._key_buttons[num] = btn

        body.addWidget(grid_frame, stretch=3)

        # Encoder column
        enc_col = QVBoxLayout()
        enc_col.setSpacing(8)
        enc_label = QLabel("Encoder")
        enc_label.setObjectName("sectionHeading")
        enc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        enc_col.addWidget(enc_label)

        knob = QLabel("◉")
        knob.setObjectName("encoderKnob")
        knob.setAlignment(Qt.AlignmentFlag.AlignCenter)
        knob.setMinimumSize(72, 72)
        enc_col.addWidget(knob, alignment=Qt.AlignmentFlag.AlignCenter)

        for slot, caption in (("cw", "CW"), ("ccw", "CCW"), ("press", "Press"), ("long_press", "Long")):
            btn = QPushButton(caption)
            btn.setObjectName("encoderButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, s=slot: self._select_encoder(s))
            enc_col.addWidget(btn)
            self._encoder_buttons[slot] = btn

        enc_col.addStretch(1)
        body.addLayout(enc_col, stretch=1)
        root.addLayout(body)

        hint = QLabel("Click a key or encoder action — details are read-only in Step 10.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

    def set_profile(self, profile: Profile | None) -> None:
        self._profile = profile
        if profile is None:
            self._oled.setText("—")
            self.clear_selection()
            return
        self._oled.setText(profile.oled_title)
        # Keep selection if still valid; otherwise clear
        if self._selected is None:
            return
        kind, sid = self._selected
        if kind == "key":
            self._select_key(int(sid))
        else:
            self._select_encoder(str(sid))

    def clear_selection(self) -> None:
        self._selected = None
        for btn in self._key_buttons.values():
            btn.setChecked(False)
        for btn in self._encoder_buttons.values():
            btn.setChecked(False)
        self.selection_changed.emit("", None)

    def _clear_checks(self) -> None:
        for btn in self._key_buttons.values():
            btn.setChecked(False)
        for btn in self._encoder_buttons.values():
            btn.setChecked(False)

    def _select_key(self, num: int) -> None:
        self._clear_checks()
        self._key_buttons[num].setChecked(True)
        self._selected = ("key", num)
        self.selection_changed.emit("key", num)

    def _select_encoder(self, slot: str) -> None:
        self._clear_checks()
        if slot in self._encoder_buttons:
            self._encoder_buttons[slot].setChecked(True)
        self._selected = ("encoder", slot)
        self.selection_changed.emit("encoder", slot)
