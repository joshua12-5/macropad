# Macro step schema (firmware Step 9)

Built-in macros live in `firmware/src/macros.c` as packed RAM/ROM step tables.
A future configurator can emit the same layout into flash or a host download.

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
