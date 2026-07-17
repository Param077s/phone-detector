#!/bin/bash
# ============================================================================
#   V I G I L  —  Desktop (native window; no browser, no localhost)
#   Quick launcher. For a true no-Terminal app, run build-desktop-app.command
#   once and use the resulting dist/Vigil.app instead.
# ============================================================================
cd "$(dirname "$0")" || exit 1

# Reuse the environment created by Vigil.command's first-run setup.
if [ ! -x venv/bin/python ]; then
  echo "  First, run Vigil.command once to install Vigil's components."
  read -r -p "  Press Enter to close…"
  exit 1
fi

# Make sure the desktop dependency is present (one-time, small).
if ! venv/bin/python -c "import webview" >/dev/null 2>&1; then
  echo "  Preparing the desktop window (one-time)…"
  venv/bin/pip install -r requirements-desktop.txt || {
    echo "  Could not install the desktop component."; read -r -p "  Press Enter…"; exit 1; }
fi

exec venv/bin/python desktop.py
