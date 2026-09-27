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

| `type` | Payload | Firmware behavior |
|--------|---------|----------------------------|
| `DISABLED` | — | No-op |
| `KEY` | `key` | Held via matrix HID report |
| `SHORTCUT` | `mods[]`, `key` | Held via matrix HID report |
| `MACRO` | `macro_id` | Non-blocking playback via `macros_fire()` / `macros_task()` (see `macros/SCHEMA.md`) |
| `TEXT` | `text_id` | Types string from firmware `text_table` over USB HID (non-blocking) |
| `MEDIA` | `code` or `usage` | Consumer HID pulse; OLED shows short label when known |
| `VOLUME` | `dir`: `up` / `down` / `mute` | Consumer volume |
| `APP` | `text_id` / `app_id` | Types launch string from text table + Enter (best-effort; true OS launch needs host helper later) |
| `URL` | `text_id` | Types URL from text table + Enter |
| `PROFILE` | `profile_id` or slot index | Switch active profile slot |

### ID fields

- **`text_id`**: index into firmware `text_table` (shared by TEXT / URL / APP).
- **`macro_id`**: index into the device macro bank (0–4).
- **`app_id`**: treated as `text_id` (launch string + Enter).

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

### Built-in macros (firmware)

| id | Name | Behavior |
|----|------|----------|
| 0 | hello | Types `HELLO` via key taps |
| 1 | sel+cpy | Ctrl+A then Ctrl+C |
| 2 | undo/redo | Ctrl+Z then Ctrl+Y |
| 3 | git st | Types `git status` + newline from text table |
| 4 | alt-tab | Alt down, Tab, release |

Demo bindings: **Default** key 10 → macro 0; **Coding** key 12 → macro 1.
