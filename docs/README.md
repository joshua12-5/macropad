# Documentation

## Using the macropad

| Document | What it covers |
|----------|----------------|
| [USER_GUIDE.md](USER_GUIDE.md) | Parts, wiring and pin map, flashing, installing the configurator, every action type, profiles, macros, idle animations, auto-switch, backups, firmware updates, command-line flags. |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Device not detected, Linux permissions, UF2 not booting, blank OLED, encoder direction or steps, ghosting, upload failures, version mismatch, filing a bug with a HIL report. |
| [ANIMATION.md](ANIMATION.md) | Idle animation behaviour, the editor, the `.mpan` blob and `*.mpanim.json` project formats, capacity, I2C timing. |
| [HARDWARE_TEST.md](HARDWARE_TEST.md) | The automated hardware-in-the-loop (HIL) suite and the manual checklist for a freshly built board. |
| [../packaging/linux/INSTALL.txt](../packaging/linux/INSTALL.txt) | Install notes shipped inside the Linux tarball. |

## How it works

| Document | What it covers |
|----------|----------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | The firmware / configurator stack, data flows, RAM vs flash, flash map, testing and CI, release packaging. |
| [PROTOCOL.md](PROTOCOL.md) | The 64-byte vendor HID configuration protocol: framing, CRC, every command and error code. |
| [PROFILE_BLOB.md](PROFILE_BLOB.md) | Binary layout of one profile as uploaded to and stored on the device. |
| [MACRO_BLOB.md](MACRO_BLOB.md) | Binary layout of one macro slot as uploaded to and stored on the device. |
| [VERSIONING.md](VERSIONING.md) | How firmware, configurator, protocol and schema versions relate, and what is compatible. |
| [../profiles/SCHEMA.md](../profiles/SCHEMA.md) | Profile JSON format (keys, encoder, actions) and the built-in text table. |
| [../macros/SCHEMA.md](../macros/SCHEMA.md) | Macro library JSON format and step opcodes. |
| [../autoswitch/SCHEMA.md](../autoswitch/SCHEMA.md) | Auto-switch rules JSON format, matching and slot resolution. |

## Building and contributing

| Document | What it covers |
|----------|----------------|
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Dev setup, the checks to run before a pull request, style and commit conventions. |
| [../firmware/README.md](../firmware/README.md) | Firmware modules, build with Pico SDK 2.1.1, flash map, debug UART. |
| [../configurator/README.md](../configurator/README.md) | Running the configurator from source, its menus, headless smokes, HIL tool, packaging. |
| [RELEASE.md](RELEASE.md) | Cutting a release: tag-triggered pipeline, dry runs, assets, unsigned-build notes. |
| [../CHANGELOG.md](../CHANGELOG.md) | What changed in each version. |
| [../protocol/README.md](../protocol/README.md) | Pointer to the protocol docs, which moved here. |
| [../LICENSE](../LICENSE) | MIT License, Copyright (c) 2026 Joshua Zamora. |
