# Macropad Configurator

PySide6 desktop app (version **0.26.0**) for editing host-side profile JSON, the macro library (schema v1),
auto-switch rules and OLED idle animations, and for talking to the device over the **USB config protocol**
(uploads, auto-switch, save, readback, animations). Prebuilt Windows / macOS / Linux bundles are on the
[Releases page](https://github.com/joshua12-5/macropad/releases).
Architecture: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md). Versions: [`../docs/VERSIONING.md`](../docs/VERSIONING.md).

## Hardware-in-the-loop tests

```bash
cd configurator
pip install -r requirements.txt          # includes `hidapi` (native lib bundled in the wheel)
python scripts/hil_test.py --list        # VID 0x2E8A / PID 0xC001 interfaces; CONFIG = usage page 0xFF00
python scripts/hil_test.py               # flash-free suite (safe to run any time)
python scripts/hil_test.py --allow-flash-write --json hil-report.json   # + COMMIT round-trips + SAVE_ALL
python scripts/hil_test.py --interactive # + guided key / encoder checklist
python scripts/hil_test.py --mock --allow-flash-write                   # no hardware (CI uses this)
```

Ordered tests: enumerate, ping (latency), info (version handshake), echo (+ CRC
injection), malformed frames, profile / macro upload protocol, profile / macro
round-trip with backup + restore, SET_ACTIVE cycle, SAVE_ALL, animation info /
protocol / preview / settings / round-trip (fw 0.25+), interactive checklist, restore check. Round-trips and SAVE_ALL write flash and are SKIPPED
unless `--allow-flash-write`. See [`../docs/HARDWARE_TEST.md`](../docs/HARDWARE_TEST.md).

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

Optional `hid` (cython-hidapi) is listed in `requirements.txt` for device actions. The app still launches if `hid` is missing; Connect/Upload then show a clear error.

### Pages and navigation

The window is a **navigation rail** (`pages/nav.py`: `NavRail`, `PageHeader`) plus a stacked
page area. Every page has a header with its title, a breadcrumb (`CODING › Key 6`,
`Library › hello`, `MACROPAD › fw 0.26`…), a **• Unsaved** badge and page-specific actions.

| Page | Shortcut | Widget | Contents |
|------|----------|--------|----------|
| **Keys** | `Ctrl+1` | `keysPage` in `main_window.py` | profile list, drawn device (`widgets/pad_preview.py`), inspector (Name / OLED title, `ActionEditor`, JSON mirror); empty state when no profiles |
| **Macros** | `Ctrl+2` | `widgets/macro_library_dialog.py` `MacroLibraryDialog(embedded=True)` | macro list, steps table, step editor, Revert / Save; empty state |
| **Idle** | `Ctrl+3` | `widgets/anim_editor.py` `AnimationEditorDialog(embedded=True)` | frames, canvas (zoom fits the window), presets, import, device section |
| **Auto-switch** | `Ctrl+4` | `widgets/autoswitch_dialog.py` `AutoswitchDialog(embedded=True)` | enable, poll interval, fallback, rules table, Revert / Save; empty state |
| **Device** | `Ctrl+5` | `pages/device_page.py` | connect / GET_INFO (`widgets/info_panels.py`), uploads, Save device state, auto-switch toggle, **Back up device / Restore backup** (`device_backup.py`), firmware update status + links |
| **Settings** | `Ctrl+6` | `pages/settings_page.py` | theme, data folders (open in the file manager), shortcut list, About |

The embedded editors keep their dialog classes (and tests) but run as pages: no window chrome,
Esc / Enter do nothing, `dirtyChanged` drives the rail dot / badge, and `save()` / `revert()`
back the header buttons and the page-aware **File → Save** (`Ctrl+S`). Menu entries from
earlier versions (**Profile → Macro library**, **Tools → Idle animation / Auto-switch rules**,
**Help → About**, **View → Go to**) switch pages. Real modal dialogs are left for
confirmations, file pickers, the new-profile / upload-slot prompts, the GIF import options and
errors; success messages go to the status bar.

**Command palette** (`pages/palette.py`, `Ctrl+K` or the header search box): fuzzy search over
pages, profiles, `Key 1`–`Key 12`, the encoder slots, every menu action (disabled ones listed
with the reason) and the theme toggle. Contiguous matches and word starts rank first, then
in-order subsequences (`k6`, `upmac`). `↑` / `↓` / `Tab` / `Ctrl+N` / `Ctrl+P` move, `Enter`
runs, `Esc` or `Ctrl+K` closes.

**Keyboard:** `Ctrl+1`…`Ctrl+6` pages, `Ctrl+K` palette, `Ctrl+Tab` / `Ctrl+Shift+Tab` next /
previous profile (wraps), arrow keys on the device drawing, `Ctrl+S` save page,
`Ctrl+Shift+S` save all profiles, `Ctrl+N` / `Ctrl+D` new / duplicate profile (`Ctrl+D` belongs
to the frame editor on the Idle page), `Ctrl+O`, `Ctrl+R`, `Ctrl+Shift+I` connect,
`Ctrl+Shift+U` / `Ctrl+Shift+M` uploads, `Ctrl+Shift+L` theme, `F1` user guide. Tooltips and
menus show the shortcut; Settings lists them all (`MainWindow.shortcut_list()`).

**Unsaved changes:** rail dot per page, header badge, a dot after each dirty profile
(`ProfileList.set_dirty_ids`), `*` in the window title; quitting lists every dirty area.

### Edit & save profiles

1. Select a profile on the left (or `Ctrl+Tab`).
2. Edit **Name** / **OLED title** at the top of the right-hand inspector (marks the profile dirty).
3. Click a keycap (1–12), the knob or an encoder slot (Turn left / Turn right / Press); change
   **Type** and type-specific fields. The encoder's `long_press` field is **reserved** (holding
   the knob opens the on-device menu): it is not shown, and whatever the file holds is kept.
4. Changes **auto-apply** into the in-memory profile; the unsaved markers appear.
5. **File → Save** (`Ctrl+S`) writes the current profile JSON; **Save all profiles** writes every dirty profile.
6. Reload / quit prompts if unsaved changes remain.

### Profile manager

| Action | UI | Notes |
|--------|-----|--------|
| **New…** | **+** icon above the profile list or **Profile → New…** (`Ctrl+N`) | Dialog: Name (required) + Id (auto from name, editable). Blank profile (all keys DISABLED; encoder volume up/down/mute). Marked dirty until Save. |
| **Duplicate…** | Copy icon or **Profile → Duplicate…** (`Ctrl+D`) | Deep-copies the selected profile with a new name/id. |
| **Delete…** | Trash icon or **Profile → Delete…** | Confirms; removes JSON from disk if saved; warns if it would empty the list. |

Id rules: non-empty, unique among loaded profiles, pattern `^[a-z][a-z0-9_]*$`.

### Device

| Action | UI | Notes |
|--------|-----|--------|
| **Connect / Get device info** | **Connect** in the header, **Device → Connect / Get device info** (`Ctrl+Shift+I`), or the Device page | Opens vendor HID (VID `0x2E8A` / PID `0xC001` / usage page `0xFF00`), sends PING + GET_INFO, shows the result on the Device page and updates the status bar. A failure shows the page's "no macropad" state (no pop-up). |
| **Upload profile to device…** | **Upload** in the Keys header, **Device → Upload profile to device…** (`Ctrl+Shift+U`), Device page | Packs the **selected** profile to `profile_blob_v1` (148 B), asks for slot **0–4** (defaults to last GET_INFO active slot, or built-in id map `default/gaming/coding/browser/photoshop` → 0..4), then BEGIN/DATA/COMMIT. |
| **Upload macros to device…** | **Upload macros** in the Macros header, **Device → Upload macros to device…** (`Ctrl+Shift+M`), Device page | Offers to save a dirty library first, packs ids **0–4** to `macro_blob_v1` (162 B each), uploads in order; skips missing ids; the count goes to the status bar. |
| **Auto-switch enabled** | **Device → Auto-switch enabled** (checkable) or the Device page toggle | Needs a prior Connect. Polls foreground app; sends `SET_ACTIVE`. Status: `Auto-switch: coding (Code)`. Disconnect mid-run stops cleanly (one reconnect attempt). Rules live on the Auto-switch page. |
| **Save device state** | **Device → Save device state**, Device page | `SAVE_ALL` (`0x32`) — immediate flash rewrite. |
| **Back up device…** | **Device → Back up device…**, Device page | fw 0.23+ (readback): `PROFILE_READ` ×5, `MACRO_READ` ×5, active slot, idle settings (fw 0.25+) → one `*.mpbackup.json` (format `macropad-device-backup` v1, `device_backup.py`). |
| **Restore backup…** | **Device → Restore backup…**, Device page | Validates every blob (size, unpack) first, confirms, uploads profiles + macros, sets idle settings and the active slot, then `SAVE_ALL`. |

If `proto_ver` ≠ host `PROTO_VER`, the Device page warns and upload / autoswitch / SAVE_ALL /
backup stay disabled. Firmware too old for a feature disables that action with a tooltip (see
`macropad_config/version.py`). The Device page's firmware section compares the connected
firmware with the expected **0.26** and links to the update guide and releases.

Protocol details: [`../docs/PROTOCOL.md`](../docs/PROTOCOL.md).
Blob layout: [`../docs/PROFILE_BLOB.md`](../docs/PROFILE_BLOB.md).

### Headless tests

```bash
python scripts/run_all_smokes.py
# or individually:
python scripts/smoke_version.py
python scripts/smoke_load.py
python scripts/smoke_edit.py
python scripts/smoke_profile_mgr.py
python scripts/smoke_macros.py
python scripts/smoke_editor_forms.py # action editor / macro step rows per type, macro library dirty tracking
python scripts/smoke_protocol.py
python scripts/smoke_storage.py
python scripts/smoke_macros_blob.py
python scripts/smoke_autoswitch.py
python scripts/smoke_hil_mock.py
python scripts/smoke_packaging.py
python scripts/smoke_anim_codec.py    # MPAN codec vs compiled firmware anim_codec.c, presets, GIF, imaging
python scripts/smoke_anim_device.py   # ANIM_* protocol vs mock (+ seeded bugs), editor GUI
python scripts/smoke_theme.py         # theme in dark + light: QSS tokens, palette contrast, icons resolve, every page renders
python scripts/smoke_oled_menu.py     # firmware OLED menu built with the host cc: navigation, timeout, toasts, persist; --out DIR → 4x PNGs
python scripts/smoke_nav.py           # pages, Ctrl+1..6, menus → pages, breadcrumbs, unsaved markers, empty states, profile cycling, backup / restore
python scripts/smoke_palette.py       # command palette: fuzzy ranking, Ctrl+K / Esc, keyboard nav, running and disabled items
```

18 smokes in total (`run_all_smokes.py`). (`QT_QPA_PLATFORM=offscreen` is optional; these scripts do not require a display. Protocol/storage/autoswitch smokes need no hardware.)

### Auto-switch

Host watches the foreground process (Windows ctypes / Linux xdotool+/proc /
macOS osascript), matches [`../autoswitch/rules.json`](../autoswitch/rules.json),
and sends USB `SET_ACTIVE` (`0x30`). Switches are instant (RAM + OLED); the device
saves the slot to flash only after it has been stable for 4 s, so rapid switching does not wear flash. The device cannot see host apps — keep the configurator running.
Override rules path with `MACROPAD_AUTOSWITCH_PATH`.

## Layout

| Area | Content |
|------|---------|
| Rail (left) | Keys · Macros · Idle · Auto-switch · Device, then the theme toggle and Settings at the bottom; dot = unsaved changes |
| Header | page title, breadcrumb, **• Unsaved**, search box (`Ctrl+K`), page actions (Save, Connect, primary **Upload** / **Upload macros**) |
| Keys page | profile list (name, id, **Slot N** badge, accent dot on the active device slot, unsaved dot) · drawn device (OLED preview, knob, 3×4 keycaps, encoder chips Turn left / Turn right / Press) · inspector |
| Status bar | messages on the left; connection pill (click → Device page), firmware and protocol version on the right |

Modules: `main_window.py` (shell, menus, actions, palette items), `pages/` (`nav.py`,
`palette.py`, `common.py`, `device_page.py`, `settings_page.py`), `widgets/` (profile list, pad
preview, action editor, macro / auto-switch / animation editors, `info_panels.py`, dialogs),
`device_backup.py`, `ui/` (theme, icons, shared widgets such as `EmptyState`).

### Theme

`macropad_config/ui/theme.py` + `ui/theme.qss` hold the single hand-written stylesheet. The QSS
is a template: `{{token}}` placeholders come from the dark / light palettes in `theme.py`,
`{{icon:name:role}}` renders a vendored SVG in a palette colour. **View → Theme** or the Settings page picks
*Match system* (default), *Dark* or *Light* (saved in QSettings; `MACROPAD_THEME=dark|light`
overrides it for a run); **View → Toggle dark / light** is `Ctrl+Shift+L`. Icons are
[Lucide](https://lucide.dev) SVGs (ISC, see `ui/icons/LICENSE`), recoloured per theme. Shared
helpers (dividers, form styling, table polish, icon buttons, status pill) are in
`ui/widgets.py`. `smoke_theme.py` checks both modes.

### Idle animation editor

The **Idle** page (`Ctrl+3`, **Tools → Idle animation**) is the OLED idle-animation editor. Authoring works offline;
device actions need firmware **0.25+** (GET_INFO flag bit3) — with older firmware the editor
explains which version to flash and sends nothing.

| Area | What it does |
|------|--------------|
| Frames | thumbnail strip; add / duplicate (`Ctrl+D`) / delete / move up·down (icon buttons) / drag-reorder; `[` `]` step |
| Canvas | 128×64 at 2–12× zoom (fits the page until you pick a zoom), page grid; pen / eraser (right button = opposite colour), brush 1–8 px; invert, clear, shift left / right / up / down (wrap), onion skin of the previous frame; undo / redo |
| Preview | live playback at the chosen fps (`Space`), OLED-styled |
| Presets | *Starfield (warp)*, *Bouncing text* (default `MACROPAD`), *Scrolling text* (your text), *Pulse / breathing* — generated in `macropad_config/animation/presets.py` |
| Import | animated GIF, PNG/JPEG/BMP sequence (multi-select, natural sort) or a single image → fit (keep aspect, centred) or stretch, threshold or Floyd–Steinberg dithering, invert, replace / append / insert |
| Files | **Save / Open** projects as `*.mpanim.json` in the user data folder (`…/animations/`, override `MACROPAD_ANIMATIONS_DIR`), **Export GIF** (OLED look), **Export .mpan** (the exact device blob) |
| Settings | fps 1–30, loop, play when idle, idle timeout (0 = never), blank timeout (0 = never) |
| Device | **Upload** (progress bar, cancellable, verified by read-back), **Preview on device**, **Built-in demo**, **Stop preview**, **Push idle settings**, **Read from device** |

Formats: [`../docs/ANIMATION.md`](../docs/ANIMATION.md) (blob, project JSON, capacity, timing).

## ActionEditor types

`DISABLED`, `KEY`, `SHORTCUT` (mods + key), `MACRO` (library id), `TEXT` / `URL` / `APP` (`text_id` 0–7), `MEDIA` (code / usage), `VOLUME`, `PROFILE` (slot / id).

## Command line

```bash
python -m macropad_config --version              # "Macropad Configurator 0.26.0 (source; …)"
QT_QPA_PLATFORM=offscreen python -m macropad_config --self-test [--report st.txt]   # exit 0/1
python -m macropad_config --hil --mock           # HIL tool (same as scripts/hil_test.py)
```

Release bundles accept the same flags (`MacropadConfigurator --self-test`).

## Packaging

Release builds come from `.github/workflows/release.yml` (tag `vX.Y.Z`): PyInstaller **one-dir**
bundles via [`../packaging/macropad_configurator.spec`](../packaging/macropad_configurator.spec)
with pinned deps in [`../packaging/requirements-build.txt`](../packaging/requirements-build.txt).
Frozen builds keep profiles / macros / rules in a per-user data dir
(`%APPDATA%\MacropadConfigurator`, `~/Library/Application Support/MacropadConfigurator`,
`~/.local/share/macropad-configurator`; override `MACROPAD_USER_DATA`), seeded from the bundled
defaults on first start. See [`../docs/RELEASE.md`](../docs/RELEASE.md).
