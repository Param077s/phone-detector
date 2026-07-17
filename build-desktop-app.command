#!/bin/bash
# ============================================================================
#   Build  dist/Vigil.app  —  a native, no-Terminal launcher.
#
#   Double-clicking a .app runs its executable DIRECTLY (macOS never opens a
#   Terminal for it), so this gives the real "just an app" experience: a native
#   window, no console, no browser, no visible localhost.
#
#   The bundle points at THIS project folder and its venv (created by
#   Vigil.command). Keep the project folder where it is after building.
# ============================================================================
set -e
cd "$(dirname "$0")"
PROJ="$(pwd)"
APP="$PROJ/dist/Vigil.app"

echo "  Building Vigil.app → $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# ---- launcher executable (runs headless; no Terminal) ----------------------
cat > "$APP/Contents/MacOS/Vigil" <<EOF
#!/bin/bash
PROJECT_DIR="$PROJ"
cd "\$PROJECT_DIR" || exit 1
LOG="\$HOME/Library/Logs/Vigil-desktop.log"
mkdir -p "\$(dirname "\$LOG")"

if [ ! -x venv/bin/python ]; then
  osascript -e 'display alert "Vigil needs setup" message "Run Vigil.command once to install Vigil, then open this app again."'
  exit 1
fi
if ! venv/bin/python -c "import webview" >/dev/null 2>&1; then
  venv/bin/pip install -r requirements-desktop.txt >>"\$LOG" 2>&1
fi
exec venv/bin/python desktop.py >>"\$LOG" 2>&1
EOF
chmod +x "$APP/Contents/MacOS/Vigil"

# ---- Info.plist ------------------------------------------------------------
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Vigil</string>
  <key>CFBundleDisplayName</key><string>Vigil</string>
  <key>CFBundleExecutable</key><string>Vigil</string>
  <key>CFBundleIdentifier</key><string>app.vigil.desktop</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>2.0</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict></plist>
EOF

# ---- reuse an existing icon if the previous build made one -----------------
ICON="$(find "$PROJ/dist" -name '*.icns' 2>/dev/null | head -1)"
if [ -n "$ICON" ]; then
  cp "$ICON" "$APP/Contents/Resources/AppIcon.icns"
fi

# refresh Finder's icon cache for the new bundle
touch "$APP"
echo "  ✓ Built. Open it from  $APP"
echo "    (First open: right-click → Open, to clear the unsigned-app warning.)"
open -R "$APP" 2>/dev/null || true
