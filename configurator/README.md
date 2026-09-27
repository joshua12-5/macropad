# Macropad Configurator

PySide6 desktop app (version **0.25.0**) for editing host-side profile JSON, the macro library (schema v1),
auto-switch rules and OLED idle animations, and for talking to the device over the **USB config protocol**
(uploads, auto-switch, save, readback, animations). Prebuilt Windows / macOS / Linux bundles are on the
[Releases page](https://github.com/joshua12-5/macropad/releases).
Architecture: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md). Versions: [`../docs/VERSIONING.md`](../docs/VERSIONING.md).

## Hardware-in-the-loop tests

```bash
cd configurator
pip install -r requirements.txt          # includes `hidapi` (native lib bundled in the wheel)
python scripts/hil_test.py --list        # VID 0x2E8A / PID 0xC001 interfaces; CONFIG = usage page 0xFF00
python scripts/hil_test.py               # flash-free suite (safe to run any time)
python scripts/hil_test.py --allow-flash-write --json hil-report.json   # + COMMIT round-trips + SAVE_ALL
python scripts/hil_test.py --interactive # + guided key / encoder checklist
python scripts/hil_test.py --mock --allow-flash-write                   # no hardware (CI uses this)
```

Ordered tests: enumerate, ping (latency), info (version handshake), echo (+ CRC
injection), malformed frames, profile / macro upload protocol, profile / macro
round-trip with backup + restore, SET_ACTIVE cycle, SAVE_ALL, animation info /
protocol / preview / settings / round-trip (fw 0.25+), interactive checklist, restore check. Round-trips and SAVE_ALL write flash and are SKIPPED
unless `--allow-flash-write`. See [`../docs/HARDWARE_TEST.md`](../docs/HARDWARE_TEST.md).

## Run

```bash
cd configurator
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m macropad_config
```

Profiles load from `../profiles/*.json` by default (repo root `profiles/`).
Override with:

```bash
export MACROPAD_PROFILES_DIR=/path/to/profiles
python -m macropad_config
```

Macro library loads from `../macros/library.json` (override with `MACROPAD_MACROS_PATH`).

Optional `hid` (cython-hidapi) is listed in `requirements.txt` for Device menu actions. The app still launches if `hid` is missing; Connect/Upload then show a clear error.

### Edit & save profiles

1. Select a profile on the left.
2. Edit **Name** / **OLED** in the right header (marks the profile dirty).
3. Click a key (1–12) or encoder slot; change **Type** and type-specific fields.
4. Changes **auto-apply** into the in-memory profile; status bar shows *Modified*.
5. **File → Save** (`Ctrl+S`) writes the current profile JSON; **Save All** writes every dirty profile.
6. Reload / quit prompts if unsaved changes remain.

### Profile manager

| Action | UI | Notes |
|--------|-----|--------|
| **New…** | Profile list buttons or **Profile → New…** (`Ctrl+N`) | Dialog: Name (required) + Id (auto from name, editable). Blank profile (all keys DISABLED; encoder volume up/down/mute). Marked dirty until Save. |
| **Duplicate…** | Buttons or **Profile → Duplicate…** (`Ctrl+D`) | Deep-copies the selected profile with a new name/id. |
| **Delete…** | Buttons or **Profile → Delete…** | Confirms; removes JSON from disk if saved; warns if it would empty the list. |

Id rules: non-empty, unique among loaded profiles, pattern `^[a-z][a-z0-9_]*$`.

### Macro library editor

**Profile → Macro library…** opens a dialog to edit `macros/library.json`.

### Device

| Action | UI | Notes |
|--------|-----|--------|
| **Connect / Get device info** | **Device → Connect / Get device info** (`Ctrl+Shift+I`) | Opens vendor HID (VID `0x2E8A` / PID `0xC001` / usage page `0xFF00`), sends PING + GET_INFO, shows a dialog + status bar. |
| **Upload profile to device…** | **Device → Upload profile to device…** (`Ctrl+Shift+U`) | Packs the **selected** profile to `profile_blob_v1` (148 B), asks for slot **0–4** (defaults to last GET_INFO active slot, or built-in id map `default/gaming/coding/browser/photoshop` → 0..4), then BEGIN/DATA/COMMIT. |
| **Upload macros to device…** | **Device → Upload macros to device…** (`Ctrl+Shift+M`) | Packs `macros/library.json` ids **0–4** to `macro_blob_v1` (162 B each), uploads in order; skips missing ids; status bar + message box report count. |
| **Auto-switch…** | **Tools → Auto-switch…** | Edit `autoswitch/rules.json` (enable, poll_ms, fallback, rules table). |
| **Auto-switch enabled** | **Device → Auto-switch enabled** (checkable) | Needs a prior Connect. Polls foreground app; sends `SET_ACTIVE`. Status: `Auto-switch: coding (Code)`. Disconnect mid-run stops cleanly (one reconnect attempt). |
| **Save device state** | **Device → Save device state** | `SAVE_ALL` (`0x32`) when connected — immediate flash rewrite. |

Connect / Get info shows **host app**, **fw major.minor**, and **proto_ver**. If `proto_ver` ≠ host `PROTO_VER`, a **warning** dialog appears and upload / autoswitch / SAVE_ALL stay disabled. Firmware too old for a feature disables that action with a tooltip (see `macropad_config/version.py`).
Help → About lists host **0.25.0**, proto, expected fw, schema versions.
Tools/Help tip points at `docs/ARCHITECTURE.md` / `docs/VERSIONING.md`.

Protocol details: [`../docs/PROTOCOL.md`](../docs/PROTOCOL.md).
Blob layout: [`../docs/PROFILE_BLOB.md`](../docs/PROFILE_BLOB.md).

### Headless tests

```bash
python scripts/run_all_smokes.py
# or individually:
python scripts/smoke_version.py
python scripts/smoke_load.py
python scripts/smoke_edit.py
python scripts/smoke_profile_mgr.py
python scripts/smoke_macros.py
python scripts/smoke_editor_forms.py # action editor / macro step rows per type, macro library dirty tracking
python scripts/smoke_protocol.py
python scripts/smoke_storage.py
python scripts/smoke_macros_blob.py
python scripts/smoke_autoswitch.py
python scripts/smoke_hil_mock.py
python scripts/smoke_packaging.py
python scripts/smoke_anim_codec.py    # MPAN codec vs compiled firmware anim_codec.c, presets, GIF, imaging
python scripts/smoke_anim_device.py   # ANIM_* protocol vs mock (+ seeded bugs), editor GUI
```

14 smokes in total (`run_all_smokes.py`). (`QT_QPA_PLATFORM=offscreen` is optional; these scripts do not require a display. Protocol/storage/autoswitch smokes need no hardware.)

### Auto-switch

Host watches the foreground process (Windows ctypes / Linux xdotool+/proc /
macOS osascript), matches [`../autoswitch/rules.json`](../autoswitch/rules.json),
and sends USB `SET_ACTIVE` (`0x30`). **RAM + OLED only** on the device (no flash
wear). The device cannot see host apps — keep the configurator running.
Override rules path with `MACROPAD_AUTOSWITCH_PATH`.

## Layout

| Area | Content |
|------|---------|
| Left | Profile list + New / Duplicate / Delete |
| Center | OLED title mock, 3×4 keys (type captions), encoder slots |
| Right | Name / OLED fields, **ActionEditor**, read-only action JSON mirror |

### Idle animation editor

**Tools → Idle animation…** opens the OLED idle-animation editor. Authoring works offline;
device actions need firmware **0.25+** (GET_INFO flag bit3) — with older firmware the editor
explains which version to flash and sends nothing.

| Area | What it does |
|------|--------------|
| Frames | thumbnail strip; add / duplicate (`Ctrl+D`) / delete / move / drag-reorder; `[` `]` step |
| Canvas | 128×64 at 2–12× zoom, page grid; pen / eraser (right button = opposite colour), brush 1–8 px; invert, clear, shift ◀▶▲▼ (wrap), onion skin of the previous frame; undo / redo |
| Preview | live playback at the chosen fps (`Space`), OLED-styled |
| Presets | *Starfield (warp)*, *Bouncing text* (default `MACROPAD`), *Scrolling text* (your text), *Pulse / breathing* — generated in `macropad_config/animation/presets.py` |
| Import | animated GIF, PNG/JPEG/BMP sequence (multi-select, natural sort) or a single image → fit (keep aspect, centred) or stretch, threshold or Floyd–Steinberg dithering, invert, replace / append / insert |
| Files | **Save / Open** projects as `*.mpanim.json` in the user data folder (`…/animations/`, override `MACROPAD_ANIMATIONS_DIR`), **Export GIF** (OLED look), **Export .mpan** (the exact device blob) |
| Settings | fps 1–30, loop, play when idle, idle timeout (0 = never), blank timeout (0 = never) |
| Device | **Upload** (progress bar, cancellable, verified by read-back), **Preview on device**, **Built-in demo**, **Stop preview**, **Push idle settings**, **Read from device** |

Formats: [`../docs/ANIMATION.md`](../docs/ANIMATION.md) (blob, project JSON, capacity, timing).

## ActionEditor types

`DISABLED`, `KEY`, `SHORTCUT` (mods + key), `MACRO` (library id), `TEXT` / `URL` / `APP` (`text_id` 0–7), `MEDIA` (code / usage), `VOLUME`, `PROFILE` (slot / id).

## Command line

```bash
python -m macropad_config --version              # "Macropad Configurator 0.25.0 (source; …)"
QT_QPA_PLATFORM=offscreen python -m macropad_config --self-test [--report st.txt]   # exit 0/1
python -m macropad_config --hil --mock           # HIL tool (same as scripts/hil_test.py)
```

Release bundles accept the same flags (`MacropadConfigurator --self-test`).

## Packaging

Release builds come from `.github/workflows/release.yml` (tag `vX.Y.Z`): PyInstaller **one-dir**
bundles via [`../packaging/macropad_configurator.spec`](../packaging/macropad_configurator.spec)
with pinned deps in [`../packaging/requirements-build.txt`](../packaging/requirements-build.txt).
Frozen builds keep profiles / macros / rules in a per-user data dir
(`%APPDATA%\MacropadConfigurator`, `~/Library/Application Support/MacropadConfigurator`,
`~/.local/share/macropad-configurator`; override `MACROPAD_USER_DATA`), seeded from the bundled
defaults on first start. See [`../docs/RELEASE.md`](../docs/RELEASE.md).
