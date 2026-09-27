#!/usr/bin/env python3
"""Headless smoke: idle animation over the device protocol + editor GUI.

* ConfigDevice anim_* API against the mock firmware: upload (progress, cancel),
  read-back, ANIM_INFO, settings persisted in the MPFL v3 image, preview,
  region-size limit, sector-write accounting, old firmware (0.24) gating;
* HIL suite catches seeded animation bugs in the mock (no CRC check on
  COMMIT, missing EBUSY);
* AnimationEditorDialog on Qt offscreen: presets, canvas drawing, frame ops,
  undo/redo, import dialog, save/open project, upload via the mock and the
  "firmware too old" message.

Usage:
  cd configurator
  QT_QPA_PLATFORM=offscreen python scripts/smoke_anim_device.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.TemporaryDirectory(prefix="smoke-anim-")
os.environ["MACROPAD_USER_DATA"] = _TMP.name
os.environ["MACROPAD_ANIMATIONS_DIR"] = str(Path(_TMP.name) / "animations")

from macropad_config.animation import codec as A
from macropad_config.animation import presets as P
from macropad_config.hil import cli
from macropad_config.hil.mock import FLASH_SECTOR_SIZE, MockFirmware, MockHidModule
from macropad_config.protocol import frames as F
from macropad_config.protocol.device import ConfigDevice, DeviceError, NakError

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  FAIL: {msg}")


def open_dev(fw: MockFirmware) -> ConfigDevice:
    dev = ConfigDevice(hid_module=MockHidModule(fw), timeout_ms=300)
    dev.open()
    return dev


def check_protocol() -> None:
    print("smoke_anim_device: device API vs mock")
    fw = MockFirmware()
    dev = open_dev(fw)
    info = dev.get_info()
    expect(info["fw_minor"] == 25 and info["flags"] & F.CFG_INFO_FLAG_ANIM, f"GET_INFO {info}")
    ai = dev.anim_info()
    expect(not ai["stored_valid"] and ai["region_size"] == A.REGION_SIZE, f"fresh info {ai}")
    frames, fps = P.starfield(frames=40)
    blob = A.build_blob(frames, fps, True, "stars")
    seen = []
    dev.anim_upload(blob, lambda d, t: seen.append((d, t)))
    expect(seen and seen[-1] == (len(blob), len(blob)), "progress reaches total")
    expect(
        fw.anim_sector_writes == (len(blob) + FLASH_SECTOR_SIZE - 1) // FLASH_SECTOR_SIZE,
        f"only needed sectors written ({fw.anim_sector_writes})",
    )
    ai = dev.anim_info()
    expect(
        ai["stored_valid"]
        and ai["frame_count"] == 40
        and ai["fps"] == fps
        and ai["name"] == "stars"
        and ai["crc"] == F.crc32(blob)
        and ai["total_len"] == len(blob),
        f"info after upload {ai}",
    )
    expect(dev.anim_download() == blob, "read-back")
    # cancel before the first sector flush keeps the stored animation
    big = A.build_blob(P.scroll_text("CANCEL ME")[0], 25)
    try:
        dev.anim_upload(big, lambda d, t: d < 1000)
        expect(False, "cancel should raise")
    except DeviceError as exc:
        expect("cancel" in str(exc), f"cancel message {exc}")
    ai = dev.anim_info()
    expect(
        ai["stored_valid"] and ai["crc"] == F.crc32(blob) and not ai["uploading"],
        "cancel before first sector keeps the old animation",
    )
    # cancel after a sector was written invalidates (builtin fallback)
    try:
        dev.anim_upload(big, lambda d, t: d < 6000)
    except DeviceError:
        pass
    expect(not dev.anim_info()["stored_valid"], "cancel after sector write invalidates")
    # region limit
    import random

    rng = random.Random(1)
    noise = [bytes(rng.randrange(256) for _ in range(1024)) for _ in range(A.MAX_FRAMES_RAW + 1)]
    too_big = A.build_blob(noise, 10)
    try:
        dev.anim_upload(too_big)
        expect(False, "oversized upload accepted")
    except NakError as exc:
        expect(exc.code == F.CFG_ERR_EINVAL, f"oversized → {exc.code}")
    max_blob = A.build_blob(noise[: A.MAX_FRAMES_RAW], 10)
    dev.anim_upload(max_blob)
    expect(dev.anim_info()["frame_count"] == A.MAX_FRAMES_RAW, "127 raw frames fit")
    expect(fw.anim_sector_writes > 32, "full region written")
    # settings persisted in MPFL v3
    got = dev.anim_settings_set(enabled=False, idle_timeout_s=5, blank_timeout_s=65535)
    expect(got == {"enabled": False, "idle_timeout_s": 5, "blank_timeout_s": 65535}, f"settings echo {got}")
    expect(fw.flash_anim_settings() == got and fw.flash[4] == 3, "MPFL v3 image holds idle settings")
    try:
        dev.anim_settings_set(enabled=True, idle_timeout_s=70000, blank_timeout_s=0)
        expect(False, "70000 s accepted")
    except ValueError:
        pass
    # preview
    dev.anim_preview(A.PREVIEW_PLAY)
    expect(dev.anim_info()["playing"] and not dev.anim_info()["builtin_active"], "play stored")
    dev.anim_preview(A.PREVIEW_STOP)
    expect(not dev.anim_info()["playing"], "stop")
    dev.close()

    print("smoke_anim_device: firmware 0.24 has no animation commands")
    old = MockFirmware(fw_minor=24)
    dev = open_dev(old)
    expect(not dev.get_info()["flags"] & F.CFG_INFO_FLAG_ANIM, "fw24 flag clear")
    try:
        dev.anim_info()
        expect(False, "fw24 ANIM_INFO accepted")
    except NakError as exc:
        expect(exc.code == F.CFG_ERR_EINVAL, "fw24 ANIM_INFO → EINVAL")
    expect(old.flash[4] == 2, "fw24 keeps writing MPFL v2")
    dev.close()


def run_hil(args, fw):
    out = io.StringIO()
    rep_path = Path(_TMP.name) / "rep.json"
    code = cli.main(
        [*args, "--json", str(rep_path), "--no-color"], hid_module=MockHidModule(fw, api="cython"), stream=out
    )
    data = json.loads(rep_path.read_text())
    return code, {r["id"]: r["status"] for r in data["results"]}, out.getvalue()


def check_hil_catches_bugs() -> None:
    print("smoke_anim_device: HIL suite catches seeded animation bugs")
    code, st, out = run_hil(["--mock", "--allow-flash-write"], MockFirmware())
    expect(
        code == 0
        and all(
            st[t] == "PASS"
            for t in ("anim_info", "anim_protocol", "anim_preview", "anim_settings", "anim_roundtrip")
        ),
        f"clean mock should pass: {st}\n{out}",
    )

    class AcceptsBadCrc(MockFirmware):
        def _handle_anim(self, cmd, seq, length, raw_pl):
            if (
                cmd == F.CFG_CMD_ANIM_COMMIT
                and self.anim_up_active
                and self.anim_up_got == self.anim_up_total
            ):
                if self.anim_up_got % FLASH_SECTOR_SIZE:
                    self._anim_flush_stage()
                self.anim_up_active = False
                self._anim_load_stored()  # BUG: no CRC compare against BEGIN
                return self._resp(cmd, seq)
            return super()._handle_anim(cmd, seq, length, raw_pl)

    code, st, _ = run_hil(["--mock", "--allow-flash-write", "--only", "anim_roundtrip"], AcceptsBadCrc())
    expect(code == 1 and st["anim_roundtrip"] == "FAIL", f"missing CRC check not caught: {st}")

    class NoEbusy(MockFirmware):
        def _anim_upload_busy_other(self):
            return False

        def handle(self, req):
            if req[4] == F.CFG_CMD_PROFILE_BEGIN and self.anim_up_active:
                saved, self.anim_up_active = self.anim_up_active, False
                try:
                    return super().handle(req)
                finally:
                    self.anim_up_active = saved
            return super().handle(req)

    code, st, _ = run_hil(["--mock", "--only", "anim_protocol"], NoEbusy())
    expect(code == 1 and st["anim_protocol"] == "FAIL", f"missing EBUSY not caught: {st}")


def check_gui() -> None:
    print("smoke_anim_device: editor dialog (offscreen)")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from macropad_config.animation.gifwriter import write_oled_gif
    from macropad_config.widgets import anim_editor as E

    app = QApplication.instance() or QApplication([])
    msgs: list[str] = []
    QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(str(a[2]) if len(a) > 2 else ""))
    QMessageBox.warning = staticmethod(
        lambda *a, **k: msgs.append("WARN " + (str(a[2]) if len(a) > 2 else ""))
    )
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

    fw = MockFirmware()
    dlg = E.AnimationEditorDialog(device_factory=lambda: ConfigDevice(hid_module=MockHidModule(fw)))
    dlg.show()
    app.processEvents()
    expect(len(dlg.frames) == 1 and not dlg.dirty, "starts with one blank frame")
    # draw a line with the mouse
    z = dlg.canvas._zoom
    QTest.mousePress(dlg.canvas, Qt.LeftButton, Qt.NoModifier, QPoint(10 * z + 1, 10 * z + 1))
    QTest.mouseMove(dlg.canvas, QPoint(20 * z + 1, 10 * z + 1))
    QTest.mouseRelease(dlg.canvas, Qt.LeftButton, Qt.NoModifier, QPoint(20 * z + 1, 10 * z + 1))
    app.processEvents()
    f0 = bytes(dlg.frames[0])
    expect(
        all(A.get_pixel(f0, x, 10) for x in range(10, 21)) and A.frame_pixel_count(f0) == 11,
        f"drag draws an 11 px line ({A.frame_pixel_count(f0)})",
    )
    expect(dlg.dirty, "drawing marks dirty")
    # right button erases
    QTest.mousePress(dlg.canvas, Qt.RightButton, Qt.NoModifier, QPoint(15 * z + 1, 10 * z + 1))
    QTest.mouseRelease(dlg.canvas, Qt.RightButton, Qt.NoModifier, QPoint(15 * z + 1, 10 * z + 1))
    expect(A.frame_pixel_count(bytes(dlg.frames[0])) == 10, "right click erases")
    dlg.undo()
    expect(A.frame_pixel_count(bytes(dlg.frames[0])) == 11, "undo")
    dlg.redo()
    expect(A.frame_pixel_count(bytes(dlg.frames[0])) == 10, "redo")
    dlg.duplicate_frame()
    dlg.shift_frame(0, 5)
    expect(len(dlg.frames) == 2 and A.get_pixel(bytes(dlg.frames[1]), 10, 15), "duplicate + shift")
    dlg.invert_frame()
    expect(A.frame_pixel_count(bytes(dlg.frames[1])) == 8192 - 10, "invert")
    dlg.move_frame(-1)
    expect(dlg.cur == 0 and A.frame_pixel_count(bytes(dlg.frames[0])) == 8182, "move earlier")
    dlg.add_frame()
    dlg.delete_frame()
    expect(len(dlg.frames) == 2, "add + delete")
    expect(dlg.frame_list.count() == 2 and not dlg.frame_list.item(0).icon().isNull(), "thumbnails")
    # onion skin shows previous frame in the canvas image
    dlg.select_frame(1)
    expect(dlg.canvas._onion is not None, "onion skin active on frame 2")
    # presets + preview playback
    for key in P.PRESETS:
        dlg.load_preset(key, confirm=False)
        expect(len(dlg.frames) >= 10, f"preset {key}")
    dlg.preset_text.setText("HELLO")
    dlg.load_preset("scroll", confirm=False)
    n_scroll = len(dlg.frames)
    expect(n_scroll == len(P.scroll_text("HELLO")[0]), "scroll preset uses the user text")
    dlg.set_playing(True)
    for _ in range(3):
        dlg._play_tick()
    expect(dlg._play_idx == 4, "preview advances")
    dlg.set_playing(False)
    dlg._update_stats()
    expect("frames" in dlg.stats.text() and "KiB" in dlg.stats.text(), "stats label")
    # import dialog (GIF written by our encoder)
    gif = Path(_TMP.name) / "in.gif"
    pf, _ = P.pulse(frames=6)
    write_oled_gif(gif, pf, 12, scale=2)
    imp = E.ImportDialog([str(gif)])
    expect(len(imp.frames()) == 6 and imp.fps_guess == 12, "import dialog reads GIF")
    imp._mode_append.setChecked(True)
    dlg.apply_import(imp)
    expect(len(dlg.frames) == n_scroll + 6 and dlg.fps.value() == 12, "append import + GIF fps")
    # save / reopen
    dlg.name_edit.setText("smoke")
    path = Path(os.environ["MACROPAD_ANIMATIONS_DIR"]) / "smoke.mpanim.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    dlg.path = path
    expect(dlg.save_project() and path.exists() and not dlg.dirty, "save project")
    saved = [bytes(f) for f in dlg.frames]
    dlg.new_project()
    expect(len(dlg.frames) == 1, "new project")
    dlg.open_project(str(path))
    expect([bytes(f) for f in dlg.frames] == saved and dlg.name_edit.text() == "smoke", "open project")
    # upload through the mock + settings
    dlg.idle_timeout.setValue(33)
    ok = dlg.upload_to_device()
    expect(ok and fw.anim_stored is not None and fw.anim_stored["name"] == "smoke", f"upload via GUI {msgs}")
    expect(fw.anim_settings["idle_timeout_s"] == 33, "settings pushed with upload")
    expect("verified" in dlg.dev_status.text(), f"status {dlg.dev_status.text()}")
    dlg.device_preview(A.PREVIEW_BUILTIN)
    expect(fw.anim_builtin_playing, "builtin preview")
    dlg.device_preview(A.PREVIEW_STOP)
    dlg.read_from_device()
    expect([bytes(f) for f in dlg.frames] == saved, "read from device restores frames")
    dlg.dirty = False
    dlg.close()
    # old firmware → clear message
    old = MockFirmware(fw_minor=24)
    dlg2 = E.AnimationEditorDialog(device_factory=lambda: ConfigDevice(hid_module=MockHidModule(old)))
    msgs.clear()
    expect(dlg2.upload_to_device() is False, "upload refused on fw 0.24")
    expect(msgs and "0.25" in msgs[-1] and "firmware 0.24" in msgs[-1], f"gate message {msgs}")
    dlg2.dirty = False
    dlg2.close()
    app.processEvents()


def main() -> int:
    check_protocol()
    check_hil_catches_bugs()
    check_gui()
    if FAILS:
        print(f"smoke_anim_device: {len(FAILS)} FAILURE(S)")
        return 1
    print("smoke_anim_device: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
