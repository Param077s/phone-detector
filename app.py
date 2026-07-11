"""
Vigil — Product v1, Step 2: the alerts panel (human-in-the-loop)
================================================================

Step 1 gave us a live dashboard that boxes phones. Step 2 adds the important
part: when a phone is detected, an ALERT card appears in the sidebar with a
cropped photo, the time, and Confirm / Dismiss buttons.

The rule of the whole product: the AI only FLAGS. A human DECIDES.
That protects students from false accusations and protects us from liability.

How it works:
  - The camera loop detects a phone -> saves a cropped photo -> adds an alert.
  - The browser asks "/alerts" every 1.5s and draws a card for each one.
  - Clicking Confirm/Dismiss calls the server, which updates that alert.

Demo mode (for showing the product without a live phone):
  run with VIGIL_DEMO=1 to seed a couple of example alerts.
"""

import os
import time
import base64
import threading
from datetime import datetime

import cv2
import numpy as np
from ultralytics import YOLO
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse


# ---------------------------------------------------------------------------
# SETTINGS (tweak freely)
# ---------------------------------------------------------------------------
CAMERA_SOURCE  = 0      # 0 = built-in webcam. Later this becomes a camera's address.
CONFIDENCE     = 0.40   # how sure YOLO must be (0.0 - 1.0)
PHONE_CLASS    = 67     # 67 = "cell phone" in YOLO's built-in list
CAMERA_LABEL   = "Camera 1 · Main Hall"
ALERT_COOLDOWN = 3      # seconds between new alerts (so we don't create hundreds)


# ---------------------------------------------------------------------------
# ALERT STORAGE (kept in memory for now; Step 3 will save it to disk)
# ---------------------------------------------------------------------------
alerts = []                       # newest first; each is a dict (see below)
alerts_lock = threading.Lock()    # keeps things safe across threads
_alert_counter = 0
_last_alert_time = 0.0


print("Loading YOLO...")
model = YOLO("yolo11n.pt")


def _jpeg_data_url(image):
    """Turn an image into a base64 'data URL' the browser can show directly."""
    ok, buf = cv2.imencode(".jpg", image)
    if not ok:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def maybe_add_alert(crop, confidence):
    """Create a new alert from a cropped phone photo — but at most once per cooldown."""
    global _last_alert_time, _alert_counter
    now = time.time()
    with alerts_lock:
        if now - _last_alert_time < ALERT_COOLDOWN or crop.size == 0:
            return
        data_url = _jpeg_data_url(crop)
        if data_url is None:
            return
        _last_alert_time = now
        _alert_counter += 1
        alerts.insert(0, {
            "id": _alert_counter,
            "time": datetime.now().strftime("%H:%M:%S"),
            "confidence": round(confidence, 2),
            "image": data_url,
            "status": "pending",           # pending | confirmed | dismissed
        })
        del alerts[50:]                    # keep only the most recent 50


def _placeholder(text):
    img = np.full((480, 640, 3), 32, dtype=np.uint8)
    cv2.putText(img, text, (40, 240), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (180, 180, 180), 2)
    return img


def generate_frames():
    """Never-ending stream of JPEG frames for the browser."""
    cap = cv2.VideoCapture(CAMERA_SOURCE)

    while True:
        if not cap.isOpened():
            frame = _placeholder("Camera not connected - demo mode")
            time.sleep(0.1)
        else:
            ok, frame = cap.read()
            if not ok:
                cap = cv2.VideoCapture(CAMERA_SOURCE)
                frame = _placeholder("Reconnecting to camera...")
            else:
                results = model(frame, classes=[PHONE_CLASS],
                                conf=CONFIDENCE, verbose=False)
                for box in results[0].boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])

                    # Crop the phone from the CLEAN frame (before drawing on it)
                    crop = frame[y1:y2, x1:x2].copy()

                    # Draw the box on the live view
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 90), 2)
                    cv2.putText(frame, f"PHONE {conf:.0%}", (x1, max(y1 - 10, 20)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 90), 2)

                    # Record an alert (cooldown handled inside)
                    maybe_add_alert(crop, conf)

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


@app.get("/alerts")
def get_alerts():
    """The browser polls this to draw the alert cards."""
    with alerts_lock:
        return list(alerts)


@app.post("/alerts/{alert_id}/{action}")
def update_alert(alert_id: int, action: str):
    """A human confirms or dismisses an alert."""
    with alerts_lock:
        for a in alerts:
            if a["id"] == alert_id:
                if action in ("confirm", "dismiss"):
                    a["status"] = "confirmed" if action == "confirm" else "dismissed"
                    return {"ok": True}
    return {"ok": False}


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
    body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif;
      background: #0e1116; color: #e6e9ef; height: 100vh; display: flex; flex-direction: column; }}
    header {{ display: flex; align-items: center; gap: 12px;
      padding: 14px 22px; background: #151a21; border-bottom: 1px solid #232a34; }}
    .logo {{ font-weight: 700; font-size: 20px; letter-spacing: .5px; }}
    .logo span {{ color: #4ade80; }}
    .dot {{ width: 9px; height: 9px; border-radius: 50%; background: #4ade80;
      box-shadow: 0 0 8px #4ade80; animation: pulse 1.6s infinite; }}
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}
    .status {{ font-size: 13px; color: #9aa4b2; }}
    .clock {{ margin-left: auto; font-size: 13px; color: #9aa4b2; font-variant-numeric: tabular-nums; }}
    main {{ flex: 1; display: flex; gap: 18px; padding: 18px; min-height: 0; }}
    .feed {{ flex: 1; background: #151a21; border: 1px solid #232a34; border-radius: 14px;
      overflow: hidden; display: flex; flex-direction: column; }}
    .feed-head {{ display:flex; align-items:center; gap:8px; padding: 12px 16px;
      border-bottom: 1px solid #232a34; font-size: 14px; }}
    .feed-body {{ flex:1; display:flex; align-items:center; justify-content:center; background:#000; min-height:0; }}
    .feed-body img {{ max-width: 100%; max-height: 100%; }}
    .live-tag {{ margin-left:auto; font-size:11px; font-weight:700; color:#0e1116;
      background:#4ade80; padding:3px 8px; border-radius:20px; }}
    aside {{ width: 340px; background: #151a21; border: 1px solid #232a34; border-radius: 14px;
      display: flex; flex-direction: column; }}
    .aside-head {{ display:flex; align-items:center; gap:8px;
      font-size: 14px; font-weight:600; padding: 14px 16px; border-bottom: 1px solid #232a34; }}
    .count {{ background:#ef4444; color:#fff; font-size:11px; font-weight:700;
      min-width:20px; text-align:center; padding:2px 6px; border-radius:20px; }}
    #alerts {{ overflow-y:auto; padding: 12px; display:flex; flex-direction:column; gap:10px; }}
    .empty {{ padding: 40px 20px; text-align: center; color: #5b6675; font-size: 13px; line-height: 1.6; }}
    .alert {{ display:flex; gap:12px; background:#1b212a; border:1px solid #283040;
      border-radius:10px; padding:10px; }}
    .alert.dismissed {{ opacity:.45; }}
    .alert img {{ width:56px; height:72px; object-fit:cover; border-radius:6px; background:#000; flex-shrink:0; }}
    .alert-info {{ flex:1; display:flex; flex-direction:column; gap:4px; min-width:0; }}
    .alert-title {{ font-size:13px; font-weight:600; }}
    .alert-time {{ font-size:12px; color:#9aa4b2; }}
    .alert-actions {{ display:flex; gap:8px; margin-top:4px; }}
    .alert-actions button {{ flex:1; border:none; border-radius:6px; padding:6px 0;
      font-size:12px; font-weight:600; cursor:pointer; }}
    button.confirm {{ background:#4ade80; color:#0e1116; }}
    button.dismiss {{ background:#2b3340; color:#c4ccd8; }}
    .badge {{ align-self:flex-start; margin-top:4px; font-size:11px; font-weight:700;
      padding:3px 10px; border-radius:20px; text-transform:capitalize; }}
    .badge.confirmed {{ background:rgba(74,222,128,.15); color:#4ade80; }}
    .badge.dismissed {{ background:rgba(148,163,184,.15); color:#94a3b8; }}
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
      <div class="feed-head">📹 {CAMERA_LABEL}<span class="live-tag">● LIVE</span></div>
      <div class="feed-body"><img src="/video_feed" alt="live camera feed"></div>
    </section>
    <aside>
      <div class="aside-head">Alerts <span class="count" id="alert-count" style="display:none"></span></div>
      <div id="alerts"><div class="empty">No alerts yet.<br>Hold a phone up to the camera.</div></div>
    </aside>
  </main>
  <script>
    const clock = document.getElementById('clock');
    setInterval(() => {{ clock.textContent = new Date().toLocaleTimeString(); }}, 1000);

    async function loadAlerts() {{
      let data = [];
      try {{ data = await (await fetch('/alerts')).json(); }} catch (e) {{ return; }}
      const box = document.getElementById('alerts');
      const countEl = document.getElementById('alert-count');
      const pending = data.filter(a => a.status === 'pending').length;
      countEl.style.display = pending ? 'inline-block' : 'none';
      countEl.textContent = pending;

      if (data.length === 0) {{
        box.innerHTML = '<div class="empty">No alerts yet.<br>Hold a phone up to the camera.</div>';
        return;
      }}
      box.innerHTML = data.map(a => `
        <div class="alert ${{a.status}}">
          <img src="${{a.image}}">
          <div class="alert-info">
            <div class="alert-title">Phone detected · ${{Math.round(a.confidence*100)}}%</div>
            <div class="alert-time">${{a.time}}</div>
            ${{a.status === 'pending'
              ? `<div class="alert-actions">
                   <button class="confirm" onclick="act(${{a.id}},'confirm')">Confirm</button>
                   <button class="dismiss" onclick="act(${{a.id}},'dismiss')">Dismiss</button>
                 </div>`
              : `<div class="badge ${{a.status}}">${{a.status}}</div>`}}
          </div>
        </div>`).join('');
    }}

    async function act(id, action) {{
      try {{ await fetch(`/alerts/${{id}}/${{action}}`, {{ method:'POST' }}); }} catch (e) {{}}
      loadAlerts();
    }}

    setInterval(loadAlerts, 1500);
    loadAlerts();
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# DEMO MODE — seed example alerts so you can show the product without a phone.
# Turn on with:  VIGIL_DEMO=1
# ---------------------------------------------------------------------------
def _seed_demo_alerts():
    global _alert_counter
    def fake_crop():
        img = np.full((160, 120, 3), 18, dtype=np.uint8)
        cv2.rectangle(img, (35, 15), (85, 145), (55, 58, 66), -1)
        cv2.rectangle(img, (40, 22), (80, 120), (30, 33, 40), -1)
        return _jpeg_data_url(img)
    for conf, status in [(0.91, "pending"), (0.87, "confirmed")]:
        _alert_counter += 1
        alerts.insert(0, {
            "id": _alert_counter,
            "time": datetime.now().strftime("%H:%M:%S"),
            "confidence": conf,
            "image": fake_crop(),
            "status": status,
        })


if os.getenv("VIGIL_DEMO") == "1":
    _seed_demo_alerts()
