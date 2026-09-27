# Macro step schema (firmware engine + host library)

Built-in macros live in `firmware/src/macros.c` as packed RAM/ROM step tables.
The **host library** (`macros/library.json`) is the configurator source of truth for
editing and labeling macros. Until a USB flash/sync protocol lands (Steps 15–16),
firmware still uses the packed C tables — host JSON and firmware may diverge.

## Step struct (`macro_step_t`)

| Field | Size | Meaning |
|-------|------|---------|
| `op` | u8 | `macro_op_t` opcode |
| `mods` | u8 | HID keyboard modifier bitmap |
| `keycode` | u8 | HID keycode (0 = mods-only / all-up) |
| `pad` | u8 | reserved (0) |
| `arg` | u16 | `delay_ms`, `text_id`, or consumer usage |

## Opcodes

| `op` | Name | Payload |
|------|------|---------|
| 0 | `MACRO_END` | — |
| 1 | `MACRO_KEY_DOWN` | `mods`, `keycode` (held via macro sticky report) |
| 2 | `MACRO_KEY_UP` | `keycode` (0 + mods 0 = release all) |
| 3 | `MACRO_TAP` | `mods`, `keycode` (down then up; ORs sticky mods) |
| 4 | `MACRO_DELAY_MS` | `arg` = milliseconds |
| 5 | `MACRO_TEXT` | `arg` = `text_table` id (shared action typer) |
| 6 | `MACRO_CONSUMER` | `arg` = consumer usage |

## Built-in ids

| id | Name | Summary |
|----|------|---------|
| 0 | `hello` | TAP H,E,L,L,O with short delays |
| 1 | `sel+cpy` | Ctrl+A, delay, Ctrl+C |
| 2 | `undo/redo` | Ctrl+Z, delay, Ctrl+Y |
| 3 | `git st` | `MACRO_TEXT` → `TEXT_ID_GIT_STATUS` |
| 4 | `alt-tab` | Alt down, Tab tap, delay, release |

Profile actions use `"type": "MACRO", "macro_id": N`.

## Playback rules

- One macro at a time; a new `macros_fire` while busy is ignored (UART note).
- Non-blocking: `macros_task()` every ~1 ms.
- Matrix HID updates are skipped while `macros_busy()` or `actions_busy()`.

## Host JSON library

File: [`macros/library.json`](library.json) (override path with `MACROPAD_MACROS_PATH`).

```json
{
  "schema_version": 1,
  "macros": [
    {
      "id": 0,
      "name": "hello",
      "steps": [
        {"op": "TAP", "mods": [], "key": "H"},
        {"op": "DELAY_MS", "arg": 30},
        {"op": "END"}
      ]
    }
  ]
}
```

### Host opcode strings

| JSON `op` | Firmware |
|-----------|----------|
| `END` | `MACRO_END` |
| `KEY_DOWN` | `MACRO_KEY_DOWN` |
| `KEY_UP` | `MACRO_KEY_UP` |
| `TAP` | `MACRO_TAP` |
| `DELAY_MS` | `MACRO_DELAY_MS` |
| `TEXT` | `MACRO_TEXT` |
| `CONSUMER` | `MACRO_CONSUMER` |

### Step fields

| Field | Used by | Notes |
|-------|---------|-------|
| `op` | all | Required string opcode |
| `mods` | `TAP`, `KEY_DOWN`, `KEY_UP` | List of `CTRL` / `SHIFT` / `ALT` / `GUI` (same as profiles). Optional; default `[]`. |
| `key` | `TAP`, `KEY_DOWN`, `KEY_UP` | Letter/name string matching profile KEY style (`A`–`Z`, `TAB`, `ENTER`, …). Empty string `""` or omitted = keycode 0 (mods-only / all-release for `KEY_UP` with empty mods). |
| `arg` | `DELAY_MS`, `TEXT`, `CONSUMER` | Delay ms, `text_id` 0–7, or consumer usage (int or `"0x…. "` hex string). |

Ids are **stable and explicit** (gaps allowed). New macros get `max_id + 1`. The configurator Macro library editor edits this file; ActionEditor MACRO labels load from it when present.
