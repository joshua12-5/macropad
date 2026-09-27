# PyInstaller spec for Macropad Configurator release builds.
#
#   cd <repo> && pyinstaller --noconfirm --clean packaging/macropad_configurator.spec
#
# Output: dist/MacropadConfigurator/            (Windows / Linux one-dir)
#         dist/MacropadConfigurator.app          (macOS app bundle)
# One-dir (not one-file): starts instantly (no temp extraction), fewer AV
# false positives on Windows, required for a proper macOS .app, and the
# bundled data files are visible/inspectable. CI zips / tars the folder.
import re
import sys
from pathlib import Path

REPO = Path(SPECPATH).resolve().parent
CONF = REPO / "configurator"

_ver_src = (CONF / "macropad_config" / "version.py").read_text(encoding="utf-8")
VERSION = re.search(r'HOST_APP_VERSION\s*=\s*"([^"]+)"', _ver_src).group(1)

APP_NAME = "MacropadConfigurator"

# Bundled read-only defaults → <bundle>/data/... (see macropad_config/paths.py)
datas = [(str(p), "data/profiles") for p in sorted((REPO / "profiles").glob("*.json"))]
datas += [
    (str(REPO / "macros" / "library.json"), "data/macros"),
    (str(REPO / "autoswitch" / "rules.json"), "data/autoswitch"),
]
# UI theme: QSS template + vendored Lucide SVG icons (and their ISC LICENSE),
# loaded next to macropad_config/ui/theme.py at runtime.
UI = CONF / "macropad_config" / "ui"
datas += [(str(UI / "theme.qss"), "macropad_config/ui")]
datas += [(str(p), "macropad_config/ui/icons") for p in sorted((UI / "icons").iterdir()) if p.is_file()]

# cython-hidapi: `hid` everywhere, `hidraw` (preferred) on Linux. The
# extension modules embed hidapi (Windows/macOS); the Linux wheel's
# auditwheel-vendored libs (hidapi.libs/libudev, libusb, ...) are found by
# PyInstaller's binary dependency analysis via the extensions' RPATH.
hiddenimports = ["hid"]
binaries = []
if sys.platform.startswith("linux"):
    hiddenimports.append("hidraw")

a = Analysis(
    [str(REPO / "packaging" / "launch.py")],
    pathex=[str(CONF)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc_data",
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtWebEngineCore",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,  # GUI app; --self-test/--version attach to the parent console
    disable_windowed_traceback=False,
    target_arch=None,  # native: arm64 on macos-latest (see docs/RELEASE.md)
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="io.github.joshua12-5.macropad-configurator",
        version=VERSION,
        info_plist={
            "CFBundleName": "Macropad Configurator",
            "CFBundleDisplayName": "Macropad Configurator",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSHumanReadableCopyright": "Copyright (c) 2026 Joshua Zamora. MIT License.",
        },
    )
