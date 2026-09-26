# Cutting a release

Short checklist for shipping Step *N* (host `0.N.0` / firmware `0.N`).

## 1. Bump versions

Per [`VERSIONING.md`](VERSIONING.md):

| Item | Value for Step *N* |
|------|--------------------|
| `FW_VERSION_MINOR` | *N* (`firmware/include/config_protocol.h`) |
| Host `HOST_APP_VERSION` | `0.N.0` (`configurator/macropad_config/version.py`, `__init__.py`) |
| CMake / UF2 target | `macropad_stepN` (`firmware/CMakeLists.txt`) |
| USB `bcdDevice` | BCD `1.N` (e.g. Step 21 → `0x0115`) in `usb_descriptors.c` |
| Docs / smokes | Matrix, READMEs, `smoke_version.py` expects |

Keep `CFG_PROTO_VERSION` / JSON `schema_version` at **1** unless intentionally breaking.

## 2. Changelog

- Move finished work from **[Unreleased]** into a new `## [0.N.0] — YYYY-MM-DD` section in [`CHANGELOG.md`](../CHANGELOG.md).
- Link compare / tag URLs at the bottom of the changelog.

## 3. Verify host smokes

```bash
cd configurator
pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen python scripts/run_all_smokes.py
```

CI (`.github/workflows/smokes.yml`) runs the same on push/PR to `main`.
**CI does not build firmware** (Pico SDK not required).

## 4. Optional firmware build + flash

If `PICO_SDK_PATH` is set:

```bash
cd firmware && mkdir -p build && cd build
cmake -DPICO_BOARD=pico ..
make -j$(nproc)
# Flash target UF2 name:
#   macropad_stepN.uf2
```

Copy the UF2 to the Pico USB mass-storage bootloader. Confirm Connect shows fw `0.N` / proto v1.

## 5. Tag and push

```bash
git tag -a v0.N.0 -m "v0.N.0 Step N"
git push origin main
git push origin v0.N.0
```

Create a GitHub Release from the tag; paste the changelog section as notes.
Flash / attach `macropad_stepN.uf2` if distributing binaries.
