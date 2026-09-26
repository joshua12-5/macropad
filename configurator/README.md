# Macropad Configurator

PySide6 desktop shell for editing host-side profile JSON (schema v1).

**Step 10** — runnable shell only (profile list, pad preview, read-only action details).
Full action editors, macro editor, and drag-drop land in Steps 11–13. USB upload is Steps 15–16.

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

Headless smoke test (no GUI display required):

```bash
QT_QPA_PLATFORM=offscreen python scripts/smoke_load.py
```

## Layout

| Area | Content |
|------|---------|
| Left | Profile list (`profiles/*.json`) |
| Center | OLED title mock, 3×4 keys, encoder (CW / CCW / press) |
| Right | Profile summary + selected key/encoder action (JSON, read-only) |

## Packaging note

Optional: `pip install pyinstaller` then build a one-file binary if desired.
