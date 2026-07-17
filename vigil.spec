# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build for the Vigil desktop app (macOS .app + Windows folder).
# Freezes desktop.py into a windowed, no-console application that bundles the
# server (app.py), the redesigned UI (web/), and a default model — so end users
# need no Python, no Terminal, and no manual setup.
#
#   pyinstaller vigil.spec --noconfirm
#
# Built on macOS  -> dist/Vigil.app
# Built on Windows -> dist/Vigil/Vigil.exe  (folder)
import os
import sys
from PyInstaller.utils.hooks import collect_all

datas = [("web", "web")]
binaries = []
hiddenimports = ["app"]

# Ship a default model inside the bundle so the first launch works offline.
for _m in ("yolo11m.pt", "yolo11n.pt"):
    if os.path.exists(_m):
        datas.append((_m, "."))

# Pull in everything these heavy packages need (data files + submodules).
for _pkg in ("ultralytics", "torch", "torchvision", "cv2", "webview"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception as e:                       # a missing optional dep is fine
        print(f"[vigil.spec] collect_all({_pkg}) skipped: {e}")

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Vigil",
    debug=False,
    strip=False,
    upx=False,
    console=False,                               # <- no Terminal / console window
    icon="build/vigil.icns" if sys.platform == "darwin" and os.path.exists("build/vigil.icns") else None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="Vigil",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Vigil.app",
        icon="build/vigil.icns" if os.path.exists("build/vigil.icns") else None,
        bundle_identifier="app.vigil.desktop",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleShortVersionString": os.environ.get("VIGIL_VERSION", "1.0.0"),
            "NSCameraUsageDescription": "Vigil detects phones in your camera feeds, on-device.",
        },
    )
