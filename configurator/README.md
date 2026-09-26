# Macropad Configurator

PySide6 desktop app for editing host-side profile JSON (schema v1).

**Step 11** — editable key/encoder action forms, profile name/OLED title, Save / Save All.

Macro sequence editor and profile create/delete are Steps 12–13. USB upload is Steps 15–16.

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

### Edit & save

1. Select a profile on the left.
2. Edit **Name** / **OLED** in the right header (marks the profile dirty).
3. Click a key (1–12) or encoder slot; change **Type** and type-specific fields.
4. Changes **auto-apply** into the in-memory profile; status bar shows *Modified*.
5. **File → Save** (`Ctrl+S`) writes the current profile JSON; **Save All** writes every dirty profile.
6. Reload / quit prompts if unsaved changes remain.

### Headless tests

```bash
python scripts/smoke_load.py
python scripts/smoke_edit.py
```

(`QT_QPA_PLATFORM=offscreen` is optional; these scripts do not require a display.)

## Layout

| Area | Content |
|------|---------|
| Left | Profile list (`profiles/*.json`) |
| Center | OLED title mock, 3×4 keys (type captions), encoder slots |
| Right | Name / OLED fields, **ActionEditor**, read-only action JSON mirror |

## ActionEditor types

`DISABLED`, `KEY`, `SHORTCUT` (mods + key), `MACRO` (0–4), `TEXT` / `URL` / `APP` (`text_id` 0–7), `MEDIA` (code / usage), `VOLUME`, `PROFILE` (slot / id).

## Packaging note

Optional: `pip install pyinstaller` then build a one-file binary if desired.
