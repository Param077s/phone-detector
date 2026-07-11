"""
Vigil — Product v1, Step 6: multiple cameras at once
====================================================

Now Vigil watches MANY cameras at the same time, in a grid — exactly like a
real security room. Each camera has its own live feed and its own detection.
So you can run your Mac's webcam AND your phone (via IP Webcam) together.

Add cameras from the "⚙ Camera" button (name + stream URL). They're saved to
cameras.json so they come back after a restart. Remove one with the × on it.

Camera source rules:
    "0"  -> the Mac's built-in webcam
    a URL -> a network camera:
        phone (IP Webcam app):  http://192.168.1.5:8080/video
        real CCTV:              rtsp://user:pass@192.168.1.50:554/stream1
"""

import os
import time
import json
import uuid
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
# Accuracy ladder (bigger = smarter but slower). You have a GPU, so 'm' is a big
# jump from 'n' with fine speed. Want the most powerful? use "yolo11x.pt".
#   yolo11n  <  yolo11s  <  yolo11m  <  yolo11l  <  yolo11x
MODEL_NAME     = "yolo11m.pt"

CONFIDENCE     = 0.55   # ignore weak guesses. Raise toward 0.7 if still false-alarming;
                        # lower toward 0.45 if it misses real phones.
PHONE_CLASS    = 67
ALERT_COOLDOWN = 3

DETECT_EVERY   = 2      # run YOLO every Nth frame; show every frame (smooth video)
IMG_SIZE       = 640    # bigger = better at small/distant phones (640 = full accuracy)
JPEG_QUALITY   = 75     # streamed video quality (lower = faster / less bandwidth)

DB_PATH        = "evidence.db"
EVIDENCE_DIR   = "evidence"
CAMERAS_CONFIG = "cameras.json"

os.makedirs(EVIDENCE_DIR, exist_ok=True)

print(f"Loading YOLO ({MODEL_NAME})...")
model = YOLO(MODEL_NAME)
model_lock = threading.Lock()          # YOLO is shared across camera threads

# Use the Mac's GPU (Apple Silicon "mps") if available — a big speed-up. Else CPU.
try:
    import torch
    DEVICE = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
except Exception:
    DEVICE = "cpu"
try:
    model(np.zeros((IMG_SIZE, IMG_SIZE, 3), dtype=np.uint8), imgsz=IMG_SIZE, device=DEVICE, verbose=False)
    print(f"Detection device: {DEVICE}")
except Exception as e:
    print(f"Device '{DEVICE}' unavailable ({e}); falling back to CPU")
    DEVICE = "cpu"


# ---------------------------------------------------------------------------
# CAMERAS (a list — each is {id, label, source})
# ---------------------------------------------------------------------------
cameras_lock = threading.Lock()


def _load_cameras():
    try:
        with open(CAMERAS_CONFIG) as f:
            data = json.load(f)
            if isinstance(data, list) and data:
                return data
    except Exception:
        pass
    # Default: one camera = the Mac's built-in webcam
    return [{"id": "cam1", "label": "Camera 1 · Webcam", "source": "0"}]


def _save_cameras():
    try:
        with open(CAMERAS_CONFIG, "w") as f:
            json.dump(cameras, f)
    except Exception:
        pass


cameras = _load_cameras()


def _resolve_source(s):
    """'0'/'1' -> webcam number; anything else -> a URL."""
    return int(s) if s.isdigit() else s


def _place(c):
    """The location shown on alerts — falls back to the camera name."""
    return (c.get("location") or "").strip() or c["label"]


def _find_camera(cam_id):
    with cameras_lock:
        for c in cameras:
            if c["id"] == cam_id:
                return c["source"], _place(c)
    return None, None


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


def _store_alert(jpg_bytes, confidence, camera, status="pending", dt=None):
    dt = dt or datetime.now()
    with _db() as c:
        cur = c.execute(
            "INSERT INTO alerts (created_at, date, time, confidence, camera, image_file, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dt.isoformat(), dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S"),
             round(confidence, 2), camera, "", status))
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
# DETECTION  (per-camera cooldown so cameras don't block each other)
# ---------------------------------------------------------------------------
_cooldown_lock = threading.Lock()
_last_alert_time = {}    # camera_id -> timestamp


def maybe_add_alert(crop, confidence, camera_label, camera_id):
    now = time.time()
    with _cooldown_lock:
        if now - _last_alert_time.get(camera_id, 0) < ALERT_COOLDOWN or crop.size == 0:
            return
        ok, buf = cv2.imencode(".jpg", crop)
        if not ok:
            return
        _last_alert_time[camera_id] = now
        _store_alert(buf.tobytes(), confidence, camera_label, status="pending")


def _placeholder(text):
    img = np.full((480, 640, 3), 32, dtype=np.uint8)
    cv2.putText(img, text, (30, 240), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (170, 170, 170), 2)
    return img


# --- Background camera reader: always keeps the NEWEST frame (low latency) ---
class CameraStream:
    """Reads a camera in its own thread and holds only the latest frame, so the
    viewer never falls behind the live action (no lag build-up)."""
    def __init__(self, source):
        self.source = source
        self.frame = None
        self.running = True
        self.lock = threading.Lock()
        self.cap = self._open()
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _open(self):
        cap = cv2.VideoCapture(_resolve_source(self.source))
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)     # don't queue old frames
        except Exception:
            pass
        return cap

    def _reader(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(0.3)
                self.cap = self._open()
                continue
            ok, f = self.cap.read()
            if not ok:
                time.sleep(0.05)
                self.cap.release()
                self.cap = self._open()
                continue
            with self.lock:
                self.frame = f

    def read(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def stop(self):
        self.running = False
        try:
            self.cap.release()
        except Exception:
            pass


streams = {}                       # camera_id -> CameraStream
streams_lock = threading.Lock()


def _get_stream(camera_id, source):
    with streams_lock:
        s = streams.get(camera_id)
        if s is None or s.source != source:
            if s is not None:
                s.stop()
            s = CameraStream(source)
            streams[camera_id] = s
        return s


def generate_frames(camera_id):
    """Serve ONE camera: always show the newest frame, detect every Nth frame."""
    frame_i = 0
    last_boxes = []                # remembered between detections so video stays smooth

    while True:
        source, label = _find_camera(camera_id)
        if source is None:                              # camera removed
            with streams_lock:
                s = streams.pop(camera_id, None)
            if s is not None:
                s.stop()
            break

        stream = _get_stream(camera_id, source)
        frame = stream.read()

        if frame is None:
            msg = "Camera not connected" if source == "0" else "Connecting to camera..."
            frame = _placeholder(msg)
            time.sleep(0.05)
        else:
            frame_i += 1
            if frame_i % DETECT_EVERY == 0:             # run YOLO on this frame
                with model_lock:
                    results = model(frame, classes=[PHONE_CLASS], conf=CONFIDENCE,
                                    imgsz=IMG_SIZE, device=DEVICE, verbose=False)
                last_boxes = []
                for box in results[0].boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    last_boxes.append((x1, y1, x2, y2, conf))
                    maybe_add_alert(frame[y1:y2, x1:x2].copy(), conf, label, camera_id)

            for (x1, y1, x2, y2, conf) in last_boxes:   # draw on EVERY frame (smooth)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 90), 2)
                cv2.putText(frame, f"PHONE {conf:.0%}", (x1, max(y1 - 10, 20)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 90), 2)

        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            continue
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")


# ---------------------------------------------------------------------------
# THE WEB APP
# ---------------------------------------------------------------------------
app = FastAPI(title="Vigil")


@app.get("/video_feed/{camera_id}")
def video_feed(camera_id: str):
    return StreamingResponse(generate_frames(camera_id),
                             media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/cameras")
def list_cameras():
    with cameras_lock:
        return list(cameras)


@app.post("/cameras")
def add_camera(payload: dict):
    label = str(payload.get("label", "Camera")).strip() or "Camera"
    location = str(payload.get("location", "")).strip()
    source = str(payload.get("source", "0")).strip() or "0"
    cam = {"id": uuid.uuid4().hex[:8], "label": label, "location": location, "source": source}
    with cameras_lock:
        cameras.append(cam)
        _save_cameras()
    return cam


@app.put("/cameras/{cam_id}")
def edit_camera(cam_id: str, payload: dict):
    with cameras_lock:
        for c in cameras:
            if c["id"] == cam_id:
                if "label" in payload:
                    c["label"] = str(payload["label"]).strip() or c["label"]
                if "location" in payload:
                    c["location"] = str(payload["location"]).strip()
                if "source" in payload:
                    c["source"] = str(payload["source"]).strip() or c["source"]
                _save_cameras()
                return c
    return {"ok": False}


@app.delete("/cameras/{cam_id}")
def remove_camera(cam_id: str):
    with cameras_lock:
        cameras[:] = [c for c in cameras if c["id"] != cam_id]
        _save_cameras()
    return {"ok": True}


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
  .cam-btn { margin-left:auto; background:#4ade80; color:#0e1116; border:none;
    padding:8px 15px; border-radius:8px; font-size:13px; font-weight:600; cursor:pointer; }
  .clock { font-size: 13px; color: #9aa4b2; font-variant-numeric: tabular-nums; }
  .clock.push { margin-left:auto; }

  main { flex: 1; display: flex; gap: 18px; padding: 18px; min-height: 0; }
  .cameras { flex:1; display:flex; min-height:0; }
  .grid { flex:1; display:grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    grid-auto-rows: minmax(240px, 1fr); gap:14px; overflow-y:auto; align-content:start; }
  .panel { background:#151a21; border:1px solid #232a34; border-radius:12px;
    overflow:hidden; display:flex; flex-direction:column; }
  .panel-head { display:flex; align-items:center; gap:8px; padding:10px 12px;
    border-bottom:1px solid #232a34; font-size:13px; }
  .panel-body { flex:1; background:#000; display:flex; align-items:center; justify-content:center; min-height:0; }
  .panel-body img { max-width:100%; max-height:100%; }
  .live-tag { margin-left:auto; font-size:10px; font-weight:700; color:#0e1116;
    background:#4ade80; padding:3px 8px; border-radius:20px; }
  .icon-btn { background:transparent; border:none; color:#7a8595; font-size:15px;
    cursor:pointer; line-height:1; padding:0 3px; }
  .icon-btn:hover { color:#e6e9ef; }
  .remove { font-size:18px; }
  .remove:hover { color:#ef4444; }
  .grid-empty { grid-column:1/-1; text-align:center; color:#5b6675; padding:60px 20px; font-size:14px; }

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
  .alert-info { flex:1; display:flex; flex-direction:column; gap:3px; min-width:0; }
  .alert-title { font-size:13px; font-weight:600; }
  .alert-cam { font-size:11px; color:#4ade80; }
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

  /* Add-camera modal */
  .modal-bg { position:fixed; inset:0; background:rgba(0,0,0,.6); display:none;
    align-items:center; justify-content:center; z-index:50; }
  .modal-bg.open { display:flex; }
  .modal { background:#151a21; border:1px solid #232a34; border-radius:14px; padding:22px; width:470px; max-width:92vw; }
  .modal h3 { font-size:16px; margin-bottom:8px; }
  .modal p { font-size:13px; color:#9aa4b2; line-height:1.55; margin-bottom:14px; }
  .modal code { background:#0e1116; padding:2px 6px; border-radius:5px; color:#4ade80; font-size:12px; }
  .modal label { display:block; font-size:12px; color:#9aa4b2; margin:0 0 5px 2px; }
  .modal input { width:100%; background:#0e1116; border:1px solid #2b3340; color:#e6e9ef;
    padding:11px 12px; border-radius:8px; font-size:13px; margin-bottom:12px; }
  .modal-actions { display:flex; gap:8px; }
  .modal-actions button { flex:1; border:none; border-radius:8px; padding:11px 0; font-size:13px; font-weight:600; cursor:pointer; }
  .btn-primary { background:#4ade80; color:#0e1116; }
  .btn-ghost { background:#2b3340; color:#c4ccd8; }
</style>
"""

CAMERA_MODAL = """
<div class="modal-bg" id="cam-modal">
  <div class="modal">
    <h3 id="cam-title">Add a camera</h3>
    <p>The <b>location</b> shows on every alert and in the evidence log, so staff know
       exactly where to go. Phone via the <b>IP Webcam</b> app? Put the URL it shows plus
       <code>/video</code>. Real CCTV uses an <code>rtsp://…</code> URL. (Same WiFi required.)</p>
    <label>Camera name</label>
    <input id="cam-label" placeholder="e.g. Cam 2">
    <label>Location / place it watches</label>
    <input id="cam-location" placeholder="e.g. Bag-drop · West gate">
    <label>Stream URL (leave blank for this Mac's webcam)</label>
    <input id="cam-input" placeholder="http://192.168.1.5:8080/video   (or rtsp://...)">
    <div class="modal-actions">
      <button class="btn-primary" id="cam-submit" onclick="submitCam()">Add camera</button>
      <button class="btn-ghost" id="cam-webcam" onclick="addWebcam()">Add this Mac's webcam</button>
      <button class="btn-ghost" onclick="closeCam()">Cancel</button>
    </div>
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
    <button class="cam-btn" id="cam-btn">+ Add camera</button>
    <span class="clock" id="clock"></span>
  </header>
  <main>
    <section class="cameras"><div class="grid" id="grid"></div></section>
    <aside>
      <div class="aside-head">Alerts <span class="count" id="alert-count" style="display:none"></span></div>
      <div id="alerts"><div class="empty">No alerts yet.<br>Hold a phone up to a camera.</div></div>
    </aside>
  </main>
  __CAMERA_MODAL__
  <script>
    const clock = document.getElementById('clock');
    setInterval(() => { clock.textContent = new Date().toLocaleTimeString(); }, 1000);

    // ---- Camera grid ----
    function panelHTML(c) {
      const place = (c.location && c.location.trim()) ? c.location : c.label;
      return `<div class="panel">
        <div class="panel-head">📹 ${place}<span class="live-tag">● LIVE</span>
          <button class="icon-btn" title="Edit camera" onclick="openEdit('${c.id}')">✎</button>
          <button class="icon-btn remove" title="Remove camera" onclick="removeCam('${c.id}')">×</button></div>
        <div class="panel-body"><img src="/video_feed/${c.id}" alt="feed"></div>
      </div>`;
    }
    async function loadCameras() {
      let cams = [];
      try { cams = await (await fetch('/cameras')).json(); } catch (e) { return; }
      const grid = document.getElementById('grid');
      grid.innerHTML = cams.length
        ? cams.map(panelHTML).join('')
        : '<div class="grid-empty">No cameras yet. Click “+ Add camera” to add one.</div>';
    }

    let editingId = null;
    function openCam(){ document.getElementById('cam-modal').classList.add('open'); }
    function closeCam(){ document.getElementById('cam-modal').classList.remove('open'); }
    function openAdd() {
      editingId = null;
      document.getElementById('cam-title').textContent = 'Add a camera';
      document.getElementById('cam-submit').textContent = 'Add camera';
      document.getElementById('cam-webcam').style.display = '';
      document.getElementById('cam-label').value = '';
      document.getElementById('cam-location').value = '';
      document.getElementById('cam-input').value = '';
      openCam();
    }
    async function openEdit(id) {
      let cams = [];
      try { cams = await (await fetch('/cameras')).json(); } catch (e) { return; }
      const c = cams.find(x => x.id === id);
      if (!c) return;
      editingId = id;
      document.getElementById('cam-title').textContent = 'Edit camera';
      document.getElementById('cam-submit').textContent = 'Save';
      document.getElementById('cam-webcam').style.display = 'none';
      document.getElementById('cam-label').value = c.label || '';
      document.getElementById('cam-location').value = c.location || '';
      document.getElementById('cam-input').value = (c.source === '0') ? '' : (c.source || '');
      openCam();
    }
    async function submitCam() {
      const label = document.getElementById('cam-label').value.trim() || 'Camera';
      const location = document.getElementById('cam-location').value.trim();
      const source = document.getElementById('cam-input').value.trim() || '0';
      const body = JSON.stringify({ label, location, source });
      if (editingId) {
        await fetch('/cameras/' + editingId, { method:'PUT', headers:{'Content-Type':'application/json'}, body });
      } else {
        await fetch('/cameras', { method:'POST', headers:{'Content-Type':'application/json'}, body });
      }
      closeCam(); loadCameras();
    }
    async function addWebcam() {
      await fetch('/cameras', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ label: "Mac webcam", location: "", source: '0' }) });
      closeCam(); loadCameras();
    }
    async function removeCam(id) {
      await fetch('/cameras/' + id, { method:'DELETE' });
      loadCameras();
    }
    document.getElementById('cam-btn').onclick = openAdd;
    loadCameras();

    // ---- Alerts ----
    async function loadAlerts() {
      let data = [];
      try { data = await (await fetch('/alerts')).json(); } catch (e) { return; }
      const box = document.getElementById('alerts');
      const countEl = document.getElementById('alert-count');
      const pending = data.filter(a => a.status === 'pending').length;
      countEl.style.display = pending ? 'inline-block' : 'none';
      countEl.textContent = pending;
      if (data.length === 0) {
        box.innerHTML = '<div class="empty">No alerts yet.<br>Hold a phone up to a camera.</div>';
        return;
      }
      box.innerHTML = data.map(a => `
        <div class="alert ${a.status}">
          <img src="${a.image}">
          <div class="alert-info">
            <div class="alert-title">Phone detected · ${Math.round(a.confidence*100)}%</div>
            <div class="alert-cam">📍 ${a.camera}</div>
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
        <thead><tr><th>Photo</th><th>Date</th><th>Time</th><th>Location</th><th>Confidence</th><th>Status</th></tr></thead>
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
            .replace("__CAMERA_MODAL__", CAMERA_MODAL))


@app.get("/evidence", response_class=HTMLResponse)
def evidence_page():
    return EVIDENCE_HTML.replace("__STYLE__", STYLE)


# ---------------------------------------------------------------------------
# DEMO MODE — seed example alerts (only if empty).  VIGIL_DEMO=1
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
    _store_alert(jpg, 0.87, "Bag-drop · West gate", status="confirmed")
    _store_alert(jpg, 0.91, "Corridor 2 · Block A", status="pending")


if os.getenv("VIGIL_DEMO") == "1":
    _seed_demo_alerts()
