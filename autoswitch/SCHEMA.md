# Auto-switch rules schema (v1)

Host-side rules that map the foreground application to a macropad profile
slot. The **configurator** polls the OS, matches rules, and sends USB
`SET_ACTIVE` (`0x30`). The device cannot see host apps — auto-switch only
works while the configurator (or another host agent) is running.

`SET_ACTIVE` switches the profile in RAM and on the OLED immediately. The device
writes the new slot to flash only once it has stayed unchanged for 4 s
(`STORAGE_ACTIVE_DEBOUNCE_MS`), and skips the write if flash already holds it,
so frequent switches do not wear flash.

## File

Default path: `autoswitch/rules.json` in the repo when running from source, or in the
per-user data folder for release builds (see [`docs/USER_GUIDE.md`](../docs/USER_GUIDE.md#where-your-data-lives)).
Override with env `MACROPAD_AUTOSWITCH_PATH`.

## Top-level object

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `schema_version` | int | `1` | Must be `1` |
| `enabled` | bool | `false` | Master switch (also toggled from Device menu) |
| `poll_ms` | int | `750` | Poll interval (clamped ~100–10000) |
| `fallback_profile_id` | string \| null | `null` | Used when no rule matches |
| `rules` | array | `[]` | First match wins |

## Rule object

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `profile_id` | string | yes | Host profile id (e.g. `coding`) |
| `process` | string[] | yes | Case-insensitive **substring** match on process **basename** |
| `title_regex` | string \| null | no | Optional `re.search` against window title |
| `slot` | int \| null | no | Explicit device slot `0..4`; else built-in map / host list index |

## Matching

1. Obtain foreground `{process, title}` (best-effort; failure → no change).
2. For each rule in order: if any `process` entry is a case-insensitive
   substring of the process basename, and `title_regex` is null or matches
   the title via `re.search`, the rule wins.
3. Else if `fallback_profile_id` is set, use that.
4. Else leave the device slot unchanged.

## Slot resolution

1. `rule.slot` if present and in `0..4`.
2. Else built-in map: `default=0`, `gaming=1`, `coding=2`, `browser=3`,
   `photoshop=4`.
3. Else index of `profile_id` in the host profile list (if provided).
