# Contributing

Thanks for helping! This repo holds the RP2040 macropad firmware (`firmware/`), the PySide6
configurator (`configurator/`), release packaging (`packaging/`) and docs (`docs/`).

## Setup

```bash
# Configurator
cd configurator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt ruff==0.16.9

# Firmware (Pico SDK 2.1.1, see firmware/README.md)
export PICO_SDK_PATH=/path/to/pico-sdk
cd firmware && cmake -B build -G Ninja -DPICO_BOARD=waveshare_rp2040_zero && ninja -C build
# → firmware/build/macropad.uf2
```

## Before you open a PR

- `ruff check . && ruff format --check .` (repo root; config in `ruff.toml`)
- `QT_QPA_PLATFORM=offscreen python configurator/scripts/run_all_smokes.py` — all smokes green
- `QT_QPA_PLATFORM=offscreen python -m macropad_config --self-test` (from `configurator/`)
- `python configurator/scripts/hil_test.py --mock --allow-flash-write` — HIL suite vs the mock
- Firmware changes: the build must stay at **zero warnings** (`-Wall -Wextra`). C style is
  described by `.clang-format` (4 spaces, attached braces, `type *name`); format new code with it,
  but don't reformat untouched files wholesale.
- Protocol / storage / blob changes: update `docs/PROTOCOL.md` (or the blob docs), the host
  codec, the mock device (`configurator/macropad_config/hil/mock.py`) and add a smoke.
- On real hardware, run the relevant parts of `docs/HARDWARE_TEST.md`.

CI runs the same checks (`.github/workflows/smokes.yml`, `firmware.yml`).

## Versions, changelog, releases

- Add user-visible changes to `CHANGELOG.md` under `[Unreleased]`.
- Version rules (firmware `0.N` ↔ host `0.N.0` ↔ `bcdDevice`): `docs/VERSIONING.md`.
- Releases are tag-driven (`vX.Y.Z`), see `docs/RELEASE.md`.

## Style

- Commit messages: short imperative summary line (≤ 72 chars), details in the body.
- Keep user-facing strings free of internal milestone names.
- Editor settings: `.editorconfig`.

By contributing you agree that your contributions are licensed under the MIT License (`LICENSE`).
