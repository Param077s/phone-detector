#!/bin/bash
# ============================================================================
#  Builds Vigil.app  +  Vigil.dmg  — the "drag to Applications" Mac experience.
#  The app is a clean launcher: app.py + model live inside the bundle; the
#  Python environment and all data live in ~/Library/Application Support/Vigil.
# ============================================================================
set -e
cd "$(dirname "$0")" || exit 1

APPNAME="Vigil"
BUILD="dist/mac"
APP="$BUILD/$APPNAME.app"
RES="$APP/Contents/Resources"
MACOS="$APP/Contents/MacOS"

echo "Cleaning…"
rm -rf "$BUILD"
mkdir -p "$RES" "$MACOS"

# --- 1) App payload (what the app runs) ------------------------------------
echo "Copying app files…"
cp app.py requirements.txt "$RES/"
[ -e vigil-phone.pt ] && cp vigil-phone.pt "$RES/"

# --- 2) The in-bundle launcher (opens Terminal so setup progress is visible)-
cat > "$RES/launch.command" <<'LAUNCH'
#!/bin/bash
# Vigil — runs from inside Vigil.app. Data + environment live in App Support.
RES="$(cd "$(dirname "$0")" && pwd)"
DATA="$HOME/Library/Application Support/Vigil"
PORT=8000
clear
echo "=========================================="
echo "            Vigil  —  starting"
echo "=========================================="
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "  Vigil needs Python 3 — a free, one-time install."
  echo "  Opening the download page…"
  open "https://www.python.org/downloads/" >/dev/null 2>&1
  echo "  Install it, then open Vigil again."
  echo ""
  read -r -p "  Press Enter to close…"
  exit 1
fi

mkdir -p "$DATA"
cd "$DATA" || exit 1

if [ ! -d "venv" ]; then
  echo "  First-time setup — installs Vigil's AI components."
  echo "  ⚠  Downloads ~2 GB the first time (5–15 min). This happens ONCE."
  echo "     Leave this window open and grab a coffee. ☕"
  echo "  ------------------------------------------------------------"
  echo ""
  python3 -m venv venv || { echo "  Could not create the environment."; read -r -p "  Press Enter…"; exit 1; }
  ./venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
  echo "  Installing components (progress below)…"
  echo ""
  if ! ./venv/bin/pip install -r "$RES/requirements.txt"; then
    echo ""
    echo "  Setup failed while installing. Check your internet and reopen Vigil."
    read -r -p "  Press Enter…"
    exit 1
  fi
  echo ""
  echo "  ✓ Setup complete!"
  echo ""
fi

# Model + code live in the app bundle; data (db, evidence, cameras) lives here.
export MODEL_NAME="$RES/vigil-phone.pt"
export PYTHONPATH="$RES"

echo "  Vigil is running at  http://localhost:$PORT"
echo "  Your browser will open in a few seconds."
echo ""
echo "  ▶ Keep this window open while you use Vigil."
echo "  ▶ To stop Vigil: close this window (or press Control-C)."
echo "  ------------------------------------------------------------"
echo ""
( sleep 5; open "http://localhost:$PORT" >/dev/null 2>&1 ) &
exec ./venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "$PORT"
LAUNCH
chmod +x "$RES/launch.command"

# --- 3) The app's executable: opens the launcher in Terminal ---------------
cat > "$MACOS/$APPNAME" <<'EXEC'
#!/bin/bash
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
open -a Terminal "$RES/launch.command"
EXEC
chmod +x "$MACOS/$APPNAME"

# --- 4) Info.plist ---------------------------------------------------------
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Vigil</string>
  <key>CFBundleDisplayName</key><string>Vigil</string>
  <key>CFBundleIdentifier</key><string>app.vigil.launcher</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>Vigil</string>
  <key>CFBundleIconFile</key><string>Vigil</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# --- 5) Icon (drawn with the venv's Pillow, then packed into .icns) ---------
echo "Building icon…"
PYBIN="./venv/bin/python"
[ -x "$PYBIN" ] || PYBIN="python3"
if "$PYBIN" - <<'PYICON'
try:
    from PIL import Image, ImageDraw
except Exception as e:
    raise SystemExit("no-pillow")
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, S-1, S-1], radius=int(S*0.225), fill=(14, 17, 22, 255))
col = (122, 133, 149, 255); w = int(S*0.045)
m = int(S*0.30); L = int(S*0.17); e = S - m
def cap(x, y): d.ellipse([x-w/2, y-w/2, x+w/2, y+w/2], fill=col)
# four viewfinder brackets
d.line([(m, m+L), (m, m), (m+L, m)], fill=col, width=w, joint="curve"); cap(m, m+L); cap(m+L, m)
d.line([(e-L, m), (e, m), (e, m+L)], fill=col, width=w, joint="curve"); cap(e-L, m); cap(e, m+L)
d.line([(m, e-L), (m, e), (m+L, e)], fill=col, width=w, joint="curve"); cap(m, e-L); cap(m+L, e)
d.line([(e-L, e), (e, e), (e, e-L)], fill=col, width=w, joint="curve"); cap(e-L, e); cap(e, e-L)
# center green dot
cr = int(S*0.135); c = S//2
d.ellipse([c-cr, c-cr, c+cr, c+cr], fill=(62, 207, 142, 255))
img.save("dist/mac/icon_1024.png")
print("ok")
PYICON
then
  ICON="$BUILD/$APPNAME.iconset"
  mkdir -p "$ICON"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$BUILD/icon_1024.png" --out "$ICON/icon_${s}x${s}.png" >/dev/null
    d=$((s*2)); sips -z $d $d "$BUILD/icon_1024.png" --out "$ICON/icon_${s}x${s}@2x.png" >/dev/null
  done
  cp "$BUILD/icon_1024.png" "$ICON/icon_512x512@2x.png"
  iconutil -c icns "$ICON" -o "$RES/$APPNAME.icns"
  rm -rf "$ICON" "$BUILD/icon_1024.png"
  echo "  ✓ icon built"
else
  echo "  (skipped custom icon — Pillow unavailable; app uses the default icon)"
fi

# --- 6) DMG with an Applications shortcut ----------------------------------
echo "Building Vigil.dmg…"
STAGE="$BUILD/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "dist/Vigil.dmg"
hdiutil create -volname "Vigil" -srcfolder "$STAGE" -ov -format UDZO "dist/Vigil.dmg" >/dev/null
rm -rf "$STAGE"

echo ""
echo "  ✓ Built dist/$APPNAME.app  and  dist/Vigil.dmg"
echo "  Open the .dmg → drag Vigil into Applications → double-click Vigil."
echo ""
