#!/bin/bash
# ============================================================
#  DOUBLE-CLICK THIS to open the Vigil dashboard in a browser.
#  First time: sets everything up by itself. After that: instant.
# ============================================================

cd "$(dirname "$0")"

echo "=================================================="
echo "        Vigil dashboard  -  starting up"
echo "=================================================="

if ! command -v python3 &> /dev/null; then
  echo ""
  echo "  Python 3 isn't installed yet."
  echo "  Get it (free) from:  https://www.python.org/downloads/"
  echo "  Then double-click this file again."
  read -p "  Press Enter to close..."
  exit 1
fi

if [ ! -d venv ]; then
  echo ""
  echo "  First-time setup - installing tools (a few minutes, one time only)..."
  python3 -m venv venv
  ./venv/bin/pip install -q -r requirements.txt
  echo "  Setup done!"
fi

# Open the browser a moment after the server starts
( sleep 3; open "http://localhost:8000" ) &

echo ""
echo "  Dashboard opening at  http://localhost:8000"
echo "  (Press Control+C here to stop the server.)"
echo ""
./venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
