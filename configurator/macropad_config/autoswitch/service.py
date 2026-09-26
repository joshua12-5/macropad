"""QTimer-based autoswitch poller: foreground → SET_ACTIVE."""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from PySide6.QtCore import QObject, QTimer

from .foreground import get_foreground
from .matcher import MatchResult, match_foreground
from .rules import AutoswitchRules, load_rules


StatusCallback = Callable[[str], None]
SwitchCallback = Callable[[MatchResult], None]


class AutoswitchService(QObject):
    """Poll foreground app and send SET_ACTIVE when the matched slot changes."""

    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        on_status: Optional[StatusCallback] = None,
        on_switch: Optional[SwitchCallback] = None,
        host_profile_ids: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_status = on_status
        self._on_switch = on_switch
        self._host_profile_ids = list(host_profile_ids) if host_profile_ids else None
        self._rules: AutoswitchRules = AutoswitchRules()
        self._enabled = False
        self._last_slot: Optional[int] = None
        self._device = None  # ConfigDevice | None (lazy)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_host_profile_ids(self, ids: Sequence[str]) -> None:
        self._host_profile_ids = list(ids)

    def load(self, path=None) -> AutoswitchRules:
        self._rules = load_rules(path)
        self._timer.setInterval(max(100, int(self._rules.poll_ms)))
        return self._rules

    @property
    def rules(self) -> AutoswitchRules:
        return self._rules

    def set_rules(self, rules: AutoswitchRules) -> None:
        self._rules = rules
        self._timer.setInterval(max(100, int(rules.poll_ms)))

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if self._enabled:
            if self._timer.interval() < 100:
                self._timer.setInterval(max(100, int(self._rules.poll_ms)))
            self._timer.start()
            self._status("Auto-switch: enabled")
            self._tick()
        else:
            self._timer.stop()
            self._close_device()
            self._last_slot = None
            self._status("Auto-switch: disabled")

    def is_enabled(self) -> bool:
        return self._enabled

    def _status(self, msg: str) -> None:
        if self._on_status:
            self._on_status(msg)

    def _close_device(self) -> None:
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    def _ensure_device(self):
        if self._device is not None:
            return self._device
        from ..protocol.device import ConfigDevice

        dev = ConfigDevice(timeout_ms=500)
        dev.open()
        self._device = dev
        return dev

    def _tick(self) -> None:
        if not self._enabled:
            return
        try:
            info = get_foreground()
        except Exception:
            info = None
        if info is None or not info.process:
            return

        result = match_foreground(
            self._rules,
            info.process,
            info.title,
            host_profile_ids=self._host_profile_ids,
        )
        if result.slot is None:
            return
        if result.slot == self._last_slot:
            return  # debounce same slot

        try:
            dev = self._ensure_device()
            dev.set_active_slot(result.slot)
        except Exception as exc:
            self._close_device()
            self._status(f"Auto-switch: device error ({exc})")
            return

        self._last_slot = result.slot
        label = result.profile_id or f"slot{result.slot}"
        proc = info.process or "?"
        msg = f"Auto-switch: {label} ({proc})"
        self._status(msg)
        if self._on_switch:
            self._on_switch(result)
