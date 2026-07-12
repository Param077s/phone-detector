#!/bin/bash
# ============================================================================
#  Double-click this to record training photos for Vigil.
#  Two short sessions: (1) hold your phone up, (2) show your room without a phone.
#  Everything else (labeling, training) is automatic.
# ============================================================================
cd "$(dirname "$0")" || exit 1
clear
echo "=========================================="
echo "     Teaching Vigil — photo capture"
echo "=========================================="
echo ""
echo "This records ~2.5 minutes of video from your camera to teach Vigil"
echo "what a phone looks like in YOUR room (and what is NOT a phone)."
echo ""
echo "Have a phone ready in your hand. Good lighting helps a lot."
echo ""
read -r -p "Press Enter when you're ready to start…"

# free the webcam if Vigil is running
pkill -f "uvicorn app:app" >/dev/null 2>&1
sleep 1

if [ ! -x "./venv/bin/python" ]; then
  echo "  Setup not found. Open Vigil once first, then run this again."
  read -r -p "  Press Enter to close…"; exit 1
fi

./venv/bin/python build_dataset.py guided

echo ""
read -r -p "Press Enter to close this window…"
