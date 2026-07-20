#!/bin/bash
# ============================================================================
#  Vigil — the real macOS release build.
#
#    icon → PyInstaller (vigil.spec) → dist/Vigil.app → dist/Vigil.dmg
#
#  The result is the full "download → open DMG → drag to Applications" flow:
#  a self-contained Vigil.app (Python, the server, the AI engine, and the UI
#  all inside the bundle — end users install nothing else).
#
#  Needs the project venv:   python3.12 -m venv venv
#                            ./venv/bin/pip install -r requirements.txt \
#                                -r requirements-desktop.txt pyinstaller dmgbuild pillow
# ============================================================================
set -e
cd "$(dirname "$0")" || exit 1
PY=./venv/bin/python
[ -x "$PY" ] || { echo "No venv — see the header of this script."; exit 1; }

echo "▸ 1/3  App icon"
$PY make_icon.py

echo "▸ 2/3  Vigil.app  (PyInstaller — takes a few minutes)"
rm -rf dist/Vigil dist/Vigil.app
$PY -m PyInstaller vigil.spec --noconfirm --log-level WARN
[ -d dist/Vigil.app ] || { echo "PyInstaller did not produce dist/Vigil.app"; exit 1; }

echo "▸ 3/3  Vigil.dmg"
$PY make_dmg_background.py
cat > build/dmg_settings.py <<'DMGPY'
import os.path
app = "dist/Vigil.app"
files = [app]
symlinks = {"Applications": "/Applications"}
badge_icon = "build/vigil.icns" if os.path.exists("build/vigil.icns") else None
background = "build/dmg-bg.png"
window_rect = ((240, 140), (640, 420))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
icon_size = 110
text_size = 15
icon_locations = {"Vigil.app": (170, 210), "Applications": (470, 210)}
format = "UDZO"
DMGPY
rm -f dist/Vigil.dmg
$PY -m dmgbuild -s build/dmg_settings.py "Vigil" dist/Vigil.dmg

echo ""
echo "  ✓ dist/Vigil.app"
echo "  ✓ dist/Vigil.dmg   ($(du -h dist/Vigil.dmg | cut -f1 | tr -d ' '))"
echo "  Upload the DMG — users open it, drag Vigil into Applications, launch."
echo ""
