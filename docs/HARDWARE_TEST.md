# Hardware test checklist

Use after flashing `macropad_step24.uf2` / release `macropad-fw-X.Y.Z.uf2` (or current step UF2) on a real
RP2040-Zero + matrix + EC11 + SSD1306 build. **Run the automated HIL suite
first** (section 0), then tick the manual items below — the protocol items it
covers are marked *(HIL)*.

**Prep:** Pico SDK 2.1.1 build (`PICO_BOARD=waveshare_rp2040_zero`) or CI `macropad-firmware-uf2` artifact → copy UF2 while BOOTSEL held → wait for USB re-enum.
Configurator: release bundle (`MacropadConfigurator --hil …` runs the suite below) or `cd configurator && python -m macropad_config` (`hidapi` from requirements.txt).

## 0. Automated HIL suite (Step 23)

```bash
cd configurator
pip install -r requirements.txt          # includes `hid` (needs the system hidapi lib)
python scripts/hil_test.py --list        # VID 0x2E8A / PID 0xC001 interfaces; CONFIG = usage page 0xFF00
python scripts/hil_test.py               # flash-free suite (safe to run any time)
python scripts/hil_test.py --allow-flash-write --json hil-report.json   # + COMMIT round-trips + SAVE_ALL
python scripts/hil_test.py --interactive # + guided key / encoder checklist
python scripts/hil_test.py --mock --allow-flash-write                   # no hardware (CI uses this)
```

Host needs a hidapi binding: `pip install hidapi` (in `requirements.txt`; native library bundled —
release builds include it too). The older `pip install hid` also works but needs the system
library (`apt install libhidapi-hidraw0` / `brew install hidapi` / `hidapi.dll`). On Linux grant
access to the config interface with `packaging/linux/70-macropad.rules` (shipped in the Linux
tarball) in `/etc/udev/rules.d/`:

```
KERNEL=="hidraw*", ATTRS{idVendor}=="2e8a", ATTRS{idProduct}=="c001", MODE="0660", TAG+="uaccess"
```

| # | Test id | What it checks | Flash writes |
|---|---------|----------------|--------------|
| 1 | `enumerate` | VID/PID match, usage page `0xFF00` interface found + opened | 0 |
| 2 | `ping` | N × PING → `PONG`, min/avg/max latency | 0 |
| 3 | `info` | GET_INFO fields, `proto_ver` handshake (FAIL on mismatch), fw minor vs host (WARN, or FAIL with `--strict-version`), flags incl. readback bit | 0 |
| 4 | `echo` | ECHO random payloads 0–52 B; corrupted CRC / payload → NAK `EBADMSG` | 0 |
| 5 | `malformed` | unknown cmds → `EINVAL`, bad magic → `EBADMSG`, bad version / length 53 → `EINVAL`, seq echo, `FLAG_RESPONSE` frames ignored, short report → `EBADMSG` (Linux) | 0 |
| 6a | `profile` | PROFILE_GET ×5, PROFILE_READ, BEGIN/DATA validation, ABORT mid-upload, incomplete / bad-CRC / bad-schema COMMIT rejected, slot unchanged | 0 |
| 6b | `profile_roundtrip` | back up slot (READ) → upload test blob → GET crc + READ byte-compare → restore original | 2 (needs `--allow-flash-write`) |
| 7a | `macro` | same for macros + `EBUSY` mutex both ways, SAVE_ALL `EBUSY` while uploading | 0 |
| 7b | `macro_roundtrip` | macro backup → upload → verify → restore | 2 (needs `--allow-flash-write`) |
| 8 | `active` | SET_ACTIVE / GET_ACTIVE over all 5 slots, GET_INFO agrees, bad slot → `EINVAL`, original restored | 0 on fw 0.23+ (debounced persist skipped when unchanged) |
| 9 | `save_all` | SAVE_ALL OK, RAM unchanged | 1 (needs `--allow-flash-write`) |
| 10 | `interactive` | `--interactive`: shows each key / encoder action from device readback, tester answers y/n/s/q | 0 |
| 11 | `restore_check` | active slot + all 5 profile / 5 macro CRCs equal the start snapshot | 0 |

Exit code 0 = no FAIL, 1 = FAIL, 2 = no device. Attach the `--json` report to
the sign-off. Every COMMIT and SAVE_ALL erases + programs the storage sector,
so keep `--allow-flash-write` runs occasional (one full run = 5 sector writes).
Key presses on IF0 are not auto-captured (Windows/macOS own keyboard HID
interfaces), hence the guided checklist.

## Flash / boot

- [ ] UF2 copies cleanly; device reboots as HID (keyboard + config IF1)
- [ ] UART (if wired): boot / `stor load …` lines look healthy
- [ ] *(HIL `info`)* Connect / Get device info: fw **0.23** (or expected), **proto v1**, product `MACROPAD`
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
- [ ] *(HIL `macro`)* Overlapping upload rejected (`EBUSY`)
- [ ] If fw minor < 16/17: upload actions disabled with tooltip (compat path)

## Autoswitch

- [ ] Connect first; Device → Auto-switch enabled
- [ ] Foreground app matching a rule sends `SET_ACTIVE`; OLED/slot change
- [ ] Status bar shows `Auto-switch: <profile> (…)`
- [ ] Disconnect / unplug stops cleanly (no crash loop)
- [ ] If fw minor < 18: autoswitch toggle disabled with tooltip

## Save debounce / SAVE_ALL

- [ ] Rapid autoswitch / SET_ACTIVE: no per-switch flash thrash; after ~4 s quiet UART `stor debounce save` then `stor save ok` (if UART); returning to the slot already in flash prints `stor debounce skip (unchanged)` (fw 0.23+)
- [ ] Device → Save device state (`SAVE_ALL` 0x32): immediate persist; survives unplug/replug
- [ ] Active slot after reboot matches last saved / debounced value

## Sign-off

| Field | Value |
|-------|--------|
| Tester | |
| Date (Asia/Manila) | |
| Firmware UF2 / commit | |
| Host app version | |
| `hil_test.py` summary / JSON | |
| Pass / fail notes | |
