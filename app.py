"""
Vigil — Product v1, Step 1: the web dashboard
=============================================

This is the real product (in miniature). Instead of a terminal window, it runs
a small web server. You open it in your browser and see a live camera with a
security-console look, and phones get boxed in real time.

How it fits together:
  - A background camera loop grabs frames and runs YOLO (same engine as Layer 0).
  - FastAPI serves two things:
        /            -> the dashboard web page (what you look at)
        /video_feed  -> the live video, streamed to the page
  - If no camera is connected, it shows a friendly "demo mode" screen instead
    of crashing (good product behaviour).

Run it with the double-click launcher (start-dashboard.command), or:
    ./venv/bin/python -m uvicorn app:app --port 8000
then open http://localhost:8000 in your browser.
"""

import time
import cv2
import numpy as np
from ultralytics import YOLO
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse


# ---------------------------------------------------------------------------
# SETTINGS (tweak freely)
# ---------------------------------------------------------------------------
CAMERA_SOURCE = 0      # 0 = built-in webcam. Later this becomes a camera's address.
CONFIDENCE    = 0.40   # how sure YOLO must be (0.0 - 1.0)
PHONE_CLASS   = 67     # 67 = "cell phone" in YOLO's built-in list
CAMERA_LABEL  = "Camera 1 · Main Hall"   # shown on the dashboard


# Load YOLO once when the server starts
print("Loading YOLO...")
model = YOLO("yolo11n.pt")


def _placeholder(text):
    """A grey frame with a message — shown when there's no camera."""
    img = np.full((480, 640, 3), 32, dtype=np.uint8)
    cv2.putText(img, text, (40, 240), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (180, 180, 180), 2)
    return img


def generate_frames():
    """Yields a never-ending stream of JPEG frames for the browser."""
    cap = cv2.VideoCapture(CAMERA_SOURCE)

    while True:
        if not cap.isOpened():
            frame = _placeholder("Camera not connected - demo mode")
            time.sleep(0.1)
        else:
            ok, frame = cap.read()
            if not ok:
                cap = cv2.VideoCapture(CAMERA_SOURCE)   # try to reconnect
                frame = _placeholder("Reconnecting to camera...")
            else:
                # Run YOLO: find only phones, above our confidence
                results = model(frame, classes=[PHONE_CLASS],
                                conf=CONFIDENCE, verbose=False)
                for box in results[0].boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 90), 2)
                    cv2.putText(frame, f"PHONE {conf:.0%}", (x1, max(y1 - 10, 20)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 90), 2)

        ok, buffer = cv2.imencode(".jpg", frame)
        if not ok:
            continue
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")


# ---------------------------------------------------------------------------
# THE WEB APP
# ---------------------------------------------------------------------------
app = FastAPI(title="Vigil")


@app.get("/video_feed")
def video_feed():
    return StreamingResponse(generate_frames(),
                             media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vigil — Live Monitor</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, Segoe UI, Roboto, sans-serif;
      background: #0e1116; color: #e6e9ef; height: 100vh; display: flex; flex-direction: column;
    }}
    header {{
      display: flex; align-items: center; gap: 12px;
      padding: 14px 22px; background: #151a21; border-bottom: 1px solid #232a34;
    }}
    .logo {{ font-weight: 700; font-size: 20px; letter-spacing: .5px; }}
    .logo span {{ color: #4ade80; }}
    .dot {{ width: 9px; height: 9px; border-radius: 50%; background: #4ade80;
            box-shadow: 0 0 8px #4ade80; animation: pulse 1.6s infinite; }}
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}
    .status {{ font-size: 13px; color: #9aa4b2; }}
    .clock {{ margin-left: auto; font-size: 13px; color: #9aa4b2; font-variant-numeric: tabular-nums; }}
    main {{ flex: 1; display: flex; gap: 18px; padding: 18px; min-height: 0; }}
    .feed {{
      flex: 1; background: #151a21; border: 1px solid #232a34; border-radius: 14px;
      overflow: hidden; display: flex; flex-direction: column;
    }}
    .feed-head {{ display:flex; align-items:center; gap:8px; padding: 12px 16px;
                  border-bottom: 1px solid #232a34; font-size: 14px; }}
    .feed-body {{ flex:1; display:flex; align-items:center; justify-content:center; background:#000; min-height:0; }}
    .feed-body img {{ max-width: 100%; max-height: 100%; }}
    .live-tag {{ margin-left:auto; font-size:11px; font-weight:700; color:#0e1116;
                 background:#4ade80; padding:3px 8px; border-radius:20px; }}
    aside {{
      width: 320px; background: #151a21; border: 1px solid #232a34; border-radius: 14px;
      display: flex; flex-direction: column;
    }}
    aside h2 {{ font-size: 14px; padding: 14px 16px; border-bottom: 1px solid #232a34; }}
    .empty {{ padding: 40px 20px; text-align: center; color: #5b6675; font-size: 13px; line-height: 1.6; }}
  </style>
</head>
<body>
  <header>
    <span class="dot"></span>
    <span class="logo">Vig<span>i</span>l</span>
    <span class="status">{CAMERA_LABEL}</span>
    <span class="clock" id="clock"></span>
  </header>
  <main>
    <section class="feed">
      <div class="feed-head">
        📹 {CAMERA_LABEL}
        <span class="live-tag">● LIVE</span>
      </div>
      <div class="feed-body">
        <img src="/video_feed" alt="live camera feed">
      </div>
    </section>
    <aside>
      <h2>Alerts</h2>
      <div class="empty">
        No alerts yet.<br>
        Hold a phone up to the camera —<br>a detection box will appear on the feed.
      </div>
    </aside>
  </main>
  <script>
    const clock = document.getElementById('clock');
    setInterval(() => {{ clock.textContent = new Date().toLocaleTimeString(); }}, 1000);
  </script>
</body>
</html>
"""
