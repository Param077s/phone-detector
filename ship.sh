#!/bin/bash
# ===========================================================================
#  Vigil — one-command ship.
#
#    bump VIGIL_VERSION → CHANGELOG entry → build DMG → GitHub Release
#
#  The release goes to the PUBLIC repo the updater polls (Param077s/vigil),
#  with the asset named Vigil.dmg — that's what installed copies auto-update
#  from. Two confirm gates: once before the (slow) build, once before publish.
#
#  Usage:
#    ./ship.sh                 # patch bump (1.3.8 → 1.3.9), prompt for a note
#    ./ship.sh 1.4.0           # explicit version
#    ./ship.sh 1.4.0 notes.md  # explicit version + a release-notes file
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")" || exit 1

REPO_SLUG="Param077s/vigil"          # public repo the updater reads
DMG="dist/Vigil.dmg"
APP_PY="app.py"

# --- preflight -------------------------------------------------------------
command -v gh >/dev/null || { echo "✗ GitHub CLI (gh) not installed."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "✗ Not logged in to gh. Run: gh auth login"; exit 1; }
[ -x ./build-app.command ] || { echo "✗ build-app.command not found/executable."; exit 1; }

CUR=$(grep -E '^VIGIL_VERSION = "' "$APP_PY" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
[ -n "$CUR" ] || { echo "✗ Couldn't read VIGIL_VERSION from $APP_PY."; exit 1; }

# --- resolve target version ------------------------------------------------
NEW="${1:-}"
if [ -z "$NEW" ]; then
  IFS='.' read -r MA MI PA <<<"$CUR"
  NEW="$MA.$MI.$((PA + 1))"          # default: bump patch
fi
if ! printf '%s' "$NEW" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "✗ Version must look like X.Y.Z (got: $NEW)"; exit 1
fi
if gh release view "v$NEW" --repo "$REPO_SLUG" >/dev/null 2>&1; then
  echo "✗ Release v$NEW already exists on $REPO_SLUG. Pick another version."; exit 1
fi

# --- release notes ---------------------------------------------------------
NOTES_FILE="${2:-}"
HEADLINE=""
if [ -n "$NOTES_FILE" ]; then
  [ -f "$NOTES_FILE" ] || { echo "✗ Notes file not found: $NOTES_FILE"; exit 1; }
  HEADLINE=$(grep -m1 . "$NOTES_FILE" | sed -E 's/^#+ *//')
else
  printf "One-line summary of what changed in %s: " "$NEW"
  read -r HEADLINE
  [ -n "$HEADLINE" ] || { echo "✗ A summary is required (or pass a notes file)."; exit 1; }
  NOTES_FILE="$(mktemp -t vigil-notes)"
  printf '## %s\n\n%s\n' "$HEADLINE" "$HEADLINE" >"$NOTES_FILE"
fi

DATE=$(date +%Y-%m-%d)

echo ""
echo "  ────────────────────────────────────────"
echo "   Ship Vigil"
echo "   version : $CUR  →  $NEW"
echo "   date    : $DATE"
echo "   notes   : $HEADLINE"
echo "   release : $REPO_SLUG  (tag v$NEW, asset Vigil.dmg)"
echo "  ────────────────────────────────────────"
printf "  Build now? This bumps the version + rebuilds the DMG (a few min). [y/N] "
read -r ok
case "$ok" in y|Y) ;; *) echo "  Aborted. No changes made."; exit 0 ;; esac

# --- bump version + changelog ----------------------------------------------
sed -i '' -E "s/^VIGIL_VERSION = \".*\"/VIGIL_VERSION = \"$NEW\"/" "$APP_PY"
awk -v v="$NEW" -v d="$DATE" -v note="$HEADLINE" '
  !done && /^## / { print "## " v " — " d; print "- " note; print ""; done=1 }
  { print }
' CHANGELOG.md >CHANGELOG.md.tmp && mv CHANGELOG.md.tmp CHANGELOG.md
echo "  ✓ bumped $APP_PY to $NEW and added a CHANGELOG entry"

# --- build -----------------------------------------------------------------
./build-app.command
[ -f "$DMG" ] || { echo "✗ Build did not produce $DMG."; exit 1; }
echo "  ✓ built $DMG ($(du -h "$DMG" | cut -f1 | tr -d ' '))"

# --- publish (second gate) -------------------------------------------------
echo ""
printf "  Publish release v%s to %s now? [y/N] " "$NEW" "$REPO_SLUG"
read -r pub
case "$pub" in
  y|Y)
    gh release create "v$NEW" --repo "$REPO_SLUG" \
      --title "Vigil $NEW" --notes-file "$NOTES_FILE" --latest "$DMG"
    echo ""
    echo "  ✓ Published: https://github.com/$REPO_SLUG/releases/tag/v$NEW"
    echo "    Installed copies will auto-update on their next check."
    ;;
  *)
    echo "  Skipped publish. DMG is ready at $DMG — release it later with:"
    echo "    gh release create v$NEW --repo $REPO_SLUG --title \"Vigil $NEW\" --latest $DMG"
    ;;
esac

echo ""
echo "  Note: the version bump + CHANGELOG are committed to your working tree"
echo "  but NOT pushed. Commit/push the source when you're ready:"
echo "    git add $APP_PY CHANGELOG.md && git commit -m \"Release $NEW\" && git push"
