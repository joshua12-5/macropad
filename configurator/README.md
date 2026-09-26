# Macropad Configurator

PySide6 desktop app for editing host-side profile JSON, the macro library (schema v1), and talking to the device over the **USB config protocol** (Steps 15–20: framing, uploads, autoswitch, SAVE_ALL, versioning).

**Steps 10–20** cover the configurator through testing / versioning polish. **Next: Step 21** more polish/testing (e.g. release notes or CI stub).
Architecture: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md). Versions: [`../docs/VERSIONING.md`](../docs/VERSIONING.md).

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

### Profile manager (Step 12)

| Action | UI | Notes |
|--------|-----|--------|
| **New…** | Profile list buttons or **Profile → New…** (`Ctrl+N`) | Dialog: Name (required) + Id (auto from name, editable). Blank profile (all keys DISABLED; encoder volume up/down/mute). Marked dirty until Save. |
| **Duplicate…** | Buttons or **Profile → Duplicate…** (`Ctrl+D`) | Deep-copies the selected profile with a new name/id. |
| **Delete…** | Buttons or **Profile → Delete…** | Confirms; removes JSON from disk if saved; warns if it would empty the list. |

Id rules: non-empty, unique among loaded profiles, pattern `^[a-z][a-z0-9_]*$`.

### Macro library editor (Step 13)

**Profile → Macro library…** opens a dialog to edit `macros/library.json`.

### Device (Step 15–20)

| Action | UI | Notes |
|--------|-----|--------|
| **Connect / Get device info** | **Device → Connect / Get device info** (`Ctrl+Shift+I`) | Opens vendor HID (VID `0x2E8A` / PID `0xC001` / usage page `0xFF00`), sends PING + GET_INFO, shows a dialog + status bar. |
| **Upload profile to device…** | **Device → Upload profile to device…** (`Ctrl+Shift+U`) | Packs the **selected** profile to `profile_blob_v1` (148 B), asks for slot **0–4** (defaults to last GET_INFO active slot, or built-in id map `default/gaming/coding/browser/photoshop` → 0..4), then BEGIN/DATA/COMMIT. |
| **Upload macros to device…** | **Device → Upload macros to device…** (`Ctrl+Shift+M`) | Packs `macros/library.json` ids **0–4** to `macro_blob_v1` (162 B each), uploads in order; skips missing ids; status bar + message box report count. |
| **Auto-switch…** | **Tools → Auto-switch…** | Edit `autoswitch/rules.json` (enable, poll_ms, fallback, rules table). |
| **Auto-switch enabled** | **Device → Auto-switch enabled** (checkable) | Needs a prior Connect. Polls foreground app; sends `SET_ACTIVE`. Status: `Auto-switch: coding (Code)`. Disconnect mid-run stops cleanly (one reconnect attempt). |
| **Save device state** | **Device → Save device state** | `SAVE_ALL` (`0x32`) when connected — immediate flash rewrite. |

Connect / Get info shows **host app**, **fw major.minor**, and **proto_ver**. If `proto_ver` ≠ host `PROTO_VER`, a **warning** dialog appears and upload / autoswitch / SAVE_ALL stay disabled. Firmware too old for a feature disables that action with a tooltip (see `macropad_config/version.py`).
Help → About lists host **0.21.0**, proto, expected fw, schema versions.
Tools/Help tip points at `docs/ARCHITECTURE.md` / `docs/VERSIONING.md`.

Protocol details: [`../protocol/PROTOCOL.md`](../protocol/PROTOCOL.md).
Blob layout: [`../protocol/PROFILE_BLOB.md`](../protocol/PROFILE_BLOB.md).

Macro flash upload is implemented (Step 17).

### Headless tests

```bash
python scripts/run_all_smokes.py
# or individually:
python scripts/smoke_version.py
python scripts/smoke_load.py
python scripts/smoke_edit.py
python scripts/smoke_profile_mgr.py
python scripts/smoke_macros.py
python scripts/smoke_protocol.py
python scripts/smoke_storage.py
python scripts/smoke_macros_blob.py
python scripts/smoke_autoswitch.py
```

(`QT_QPA_PLATFORM=offscreen` is optional; these scripts do not require a display. Protocol/storage/autoswitch smokes need no hardware.)

### Auto-switch (Step 18)

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

## ActionEditor types

`DISABLED`, `KEY`, `SHORTCUT` (mods + key), `MACRO` (library id), `TEXT` / `URL` / `APP` (`text_id` 0–7), `MEDIA` (code / usage), `VOLUME`, `PROFILE` (slot / id).

## Packaging note

Optional: `pip install pyinstaller` then build a one-file binary if desired.
