"""
Vigil — Product v1, Step 5: real IP cameras (RTSP / IP Webcam)
=============================================================

Until now we only used the built-in webcam. Step 5 lets Vigil connect to a
REAL camera over the network by its address — exactly like a university's CCTV.

You can test it right now with your phone:
    1. Install the "IP Webcam" app (Android) — or "DroidCam" / "IP Camera Lite" (iOS).
    2. Start the server in the app. It shows a URL like  http://192.168.1.5:8080
    3. In Vigil, click "Camera" (top right), paste:  http://192.168.1.5:8080/video
    4. Connect. Your phone is now a live CCTV camera and Vigil watches it.

Your phone and computer must be on the SAME WiFi.

How the camera switching works:
    - The current source is kept in camera_state and saved to camera_config.json.
    - The video loop notices when the source changes and reconnects on the fly.
    - "0" means the built-in webcam; anything else is treated as a URL.
"""

import os
import time
import json
import sqlite3
import threading
from datetime import datetime

import cv2
import numpy as np
from ultralytics import YOLO
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse


# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------
CONFIDENCE     = 0.40
PHONE_CLASS    = 67
CAMERA_LABEL   = "Camera 1 · Main Hall"
ALERT_COOLDOWN = 3

DB_PATH        = "evidence.db"
EVIDENCE_DIR   = "evidence"
CAMERA_CONFIG  = "camera_config.json"

os.makedirs(EVIDENCE_DIR, exist_ok=True)
_cooldown_lock = threading.Lock()
_last_alert_time = 0.0

print("Loading YOLO...")
model = YOLO("yolo11n.pt")


# ---------------------------------------------------------------------------
# CAMERA SOURCE (which camera we're watching — webcam or a network URL)
# ---------------------------------------------------------------------------
camera_lock = threading.Lock()


def _load_camera():
    try:
        with open(CAMERA_CONFIG) as f:
            return str(json.load(f).get("source", "0"))
    except Exception:
        return os.getenv("VIGIL_CAMERA", "0")


def _save_camera(src):
    try:
        with open(CAMERA_CONFIG, "w") as f:
            json.dump({"source": src}, f)
    except Exception:
        pass


camera_state = {"source": _load_camera()}


def _resolve_source(s):
    """'0' or '1' -> webcam number; anything else -> a URL (rtsp/http)."""
    return int(s) if s.isdigit() else s


# ---------------------------------------------------------------------------
# DATABASE (SQLite)
# ---------------------------------------------------------------------------
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT,
                date        TEXT,
                time        TEXT,
                confidence  REAL,
                camera      TEXT,
                image_file  TEXT,
                status      TEXT
            )
        """)


def _store_alert(jpg_bytes, confidence, status="pending", dt=None):
    dt = dt or datetime.now()
    with _db() as c:
        cur = c.execute(
            "INSERT INTO alerts (created_at, date, time, confidence, camera, image_file, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dt.isoformat(), dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S"),
             round(confidence, 2), CAMERA_LABEL, "", status))
        alert_id = cur.lastrowid
        fname = os.path.join(EVIDENCE_DIR, f"alert_{alert_id}_{dt.strftime('%Y%m%d_%H%M%S')}.jpg")
        with open(fname, "wb") as f:
            f.write(jpg_bytes)
        c.execute("UPDATE alerts SET image_file = ? WHERE id = ?", (fname, alert_id))
    return alert_id


def _row_to_dict(r):
    return {
        "id": r["id"], "time": r["time"], "date": r["date"],
        "confidence": r["confidence"], "camera": r["camera"],
        "status": r["status"], "image": f"/evidence/image/{r['id']}",
    }


init_db()


# ---------------------------------------------------------------------------
# DETECTION
# ---------------------------------------------------------------------------
def maybe_add_alert(crop, confidence):
    global _last_alert_time
    now = time.time()
    with _cooldown_lock:
        if now - _last_alert_time < ALERT_COOLDOWN or crop.size == 0:
            return
        ok, buf = cv2.imencode(".jpg", crop)
        if not ok:
            return
        _last_alert_time = now
        _store_alert(buf.tobytes(), confidence, status="pending")


def _placeholder(text):
    img = np.full((480, 640, 3), 32, dtype=np.uint8)
    cv2.putText(img, text, (40, 240), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (180, 180, 180), 2)
    return img


def generate_frames():
    """Streams frames, and reconnects automatically if the camera source changes."""
    current_source = None
    cap = None

    while True:
        # Has the user pointed us at a different camera?
        with camera_lock:
            desired = camera_state["source"]
        if desired != current_source:
            if cap is not None:
                cap.release()
            cap = cv2.VideoCapture(_resolve_source(desired))
            current_source = desired

        frame = None
        if cap is not None and cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                cap.release()                                   # lost the stream — retry
                cap = cv2.VideoCapture(_resolve_source(desired))
                frame = None

        if frame is None:
            msg = "Camera not connected - demo mode" if desired == "0" else "Connecting to camera..."
            frame = _placeholder(msg)
            time.sleep(0.15)
        else:
            results = model(frame, classes=[PHONE_CLASS], conf=CONFIDENCE, verbose=False)
            for box in results[0].boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                crop = frame[y1:y2, x1:x2].copy()
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 90), 2)
                cv2.putText(frame, f"PHONE {conf:.0%}", (x1, max(y1 - 10, 20)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 90), 2)
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


@app.get("/camera")
def get_camera():
    with camera_lock:
        return {"source": camera_state["source"]}


@app.post("/camera")
def set_camera(payload: dict):
    src = str(payload.get("source", "0")).strip() or "0"
    with camera_lock:
        camera_state["source"] = src
    _save_camera(src)
    return {"ok": True, "source": src}


@app.get("/alerts")
def get_alerts():
    with _db() as c:
        rows = c.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 25").fetchall()
    return [_row_to_dict(r) for r in rows]


@app.get("/evidence/list")
def evidence_list(status: str = "all", date: str = ""):
    query, params = "SELECT * FROM alerts WHERE 1=1", []
    if status != "all":
        query += " AND status = ?"
        params.append(status)
    if date:
        query += " AND date = ?"
        params.append(date)
    query += " ORDER BY id DESC LIMIT 500"
    with _db() as c:
        rows = c.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


@app.get("/evidence/image/{alert_id}")
def evidence_image(alert_id: int):
    with _db() as c:
        row = c.execute("SELECT image_file FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row and row["image_file"] and os.path.exists(row["image_file"]):
        return FileResponse(row["image_file"], media_type="image/jpeg")
    return Response(status_code=404)


@app.post("/alerts/{alert_id}/{action}")
def update_alert(alert_id: int, action: str):
    if action not in ("confirm", "dismiss"):
        return {"ok": False}
    new_status = "confirmed" if action == "confirm" else "dismissed"
    with _db() as c:
        c.execute("UPDATE alerts SET status = ? WHERE id = ?", (new_status, alert_id))
    return {"ok": True}


# ---- Shared look ----------------------------------------------------------
STYLE = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif;
    background: #0e1116; color: #e6e9ef; height: 100vh; display: flex; flex-direction: column; }
  header { display: flex; align-items: center; gap: 14px;
    padding: 12px 22px; background: #151a21; border-bottom: 1px solid #232a34; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: #4ade80;
    box-shadow: 0 0 8px #4ade80; animation: pulse 1.6s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .logo { font-weight: 700; font-size: 20px; letter-spacing: .5px; }
  .logo span { color: #4ade80; }
  .nav { display:flex; gap:6px; margin-left: 10px; }
  .nav a { font-size:13px; color:#9aa4b2; text-decoration:none; padding:6px 12px; border-radius:8px; }
  .nav a.active { background:#232a34; color:#e6e9ef; }
  .cam-btn { margin-left:auto; background:#232a34; color:#e6e9ef; border:none;
    padding:7px 14px; border-radius:8px; font-size:13px; cursor:pointer; }
  .clock { font-size: 13px; color: #9aa4b2; font-variant-numeric: tabular-nums; }
  .clock.push { margin-left: auto; }

  main { flex: 1; display: flex; gap: 18px; padding: 18px; min-height: 0; }
  .feed { flex: 1; background: #151a21; border: 1px solid #232a34; border-radius: 14px;
    overflow: hidden; display: flex; flex-direction: column; }
  .feed-head { display:flex; align-items:center; gap:8px; padding: 12px 16px;
    border-bottom: 1px solid #232a34; font-size: 14px; }
  .feed-body { flex:1; display:flex; align-items:center; justify-content:center; background:#000; min-height:0; }
  .feed-body img { max-width: 100%; max-height: 100%; }
  .live-tag { margin-left:auto; font-size:11px; font-weight:700; color:#0e1116;
    background:#4ade80; padding:3px 8px; border-radius:20px; }

  aside { width: 340px; background: #151a21; border: 1px solid #232a34; border-radius: 14px;
    display: flex; flex-direction: column; }
  .aside-head { display:flex; align-items:center; gap:8px;
    font-size: 14px; font-weight:600; padding: 14px 16px; border-bottom: 1px solid #232a34; }
  .count { background:#ef4444; color:#fff; font-size:11px; font-weight:700;
    min-width:20px; text-align:center; padding:2px 6px; border-radius:20px; }
  #alerts { overflow-y:auto; padding: 12px; display:flex; flex-direction:column; gap:10px; }
  .empty { padding: 40px 20px; text-align: center; color: #5b6675; font-size: 13px; line-height: 1.6; }
  .alert { display:flex; gap:12px; background:#1b212a; border:1px solid #283040;
    border-radius:10px; padding:10px; }
  .alert.dismissed { opacity:.45; }
  .alert img { width:56px; height:72px; object-fit:cover; border-radius:6px; background:#000; flex-shrink:0; }
  .alert-info { flex:1; display:flex; flex-direction:column; gap:4px; min-width:0; }
  .alert-title { font-size:13px; font-weight:600; }
  .alert-time { font-size:12px; color:#9aa4b2; }
  .alert-actions { display:flex; gap:8px; margin-top:4px; }
  .alert-actions button { flex:1; border:none; border-radius:6px; padding:6px 0;
    font-size:12px; font-weight:600; cursor:pointer; }
  button.confirm { background:#4ade80; color:#0e1116; }
  button.dismiss { background:#2b3340; color:#c4ccd8; }
  .badge { align-self:flex-start; margin-top:4px; font-size:11px; font-weight:700;
    padding:3px 10px; border-radius:20px; text-transform:capitalize; }
  .badge.confirmed { background:rgba(74,222,128,.15); color:#4ade80; }
  .badge.dismissed { background:rgba(148,163,184,.15); color:#94a3b8; }
  .badge.pending   { background:rgba(234,179,8,.15); color:#eab308; }

  /* Evidence Log page */
  .evidence-wrap { flex:1; display:flex; flex-direction:column; gap:16px; padding:18px; overflow:hidden; }
  .filters { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .filters .fbtn { font-size:13px; color:#9aa4b2; background:#151a21; border:1px solid #232a34;
    padding:7px 14px; border-radius:8px; cursor:pointer; }
  .filters .fbtn.active { background:#4ade80; color:#0e1116; border-color:#4ade80; font-weight:600; }
  .filters input[type=date] { margin-left:auto; background:#151a21; color:#e6e9ef;
    border:1px solid #232a34; padding:7px 10px; border-radius:8px; font-size:13px; }
  .table { flex:1; overflow-y:auto; background:#151a21; border:1px solid #232a34; border-radius:14px; }
  table { width:100%; border-collapse:collapse; }
  th { text-align:left; font-size:12px; color:#9aa4b2; font-weight:600;
    padding:12px 16px; border-bottom:1px solid #232a34; position:sticky; top:0; background:#151a21; }
  td { padding:10px 16px; border-bottom:1px solid #1c222b; font-size:13px; vertical-align:middle; }
  td img { width:40px; height:52px; object-fit:cover; border-radius:5px; background:#000; }
  tr:hover td { background:#1a2028; }

  /* Camera settings modal */
  .modal-bg { position:fixed; inset:0; background:rgba(0,0,0,.6); display:none;
    align-items:center; justify-content:center; z-index:50; }
  .modal-bg.open { display:flex; }
  .modal { background:#151a21; border:1px solid #232a34; border-radius:14px; padding:22px; width:460px; max-width:92vw; }
  .modal h3 { font-size:16px; margin-bottom:8px; }
  .modal p { font-size:13px; color:#9aa4b2; line-height:1.55; margin-bottom:14px; }
  .modal code { background:#0e1116; padding:2px 6px; border-radius:5px; color:#4ade80; font-size:12px; }
  .modal input { width:100%; background:#0e1116; border:1px solid #2b3340; color:#e6e9ef;
    padding:11px 12px; border-radius:8px; font-size:13px; margin-bottom:12px; }
  .modal-actions { display:flex; gap:8px; }
  .modal-actions button { flex:1; border:none; border-radius:8px; padding:11px 0; font-size:13px; font-weight:600; cursor:pointer; }
  .btn-primary { background:#4ade80; color:#0e1116; }
  .btn-ghost { background:#2b3340; color:#c4ccd8; }
  .hint { font-size:12px; color:#5b6675; margin-top:12px; }
</style>
"""

CAMERA_MODAL = """
<div class="modal-bg" id="cam-modal">
  <div class="modal">
    <h3>Connect a camera</h3>
    <p>Paste your camera's stream address.<br>
       Testing with your phone and the <b>IP Webcam</b> app? Enter the URL it shows plus <code>/video</code>,
       for example <code>http://192.168.1.5:8080/video</code>.<br>
       (Phone and computer must be on the same WiFi.)</p>
    <input id="cam-input" placeholder="http://192.168.1.5:8080/video   (or rtsp://...)">
    <div class="modal-actions">
      <button class="btn-primary" onclick="connectCam()">Connect</button>
      <button class="btn-ghost" onclick="useWebcam()">Use webcam</button>
      <button class="btn-ghost" onclick="closeCam()">Cancel</button>
    </div>
    <div class="hint" id="cam-current"></div>
  </div>
</div>
"""


# ---- Live Monitor page ----------------------------------------------------
DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — Live Monitor</title>__STYLE__</head>
<body>
  <header>
    <span class="dot"></span>
    <span class="logo">Vig<span>i</span>l</span>
    <nav class="nav"><a href="/" class="active">Live Monitor</a><a href="/evidence">Evidence Log</a></nav>
    <button class="cam-btn" id="cam-btn">⚙ Camera</button>
    <span class="clock" id="clock"></span>
  </header>
  <main>
    <section class="feed">
      <div class="feed-head">📹 __CAMERA_LABEL__<span class="live-tag">● LIVE</span></div>
      <div class="feed-body"><img src="/video_feed" alt="live camera feed"></div>
    </section>
    <aside>
      <div class="aside-head">Alerts <span class="count" id="alert-count" style="display:none"></span></div>
      <div id="alerts"><div class="empty">No alerts yet.<br>Hold a phone up to the camera.</div></div>
    </aside>
  </main>
  __CAMERA_MODAL__
  <script>
    const clock = document.getElementById('clock');
    setInterval(() => { clock.textContent = new Date().toLocaleTimeString(); }, 1000);

    async function loadAlerts() {
      let data = [];
      try { data = await (await fetch('/alerts')).json(); } catch (e) { return; }
      const box = document.getElementById('alerts');
      const countEl = document.getElementById('alert-count');
      const pending = data.filter(a => a.status === 'pending').length;
      countEl.style.display = pending ? 'inline-block' : 'none';
      countEl.textContent = pending;
      if (data.length === 0) {
        box.innerHTML = '<div class="empty">No alerts yet.<br>Hold a phone up to the camera.</div>';
        return;
      }
      box.innerHTML = data.map(a => `
        <div class="alert ${a.status}">
          <img src="${a.image}">
          <div class="alert-info">
            <div class="alert-title">Phone detected · ${Math.round(a.confidence*100)}%</div>
            <div class="alert-time">${a.time}</div>
            ${a.status === 'pending'
              ? `<div class="alert-actions">
                   <button class="confirm" onclick="act(${a.id},'confirm')">Confirm</button>
                   <button class="dismiss" onclick="act(${a.id},'dismiss')">Dismiss</button>
                 </div>`
              : `<div class="badge ${a.status}">${a.status}</div>`}
          </div>
        </div>`).join('');
    }
    async function act(id, action) {
      try { await fetch(`/alerts/${id}/${action}`, { method:'POST' }); } catch (e) {}
      loadAlerts();
    }
    setInterval(loadAlerts, 1500);
    loadAlerts();

    // ---- Camera settings ----
    function openCam(){ document.getElementById('cam-modal').classList.add('open'); loadCam(); }
    function closeCam(){ document.getElementById('cam-modal').classList.remove('open'); }
    async function loadCam(){
      try {
        const c = await (await fetch('/camera')).json();
        const label = c.source === '0' ? 'Built-in webcam' : c.source;
        document.getElementById('cam-current').textContent = 'Current source: ' + label;
        document.getElementById('cam-input').value = c.source === '0' ? '' : c.source;
      } catch (e) {}
    }
    async function connectCam(){
      const v = document.getElementById('cam-input').value.trim();
      await fetch('/camera', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ source: v || '0' }) });
      closeCam();
    }
    async function useWebcam(){
      await fetch('/camera', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ source: '0' }) });
      closeCam();
    }
    document.getElementById('cam-btn').onclick = openCam;
  </script>
</body></html>"""


# ---- Evidence Log page ----------------------------------------------------
EVIDENCE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — Evidence Log</title>__STYLE__</head>
<body>
  <header>
    <span class="dot"></span>
    <span class="logo">Vig<span>i</span>l</span>
    <nav class="nav"><a href="/">Live Monitor</a><a href="/evidence" class="active">Evidence Log</a></nav>
    <span class="clock push" id="clock"></span>
  </header>
  <div class="evidence-wrap">
    <div class="filters">
      <button class="fbtn active" data-status="all"       onclick="setStatus(this)">All</button>
      <button class="fbtn"        data-status="confirmed" onclick="setStatus(this)">Confirmed</button>
      <button class="fbtn"        data-status="pending"   onclick="setStatus(this)">Pending</button>
      <button class="fbtn"        data-status="dismissed" onclick="setStatus(this)">Dismissed</button>
      <input type="date" id="date" onchange="load()">
    </div>
    <div class="table">
      <table>
        <thead><tr><th>Photo</th><th>Date</th><th>Time</th><th>Camera</th><th>Confidence</th><th>Status</th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  </div>
  <script>
    const clock = document.getElementById('clock');
    setInterval(() => { clock.textContent = new Date().toLocaleTimeString(); }, 1000);

    let currentStatus = 'all';
    function setStatus(btn) {
      currentStatus = btn.dataset.status;
      document.querySelectorAll('.fbtn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      load();
    }
    async function load() {
      const date = document.getElementById('date').value;
      const url = `/evidence/list?status=${currentStatus}&date=${date}`;
      let rows = [];
      try { rows = await (await fetch(url)).json(); } catch (e) { return; }
      const body = document.getElementById('rows');
      if (rows.length === 0) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#5b6675;padding:40px">No matching records.</td></tr>';
        return;
      }
      body.innerHTML = rows.map(r => `
        <tr>
          <td><img src="${r.image}"></td>
          <td>${r.date}</td>
          <td>${r.time}</td>
          <td>${r.camera}</td>
          <td>${Math.round(r.confidence*100)}%</td>
          <td><span class="badge ${r.status}">${r.status}</span></td>
        </tr>`).join('');
    }
    setInterval(load, 3000);
    load();
  </script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return (DASHBOARD_HTML
            .replace("__STYLE__", STYLE)
            .replace("__CAMERA_MODAL__", CAMERA_MODAL)
            .replace("__CAMERA_LABEL__", CAMERA_LABEL))


@app.get("/evidence", response_class=HTMLResponse)
def evidence_page():
    return EVIDENCE_HTML.replace("__STYLE__", STYLE)


# ---------------------------------------------------------------------------
# DEMO MODE — seed example alerts (only if the log is empty).  VIGIL_DEMO=1
# ---------------------------------------------------------------------------
def _seed_demo_alerts():
    with _db() as c:
        n = c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    if n > 0:
        return
    fake = np.full((160, 120, 3), 18, dtype=np.uint8)
    cv2.rectangle(fake, (35, 15), (85, 145), (55, 58, 66), -1)
    cv2.rectangle(fake, (40, 22), (80, 120), (30, 33, 40), -1)
    ok, buf = cv2.imencode(".jpg", fake)
    jpg = buf.tobytes()
    _store_alert(jpg, 0.87, status="confirmed")
    _store_alert(jpg, 0.91, status="pending")


if os.getenv("VIGIL_DEMO") == "1":
    _seed_demo_alerts()
