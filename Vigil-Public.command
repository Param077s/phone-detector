#!/bin/bash
# ============================================================================
#   V I G I L  —  P U B L I C   (double-click)
#   Starts Vigil AND a free secure tunnel, so you get one public https link.
#   Anyone — on ANY network, no app install — can open that link on their
#   phone/laptop and become a camera on your wall.
#   Detection still runs on THIS computer; the tunnel only relays the feed.
#   (macOS)
# ============================================================================

cd "$(dirname "$0")" || exit 1
clear
echo "=============================================="
echo "        Vigil  —  Public (secure tunnel)"
echo "=============================================="
echo ""

PORT=8000

# --- 1) Vigil must already be set up (run Vigil once first) -----------------
if [ ! -f ".vigil-installed" ] || [ ! -x "./venv/bin/python" ]; then
  echo "  Set Vigil up first: double-click \"Vigil\" once and let it finish,"
  echo "  then use \"Vigil-Public\" to go online."
  echo ""
  read -r -p "  Press Enter to close…"
  exit 1
fi

# --- 2) Make sure the tunnel tool (cloudflared) is available ---------------
CF=""
if command -v cloudflared >/dev/null 2>&1; then
  CF="cloudflared"
elif [ -x "./cloudflared" ]; then
  CF="./cloudflared"
else
  echo "  One-time: installing the secure tunnel tool (cloudflared)…"
  echo ""
  if command -v brew >/dev/null 2>&1; then
    brew install cloudflared && CF="cloudflared"
  fi
  if [ -z "$CF" ]; then
    # Fallback: download the binary right next to the app.
    ARCH="$(uname -m)"
    ASSET="cloudflared-darwin-amd64.tgz"        # universal enough (runs via Rosetta on Apple Silicon)
    [ "$ARCH" = "arm64" ] && ASSET="cloudflared-darwin-arm64.tgz"
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/$ASSET"
    echo "  Downloading $ASSET …"
    if curl -fL -o cloudflared.tgz "$URL" && tar xzf cloudflared.tgz; then
      chmod +x cloudflared; rm -f cloudflared.tgz; CF="./cloudflared"
    else
      # Some releases ship the arm64 build only as amd64; retry that.
      rm -f cloudflared.tgz
      URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"
      if curl -fL -o cloudflared.tgz "$URL" && tar xzf cloudflared.tgz; then
        chmod +x cloudflared; rm -f cloudflared.tgz; CF="./cloudflared"
      fi
    fi
  fi
fi

if [ -z "$CF" ]; then
  echo ""
  echo "  Couldn't install the tunnel tool automatically."
  echo "  Install it once with:   brew install cloudflared"
  echo "  then double-click Vigil-Public again."
  echo ""
  read -r -p "  Press Enter to close…"
  exit 1
fi

# --- 3) Open the tunnel and read back its public URL -----------------------
echo "  Opening a secure tunnel…"
CF_LOG="$(mktemp -t vigil-cf)"
"$CF" tunnel --url "http://localhost:$PORT" >"$CF_LOG" 2>&1 &
CF_PID=$!

PUBLIC_URL=""
for _ in $(seq 1 40); do
  PUBLIC_URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$CF_LOG" | head -1)"
  [ -n "$PUBLIC_URL" ] && break
  # if cloudflared died, stop waiting
  kill -0 "$CF_PID" 2>/dev/null || break
  sleep 1
done

if [ -z "$PUBLIC_URL" ]; then
  echo ""
  echo "  Could not get a public link (network blocked the tunnel?)."
  echo "  Vigil will still start on this Wi-Fi only."
  echo ""
else
  export PUBLIC_URL
  echo ""
  echo "  ------------------------------------------------------------"
  echo "   PUBLIC LINK (share this):  $PUBLIC_URL"
  echo ""
  echo "   • Open it yourself to sign in from anywhere."
  echo "   • In Vigil: add \"A device's camera (via link)\", press Share,"
  echo "     and send that camera link to anyone — any network, no install."
  echo "  ------------------------------------------------------------"
  echo ""
fi

# --- 4) Launch Vigil (browser opens locally) -------------------------------
echo "  Vigil is starting at  http://localhost:$PORT"
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
[ -n "$LAN_IP" ] && echo "  On a phone (same WiFi):  http://$LAN_IP:$PORT"
echo "  ▶ Keep this window open while you use Vigil."
echo "  ▶ To stop Vigil AND the public link: close this window."
echo ""

# Stop the tunnel whenever the app stops.
cleanup() { kill "$CF_PID" 2>/dev/null; rm -f "$CF_LOG"; }
trap cleanup EXIT INT TERM

( sleep 5; open "http://localhost:$PORT" >/dev/null 2>&1 ) &
./venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port "$PORT"
