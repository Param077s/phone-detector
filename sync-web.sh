#!/bin/bash
# ---------------------------------------------------------------------------
# Vigil — auto-sync a changed web/ asset into every Vigil bundle.
#
# The server serves web/ as static, no-cache files, so a UI change takes
# effect the moment the file on disk changes — no rebuild needed. This copies
# an edited web/<file> into the installed app and any built bundles so the
# running app (and future rebuilds) never drift from source.
#
# Usage:  sync-web.sh <absolute-path-to-a-file-under-web/>
# Meant to be driven by the PostToolUse hook in .claude/settings.json, but
# safe to run by hand. Always exits 0 so it never blocks an edit.
# ---------------------------------------------------------------------------
REPO="$(cd "$(dirname "$0")" && pwd)"
SRC_WEB="$REPO/web"
FILE="$1"

# Nothing to do unless we got a real file that lives under this repo's web/.
[ -n "$FILE" ] || exit 0
case "$FILE" in
  "$SRC_WEB"/*) ;;              # inside web/ — proceed
  *) exit 0 ;;                  # any other edit — ignore
esac
[ -f "$FILE" ] || exit 0

REL="${FILE#"$SRC_WEB"/}"       # path relative to web/, e.g. app.js or sub/x.css

# Every place a Vigil web asset can live. Missing targets are skipped.
TARGETS=(
  "/Applications/Vigil.app/Contents/Resources/web"
  "$REPO/dist/Vigil.app/Contents/Resources/web"
  "$REPO/dist/Vigil/_internal/web"
  "$REPO/dist/mac/Vigil.app/Contents/Resources/web"
)

for base in "${TARGETS[@]}"; do
  dest="$base/$REL"
  [ -d "$base" ] || continue                       # bundle not present
  mkdir -p "$(dirname "$dest")" 2>/dev/null
  cp "$FILE" "$dest" 2>/dev/null && echo "synced web/$REL → $base"
done
exit 0
