#!/bin/bash
# ---------------------------------------------------------------------------
# Vigil — one-click sync
# Copies your latest source code into the Dock app bundle, so clicking the
# Vigil icon on the Dock runs your newest changes. Double-click this file
# after editing Vigil's code.
# ---------------------------------------------------------------------------
SRC="$(cd "$(dirname "$0")" && pwd)"
DOCK_RES="$SRC/dist/mac/Vigil.app/Contents/Resources"
APP_RES="/Applications/Vigil.app/Contents/Resources"

# Python files that make up the running app. Add new modules here if you create them.
FILES="app.py vlm.py"

clear
echo "=========================================="
echo "        Vigil  —  sync to Dock app"
echo "=========================================="
echo ""

if [ ! -d "$DOCK_RES" ]; then
  echo "  ✗ Couldn't find the Dock app bundle at:"
  echo "    $DOCK_RES"
  echo "  Nothing synced."
  echo ""
  read -r -p "  Press Enter to close…"
  exit 1
fi

echo "  Source : $SRC"
echo ""
for f in $FILES; do
  if [ -f "$SRC/$f" ]; then
    cp "$SRC/$f" "$DOCK_RES/$f" && echo "  ✓ $f  →  Dock app"
    if [ -d "$APP_RES" ]; then
      cp "$SRC/$f" "$APP_RES/$f" 2>/dev/null && echo "  ✓ $f  →  /Applications copy"
    fi
  else
    echo "  – $f  (not found in source, skipped)"
  fi
done

echo ""
echo "  Done. Next time you open Vigil from the Dock it runs the latest code."
echo "  (If Vigil is open now, close it and reopen to load the changes.)"
echo ""
read -r -p "  Press Enter to close…"
