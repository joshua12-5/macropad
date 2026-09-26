# Macropad Configurator

PySide6 desktop app for editing host-side profile JSON, the macro library (schema v1), and talking to the device over the **Step 15 USB config protocol**.

**Steps 10–15** cover the configurator shell through vendor-HID Connect/Info. **Upload to device** / flash storage is **Step 16+**.

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

Optional `hid` (cython-hidapi) is listed in `requirements.txt` for Device → Connect. The app still launches if `hid` is missing; Connect then shows a clear error.

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

### Device (Step 15)

| Action | UI | Notes |
|--------|-----|--------|
| **Connect / Get device info** | **Device → Connect / Get device info** (`Ctrl+Shift+I`) | Opens vendor HID (VID `0x2E8A` / PID `0xC001` / usage page `0xFF00`), sends PING + GET_INFO, shows a dialog + status bar. |
| **Upload to device** | Disabled | Tooltip: Step 16+ |

Protocol details: [`../protocol/PROTOCOL.md`](../protocol/PROTOCOL.md).

### Headless tests

```bash
python scripts/smoke_load.py
python scripts/smoke_edit.py
python scripts/smoke_profile_mgr.py
python scripts/smoke_macros.py
python scripts/smoke_protocol.py
```

(`QT_QPA_PLATFORM=offscreen` is optional; these scripts do not require a display. `smoke_protocol.py` needs no hardware.)

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
