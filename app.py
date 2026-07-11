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

# Quiet OpenCV/FFmpeg so a disconnected camera doesn't flood the terminal.
# (must be set before cv2 is imported)
os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")

import time
import json
import uuid
import urllib.request
import urllib.parse
import hmac
import hashlib
import secrets
import sqlite3
import threading
from datetime import datetime

import cv2
import numpy as np
from ultralytics import YOLO
from fastapi import FastAPI, Response, Request, Form
from fastapi.responses import (StreamingResponse, HTMLResponse, FileResponse,
                               RedirectResponse, JSONResponse)

try:
    cv2.setLogLevel(0)     # extra-quiet OpenCV (belt and braces with the env vars above)
except Exception:
    pass


# ---------------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------------
# Accuracy ladder (bigger = smarter but slower). You have a GPU, so 'm' is a big
# jump from 'n' with fine speed. Want the most powerful? use "yolo11x.pt".
#   yolo11n  <  yolo11s  <  yolo11m  <  yolo11l  <  yolo11x
MODEL_NAME     = "yolo11m.pt"       # generic model (reliable). The auto-labeled
                                    # "vigil-phone.pt" fine-tune learned bad labels
                                    # (faces marked as phones) — needs clean labels first.

CONFIDENCE     = 0.45   # lower = catches faint/distant phones (but more false alarms).
                        # Raise toward 0.6 if it false-alarms; lower toward 0.35 for more range.
REQUIRED_HITS  = 3      # a phone must be seen this many detections IN A ROW before it
                        # raises an alert — this is what kills brief false positives on
                        # random objects (a real phone held up stays; junk flickers).
PHONE_CLASS    = 67
ALERT_COOLDOWN = 3

IMG_SIZE       = 960    # detail for the full-frame pass (catches near/large phones)
JPEG_QUALITY   = 75     # streamed video quality (lower = faster / less bandwidth)

# --- Tiling (for spotting phones far away) -------------------------------
# Slice each frame into overlapping tiles and scan each one zoomed-in, so a
# distant phone (tiny in the whole frame) is large enough inside its tile to see.
TILING         = True
TILE_COLS      = 2      # tiles across
TILE_ROWS      = 2      # tiles down   (2x2 = 4 tiles + 1 full-frame pass)
TILE_OVERLAP   = 0.15   # overlap so a phone on a tile seam isn't cut in half
TILE_IMGSZ     = 768    # detail per tile

DB_PATH        = "evidence.db"
EVIDENCE_DIR   = "evidence"
CAMERAS_CONFIG = "cameras.json"

os.makedirs(EVIDENCE_DIR, exist_ok=True)


# --- Live-tunable settings (editable from the in-app Settings page) ---------
# The values above are the DEFAULTS; settings.json (if present) overrides them,
# and the Settings page updates both the running values and settings.json.
TELEGRAM_TOKEN    = ""   # Telegram bot token (set from the Settings page)
TELEGRAM_CHAT_IDS = ""   # comma-separated chat id(s) to send alerts to

SETTINGS_FILE = "settings.json"
TUNABLE = ["MODEL_NAME", "CONFIDENCE", "REQUIRED_HITS", "ALERT_COOLDOWN", "IMG_SIZE",
           "TILING", "TILE_COLS", "TILE_ROWS", "TILE_OVERLAP", "TILE_IMGSZ",
           "TELEGRAM_TOKEN", "TELEGRAM_CHAT_IDS"]


def _apply_saved_settings():
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
    except Exception:
        return
    g = globals()
    for k in TUNABLE:
        if k in data:
            g[k] = data[k]


def current_settings():
    g = globals()
    return {k: g[k] for k in TUNABLE}


def save_settings(new):
    g = globals()
    for k in TUNABLE:
        if k in new:
            g[k] = new[k]
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(current_settings(), f, indent=2)
    except Exception:
        pass


_apply_saved_settings()

print(f"Loading YOLO ({MODEL_NAME})...")
model = YOLO(MODEL_NAME)

# Auto-detect which class id is the phone, so a FINE-TUNED model works too:
#   COCO pretrained -> 67 ("cell phone");  fine-tuned single-class -> usually 0 ("phone")
try:
    PHONE_CLASS = next((i for i, n in model.names.items() if "phone" in str(n).lower()), PHONE_CLASS)
    print(f"Phone class id: {PHONE_CLASS} ({model.names.get(PHONE_CLASS)})")
except Exception:
    pass
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


def reload_model():
    """Swap in a different model (called when MODEL_NAME changes in Settings)."""
    global model, PHONE_CLASS
    with model_lock:
        new_model = YOLO(MODEL_NAME)                      # raises if the file/name is bad
        model = new_model
        try:
            PHONE_CLASS = next((i for i, n in model.names.items() if "phone" in str(n).lower()), PHONE_CLASS)
        except Exception:
            pass


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
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT UNIQUE,
                pw_hash     TEXT,
                salt        TEXT,
                role        TEXT,
                created_at  TEXT
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
# ACCOUNTS & LOGIN
# ---------------------------------------------------------------------------
SECRET_FILE = "secret.key"


def _load_secret():
    try:
        with open(SECRET_FILE) as f:
            return f.read().strip()
    except Exception:
        s = secrets.token_hex(32)
        try:
            with open(SECRET_FILE, "w") as f:
                f.write(s)
        except Exception:
            pass
        return s


SECRET = _load_secret()


def _hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def user_count():
    with _db() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def list_users():
    with _db() as c:
        rows = c.execute("SELECT username, role, created_at FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def create_user(username, password, role="invigilator"):
    username = username.strip()
    if not username or not password:
        return False, "Username and password are required."
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    salt = secrets.token_hex(16)
    try:
        with _db() as c:
            c.execute("INSERT INTO users (username, pw_hash, salt, role, created_at) VALUES (?,?,?,?,?)",
                      (username, _hash_pw(password, salt), salt, role, datetime.now().isoformat()))
        return True, None
    except sqlite3.IntegrityError:
        return False, "That username already exists."


def delete_user(username):
    with _db() as c:
        c.execute("DELETE FROM users WHERE username = ?", (username,))


def verify_user(username, password):
    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row and _hash_pw(password, row["salt"]) == row["pw_hash"]:
        return {"username": row["username"], "role": row["role"]}
    return None


def _sign(username):
    sig = hmac.new(SECRET.encode(), username.encode(), hashlib.sha256).hexdigest()
    return f"{username}|{sig}"


def _verify_token(token):
    if not token or "|" not in token:
        return None
    username, sig = token.rsplit("|", 1)
    expected = hmac.new(SECRET.encode(), username.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    with _db() as c:
        row = c.execute("SELECT username, role FROM users WHERE username = ?", (username,)).fetchone()
    return {"username": row["username"], "role": row["role"]} if row else None


def current_user(request):
    return _verify_token(request.cookies.get("vigil_session"))


# ---------------------------------------------------------------------------
# DETECTION  (per-camera cooldown so cameras don't block each other)
# ---------------------------------------------------------------------------
_cooldown_lock = threading.Lock()
_last_alert_time = {}    # camera_id -> timestamp


# --- Telegram alerts (optional; configured in Settings) --------------------
def _telegram_chat_ids():
    return [c.strip() for c in (TELEGRAM_CHAT_IDS or "").replace(";", ",").split(",") if c.strip()]


def _telegram_send_message(token, chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    urllib.request.urlopen(req, timeout=10).read()


def _telegram_send_photo(token, chat_id, jpg_bytes, caption):
    boundary = "----VigilBoundaryZ9x1"
    parts = []
    for name, value in (("chat_id", str(chat_id)), ("caption", caption)):
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="alert.jpg"\r\n'
                  f'Content-Type: image/jpeg\r\n\r\n').encode())
    body = b"".join(parts) + jpg_bytes + b"\r\n" + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendPhoto", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(req, timeout=15).read()


def send_telegram_alert(jpg_bytes, caption):
    """Send an alert photo to all configured Telegram chats, in the background."""
    token = (TELEGRAM_TOKEN or "").strip()
    chat_ids = _telegram_chat_ids()
    if not token or not chat_ids:
        return
    def _worker():
        for cid in chat_ids:
            try:
                _telegram_send_photo(token, cid, jpg_bytes, caption)
            except Exception as e:
                print(f"Telegram send failed for {cid}: {e}")
    threading.Thread(target=_worker, daemon=True).start()


def maybe_add_alert(crop, confidence, camera_label, camera_id):
    now = time.time()
    with _cooldown_lock:
        if now - _last_alert_time.get(camera_id, 0) < ALERT_COOLDOWN or crop.size == 0:
            return
        ok, buf = cv2.imencode(".jpg", crop)
        if not ok:
            return
        _last_alert_time[camera_id] = now
        jpg = buf.tobytes()
        _store_alert(jpg, confidence, camera_label, status="pending")
        caption = (f"📱 Phone detected · {round(confidence * 100)}%\n"
                   f"📍 {camera_label}\n🕐 {datetime.now().strftime('%H:%M:%S')}")
        send_telegram_alert(jpg, caption)


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
        self.cap = None
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
        self.cap = self._open()                     # open IN this thread (thread-safe)
        fails = 0
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(1.0)
                self.cap = self._open()
                continue
            ok, f = self.cap.read()
            if not ok:                                  # stream dropped / camera off
                fails += 1
                with self.lock:
                    self.frame = None
                self.cap.release()
                time.sleep(min(10.0, 1.0 * fails))      # back off hard — a dead camera logs rarely
                self.cap = self._open()
                continue
            fails = 0
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


def _iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / union if union > 0 else 0.0


def _nms(boxes, iou_thr=0.5):
    """Remove duplicate boxes (same phone seen in overlapping tiles)."""
    boxes = sorted(boxes, key=lambda b: b[4], reverse=True)
    keep = []
    for b in boxes:
        if all(_iou(b, k) < iou_thr for k in keep):
            keep.append(b)
    return keep


def _detect(image, imgsz):
    with model_lock:
        res = model(image, classes=[PHONE_CLASS], conf=CONFIDENCE,
                    imgsz=imgsz, device=DEVICE, verbose=False)
    return [(*map(int, b.xyxy[0]), float(b.conf[0])) for b in res[0].boxes]


def detect_phones(frame):
    """Detect phones. With TILING on, also scan zoomed tiles so far-away phones
    (tiny in the full frame) become big enough inside a tile to be recognized."""
    h, w = frame.shape[:2]
    boxes = _detect(frame, IMG_SIZE)                       # full frame: near/large phones
    if TILING and w > 0 and h > 0:
        tw, th = w // TILE_COLS, h // TILE_ROWS
        ox, oy = int(tw * TILE_OVERLAP), int(th * TILE_OVERLAP)
        for r in range(TILE_ROWS):
            for c in range(TILE_COLS):
                x0, y0 = max(0, c * tw - ox), max(0, r * th - oy)
                x1, y1 = min(w, (c + 1) * tw + ox), min(h, (r + 1) * th + oy)
                tile = frame[y0:y1, x0:x1]
                if tile.size == 0:
                    continue
                for (bx1, by1, bx2, by2, cf) in _detect(tile, TILE_IMGSZ):
                    boxes.append((bx1 + x0, by1 + y0, bx2 + x0, by2 + y0, cf))
    return _nms(boxes, 0.5)


class Detector:
    """Runs phone detection in the background on the LATEST frame, so the video
    loop stays smooth even when tiling makes each detection heavy. Also raises the
    alerts (with the persistence filter), so that happens once per camera."""
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self._frame = None
        self._label = ""
        self._boxes = []
        self._lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, frame, label):
        with self._lock:
            self._frame = frame
            self._label = label

    def boxes(self):
        with self._lock:
            return list(self._boxes)

    def _run(self):
        streak = 0
        while self.running:
            with self._lock:
                frame, label = self._frame, self._label
                self._frame = None
            if frame is None:
                time.sleep(0.02)
                continue
            found = detect_phones(frame)
            with self._lock:
                self._boxes = found
            if found:
                streak += 1
                if streak >= REQUIRED_HITS:             # persistence filter
                    x1, y1, x2, y2, cf = max(found, key=lambda b: b[4])
                    maybe_add_alert(frame[y1:y2, x1:x2].copy(), cf, label, self.camera_id)
            else:
                streak = 0

    def stop(self):
        self.running = False


detectors = {}                     # camera_id -> Detector
detectors_lock = threading.Lock()


def _get_detector(camera_id):
    with detectors_lock:
        d = detectors.get(camera_id)
        if d is None:
            d = Detector(camera_id)
            detectors[camera_id] = d
        return d


# --- One producer per camera: always running, keeps the latest annotated JPEG.
#     The dashboard polls cheap snapshots, so there's NO limit on the number of
#     cameras (old live-streams were capped at ~6 by the browser). Detection also
#     runs for every camera even when nobody is watching it. ---
snapshots = {}                     # camera_id -> latest annotated JPEG bytes
snapshots_lock = threading.Lock()
camera_status = {}                 # camera_id -> "online" | "offline"
status_lock = threading.Lock()
producers = {}                     # camera_id -> Producer
producers_lock = threading.Lock()


class Producer:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        inline_cap = None
        inline_source = None
        while self.running:
            source, label = _find_camera(self.camera_id)
            if source is None:                          # camera removed
                break
            is_webcam = source.isdigit()

            if is_webcam:
                # Open+read the webcam in THIS one thread (the safe pattern).
                if inline_cap is None or inline_source != source:
                    if inline_cap is not None:
                        inline_cap.release()
                    inline_cap = cv2.VideoCapture(_resolve_source(source))
                    inline_source = source
                frame = None
                if inline_cap is not None and inline_cap.isOpened():
                    ok, frame = inline_cap.read()
                    if not ok:
                        inline_cap.release()
                        inline_cap = None
                        frame = None
            else:
                if inline_cap is not None:
                    inline_cap.release()
                    inline_cap = None
                    inline_source = None
                frame = _get_stream(self.camera_id, source).read()

            if frame is None:
                with status_lock:
                    camera_status[self.camera_id] = "offline"
                msg = "Camera not connected" if is_webcam else "Connecting to camera..."
                frame = _placeholder(msg)
                time.sleep(0.1)
            else:
                with status_lock:
                    camera_status[self.camera_id] = "online"
                detector = _get_detector(self.camera_id)
                detector.submit(frame, label)
                boxes = detector.boxes()
                if boxes:
                    frame = frame.copy()
                    for (x1, y1, x2, y2, conf) in boxes:
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 90), 2)
                        cv2.putText(frame, f"PHONE {conf:.0%}", (x1, max(y1 - 10, 20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 90), 2)

            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if ok:
                with snapshots_lock:
                    snapshots[self.camera_id] = buf.tobytes()
            time.sleep(0.04)

        # cleanup when the camera is removed or stopped
        if inline_cap is not None:
            inline_cap.release()
        with streams_lock:
            s = streams.pop(self.camera_id, None)
        if s is not None:
            s.stop()
        with detectors_lock:
            d = detectors.pop(self.camera_id, None)
        if d is not None:
            d.stop()
        with snapshots_lock:
            snapshots.pop(self.camera_id, None)
        with status_lock:
            camera_status.pop(self.camera_id, None)
        with producers_lock:
            producers.pop(self.camera_id, None)

    def stop(self):
        self.running = False


def _get_producer(camera_id):
    with producers_lock:
        p = producers.get(camera_id)
        if p is None or not p.running:
            p = Producer(camera_id)
            producers[camera_id] = p
        return p


def ensure_producers():
    """Make sure every configured camera has a running producer (so detection
    and alerts run for all of them, viewed or not)."""
    with cameras_lock:
        ids = [c["id"] for c in cameras]
    for cid in ids:
        _get_producer(cid)


# ---------------------------------------------------------------------------
# THE WEB APP
# ---------------------------------------------------------------------------
app = FastAPI(title="Vigil")

# Paths reachable without logging in
_PUBLIC = {"/login", "/setup", "/logout", "/favicon.svg"}
# API paths that should return 401 (not redirect) when not authed
_API_PREFIXES = ("/alerts", "/cameras", "/evidence/list", "/evidence/image", "/snapshot", "/camera_status")


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path

    # First run: no accounts yet -> force the create-admin setup page
    if user_count() == 0:
        if path == "/setup":
            return await call_next(request)
        return RedirectResponse("/setup")

    if path in _PUBLIC:
        return await call_next(request)

    user = current_user(request)
    if not user:
        if path.startswith(_API_PREFIXES):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse("/login")

    # Only admins may change cameras or manage users
    if request.method in ("POST", "PUT", "DELETE") and \
            (path.startswith("/cameras") or path.startswith("/users") or path.startswith("/settings")):
        if user["role"] != "admin":
            return JSONResponse({"error": "admin only"}, status_code=403)
    if path.startswith(("/users", "/settings")) and user["role"] != "admin":
        return RedirectResponse("/")

    request.state.user = user
    return await call_next(request)


@app.get("/favicon.svg")
def favicon():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">'
           '<rect width="24" height="24" rx="6" fill="#0e1116"/>'
           '<path d="M6 10V7.5A1.5 1.5 0 0 1 7.5 6H10M14 6h2.5A1.5 1.5 0 0 1 18 7.5V10'
           'M18 14v2.5a1.5 1.5 0 0 1-1.5 1.5H14M10 18H7.5A1.5 1.5 0 0 1 6 16.5V14" '
           'stroke="#7a8595" stroke-width="1.8" stroke-linecap="round"/>'
           '<circle cx="12" cy="12" r="2.6" fill="#4ade80"/></svg>')
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/stats")
def stats():
    today = datetime.now().strftime("%Y-%m-%d")
    with _db() as c:
        alerts_today = c.execute("SELECT COUNT(*) FROM alerts WHERE date = ?", (today,)).fetchone()[0]
        pending = c.execute("SELECT COUNT(*) FROM alerts WHERE status = 'pending'").fetchone()[0]
    with cameras_lock:
        cams = len(cameras)
    return {"cameras": cams, "alerts_today": alerts_today, "pending": pending}


@app.get("/camera_status")
def camera_status_ep():
    with status_lock:
        return dict(camera_status)


@app.get("/snapshot/{camera_id}")
def snapshot(camera_id: str):
    _get_producer(camera_id)                            # make sure it's running
    with snapshots_lock:
        data = snapshots.get(camera_id)
    if not data:
        ok, buf = cv2.imencode(".jpg", _placeholder("Starting..."))
        data = buf.tobytes() if ok else b""
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store, max-age=0"})


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
    _get_producer(cam["id"])
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
    with producers_lock:
        p = producers.get(cam_id)
    if p is not None:
        p.stop()
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
LOGO_MARK = ('<svg class="logo-mark" width="21" height="21" viewBox="0 0 24 24" fill="none">'
             '<path d="M4 9V6a2 2 0 0 1 2-2h3M15 4h3a2 2 0 0 1 2 2v3M20 15v3a2 2 0 0 1-2 2h-3M9 20H6a2 2 0 0 1-2-2v-3" '
             'stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
             '<circle cx="12" cy="12" r="3" fill="#4ade80"/></svg>')

STYLE = """
<link rel="icon" href="/favicon.svg">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif;
    background: radial-gradient(1100px 560px at 82% -12%, #17212c 0%, #0e1116 55%) fixed, #0e1116;
    color: #e6e9ef; height: 100vh; display: flex; flex-direction: column; -webkit-font-smoothing: antialiased; }
  header { display: flex; align-items: center; gap: 14px; padding: 11px 22px;
    background: rgba(21,26,33,.92); border-bottom: 1px solid #232a34; z-index: 5; }
  .brand { display:flex; align-items:center; gap:9px; }
  .logo-mark { color:#7a8595; flex-shrink:0; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: #4ade80;
    box-shadow: 0 0 8px #4ade80; animation: pulse 1.6s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
  .logo { font-weight: 800; font-size: 20px; letter-spacing: .3px; }
  .logo span { color: #4ade80; }
  .nav { display:flex; gap:4px; margin-left: 14px; margin-right:auto; }
  .nav a { font-size:13px; color:#9aa4b2; text-decoration:none; padding:7px 13px;
    border-radius:8px; transition: background .15s, color .15s; }
  .nav a:hover { color:#e6e9ef; background:#1c222b; }
  .nav a.active { background:#232a34; color:#fff; }
  .cam-btn { background:#4ade80; color:#0e1116; border:none; padding:8px 16px;
    border-radius:8px; font-size:13px; font-weight:700; cursor:pointer;
    transition: transform .1s, box-shadow .15s; box-shadow: 0 2px 12px rgba(74,222,128,.22); }
  .cam-btn:hover { transform: translateY(-1px); box-shadow: 0 5px 18px rgba(74,222,128,.34); }
  .clock { font-size: 13px; color: #9aa4b2; font-variant-numeric: tabular-nums; }
  .clock.push { }
  .userchip { font-size:13px; color:#9aa4b2; }
  .logout { font-size:13px; color:#9aa4b2; text-decoration:none; padding:6px 12px;
    border:1px solid #232a34; border-radius:8px; transition: color .15s, border-color .15s; }
  .logout:hover { color:#e6e9ef; border-color:#3a4557; }
  .badge.admin { background:rgba(74,222,128,.15); color:#4ade80; }
  .badge.invigilator { background:rgba(148,163,184,.15); color:#94a3b8; }

  main { flex: 1; display: flex; gap: 18px; padding: 18px; min-height: 0; }
  .cameras { flex:1; display:flex; flex-direction:column; gap:14px; min-height:0; }
  .overview { display:flex; gap:12px; flex-wrap:wrap; }
  .stat { background:#151a21; border:1px solid #232a34; border-radius:12px; padding:11px 16px; min-width:118px; }
  .stat .n { font-size:22px; font-weight:800; letter-spacing:.5px; line-height:1; }
  .stat .l { font-size:10.5px; color:#9aa4b2; text-transform:uppercase; letter-spacing:.7px; margin-top:6px; }
  .stat.ok .n { color:#4ade80; }
  .stat.warn .n { color:#eab308; }
  .grid { flex:1; display:grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    grid-auto-rows: minmax(230px, 1fr); gap:14px; overflow-y:auto; align-content:start; padding-right:2px; }
  .panel { background:#151a21; border:1px solid #232a34; border-radius:12px; overflow:hidden;
    display:flex; flex-direction:column; transition: border-color .15s, transform .15s, box-shadow .15s; }
  .panel:hover { border-color:#2f3a49; transform: translateY(-2px); box-shadow: 0 10px 26px rgba(0,0,0,.35); }
  .panel-head { display:flex; align-items:center; gap:8px; padding:10px 13px;
    border-bottom:1px solid #232a34; font-size:13px; font-weight:600; }
  .panel-body { flex:1; background:#000; display:flex; align-items:center; justify-content:center; min-height:0; }
  .panel-body img { max-width:100%; max-height:100%; }
  .status-pill { margin-left:auto; display:inline-flex; align-items:center; gap:5px;
    font-size:10px; font-weight:800; letter-spacing:.5px; padding:3px 9px 3px 8px; border-radius:20px; }
  .status-pill .sdot { width:6px; height:6px; border-radius:50%; }
  .status-pill.online { color:#4ade80; background:rgba(74,222,128,.12); }
  .status-pill.online .sdot { background:#4ade80; box-shadow:0 0 6px #4ade80; animation: pulse 1.4s infinite; }
  .status-pill.offline { color:#94a3b8; background:rgba(148,163,184,.12); }
  .status-pill.offline .sdot { background:#7a8595; }
  .icon-btn { background:transparent; border:none; color:#7a8595; font-size:15px;
    cursor:pointer; line-height:1; padding:0 3px; transition: color .12s; }
  .icon-btn:hover { color:#e6e9ef; }
  .remove { font-size:18px; }
  .remove:hover { color:#ef4444; }
  .grid-empty { grid-column:1/-1; display:flex; flex-direction:column; align-items:center;
    justify-content:center; gap:12px; color:#7a8595; padding:64px 20px; text-align:center; }
  .grid-empty h3 { color:#e6e9ef; font-size:17px; font-weight:700; }
  .grid-empty p { font-size:13px; max-width:340px; line-height:1.6; }
  .grid-empty .cam-btn { margin-top:6px; }

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
  .alert.pending { border-color: rgba(234,179,8,.35); box-shadow: 0 0 0 1px rgba(234,179,8,.10); }
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
    __LOGO__
    <span class="logo">Vig<span>i</span>l</span>
    <nav class="nav"><a href="/" class="active">Live Monitor</a><a href="/evidence">Evidence Log</a>__ADMIN_NAV__</nav>
    <button class="cam-btn" id="cam-btn">+ Add camera</button>
    <span class="userchip">👤 __USERNAME__</span>
    <a class="logout" href="/logout">Log out</a>
    <span class="clock" id="clock"></span>
  </header>
  <main>
    <section class="cameras">
      <div class="overview">
        <div class="stat ok"><div class="n" id="stat-cameras">–</div><div class="l">Cameras</div></div>
        <div class="stat"><div class="n" id="stat-today">–</div><div class="l">Alerts today</div></div>
        <div class="stat warn"><div class="n" id="stat-pending">–</div><div class="l">Pending review</div></div>
      </div>
      <div class="grid" id="grid"></div>
    </section>
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
    const IS_ADMIN = __IS_ADMIN__;
    function panelHTML(c) {
      const place = (c.location && c.location.trim()) ? c.location : c.label;
      const controls = IS_ADMIN
        ? `<button class="icon-btn" title="Edit camera" onclick="openEdit('${c.id}')">✎</button>
           <button class="icon-btn remove" title="Remove camera" onclick="removeCam('${c.id}')">×</button>`
        : '';
      return `<div class="panel">
        <div class="panel-head">📹 ${place}<span class="status-pill offline" data-cam="${c.id}"><span class="sdot"></span><span class="stext">…</span></span>${controls}</div>
        <div class="panel-body"><img class="cam-snap" data-cam="${c.id}" alt="feed"></div>
      </div>`;
    }
    async function loadCameras() {
      let cams = [];
      try { cams = await (await fetch('/cameras')).json(); } catch (e) { return; }
      const grid = document.getElementById('grid');
      grid.innerHTML = cams.length
        ? cams.map(panelHTML).join('')
        : `<div class="grid-empty">
             <svg width="46" height="46" viewBox="0 0 24 24" fill="none"><path d="M4 9V6a2 2 0 0 1 2-2h3M15 4h3a2 2 0 0 1 2 2v3M20 15v3a2 2 0 0 1-2 2h-3M9 20H6a2 2 0 0 1-2-2v-3" stroke="#3a4557" stroke-width="1.6" stroke-linecap="round"/><circle cx="12" cy="12" r="2.4" fill="#3a4557"/></svg>
             <h3>No cameras yet</h3>
             <p>Add your webcam, a phone (via the IP Webcam app), or a CCTV camera to start watching for phones.</p>
             ${IS_ADMIN ? '<button class="cam-btn" onclick="openAdd()">+ Add your first camera</button>' : '<p style="color:#5b6675">Ask an admin to add a camera.</p>'}
           </div>`;
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
    if (IS_ADMIN) {
      document.getElementById('cam-btn').onclick = openAdd;
    } else {
      document.getElementById('cam-btn').style.display = 'none';
    }
    loadCameras();

    // ---- Real-time notification when a NEW phone alert arrives ----
    let lastAlertId = 0, firstAlertLoad = true;
    if ('Notification' in window && Notification.permission === 'default') {
      try { Notification.requestPermission(); } catch (e) {}
    }
    function notifyAlert(a) {
      try {                                    // short beep
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.connect(g); g.connect(ctx.destination);
        o.type = 'sine'; o.frequency.value = 880; g.gain.value = 0.08;
        o.start(); o.stop(ctx.currentTime + 0.18);
      } catch (e) {}
      try {                                    // desktop notification
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification('📱 Phone detected · ' + Math.round(a.confidence * 100) + '%',
            { body: '📍 ' + a.camera + '  ·  ' + a.time });
        }
      } catch (e) {}
    }

    // ---- Alerts ----
    async function loadAlerts() {
      let data = [];
      try { data = await (await fetch('/alerts')).json(); } catch (e) { return; }
      if (data.length) {                       // ping on a genuinely new pending alert
        const newest = data[0];
        if (!firstAlertLoad && newest.id > lastAlertId && newest.status === 'pending') notifyAlert(newest);
        lastAlertId = Math.max(lastAlertId, newest.id);
      }
      firstAlertLoad = false;
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

    // ---- Live camera snapshots (poll — no limit on number of cameras) ----
    function refreshSnapshots() {
      document.querySelectorAll('img.cam-snap').forEach(img => {
        const id = img.dataset.cam;
        fetch('/snapshot/' + id + '?t=' + Date.now())
          .then(r => r.ok ? r.blob() : null)
          .then(blob => {
            if (!blob) return;
            const url = URL.createObjectURL(blob);
            const prev = img.dataset.url;
            img.src = url;
            img.dataset.url = url;
            if (prev) URL.revokeObjectURL(prev);
          }).catch(() => {});
      });
    }
    setInterval(refreshSnapshots, 250);

    // ---- Per-camera online/offline status ----
    async function refreshStatus() {
      let st = {};
      try { st = await (await fetch('/camera_status')).json(); } catch (e) { return; }
      document.querySelectorAll('.status-pill').forEach(p => {
        const online = st[p.dataset.cam] === 'online';
        p.classList.toggle('online', online);
        p.classList.toggle('offline', !online);
        p.querySelector('.stext').textContent = online ? 'LIVE' : 'OFFLINE';
      });
    }
    setInterval(refreshStatus, 1500);
    refreshStatus();

    // ---- Overview stats ----
    async function loadStats() {
      try {
        const s = await (await fetch('/stats')).json();
        document.getElementById('stat-cameras').textContent = s.cameras;
        document.getElementById('stat-today').textContent = s.alerts_today;
        document.getElementById('stat-pending').textContent = s.pending;
      } catch (e) {}
    }
    setInterval(loadStats, 2000);
    loadStats();
  </script>
</body></html>"""


# ---- Evidence Log page ----------------------------------------------------
EVIDENCE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — Evidence Log</title>__STYLE__</head>
<body>
  <header>
    __LOGO__
    <span class="logo">Vig<span>i</span>l</span>
    <nav class="nav"><a href="/">Live Monitor</a><a href="/evidence" class="active">Evidence Log</a>__ADMIN_NAV__</nav>
    <span class="userchip">👤 __USERNAME__</span>
    <a class="logout" href="/logout">Log out</a>
    <span class="clock" id="clock"></span>
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


# ---- Users admin page -----------------------------------------------------
USERS_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — Users</title>__STYLE__
<style>
  .users-wrap { flex:1; padding:18px; display:flex; gap:18px; align-items:flex-start; flex-wrap:wrap; }
  .card { background:#151a21; border:1px solid #232a34; border-radius:14px; padding:20px; }
  .card h2 { font-size:15px; margin-bottom:14px; }
  .add { width:300px; }
  .add label { display:block; font-size:12px; color:#9aa4b2; margin:0 0 5px 2px; }
  .add input, .add select { width:100%; background:#0e1116; border:1px solid #2b3340; color:#e6e9ef;
    padding:10px 12px; border-radius:8px; font-size:13px; margin-bottom:12px; }
  .add button { width:100%; background:#4ade80; color:#0e1116; border:none; padding:11px;
    border-radius:8px; font-weight:700; cursor:pointer; }
  .list { flex:1; min-width:320px; }
  .del { background:#2b3340; color:#f87171; border:none; padding:6px 12px; border-radius:6px; font-size:12px; cursor:pointer; }
</style></head>
<body>
  <header>
    __LOGO__<span class="logo">Vig<span>i</span>l</span>
    <nav class="nav"><a href="/">Live Monitor</a><a href="/evidence">Evidence Log</a><a href="/users" class="active">Users</a><a href="/settings">Settings</a></nav>
    <span class="userchip">👤 __USERNAME__</span>
    <a class="logout" href="/logout">Log out</a>
  </header>
  <div class="users-wrap">
    <div class="card add">
      <h2>Add a user</h2>
      <form method="post" action="/users">
        <label>Username</label><input name="username" required>
        <label>Password</label><input name="password" type="password" required>
        <label>Role</label>
        <select name="role">
          <option value="invigilator">Invigilator — receives alerts</option>
          <option value="admin">Admin — full access</option>
        </select>
        <button type="submit">Add user</button>
      </form>
    </div>
    <div class="card list">
      <h2>Users</h2>
      <table>
        <thead><tr><th>Username</th><th>Role</th><th></th></tr></thead>
        <tbody>__ROWS__</tbody>
      </table>
    </div>
  </div>
</body></html>"""


def _admin_nav(user):
    return ('<a href="/users">Users</a><a href="/settings">Settings</a>'
            if user.get("role") == "admin" else "")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = getattr(request.state, "user", None) or {"username": "", "role": "invigilator"}
    return (DASHBOARD_HTML
            .replace("__STYLE__", STYLE).replace("__LOGO__", LOGO_MARK)
            .replace("__CAMERA_MODAL__", CAMERA_MODAL)
            .replace("__USERNAME__", user["username"])
            .replace("__ADMIN_NAV__", _admin_nav(user))
            .replace("__IS_ADMIN__", "true" if user["role"] == "admin" else "false"))


@app.get("/evidence", response_class=HTMLResponse)
def evidence_page(request: Request):
    user = getattr(request.state, "user", None) or {"username": "", "role": "invigilator"}
    return (EVIDENCE_HTML.replace("__STYLE__", STYLE).replace("__LOGO__", LOGO_MARK)
            .replace("__USERNAME__", user["username"])
            .replace("__ADMIN_NAV__", _admin_nav(user)))


# ---- Login / Setup / Logout ----------------------------------------------
AUTH_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — __TITLE__</title>__STYLE__
<style>
  .auth-wrap { flex:1; display:flex; align-items:center; justify-content:center; }
  .auth { background:#151a21; border:1px solid #232a34; border-radius:14px; padding:30px; width:360px; max-width:92vw; }
  .auth h2 { font-size:19px; margin-bottom:6px; }
  .auth p { font-size:13px; color:#9aa4b2; margin-bottom:18px; }
  .auth label { display:block; font-size:12px; color:#9aa4b2; margin:0 0 5px 2px; }
  .auth input { width:100%; background:#0e1116; border:1px solid #2b3340; color:#e6e9ef;
    padding:11px 12px; border-radius:8px; font-size:14px; margin-bottom:14px; }
  .auth button { width:100%; background:#4ade80; color:#0e1116; border:none; padding:12px;
    border-radius:8px; font-size:14px; font-weight:700; cursor:pointer; }
  .auth .err { background:rgba(239,68,68,.15); color:#f87171; font-size:13px;
    padding:9px 12px; border-radius:8px; margin-bottom:14px; }
</style></head>
<body>
  <header>__LOGO__<span class="logo">Vig<span>i</span>l</span>
    <span style="color:#5b6675;font-size:12.5px;margin-left:4px">AI phone detection for exams &amp; secure areas</span>
  </header>
  <div class="auth-wrap">
    <form class="auth" method="post" action="__ACTION__">
      <h2>__HEADING__</h2>
      <p>__HINT__</p>
      __ERROR__
      <label>Username</label>
      <input name="username" autofocus autocomplete="username">
      <label>Password</label>
      <input name="password" type="password" autocomplete="current-password">
      <button type="submit">__BUTTON__</button>
    </form>
  </div>
</body></html>"""


def _auth_page(title, heading, hint, action, button, error=""):
    err = f'<div class="err">{error}</div>' if error else ""
    return (AUTH_TEMPLATE.replace("__STYLE__", STYLE).replace("__LOGO__", LOGO_MARK).replace("__TITLE__", title)
            .replace("__HEADING__", heading).replace("__HINT__", hint)
            .replace("__ACTION__", action).replace("__BUTTON__", button)
            .replace("__ERROR__", err))


_COOKIE_KW = dict(httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)


@app.get("/setup", response_class=HTMLResponse)
def setup_page():
    if user_count() > 0:
        return RedirectResponse("/login")
    return _auth_page("Setup", "Create the admin account",
                      "This first account manages cameras and other users.", "/setup", "Create admin")


@app.post("/setup")
def setup_submit(username: str = Form(...), password: str = Form(...)):
    if user_count() > 0:
        return RedirectResponse("/login", status_code=303)
    ok, err = create_user(username, password, role="admin")
    if not ok:
        return HTMLResponse(_auth_page("Setup", "Create the admin account",
                            "This first account manages cameras and other users.",
                            "/setup", "Create admin", err), status_code=400)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("vigil_session", _sign(username.strip()), **_COOKIE_KW)
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_page():
    if user_count() == 0:
        return RedirectResponse("/setup")
    return _auth_page("Login", "Sign in to Vigil", "Enter your credentials.", "/login", "Sign in")


@app.post("/login")
def login_submit(username: str = Form(...), password: str = Form(...)):
    u = verify_user(username, password)
    if not u:
        return HTMLResponse(_auth_page("Login", "Sign in to Vigil", "Enter your credentials.",
                            "/login", "Sign in", "Invalid username or password."), status_code=401)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("vigil_session", _sign(u["username"]), **_COOKIE_KW)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("vigil_session")
    return resp


# ---- Users (admin only; gated in the middleware) --------------------------
def _users_rows(current_username):
    out = []
    for u in list_users():
        if u["username"] == current_username:
            action = '<span style="color:#5b6675;font-size:12px">you</span>'
        else:
            action = ('<form method="post" action="/users/delete" style="margin:0">'
                      f'<input type="hidden" name="username" value="{u["username"]}">'
                      '<button class="del">Remove</button></form>')
        out.append(f'<tr><td>{u["username"]}</td>'
                   f'<td><span class="badge {u["role"]}">{u["role"]}</span></td>'
                   f'<td>{action}</td></tr>')
    return "".join(out)


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    user = getattr(request.state, "user", None) or {"username": "", "role": ""}
    return (USERS_HTML.replace("__STYLE__", STYLE).replace("__LOGO__", LOGO_MARK)
            .replace("__USERNAME__", user["username"])
            .replace("__ROWS__", _users_rows(user["username"])))


@app.post("/users")
def users_add(username: str = Form(...), password: str = Form(...), role: str = Form("invigilator")):
    create_user(username, password, "admin" if role == "admin" else "invigilator")
    return RedirectResponse("/users", status_code=303)


@app.post("/users/delete")
def users_delete(username: str = Form(...)):
    delete_user(username)
    return RedirectResponse("/users", status_code=303)


# ---- Settings (admin only; gated in the middleware) -----------------------
SETTINGS_SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — Settings</title>__STYLE__
<style>
  .settings-wrap { flex:1; padding:18px; overflow-y:auto; }
  .settings { max-width:720px; background:#151a21; border:1px solid #232a34; border-radius:14px; padding:24px; }
  .settings h2 { font-size:16px; margin-bottom:4px; }
  .settings .sub { font-size:13px; color:#9aa4b2; margin-bottom:18px; }
  .field { margin-bottom:16px; }
  .field label { display:block; font-size:13px; font-weight:600; margin-bottom:3px; }
  .field .hint { font-size:12px; color:#9aa4b2; margin-bottom:7px; }
  .field input[type=text], .field input[type=number] { width:180px; background:#0e1116;
    border:1px solid #2b3340; color:#e6e9ef; padding:9px 11px; border-radius:8px; font-size:13px; }
  .toggle { display:flex; align-items:center; gap:8px; }
  .toggle label { margin:0; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; max-width:420px; }
  .save-row { margin-top:20px; }
  .save-row button { background:#4ade80; color:#0e1116; border:none; padding:11px 24px;
    border-radius:8px; font-weight:700; cursor:pointer; }
  .saved { background:rgba(74,222,128,.15); color:#4ade80; font-size:13px; padding:10px 12px; border-radius:8px; margin-bottom:16px; }
  .sec { border-top:1px solid #232a34; margin:22px 0 16px; padding-top:16px; font-size:13px; color:#9aa4b2; font-weight:700; }
</style></head>
<body>
  <header>
    __LOGO__<span class="logo">Vig<span>i</span>l</span>
    <nav class="nav"><a href="/">Live Monitor</a><a href="/evidence">Evidence Log</a><a href="/users">Users</a><a href="/settings" class="active">Settings</a></nav>
    <span class="userchip">👤 __USERNAME__</span>
    <a class="logout" href="/logout">Log out</a>
  </header>
  <div class="settings-wrap"><div class="settings">__BODY__</div></div>
</body></html>"""


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = "", test: str = ""):
    u = getattr(request.state, "user", None) or {"username": "", "role": ""}
    g = globals()
    banner = ('<div class="saved">✓ Saved — changes apply live (a model change takes a few seconds).</div>'
              if saved else '')
    if test == "ok":
        banner += '<div class="saved">✓ Test message sent — check your Telegram.</div>'
    elif test == "fail":
        banner += '<div class="saved" style="background:rgba(239,68,68,.15);color:#f87171">✗ Test failed — check the token and chat ID.</div>'
    elif test == "noconfig":
        banner += '<div class="saved" style="background:rgba(234,179,8,.15);color:#eab308">Add a bot token and chat ID, click Save, then test.</div>'
    checked = "checked" if g["TILING"] else ""
    body = f"""
      <h2>Detection settings</h2>
      <div class="sub">Accuracy vs. speed. Changes apply live — no restart needed.</div>
      {banner}
      <form method="post" action="/settings">
        <div class="field">
          <label>Confidence threshold</label>
          <div class="hint">Lower catches faint/distant phones but false-alarms more. 0.05–0.95.</div>
          <input type="number" name="confidence" step="0.05" min="0.05" max="0.95" value="{g['CONFIDENCE']}">
        </div>
        <div class="field">
          <label>Persistence (frames in a row)</label>
          <div class="hint">A phone must be seen this many detections in a row before it alerts. Higher = fewer false alarms.</div>
          <input type="number" name="required_hits" min="1" max="10" value="{g['REQUIRED_HITS']}">
        </div>
        <div class="field">
          <label>Alert cooldown (seconds)</label>
          <div class="hint">Minimum gap between alerts from one camera.</div>
          <input type="number" name="alert_cooldown" min="1" max="60" value="{g['ALERT_COOLDOWN']}">
        </div>
        <div class="field">
          <label>Detection detail (image size)</label>
          <div class="hint">Higher = better on small/distant phones, but slower. 320–1536 (640 fast · 960 balanced · 1280 long-range).</div>
          <input type="number" name="img_size" step="32" min="320" max="1536" value="{g['IMG_SIZE']}">
        </div>

        <div class="sec">Tiling — extra range for far-away phones (heavier)</div>
        <div class="field toggle">
          <input type="checkbox" name="tiling" {checked}>
          <label>Enable tiling</label>
        </div>
        <div class="grid2">
          <div class="field"><label>Tiles across</label><input type="number" name="tile_cols" min="1" max="4" value="{g['TILE_COLS']}"></div>
          <div class="field"><label>Tiles down</label><input type="number" name="tile_rows" min="1" max="4" value="{g['TILE_ROWS']}"></div>
          <div class="field"><label>Tile overlap</label><input type="number" name="tile_overlap" step="0.05" min="0" max="0.4" value="{g['TILE_OVERLAP']}"></div>
          <div class="field"><label>Tile detail</label><input type="number" name="tile_imgsz" step="32" min="320" max="1280" value="{g['TILE_IMGSZ']}"></div>
        </div>

        <div class="sec">Model</div>
        <div class="field">
          <label>Model</label>
          <div class="hint">yolo11n · yolo11s · yolo11m · yolo11l · yolo11x (bigger = smarter, slower), or a path to a fine-tuned .pt. Changing this reloads the model.</div>
          <input type="text" name="model_name" value="{g['MODEL_NAME']}" style="width:340px">
        </div>

        <div class="sec">Phone alerts via Telegram (optional)</div>
        <div class="field">
          <div class="hint">Get alerts on your phone with the photo + location. Setup: in Telegram, message
          <b>@BotFather</b> → <code>/newbot</code> → copy the <b>token</b>. Then send any message to your new
          bot, open <code>https://api.telegram.org/bot&lt;token&gt;/getUpdates</code> and copy the <b>chat id</b>.
          Leave blank to turn off.</div>
        </div>
        <div class="field">
          <label>Bot token</label>
          <input type="text" name="telegram_token" value="{g['TELEGRAM_TOKEN']}" style="width:340px" placeholder="123456:ABC-DEF...">
        </div>
        <div class="field">
          <label>Chat ID(s)</label>
          <div class="hint">One or more, comma-separated (one per person who should get alerts).</div>
          <input type="text" name="telegram_chat_ids" value="{g['TELEGRAM_CHAT_IDS']}" style="width:340px" placeholder="123456789, 987654321">
        </div>

        <div class="save-row"><button type="submit">Save settings</button></div>
      </form>
      <form method="post" action="/settings/telegram-test" style="margin-top:12px;display:flex;gap:12px;align-items:center">
        <button type="submit" style="background:#2b3340;color:#c4ccd8;border:none;padding:10px 18px;border-radius:8px;font-weight:600;cursor:pointer">Send test message</button>
        <span class="hint" style="margin:0">Uses the saved config — click Save first.</span>
      </form>
    """
    return (SETTINGS_SHELL.replace("__STYLE__", STYLE).replace("__LOGO__", LOGO_MARK)
            .replace("__USERNAME__", u["username"]).replace("__BODY__", body))


def _round32(v):
    return max(1, round(v / 32)) * 32


@app.post("/settings")
def settings_save(
    confidence: float = Form(0.45),
    required_hits: int = Form(3),
    alert_cooldown: int = Form(3),
    img_size: int = Form(960),
    tiling: str = Form(None),
    tile_cols: int = Form(2),
    tile_rows: int = Form(2),
    tile_overlap: float = Form(0.15),
    tile_imgsz: int = Form(768),
    model_name: str = Form("yolo11m.pt"),
    telegram_token: str = Form(""),
    telegram_chat_ids: str = Form(""),
):
    old_model = MODEL_NAME
    save_settings({
        "CONFIDENCE": min(max(confidence, 0.05), 0.95),
        "REQUIRED_HITS": max(1, min(required_hits, 10)),
        "ALERT_COOLDOWN": max(1, min(alert_cooldown, 60)),
        "IMG_SIZE": min(max(_round32(img_size), 320), 1536),
        "TILING": tiling is not None,
        "TILE_COLS": max(1, min(tile_cols, 4)),
        "TILE_ROWS": max(1, min(tile_rows, 4)),
        "TILE_OVERLAP": min(max(tile_overlap, 0.0), 0.4),
        "TILE_IMGSZ": min(max(_round32(tile_imgsz), 320), 1280),
        "MODEL_NAME": model_name.strip() or old_model,
        "TELEGRAM_TOKEN": telegram_token.strip(),
        "TELEGRAM_CHAT_IDS": telegram_chat_ids.strip(),
    })
    if MODEL_NAME != old_model:
        try:
            reload_model()
        except Exception:
            save_settings({"MODEL_NAME": old_model})       # bad model -> revert
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/telegram-test")
def telegram_test():
    token = (TELEGRAM_TOKEN or "").strip()
    chat_ids = _telegram_chat_ids()
    if not token or not chat_ids:
        return RedirectResponse("/settings?test=noconfig", status_code=303)
    ok_any = False
    for cid in chat_ids:
        try:
            _telegram_send_message(token, cid, "✅ Vigil test — phone alerts are working. You'll get a photo here when a phone is detected.")
            ok_any = True
        except Exception as e:
            print(f"Telegram test failed for {cid}: {e}")
    return RedirectResponse(f"/settings?test={'ok' if ok_any else 'fail'}", status_code=303)


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

# Start a producer for every configured camera (detection/alerts run for all).
ensure_producers()
