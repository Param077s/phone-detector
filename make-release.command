#!/bin/bash
# Builds a clean, shareable Vigil.zip that anyone can download, unzip, and run.
# (Excludes your local data, environment, and secrets.)
cd "$(dirname "$0")" || exit 1

OUT="dist/vigil"
echo "Building release…"
rm -rf "$OUT"
mkdir -p "$OUT"

# Only the files an end user needs to RUN Vigil — no developer/training tools,
# no Dockerfile, no docs site. Keeps the download clean and un-scary.
FILES=(
  "READ ME FIRST.txt"
  app.py requirements.txt
  Vigil.command Vigil-Windows.bat Vigil-Linux.sh
  INSTALL.md README.md
)
for f in "${FILES[@]}"; do
  [ -e "$f" ] && cp "$f" "$OUT/"
done
# Include the fine-tuned model if present (optional; app defaults to yolo11m)
[ -e vigil-phone.pt ] && cp vigil-phone.pt "$OUT/"

chmod +x "$OUT"/*.command "$OUT"/*.sh 2>/dev/null

( cd dist && rm -f Vigil.zip && zip -r -q Vigil.zip vigil )
echo ""
echo "✓ Built dist/Vigil.zip"
echo "  Share that file — anyone unzips it and double-clicks Vigil.command (Mac)"
echo "  or Vigil-Windows.bat (Windows)."
echo ""
read -r -p "Press Enter to close…"
