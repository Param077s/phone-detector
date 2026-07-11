#!/bin/bash
# ==========================================================================
#   V I G I L  -  run to start.  (Linux)
#   First run sets everything up. Every run after: it just opens.
# ==========================================================================
cd "$(dirname "$0")" || exit 1
echo "=========================================="
echo "            Vigil  —  starting"
echo "=========================================="
echo ""
PORT=8000

if ! command -v python3 >/dev/null 2>&1; then
  echo "  Vigil needs Python 3. Install it with your package manager, e.g.:"
  echo "     sudo apt install python3 python3-venv python3-pip"
  echo "  then run Vigil again."
  exit 1
fi

if [ ! -d "venv" ]; then
  echo "  First-time setup (downloads ~2 GB, 5–15 min, happens once)…"
  echo ""
  python3 -m venv venv || { echo "  Could not create the environment."; exit 1; }
  ./venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
  echo "  Installing components…"
  ./venv/bin/pip install -r requirements.txt || { echo "  Setup failed — check internet."; exit 1; }
  echo "  Preparing the detector…"
  ./venv/bin/python -c "from ultralytics import YOLO; YOLO('yolo11m.pt')" >/dev/null 2>&1
  echo "  ✓ Setup complete!"
  echo ""
fi

echo "  Vigil is starting at  http://localhost:$PORT  (opening browser)…"
echo "  Keep this terminal open while using Vigil. Press Control-C to stop."
echo ""
( sleep 5; xdg-open "http://localhost:$PORT" >/dev/null 2>&1 ) &
./venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "$PORT"
