# Profile JSON Schema (version 1)

Matches firmware `PROFILE_SCHEMA_VERSION` in `firmware/include/profile_schema.h`.

## Top level

| Field | Type | Notes |
|-------|------|--------|
| `schema_version` | number | Must be `1` |
| `id` | string | Stable id (`coding`) |
| `name` | string | Display name |
| `oled` | object | `title`, `animation` |
| `keys` | object | `"1"`..`"12"` → action |
| `encoder` | object | `cw`, `ccw`, `press`, `long_press` |

## Action object

| `type` | Payload | Firmware behavior (Step 8) |
|--------|---------|----------------------------|
| `DISABLED` | — | No-op |
| `KEY` | `key` | Held via matrix HID report |
| `SHORTCUT` | `mods[]`, `key` | Held via matrix HID report |
| `MACRO` | `macro_id` | OLED toast + UART; Step 9 sequencing hooks via `macros_fire()` |
| `TEXT` | `text_id` | Types string from firmware `text_table` over USB HID (non-blocking) |
| `MEDIA` | `code` or `usage` | Consumer HID pulse; OLED shows short label when known |
| `VOLUME` | `dir`: `up` / `down` / `mute` | Consumer volume |
| `APP` | `text_id` / `app_id` | Types launch string from text table + Enter (best-effort; true OS launch needs host helper later) |
| `URL` | `text_id` | Types URL from text table + Enter |
| `PROFILE` | `profile_id` or slot index | Switch active profile slot |

### ID fields

- **`text_id`**: index into firmware `text_table` (shared by TEXT / URL / APP).
- **`macro_id`**: reserved for Step 9 macro engine.
- **`app_id`**: treated as `text_id` in Step 8 (launch string + Enter).

Firmware ships packed C copies of five profiles; JSON is the host/library form for the configurator.

### Built-in text table (firmware)

| id | String |
|----|--------|
| 0 | `Hello` |
| 1 | `https://github.com/joshua12-5/macropad` |
| 2 | `git status\n` |
| 3 | `console.log(` |
| 4 | `notepad` |
| 5 | `calc` |
| 6 | `Hello, World!` |
| 7 | `ls -la\n` |
