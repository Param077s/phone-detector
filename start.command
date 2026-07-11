#!/bin/bash
# ============================================================
#  DOUBLE-CLICK THIS FILE to run the Phone Detector.
#  First time: it sets everything up by itself (a few minutes).
#  After that: it just runs. No terminal knowledge needed.
# ============================================================

# Go to the folder this file lives in
cd "$(dirname "$0")"

echo "=================================================="
echo "        Phone Detector  -  starting up"
echo "=================================================="

# 1) Make sure Python is installed
if ! command -v python3 &> /dev/null; then
  echo ""
  echo "  Python 3 isn't installed on this Mac yet."
  echo "  Install it once (free) from:  https://www.python.org/downloads/"
  echo "  Then double-click this file again."
  echo ""
  read -p "  Press Enter to close..."
  exit 1
fi

# 2) First time only: build the workspace and install the tools
if [ ! -d venv ]; then
  echo ""
  echo "  First-time setup - installing tools (takes a few minutes)."
  echo "  This only happens once. Grab a coffee."
  echo ""
  python3 -m venv venv
  ./venv/bin/pip install -q -r requirements.txt
  echo "  Setup done!"
fi

# 3) Run it
echo ""
echo "  Opening the camera. Hold a phone up to it."
echo "  Press the 'q' key in the video window to stop."
echo ""
./venv/bin/python detect.py

echo ""
read -p "  Stopped. Press Enter to close this window..."
