# Hardware test checklist (manual)

Use after flashing `macropad_step21.uf2` (or current step UF2). Tick each item
on a real RP2040-Zero + matrix + EC11 + SSD1306 build.

**Prep:** Pico SDK build → copy UF2 while BOOTSEL held → wait for USB re-enum.
Configurator: `cd configurator && python -m macropad_config` (optional `hid`).

## Flash / boot

- [ ] UF2 copies cleanly; device reboots as HID (keyboard + config IF1)
- [ ] UART (if wired): boot / `stor load …` lines look healthy
- [ ] Connect / Get device info: fw **0.21** (or expected), **proto v1**, product `MACROPAD`
- [ ] Proto mismatch warning appears if testing against a deliberately wrong host `PROTO_VER` (optional)

## Keys (matrix)

- [ ] Keys 1–12 register press/release (HID or OLED toast)
- [ ] No stuck keys / ghosting on adjacent presses
- [ ] Active profile KEY/SHORTCUT actions type expected characters

## Encoder

- [ ] CW / CCW change volume (or profile encoder actions)
- [ ] Short press fires press action (e.g. mute)
- [ ] Long press (~800 ms) opens on-device profile menu

## OLED

- [ ] Idle title matches active profile OLED title
- [ ] Key toast appears briefly on press
- [ ] Profile-select menu draws; highlight moves with encoder

## Profile menu (on-device)

- [ ] Rotate highlights slots; short-press confirms switch
- [ ] Long-press or ~9 s idle cancels without change
- [ ] Confirmed switch updates OLED title + active slot (GET_INFO)

## Upload profile / macro

- [ ] Device → Upload profile: selected JSON → chosen slot 0–4; OLED/title updates if active
- [ ] Device → Upload macros: library ids 0–4 sync; MACRO actions play new bank
- [ ] Overlapping upload rejected (`EBUSY`) — optional stress
- [ ] If fw minor < 16/17: upload actions disabled with tooltip (compat path)

## Autoswitch

- [ ] Connect first; Device → Auto-switch enabled
- [ ] Foreground app matching a rule sends `SET_ACTIVE`; OLED/slot change
- [ ] Status bar shows `Auto-switch: <profile> (…)`
- [ ] Disconnect / unplug stops cleanly (no crash loop)
- [ ] If fw minor < 18: autoswitch toggle disabled with tooltip

## Save debounce / SAVE_ALL

- [ ] Rapid autoswitch / SET_ACTIVE: no per-switch flash thrash; after ~4 s quiet UART `stor debounce save` then `stor save ok` (if UART)
- [ ] Device → Save device state (`SAVE_ALL` 0x32): immediate persist; survives unplug/replug
- [ ] Active slot after reboot matches last saved / debounced value

## Sign-off

| Field | Value |
|-------|--------|
| Tester | |
| Date (Asia/Manila) | |
| Firmware UF2 / commit | |
| Host app version | |
| Pass / fail notes | |
