#!/usr/bin/env python3
"""Theme smoke: QSS template + palettes in dark and light, icons resolve and recolour.

Checks
  * every {{token}} in ui/theme.qss resolves in both palettes (no leftovers),
  * QSS image URLs point at rendered icon files (+ @2x),
  * every vendored Lucide SVG renders, uses currentColor and is referenced,
  * every icon name used in the code exists (static scan + runtime tables),
  * text / accent contrast meets WCAG AA,
  * MainWindow + device view render in both modes; keycap legends.

Run:  cd configurator && QT_QPA_PLATFORM=offscreen python scripts/smoke_theme.py
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from macropad_config.ui import theme

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  FAIL: {msg}")


def luminance(hex_color: str) -> float:
    c = theme.qcolor(hex_color)
    out = []
    for v in (c.redF(), c.greenF(), c.blueF()):
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    r, g, b = out
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def main() -> int:
    from macropad_config.ui.theme import _MSG_ICONS
    from macropad_config.widgets import pad_preview as pp

    app = QApplication(sys.argv[:1])
    names = theme.icon_names()
    print(f"icons: {len(names)} vendored in {theme.ICON_DIR}")
    expect((theme.ICON_DIR / "LICENSE").is_file(), "icons/LICENSE present")
    expect(
        "ISC License" in (theme.ICON_DIR / "LICENSE").read_text(encoding="utf-8"), "Lucide ISC license text"
    )
    expect(theme.QSS_TEMPLATE.is_file(), "theme.qss present")

    spec = (ROOT.parent / "packaging" / "macropad_configurator.spec").read_text(encoding="utf-8")
    expect('"theme.qss"' in spec and '"icons"' in spec, "PyInstaller spec bundles theme.qss + icons")

    # --- palettes -------------------------------------------------------------
    keys_dark, keys_light = set(theme.PALETTES["dark"]), set(theme.PALETTES["light"])
    expect(keys_dark == keys_light, f"palette keys differ: {keys_dark ^ keys_light}")
    for scheme, pal in theme.PALETTES.items():
        for fg, bg, need in (
            ("text", "window", 7.0),
            ("text", "panel", 7.0),
            ("text_muted", "window", 4.5),
            ("text_muted", "panel", 4.5),
            ("text_muted", "raised", 4.5),
            ("accent_text", "accent", 4.5),
            ("cap_legend", "cap_top", 7.0),
            ("tooltip_text", "tooltip_bg", 7.0),
        ):
            ratio = contrast(pal[fg], pal[bg])
            expect(ratio >= need, f"{scheme}: contrast {fg}/{bg} = {ratio:.2f} < {need}")
        print(
            f"{scheme}: text/window {contrast(pal['text'], pal['window']):.1f}:1, "
            f"muted/panel {contrast(pal['text_muted'], pal['panel']):.1f}:1, "
            f"accent_text/accent {contrast(pal['accent_text'], pal['accent']):.1f}:1"
        )

    # --- both modes -------------------------------------------------------------
    for mode in ("dark", "light"):
        got = theme.apply_theme(app, mode)
        expect(got == mode, f"apply_theme({mode}) -> {got}")
        qss = app.styleSheet()
        expect(len(qss) > 2000, f"{mode}: stylesheet applied ({len(qss)} chars)")
        expect("{{" not in qss and "}}" not in qss, f"{mode}: unresolved tokens")
        expect(theme.PALETTES[mode]["accent"] in qss, f"{mode}: accent colour in QSS")
        urls = re.findall(r"url\(([^)]+)\)", qss)
        expect(len(urls) >= 8, f"{mode}: QSS icon urls ({len(urls)})")
        for u in set(urls):
            p = Path(u)
            expect(p.is_file(), f"{mode}: QSS image missing {u}")
            expect(p.with_name(p.stem + "@2x.png").is_file(), f"{mode}: @2x missing for {p.name}")
        window = app.palette().window().color().name()
        expect(window == theme.PALETTES[mode]["window"], f"{mode}: QPalette window {window}")
        for name in names:
            pix = theme.render_icon(name, theme.PALETTES[mode]["text"], 16, 2.0)
            img = pix.toImage()
            opaque = sum(
                1
                for y in range(0, img.height(), 2)
                for x in range(0, img.width(), 2)
                if img.pixelColor(x, y).alpha() > 128
            )
            expect(opaque > 0, f"{mode}: icon {name} renders empty")
            ic = theme.icon(name)
            expect(not ic.isNull(), f"{mode}: QIcon {name} null")
        print(f"{mode}: {len(qss)} chars QSS, {len(set(urls))} QSS icon files, {len(names)} icons rendered")

    theme.REQUESTED_ICONS.clear()  # from here on: only what the UI itself asks for

    # system mode resolves to one of the two
    expect(theme.manager().resolve("system") in ("dark", "light"), "system mode resolves")

    # --- legends ---------------------------------------------------------------------
    lg = pp.action_legend({"type": "SHORTCUT", "key": "S", "mods": ["CTRL", "SHIFT"]})
    expect(lg.primary == "S" and lg.secondary == "Ctrl + Shift", f"shortcut legend {lg}")
    expect(pp.action_legend({"type": "DISABLED"}).disabled, "disabled legend")
    expect(pp.action_legend({"type": "MEDIA", "code": "MUTE"}).icon == "volume-x", "media legend icon")
    expect(
        pp.action_legend({"type": "MACRO", "macro_id": 1}, {1: "sel+cpy"}).primary == "sel+cpy",
        "macro legend",
    )
    expect(pp.action_legend({"type": "KEY", "key": "ENTER"}).primary == "Enter", "key legend")

    # --- main window in both modes ------------------------------------------------------
    from macropad_config.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 760)
    win.show()
    app.processEvents()
    for mode in ("light", "dark"):
        theme.apply_theme(app, mode)
        app.processEvents()
        img = win.grab().toImage()
        expect(not img.isNull() and img.width() > 100, f"{mode}: main window grab")
        bg = img.pixelColor(img.width() // 2, img.height() - 60).name()
        expect(bg == theme.PALETTES[mode]["window"], f"{mode}: canvas background {bg}")
        expect(not win._theme_btn.icon().isNull(), f"{mode}: theme toggle icon")
        expect(win._theme_acts[theme.manager().mode].isChecked(), f"{mode}: View → Theme radio synced")
    titles = [a.text().replace("&", "") for a in win.menuBar().actions()]
    expect("View" in titles, f"View menu present {titles}")
    sub = win._theme_menu
    expect([a.data() for a in sub.actions()] == ["system", "dark", "light"], "View → Theme")
    win._pad._select_key(6)
    expect(win._pad.selection() == ("key", 6), "key selection")
    expect(win._selection_title.text() == "Key 6", f"inspector title {win._selection_title.text()!r}")
    win._pad._select_encoder("cw")
    expect(win._selection_title.text().startswith("Encoder"), "encoder selection title")
    expect(win._conn_pill.text() == "Not connected", "status pill idle text")
    # Dialogs (icons they request are recorded by the theme).
    os.environ.setdefault("MACROPAD_ANIMATIONS_DIR", tempfile.mkdtemp(prefix="smoke-theme-anim-"))
    from macropad_config.autoswitch.rules import load_rules
    from macropad_config.widgets.anim_editor import AnimationEditorDialog
    from macropad_config.widgets.autoswitch_dialog import AutoswitchDialog
    from macropad_config.widgets.info_panels import AboutPanel, DeviceInfoPanel
    from macropad_config.widgets.macro_library_dialog import MacroLibraryDialog
    from macropad_config.widgets.profile_dialog import ProfileNameIdDialog

    info = {
        "fw_major": 0,
        "fw_minor": 25,
        "proto_ver": 1,
        "product_tag": "MACROPAD",
        "active_slot": 2,
        "slot_count": 5,
        "flags": 0x0F,
        "ping_payload": b"PONG",
    }
    dialogs = [
        AnimationEditorDialog(win),
        MacroLibraryDialog(parent=win),
        AutoswitchDialog(load_rules(), parent=win),
        ProfileNameIdDialog(title="New profile", existing_ids=set(), parent=win),
        AboutPanel(),
        DeviceInfoPanel(),
    ]
    dialogs[-1].set_info(info, True)
    anim = dialogs[0]
    anim.set_playing(True)
    anim.set_playing(False)
    for d in dialogs:
        d.show()
        app.processEvents()
        expect(not d.grab().toImage().isNull(), f"{type(d).__name__} renders")
        if hasattr(d, "dirty"):
            d.dirty = False
        if hasattr(d, "_dirty"):
            d._dirty = False
        d.close()
    # every page of the window renders in both modes (records the icons they request)
    for mode in ("dark", "light"):
        theme.apply_theme(app, mode)
        for key in ("keys", "macros", "idle", "autoswitch", "device", "settings"):
            win.go_to_page(key)
            app.processEvents()
            expect(not win.grab().toImage().isNull(), f"{mode}: {key} page renders")
    win.open_palette().close()
    win._dirty_ids.clear()
    win.close()

    # --- icon references --------------------------------------------------------------
    used = set(theme.REQUESTED_ICONS)  # everything the widgets asked for so far
    used |= {n for n, _ in _MSG_ICONS.values()}
    used |= set(pp.ENCODER_SLOT_ICONS.values())
    used |= {i for i, _ in pp._MEDIA.values()} | {i for i, _ in pp._VOLUME.values()}
    qss_icons = set(re.findall(r"\{\{icon:([a-z0-9-]+):", theme.QSS_TEMPLATE.read_text(encoding="utf-8")))
    used |= qss_icons
    missing = sorted(used - set(names))
    unused = sorted(set(names) - used)
    expect(not missing, f"icons referenced but not vendored: {missing}")
    expect(not unused, f"vendored icons never used (drop them): {unused}")
    for name in names:
        expect(
            "currentColor" in theme.icon_path(name).read_text(encoding="utf-8"), f"{name}: no currentColor"
        )
    print(f"icon refs: {len(used)} used, missing={missing}, unused={unused}")

    if FAILS:
        print(f"smoke_theme: {len(FAILS)} FAIL(S)")
        return 1
    print("smoke_theme: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
