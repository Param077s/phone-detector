#!/bin/bash
# ============================================================================
#   V I G I L  —  double-click to start.
#   First run sets everything up automatically. Every run after: it just opens.
#   (macOS)
# ============================================================================

cd "$(dirname "$0")" || exit 1
clear
echo "=========================================="
echo "            Vigil  —  starting"
echo "=========================================="
echo ""

PORT=8000

# --- 1) Python 3 required --------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "  Vigil needs Python 3 — a free, one-time install."
  echo "  Opening the download page in your browser…"
  open "https://www.python.org/downloads/" >/dev/null 2>&1
  echo ""
  echo "  Install Python, then double-click Vigil again."
  echo ""
  read -r -p "  Press Enter to close…"
  exit 1
fi

# --- 2) First-time setup ---------------------------------------------------
# The ".vigil-installed" sentinel is written only after a SUCCESSFUL install,
# so an interrupted setup (window closed early) resumes cleanly next time
# instead of leaving a half-built venv that reinstalls or fails to run.
if [ ! -f ".vigil-installed" ]; then
  echo "  First-time setup. This installs Vigil's components."
  echo "  ⚠  It downloads ~2 GB the first time, so it needs a good internet"
  echo "     connection and can take 5–15 minutes. This happens ONCE."
  echo ""
  echo "  Keep this window open until you see 'Setup complete' ☕"
  echo "  ------------------------------------------------------------"
  echo ""
  rm -rf venv                                   # clear any half-finished attempt
  python3 -m venv venv || { echo "  Could not create the environment."; read -r -p "  Press Enter…"; exit 1; }
  ./venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
  echo "  Installing components (progress below)…"
  echo ""
  if ! ./venv/bin/pip install -r requirements.txt; then
    echo ""
    echo "  Setup didn't finish (connection interrupted?). Just run Vigil again to resume."
    rm -rf venv                                 # next run starts clean
    read -r -p "  Press Enter…"
    exit 1
  fi
  echo ""
  echo "  Preparing the detector…"
  ./venv/bin/python -c "from ultralytics import YOLO; YOLO('yolo11m.pt')" >/dev/null 2>&1
  touch ".vigil-installed"                      # mark complete ONLY after success
  echo "  ✓ Setup complete!"
  echo ""
fi

# --- 3) Launch + open the browser ------------------------------------------
echo "  Vigil is starting at  http://localhost:$PORT"
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
[ -n "$LAN_IP" ] && echo "  On a phone (same WiFi):  http://$LAN_IP:$PORT"
echo "  Your browser will open in a few seconds."
echo ""
echo "  ▶ Keep this window open while you use Vigil."
echo "  ▶ To stop Vigil: close this window (or press Control-C)."
echo "  ------------------------------------------------------------"
echo ""

( sleep 5; open "http://localhost:$PORT" >/dev/null 2>&1 ) &
./venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port "$PORT"
