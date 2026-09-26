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

| `type` | Payload |
|--------|---------|
| `DISABLED` | — |
| `KEY` | `key` |
| `SHORTCUT` | `mods[]`, `key` |
| `MACRO` | `macro_id` (Step 9) |
| `TEXT` | `text` / `text_id` |
| `MEDIA` | `code` or `usage` |
| `VOLUME` | `dir`: `up` / `down` / `mute` |
| `APP` | reserved |
| `URL` | reserved |
| `PROFILE` | `profile_id` or slot index |

Firmware currently ships packed C copies of these five profiles; JSON is the host/library form for the configurator.
