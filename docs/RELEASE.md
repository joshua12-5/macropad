# Releases

Releases are built and published by **`.github/workflows/release.yml`** when a tag `vX.Y.Z` is
pushed. Nothing is built on a developer machine; the workflow verifies versions, builds firmware
and configurator for every platform, self-tests each package and publishes a GitHub
**prerelease** (all `0.x` versions are prereleases).

```
push tag vX.Y.Z ──► meta ──────────► firmware (reuses firmware.yml) ─┐
                    │ tag == version.py == __init__ == FW_VERSION     ├─► release: rename, SHA256SUMS,
                    │ CHANGELOG [X.Y.Z] section → notes               │   gh release create --prerelease
                    └──────────────► configurator matrix ────────────┘
                                     windows-latest   → windows-x64.zip
                                     macos-latest     → macos-arm64.zip (.app)
                                     macos-15-intel   → macos-x86_64.zip (experimental, optional)
                                     ubuntu-22.04     → linux-x86_64.tar.gz
                                     each: PyInstaller → --self-test → archive → extract → --self-test
```

## Cutting a release

1. **Bump versions** (per [`VERSIONING.md`](VERSIONING.md)) for release `0.N.0`:

   | Item | Value | File |
   |------|-------|------|
   | `FW_VERSION_MINOR` | *N* | `firmware/include/config_protocol.h` |
   | `HOST_APP_VERSION`, `FW_VERSION_MINOR_CURRENT` | `0.N.0`, *N* | `configurator/macropad_config/version.py` |
   | `__version__` | `0.N.0` | `configurator/macropad_config/__init__.py` |
   | USB `bcdDevice` | BCD `1.N` (fw 0.25 → `0x0119`) | `firmware/src/usb_descriptors.c` |
   | Smokes / docs | expectations, matrix, READMEs | `scripts/smoke_version.py`, docs |

   Keep `CFG_PROTO_VERSION` and JSON `schema_version` at **1** unless intentionally breaking.

2. **Changelog**: move finished work from `[Unreleased]` into `## [0.N.0] — YYYY-MM-DD` in
   [`CHANGELOG.md`](../CHANGELOG.md) and add the link reference at the bottom. That section becomes
   the release notes verbatim.

3. **Check locally** (optional but fast):

   ```bash
   python packaging/release_tools.py check v0.N.0      # versions + changelog agree
   python packaging/release_tools.py notes v0.N.0      # preview release notes
   cd configurator && QT_QPA_PLATFORM=offscreen python scripts/run_all_smokes.py
   QT_QPA_PLATFORM=offscreen python -m macropad_config --self-test
   ```

4. **Push `main` and let CI go green** (`Host smokes`, `Firmware build`).

5. **Dry run**: Actions → *Release* → *Run workflow* on `main` (or
   `gh workflow run release.yml --ref main`). Same jobs, but instead of publishing it uploads the
   `release-dry-run` artifact (all assets, `SHA256SUMS.txt`, self-test reports, notes). The optional
   `tag` input validates the sources against another tag name.

6. **Tag and push**:

   ```bash
   git tag -a v0.N.0 -m "v0.N.0 — Step N"
   git push origin v0.N.0
   ```

   The release appears under *Releases* when the workflow finishes (~10 min). Re-running the
   workflow for an existing release replaces its assets (`gh release upload --clobber`).

If `meta` fails, the tag and sources disagree: fix the sources, delete the tag
(`git push origin :refs/tags/v0.N.0`, `git tag -d v0.N.0`) and tag the fixed commit.

## Assets

| Asset | Contents |
|-------|----------|
| `macropad-fw-X.Y.Z.uf2` | Firmware for the Waveshare RP2040-Zero (Pico SDK 2.1.1). Hold BOOT, plug in, copy to `RPI-RP2`. |
| `macropad-fw-X.Y.Z.elf` | Same build with symbols (debugging / SWD). |
| `macropad-fw-X.Y.Z.uf2.sha256` | Checksum of the UF2 alone. |
| `MacropadConfigurator-X.Y.Z-windows-x64.zip` | `MacropadConfigurator\MacropadConfigurator.exe` + `_internal\`. Windows 10/11 x64. |
| `MacropadConfigurator-X.Y.Z-macos-arm64.zip` | `MacropadConfigurator.app` for Apple Silicon, macOS 12+. |
| `MacropadConfigurator-X.Y.Z-macos-x86_64.zip` | Intel Mac build — only present when the experimental leg succeeded. |
| `macropad-configurator-X.Y.Z-linux-x86_64.tar.gz` | App folder, `70-macropad.rules`, `INSTALL.txt`, `.desktop` template, `install.sh`. glibc ≥ 2.35. |
| `SHA256SUMS.txt` | SHA-256 of every asset (`sha256sum -c SHA256SUMS.txt`). |

## Packaging choices

- **PyInstaller one-dir, zipped** (not one-file): starts instantly (one-file unpacks ~150 MB to a
  temp dir on every launch), triggers far fewer antivirus false positives on Windows, is the only
  layout a macOS `.app` supports, and leaves bundled data inspectable. Spec:
  `packaging/macropad_configurator.spec`; pinned deps: `packaging/requirements-build.txt`
  (Python 3.12, PySide6-Essentials 6.8.3 = QtCore/QtGui/QtWidgets only, hidapi 0.15.0,
  PyInstaller 6.22.3).
- **hidapi**: the build uses **cython-hidapi** (`pip install hidapi`), whose wheels embed the native
  hidapi library (Windows: statically linked; macOS: IOKit backend compiled in; Linux: auditwheel
  vendors libudev/libusb). Users install nothing. On Linux the app uses the package's `hidraw`
  module (kernel hidraw nodes + the shipped udev rule) rather than its libusb-based `hid` module.
  `protocol/device.py` still accepts the pyhidapi `hid` package for source installs.
- **Bundled data**: `profiles/*.json`, `macros/library.json`, `autoswitch/rules.json` go into the
  bundle's `data/` dir; on first start they are copied to the per-user data dir
  (`%APPDATA%\MacropadConfigurator`, `~/Library/Application Support/MacropadConfigurator`,
  `~/.local/share/macropad-configurator`) and never overwritten afterwards.
- **Self-test gate**: every package runs `MacropadConfigurator --version` and
  `--self-test --report …` (Qt `offscreen`) twice — straight from `dist/` and again after
  extracting the final archive — via `packaging/ci_selftest.py`. Reports are in the release job
  summary and in the dry-run artifact.
- **macOS universal2 is not shipped**: hidapi publishes only thin `arm64` and `x86_64` wheels (no
  `universal2`), so a universal build would need hidapi compiled from source for both archs and
  `lipo`-merged. Instead `macos-latest` builds arm64 and an experimental `macos-15-intel` leg builds
  x86_64 when that runner is available.

## Unsigned builds — what users will see

The configurator builds are **not code-signed or notarised** (no paid certificates yet).

**Windows — SmartScreen.** Running `MacropadConfigurator.exe` from a downloaded zip shows
*"Windows protected your PC"*. Click **More info → Run anyway**. Alternatively, before
extracting: right-click the zip → *Properties* → tick **Unblock** → OK (removes the
mark-of-the-web for everything inside). Always extract the whole zip first; running from inside
the zip viewer fails because `_internal\` is missing.

**macOS — Gatekeeper.** The `.app` is only ad-hoc signed, so the first open says it *"cannot be
opened because Apple cannot check it for malicious software"* (or *"is damaged"* on some
versions). Either:

- right-click (Control-click) `MacropadConfigurator.app` → **Open** → **Open**; on macOS 15+ open
  it once, then *System Settings → Privacy & Security → "MacropadConfigurator" was blocked →
  Open Anyway*; or
- remove the quarantine attribute: `xattr -dr com.apple.quarantine /Applications/MacropadConfigurator.app`.

**Linux.** No signing concept for the tarball; verify with `sha256sum -c SHA256SUMS.txt
--ignore-missing`. Install the udev rule (`./install.sh`) for non-root device access.

Firmware UF2 files are unsigned too (the RP2040 boot ROM does not verify signatures).

## Manual build (fallback)

```bash
python3.12 -m venv .venv-build && . .venv-build/bin/activate
pip install -r packaging/requirements-build.txt
pyinstaller --noconfirm --clean packaging/macropad_configurator.spec
QT_QPA_PLATFORM=offscreen python packaging/ci_selftest.py dist/MacropadConfigurator/MacropadConfigurator selftest.txt
```

Firmware: see [`../firmware/README.md`](../firmware/README.md) (`cmake -B build -G Ninja
-DPICO_BOARD=waveshare_rp2040_zero && ninja -C build` → `build/macropad.uf2`). After
flashing, confirm Connect shows fw `0.N` / proto v1 and run
`MacropadConfigurator --hil --allow-flash-write --json hil.json` (or
`python configurator/scripts/hil_test.py …`) plus the manual part of
[`HARDWARE_TEST.md`](HARDWARE_TEST.md).
