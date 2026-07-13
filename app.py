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
import itertools
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

CONFIDENCE     = 0.55   # higher = fewer false alarms on phone-shaped objects (bed, book…).
                        # Raise toward 0.6 if it false-alarms; lower toward 0.35 for more range.
REQUIRED_HITS  = 3      # a phone must be seen this many detections IN A ROW before it
                        # raises an alert — this is what kills brief false positives on
                        # random objects (a real phone held up stays; junk flickers).
PHONE_CLASS    = 67
ALERT_COOLDOWN = 3

IMG_SIZE       = 640    # detail for the full-frame pass (640 = fast/smooth; raise for range)
JPEG_QUALITY   = 75     # streamed video quality (lower = faster / less bandwidth)

# --- Tiling (for spotting phones far away) -------------------------------
# Slice each frame into overlapping tiles and scan each one zoomed-in, so a
# distant phone (tiny in the whole frame) is large enough inside its tile to see.
TILING         = False  # off by default = smooth video; enable in Settings for far phones
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

# What Vigil watches for. "phone" uses the fine-tuned exam model; any other
# target (laptop, backpack, book, bottle, person, …) auto-switches to the
# general 80-class model. Set from Settings → "Watch for".
WATCH_TARGET = "phone"

SETTINGS_FILE = "settings.json"
TUNABLE = ["MODEL_NAME", "CONFIDENCE", "REQUIRED_HITS", "ALERT_COOLDOWN", "IMG_SIZE",
           "TILING", "TILE_COLS", "TILE_ROWS", "TILE_OVERLAP", "TILE_IMGSZ",
           "TELEGRAM_TOKEN", "TELEGRAM_CHAT_IDS", "WATCH_TARGET"]


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


def _apply_env_settings():
    """Environment variables override defaults (used for cloud deploys,
    e.g. MODEL_NAME=yolo11n.pt TILING=false on a small instance)."""
    g = globals()
    for k in TUNABLE:
        if k in os.environ:
            v = os.environ[k]
            try:
                v = json.loads(v.lower() if v.lower() in ("true", "false") else v)
            except Exception:
                pass
            g[k] = v


_apply_saved_settings()
_apply_env_settings()

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


# --- Watch target: what Vigil is looking for --------------------------------
TARGET_CLASS = PHONE_CLASS
TARGET_NAME = "Phone"

_PHONE_WORDS = ("phone", "cell phone", "mobile", "mobile phone", "smartphone", "cellphone")


def _resolve_target_in(names, want):
    tid = next((i for i, n in names.items() if str(n).lower() == want), None)
    if tid is None:
        tid = next((i for i, n in names.items() if want in str(n).lower()), None)
    return tid


def apply_watch_target():
    """Resolve WATCH_TARGET to a class id in the current model — switching to
    the right model if needed (phone → fine-tuned model when present; anything
    else → the general 80-class model). Returns True if the target resolved."""
    global TARGET_CLASS, TARGET_NAME
    want = (WATCH_TARGET or "phone").strip().lower()
    if want in _PHONE_WORDS:
        want = "phone"
    with model_lock:
        names = dict(model.names)
    tid = _resolve_target_in(names, "cell phone" if want == "phone" else want)
    if tid is None and want == "phone":
        tid = _resolve_target_in(names, "phone")
    if tid is None:
        # Current model doesn't know this target — swap to the one that does.
        fallback = ("vigil-phone.pt" if want == "phone" and os.path.exists("vigil-phone.pt")
                    else "yolo11m.pt")
        if MODEL_NAME != fallback:
            save_settings({"MODEL_NAME": fallback})
            reload_model()
            with model_lock:
                names = dict(model.names)
            tid = _resolve_target_in(names, "cell phone" if want == "phone" else want)
            if tid is None and want == "phone":
                tid = _resolve_target_in(names, "phone")
    if tid is None:
        return False
    raw = str(names.get(tid, want))
    TARGET_CLASS = tid
    TARGET_NAME = "Phone" if raw.lower() in _PHONE_WORDS else raw.title()
    return True


try:
    apply_watch_target()
    print(f"Watching for: {TARGET_NAME} (class {TARGET_CLASS})")
except Exception as _e:
    print(f"Watch-target init failed ({_e}); defaulting to phone")


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
    # Cloud deploys have no local webcam — start with no cameras there
    if os.getenv("VIGIL_NO_DEFAULT_CAMERA") == "1":
        return []
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
        # v1.1: what the alert was for (older installs get the column added here)
        try:
            c.execute("ALTER TABLE alerts ADD COLUMN thing TEXT DEFAULT 'Phone'")
        except sqlite3.OperationalError:
            pass


def _store_alert(jpg_bytes, confidence, camera, status="pending", dt=None, thing="Phone"):
    dt = dt or datetime.now()
    with _db() as c:
        cur = c.execute(
            "INSERT INTO alerts (created_at, date, time, confidence, camera, image_file, status, thing)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (dt.isoformat(), dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S"),
             round(confidence, 2), camera, "", status, thing))
        alert_id = cur.lastrowid
        fname = os.path.join(EVIDENCE_DIR, f"alert_{alert_id}_{dt.strftime('%Y%m%d_%H%M%S')}.jpg")
        with open(fname, "wb") as f:
            f.write(jpg_bytes)
        c.execute("UPDATE alerts SET image_file = ? WHERE id = ?", (fname, alert_id))
    return alert_id


def _row_to_dict(r):
    try:
        thing = r["thing"] or "Phone"
    except (IndexError, KeyError):
        thing = "Phone"
    return {
        "id": r["id"], "time": r["time"], "date": r["date"],
        "confidence": r["confidence"], "camera": r["camera"],
        "status": r["status"], "image": f"/evidence/image/{r['id']}",
        "thing": thing,
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
        thing = TARGET_NAME
        _store_alert(jpg, confidence, camera_label, status="pending", thing=thing)
        caption = (f"🚨 {thing} detected · {round(confidence * 100)}%\n"
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
        res = model(image, classes=[TARGET_CLASS], conf=CONFIDENCE,
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
        DETECT_INTERVAL = 0.12          # cap detection at ~8/s — plenty for a held-up
                                        # phone, and leaves GPU headroom so video stays smooth
        while self.running:
            t0 = time.time()
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
            dt = time.time() - t0                       # throttle to leave room for the video pipeline
            if dt < DETECT_INTERVAL:
                time.sleep(DETECT_INTERVAL - dt)

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
# Browser cameras: any phone/laptop opens the sender page and pushes frames here.
browser_frames = {}                # camera_id -> (np frame, seq, received_at)
browser_frames_lock = threading.Lock()
BROWSER_STALE = 3.0                # no frame for this long -> camera shows offline
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
        last_browser_seq = -1
        while self.running:
            source, label = _find_camera(self.camera_id)
            if source is None:                          # camera removed
                break
            is_webcam = source.isdigit()
            is_browser = source == "browser"

            if is_browser:
                # Frames are pushed by a device's browser via POST /push/<id>
                if inline_cap is not None:
                    inline_cap.release()
                    inline_cap = None
                    inline_source = None
                frame, fresh = None, False
                with browser_frames_lock:
                    item = browser_frames.get(self.camera_id)
                if item is not None and time.time() - item[2] < BROWSER_STALE:
                    frame = item[0]
                    fresh = item[1] != last_browser_seq
                    last_browser_seq = item[1]
                if frame is None:
                    with status_lock:
                        camera_status[self.camera_id] = "offline"
                    ok, buf = cv2.imencode(".jpg", _placeholder("Open this camera's link on a device"),
                                           [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                    if ok:
                        with snapshots_lock:
                            snapshots[self.camera_id] = buf.tobytes()
                    time.sleep(0.15)
                    continue
                with status_lock:
                    camera_status[self.camera_id] = "online"
                detector = _get_detector(self.camera_id)
                if fresh:                               # only detect NEW frames
                    detector.submit(frame, label)
                boxes = detector.boxes()
                if boxes:
                    frame = frame.copy()
                    for (x1, y1, x2, y2, conf) in boxes:
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 90), 2)
                        cv2.putText(frame, f"{TARGET_NAME.upper()} {conf:.0%}", (x1, max(y1 - 10, 20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 90), 2)
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if ok:
                    with snapshots_lock:
                        snapshots[self.camera_id] = buf.tobytes()
                time.sleep(0.05)
                continue

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
                        cv2.putText(frame, f"{TARGET_NAME.upper()} {conf:.0%}", (x1, max(y1 - 10, 20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 90), 2)

            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if ok:
                with snapshots_lock:
                    snapshots[self.camera_id] = buf.tobytes()
            time.sleep(0.008)   # run near the camera's native frame rate (~30fps); no disk cost

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
        with browser_frames_lock:
            browser_frames.pop(self.camera_id, None)
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
_API_PREFIXES = ("/alerts", "/cameras", "/evidence/list", "/evidence/image", "/snapshot", "/camera_status", "/push")


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
        if path == "/":   # visitors get the public website; the app stays behind login
            return HTMLResponse(LANDING_HTML.replace("__LOGO__", LOGO_MARK))
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
           '<circle cx="12" cy="12" r="2.6" fill="#3ecf8e"/></svg>')
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


_push_seq = itertools.count()


@app.post("/push/{camera_id}")
async def push_frame(camera_id: str, request: Request):
    """A browser-camera sender page posts JPEG frames here."""
    if _find_camera(camera_id)[0] != "browser":
        return JSONResponse({"error": "not a browser camera"}, status_code=404)
    body = await request.body()
    if not body or len(body) > 3_000_000:
        return JSONResponse({"error": "bad frame"}, status_code=400)
    frame = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return JSONResponse({"error": "bad frame"}, status_code=400)
    with browser_frames_lock:
        browser_frames[camera_id] = (frame, next(_push_seq), time.time())
    _get_producer(camera_id)
    return {"ok": True}


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


@app.post("/cameras/reorder")
def reorder_cameras(payload: dict):
    """Persist a new camera order (list of ids) from drag-and-drop."""
    order = payload.get("order") or []
    with cameras_lock:
        pos = {cid: i for i, cid in enumerate(order)}
        # keep any camera not in the list at the end, in existing order
        cameras.sort(key=lambda c: pos.get(c["id"], len(pos) + 1))
        _save_cameras()
        return list(cameras)


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
             '<circle cx="12" cy="12" r="3" fill="#3ecf8e"/></svg>')

STYLE = """
<link rel="icon" href="/favicon.svg">
<style>
  :root { --ease: cubic-bezier(.22,.9,.3,1); --spring: cubic-bezier(.34,1.56,.64,1); }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif;
    background: radial-gradient(1100px 560px at 82% -12%, #17212c 0%, #0e1116 55%) fixed, #0e1116;
    color: #e6e9ef; height: 100vh; display: flex; flex-direction: column; -webkit-font-smoothing: antialiased; }
  header { display: flex; align-items: center; gap: 14px; padding: 11px 22px;
    background: rgba(21,26,33,.78); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
    border-bottom: 1px solid #232a34; z-index: 5; }
  button:active { transform: scale(.97); }
  .brand { display:flex; align-items:center; gap:9px; }
  .logo-mark { color:#7a8595; flex-shrink:0; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: #3ecf8e;
    box-shadow: 0 0 8px #3ecf8e; animation: pulse 1.6s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
  .logo { font-weight: 800; font-size: 20px; letter-spacing: .3px; }
  .logo span { color: #3ecf8e; }
  .nav { display:flex; gap:4px; margin-left: 14px; margin-right:auto; }
  .nav a { font-size:13px; color:#9aa4b2; text-decoration:none; padding:7px 13px;
    border-radius:8px; transition: background .2s var(--ease), color .2s var(--ease); position:relative; }
  .nav a::after { content:''; position:absolute; left:13px; right:13px; bottom:3px; height:2px;
    border-radius:2px; background:#3ecf8e; transform:scaleX(0); transform-origin:left;
    transition: transform .28s var(--ease); }
  .nav a:hover { color:#e6e9ef; background:#1c222b; }
  .nav a:hover::after { transform:scaleX(1); }
  .nav a.active { background:#232a34; color:#fff; }
  .cam-btn { background:#3ecf8e; color:#0e1116; border:none; padding:8px 16px;
    border-radius:8px; font-size:13px; font-weight:700; cursor:pointer;
    transition: transform .1s, box-shadow .15s; box-shadow: 0 2px 12px rgba(62,207,142,.22); }
  .cam-btn:hover { transform: translateY(-1px); box-shadow: 0 5px 18px rgba(62,207,142,.34); }
  .clock { font-size: 13px; color: #9aa4b2; font-variant-numeric: tabular-nums; }
  .clock.push { }
  .userchip { font-size:13px; color:#9aa4b2; display:inline-flex; align-items:center; gap:6px; }
  .panel-head svg { color:#7a8595; flex-shrink:0; }
  .alert-cam { display:flex; align-items:center; gap:5px; }
  .logout { font-size:13px; color:#9aa4b2; text-decoration:none; padding:6px 12px;
    border:1px solid #232a34; border-radius:8px; transition: color .15s, border-color .15s; }
  .logout:hover { color:#e6e9ef; border-color:#3a4557; }
  .badge.admin { background:rgba(62,207,142,.15); color:#3ecf8e; }
  .badge.invigilator { background:rgba(148,163,184,.15); color:#94a3b8; }

  main { flex: 1; display: flex; gap: 18px; padding: 18px; min-height: 0; }
  .cameras { flex:1; display:flex; flex-direction:column; gap:14px; min-height:0; }
  .overview { display:flex; gap:12px; flex-wrap:wrap; }
  .stat { background:#151a21; border:1px solid #232a34; border-radius:12px; padding:11px 16px; min-width:118px; }
  .stat .n { font-size:22px; font-weight:800; letter-spacing:.5px; line-height:1; }
  .stat .l { font-size:10.5px; color:#9aa4b2; text-transform:uppercase; letter-spacing:.7px; margin-top:6px; }
  .stat.ok .n { color:#3ecf8e; }
  .stat.warn .n { color:#eab308; }
  .grid { flex:1; display:grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    grid-auto-rows: minmax(230px, 1fr); gap:14px; overflow-y:auto; align-content:start; padding-right:2px; }
  .panel { background:#151a21; border:1px solid #232a34; border-radius:12px; overflow:hidden;
    display:flex; flex-direction:column;
    transition: border-color .25s var(--ease), transform .3s var(--ease), box-shadow .3s var(--ease); }
  .panel:hover { border-color:#2f3a49; }
  .panel.enter { animation: panelIn .55s var(--ease) backwards; animation-delay: calc(var(--i,0) * 60ms); }
  @keyframes panelIn { from { opacity:0; transform: translateY(18px) scale(.965); } }
  .grid .panel-body { cursor: zoom-in; }
  /* Drag-to-reorder */
  .grid.sortable .panel-head { cursor:grab; user-select:none; touch-action:none; }
  .grid.sortable .panel-head:active { cursor:grabbing; }
  .grid.reordering .panel { transition:none; will-change:transform; }  /* pre-promote: FLIP starts cost no paint */
  .grid.reordering .panel:hover { transform:none; box-shadow:none; border-color:#232a34; }
  .grid.reordering .panel-body img { transform:none !important; }
  .panel.dragging { transition:none; cursor:grabbing; will-change:transform;
    box-shadow:0 30px 70px rgba(0,0,0,.62), 0 0 0 1px rgba(62,207,142,.3); border-color:#3a4557; }
  .panel.dragging .cam-snap { pointer-events:none; }
  .drag-spacer { border:1.5px dashed #2c3542; border-radius:12px; background:rgba(255,255,255,.02); }
  /* Fullscreen camera focus view */
  #focus { position:fixed; inset:0; background:rgba(5,7,10,.66); backdrop-filter:blur(7px);
    -webkit-backdrop-filter:blur(7px); opacity:0; pointer-events:none;
    transition:opacity .32s var(--ease); z-index:60; }
  #focus.open { opacity:1; pointer-events:auto; }
  #focus.closing { opacity:0; }
  .focus-card { position:fixed; background:#151a21; border:1px solid #2f3a49; border-radius:14px;
    overflow:hidden; display:flex; flex-direction:column; box-shadow:0 40px 120px rgba(0,0,0,.65);
    transition:left .36s var(--ease), top .36s var(--ease), width .36s var(--ease), height .36s var(--ease); }
  .focus-card .panel-head { font-size:14.5px; padding:12px 16px; }
  .focus-card .panel-body { position:relative; cursor:default; }
  .focus-card .panel-body img { transform:none !important; }
  .focus-card img.swap { animation: camSwap .38s var(--ease); }
  @keyframes camSwap { from { opacity:0; transform:translateX(26px) scale(.985); } }
  .focus-nav { position:absolute; top:50%; transform:translateY(-50%); z-index:2;
    width:42px; height:42px; border-radius:50%; border:1px solid rgba(255,255,255,.14);
    background:rgba(14,17,22,.55); backdrop-filter:blur(8px); color:#e6e9ef; font-size:22px;
    cursor:pointer; opacity:0; transition:opacity .25s var(--ease), background .2s, transform .2s var(--ease);
    display:flex; align-items:center; justify-content:center; padding-bottom:3px; }
  .focus-card:hover .focus-nav { opacity:1; }
  .focus-nav:hover { background:rgba(62,207,142,.25); }
  .focus-nav:active { transform:translateY(-50%) scale(.92); }
  .focus-nav.prev { left:14px; } .focus-nav.next { right:14px; }
  .focus-hint { position:absolute; bottom:12px; left:50%; transform:translateX(-50%);
    font-size:11px; color:#8b95a3; background:rgba(14,17,22,.55); backdrop-filter:blur(8px);
    padding:5px 12px; border-radius:20px; border:1px solid rgba(255,255,255,.08);
    opacity:0; transition:opacity .25s var(--ease); pointer-events:none; white-space:nowrap; }
  .focus-card:hover .focus-hint { opacity:1; }
  .drag-handle { cursor:grab; color:#5b6675; font-size:15px; line-height:1;
    padding:0 4px 0 0; margin-right:-2px; user-select:none; touch-action:none;
    transition:color .12s; letter-spacing:-1px; }
  .drag-handle:hover { color:#e6e9ef; }
  .drag-handle:active { cursor:grabbing; }
  .panel-head { display:flex; align-items:center; gap:8px; padding:10px 13px;
    border-bottom:1px solid #232a34; font-size:13px; font-weight:600; }
  .panel-body { flex:1; background:#000; display:flex; align-items:center; justify-content:center; min-height:0; }
  .panel-body img { max-width:100%; max-height:100%; }
  .status-pill { margin-left:auto; display:inline-flex; align-items:center; gap:5px;
    font-size:10px; font-weight:800; letter-spacing:.5px; padding:3px 9px 3px 8px; border-radius:20px; }
  .status-pill .sdot { width:6px; height:6px; border-radius:50%; }
  .status-pill.online { color:#3ecf8e; background:rgba(62,207,142,.12); }
  .status-pill.online .sdot { background:#3ecf8e; box-shadow:0 0 6px #3ecf8e; animation: pulse 1.4s infinite; }
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
  .alert.new { animation: alertIn .55s var(--spring) backwards; }
  @keyframes alertIn { from { opacity:0; transform: translateX(34px) scale(.96); } }
  .stat .n.bump { animation: bump .5s var(--spring); }
  @keyframes bump { 35% { transform: scale(1.22); } }
  .grid-empty svg { animation: floaty 4.5s ease-in-out infinite; }
  @keyframes floaty { 50% { transform: translateY(-9px); } }
  .alert { display:flex; gap:12px; background:#1b212a; border:1px solid #283040;
    border-radius:10px; padding:10px; }
  .alert.pending { border-color: rgba(234,179,8,.35); box-shadow: 0 0 0 1px rgba(234,179,8,.10); }
  .alert.dismissed { opacity:.45; }
  .alert img { width:56px; height:72px; object-fit:cover; border-radius:6px; background:#000; flex-shrink:0; }
  .alert-info { flex:1; display:flex; flex-direction:column; gap:3px; min-width:0; }
  .alert-title { font-size:13px; font-weight:600; }
  .alert-cam { font-size:11px; color:#3ecf8e; }
  .alert-time { font-size:12px; color:#9aa4b2; }
  .alert-actions { display:flex; gap:8px; margin-top:4px; }
  .alert-actions button { flex:1; border:none; border-radius:6px; padding:6px 0;
    font-size:12px; font-weight:600; cursor:pointer; }
  button.confirm { background:#3ecf8e; color:#0e1116; }
  button.dismiss { background:#2b3340; color:#c4ccd8; }
  .badge { align-self:flex-start; margin-top:4px; font-size:11px; font-weight:700;
    padding:3px 10px; border-radius:20px; text-transform:capitalize; }
  .badge.confirmed { background:rgba(62,207,142,.15); color:#3ecf8e; }
  .badge.dismissed { background:rgba(148,163,184,.15); color:#94a3b8; }
  .badge.pending   { background:rgba(234,179,8,.15); color:#eab308; }

  /* Evidence Log page */
  .evidence-wrap { flex:1; display:flex; flex-direction:column; gap:16px; padding:18px; overflow:hidden; }
  .filters { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .filters .fbtn { font-size:13px; color:#9aa4b2; background:#151a21; border:1px solid #232a34;
    padding:7px 14px; border-radius:8px; cursor:pointer; }
  .filters .fbtn.active { background:#3ecf8e; color:#0e1116; border-color:#3ecf8e; font-weight:600; }
  .filters input[type=date] { margin-left:auto; background:#151a21; color:#e6e9ef;
    border:1px solid #232a34; padding:7px 10px; border-radius:8px; font-size:13px; }
  .table { flex:1; overflow-y:auto; background:#151a21; border:1px solid #232a34; border-radius:14px; }
  table { width:100%; border-collapse:collapse; }
  th { text-align:left; font-size:12px; color:#9aa4b2; font-weight:600;
    padding:12px 16px; border-bottom:1px solid #232a34; position:sticky; top:0; background:#151a21; }
  td { padding:10px 16px; border-bottom:1px solid #1c222b; font-size:13px; vertical-align:middle; }
  td img { width:40px; height:52px; object-fit:cover; border-radius:5px; background:#000; }
  tr:hover td { background:#1a2028; }

  /* First-run setup guide */
  .ob-bg { position:fixed; inset:0; background:rgba(8,10,14,.72); backdrop-filter:blur(6px);
    -webkit-backdrop-filter:blur(6px); display:flex; align-items:center; justify-content:center;
    z-index:80; opacity:0; pointer-events:none; transition:opacity .3s var(--ease); }
  .ob-bg.open { opacity:1; pointer-events:auto; }
  @keyframes obfade { from { opacity:0; } to { opacity:1; } }
  .ob { background:#151a21; border:1px solid #232a34; border-radius:18px; width:560px; max-width:94vw;
    padding:30px 30px 24px; box-shadow:0 30px 80px rgba(0,0,0,.6);
    transform:scale(.93) translateY(14px); opacity:0;
    transition:transform .45s var(--spring), opacity .28s var(--ease); }
  .ob-bg.open .ob { transform:none; opacity:1; }
  .ob-badge { display:inline-flex; align-items:center; gap:7px; font-size:12px; font-weight:700;
    color:#3ecf8e; background:rgba(62,207,142,.12); padding:4px 11px; border-radius:20px; margin-bottom:14px; }
  .ob h2 { font-size:22px; font-weight:800; margin-bottom:10px; letter-spacing:-.3px; }
  .ob p { font-size:14px; color:#9aa4b2; line-height:1.6; margin-bottom:14px; }
  .ob .step { display:none; }
  .ob .step.on { display:block; animation: stepIn .38s var(--ease); }
  @keyframes stepIn { from { opacity:0; transform:translateX(22px); } }
  .ob-opt { display:flex; gap:13px; align-items:flex-start; background:#0e1116; border:1px solid #232a34;
    border-radius:11px; padding:13px 15px; margin-bottom:10px; }
  .ob-opt .ico { width:34px; height:34px; border-radius:9px; background:#1a212b; color:#3ecf8e;
    display:flex; align-items:center; justify-content:center; flex-shrink:0; }
  .ob-opt b { font-size:13.5px; color:#e6e9ef; }
  .ob-opt span { display:block; font-size:12.5px; color:#8b95a3; line-height:1.5; margin-top:2px; }
  .ob-opt code { background:#1c222b; padding:1px 6px; border-radius:5px; color:#3ecf8e; font-size:11.5px; }
  .ob-foot { display:flex; align-items:center; gap:10px; margin-top:22px; }
  .ob-dots { display:flex; gap:6px; margin-right:auto; }
  .ob-dots i { width:7px; height:7px; border-radius:50%; background:#2b3340; transition:background .2s, width .2s; }
  .ob-dots i.on { background:#3ecf8e; width:20px; border-radius:4px; }
  .ob-btn { border:none; border-radius:9px; padding:11px 20px; font-size:13.5px; font-weight:700; cursor:pointer; }
  .ob-next { background:#3ecf8e; color:#0e1116; }
  .ob-back { background:#2b3340; color:#c4ccd8; }
  .ob-skip { background:transparent; color:#7a8595; font-size:12.5px; cursor:pointer; border:none; }
  .nav a.guide-link { color:#3ecf8e; }

  /* Add-camera modal */
  .modal-bg { position:fixed; inset:0; background:rgba(0,0,0,.55); backdrop-filter:blur(5px);
    -webkit-backdrop-filter:blur(5px); display:flex; align-items:center; justify-content:center;
    z-index:50; opacity:0; pointer-events:none; transition:opacity .28s var(--ease); }
  .modal-bg.open { opacity:1; pointer-events:auto; }
  .modal { background:#151a21; border:1px solid #232a34; border-radius:14px; padding:22px; width:470px; max-width:92vw;
    transform:scale(.93) translateY(12px); opacity:0;
    transition:transform .42s var(--spring), opacity .25s var(--ease); }
  .modal-bg.open .modal { transform:none; opacity:1; }
  .modal h3 { font-size:16px; margin-bottom:8px; }
  .modal p { font-size:13px; color:#9aa4b2; line-height:1.55; margin-bottom:14px; }
  .modal code { background:#0e1116; padding:2px 6px; border-radius:5px; color:#3ecf8e; font-size:12px; }
  .modal label { display:block; font-size:12px; color:#9aa4b2; margin:0 0 5px 2px; }
  .modal input { width:100%; background:#0e1116; border:1px solid #2b3340; color:#e6e9ef;
    padding:11px 12px; border-radius:8px; font-size:13px; margin-bottom:12px; }
  .modal-actions { display:flex; gap:8px; }
  .modal-actions button { flex:1; border:none; border-radius:8px; padding:11px 0; font-size:13px; font-weight:600; cursor:pointer; }
  .modal-quick { display:flex; gap:8px; margin-bottom:8px; }
  .modal-quick button { flex:1; border:none; border-radius:8px; padding:11px 0; font-size:13px; font-weight:600; cursor:pointer; }
  .btn-primary { background:#3ecf8e; color:#0e1116; }
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
    <div class="modal-quick" id="cam-quick">
      <button class="btn-ghost" onclick="addWebcam()">This computer's webcam</button>
      <button class="btn-ghost" onclick="addBrowserCam()">A device's camera (via link)</button>
    </div>
    <div class="modal-actions">
      <button class="btn-primary" id="cam-submit" onclick="submitCam()">Add camera</button>
      <button class="btn-ghost" onclick="closeCam()">Cancel</button>
    </div>
  </div>
</div>

<div class="ob-bg" id="onboard">
  <div class="ob">
    <div class="step on" data-step="0">
      <span class="ob-badge">● Getting started</span>
      <h2>Welcome to Vigil</h2>
      <p>Vigil watches your camera feeds and raises an alert the moment it spots a phone
         in someone's hand — with a photo and the exact location. Let's get your first
         camera watching. It takes about 2 minutes.</p>
      <div class="ob-opt"><span class="ico"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/></svg></span><div><b>Everything stays on this computer</b>
        <span>Detection photos are saved locally in the <code>evidence</code> folder and in the
        Evidence Log. Nothing is uploaded anywhere.</span></div></div>
    </div>

    <div class="step" data-step="1">
      <span class="ob-badge">● Step 1 of 3</span>
      <h2>Add a camera</h2>
      <p>Pick whatever camera you have. You can add more later.</p>
      <div class="ob-opt"><span class="ico"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 16V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9m16 0H4m16 0 1.28 2.55a1 1 0 0 1-.9 1.45H3.62a1 1 0 0 1-.9-1.45L4 16"/></svg></span><div><b>This computer's webcam</b>
        <span>The simplest start. In the next window just press
        <b>"Add this Mac's webcam"</b> — no URL needed.</span></div></div>
      <div class="ob-opt"><span class="ico"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="20" x="5" y="2" rx="2"/><path d="M12 18h.01"/></svg></span><div><b>Any phone or laptop — no app needed</b>
        <span>Choose <b>"A device's camera (via link)"</b>, then open the camera's <b>&#8599; link</b>
        on that device and allow the camera. Any phone browser works.
        (An <b>IP Webcam</b>-app URL still works too.)</span></div></div>
      <div class="ob-opt"><span class="ico"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h9A1.5 1.5 0 0 1 15 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 3 16.5z"/><path d="m15 10.5 4.55-2.6A1 1 0 0 1 21 8.77v6.46a1 1 0 0 1-1.45.87L15 13.5z"/></svg></span><div><b>A CCTV / IP camera</b>
        <span>Paste its <code>rtsp://…</code> stream URL in the URL box.</span></div></div>
    </div>

    <div class="step" data-step="2">
      <span class="ob-badge">● Step 2 of 3</span>
      <h2>Aim it and test</h2>
      <p>Point the camera where people sit. Then <b>hold a phone up in front of it</b> like
         someone using it.</p>
      <div class="ob-opt"><span class="ico"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg></span><div><b>Watch the right-hand Alerts panel</b>
        <span>Within a second or two a red alert with a photo appears, and you'll hear a beep.
        That's Vigil working. Confirm or dismiss each alert to keep the log clean.</span></div></div>
      <div class="ob-opt"><span class="ico"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="15 19 12 22 9 19"/><polyline points="19 9 22 12 19 15"/><line x1="2" x2="22" y1="12" y2="12"/><line x1="12" x2="12" y1="2" y2="22"/></svg></span><div><b>Rearrange your cameras any time</b>
        <span>Grab the <b>⠿</b> handle on a camera's title bar and drag it to reorder the wall.</span></div></div>
    </div>

    <div class="step" data-step="3">
      <span class="ob-badge">● Optional</span>
      <h2>Get alerts on your phone</h2>
      <p>Want a photo sent to your phone even when you're not at the screen? Open
         <b>Settings → Telegram alerts</b> and follow the steps there. Great for when the
         person running an exam is walking the room.</p>
      <div class="ob-opt"><span class="ico"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg></span><div><b>You're all set</b>
        <span>Your cameras keep watching as long as Vigil is running. Reopen this guide any time
        from <b>"Setup guide"</b> in the top bar.</span></div></div>
    </div>

    <div class="ob-foot">
      <div class="ob-dots" id="ob-dots"></div>
      <button class="ob-skip" onclick="closeOnboard()">Skip</button>
      <button class="ob-btn ob-back" id="ob-back" onclick="obStep(-1)" style="display:none">Back</button>
      <button class="ob-btn ob-next" id="ob-next" onclick="obNext()">Next</button>
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
    <nav class="nav"><a href="/" class="active">Live Monitor</a><a href="/evidence">Evidence Log</a><a href="/display">Display</a>__ADMIN_NAV__<a href="#" class="guide-link" onclick="openOnboard();return false;">Setup guide</a></nav>
    <button class="cam-btn" id="cam-btn">+ Add camera</button>
    <span class="userchip"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>__USERNAME__</span>
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
  <div id="focus" onclick="if (event.target === this) closeFocus()">
    <div class="focus-card" id="focus-card">
      <div class="panel-head"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h9A1.5 1.5 0 0 1 15 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 3 16.5z"/><path d="m15 10.5 4.55-2.6A1 1 0 0 1 21 8.77v6.46a1 1 0 0 1-1.45.87L15 13.5z"/></svg> <span id="focus-title"></span>
        <span class="status-pill offline" id="focus-pill" data-cam=""><span class="sdot"></span><span class="stext">…</span></span>
        <button class="icon-btn remove" title="Close" onclick="closeFocus()">×</button>
      </div>
      <div class="panel-body">
        <img id="focus-img" class="cam-snap" data-cam="" alt="feed">
        <button class="focus-nav prev" onclick="stepFocus(-1)">‹</button>
        <button class="focus-nav next" onclick="stepFocus(1)">›</button>
        <span class="focus-hint">← → switch camera · Esc close</span>
      </div>
    </div>
  </div>
  <script>
    const clock = document.getElementById('clock');
    setInterval(() => { clock.textContent = new Date().toLocaleTimeString(); }, 1000);

    // ---- Camera grid ----
    const IS_ADMIN = __IS_ADMIN__;
    const I = {
      cam: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h9A1.5 1.5 0 0 1 15 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 3 16.5z"/><path d="m15 10.5 4.55-2.6A1 1 0 0 1 21 8.77v6.46a1 1 0 0 1-1.45.87L15 13.5z"/></svg>',
      pin: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0"/><circle cx="12" cy="10" r="3"/></svg>'
    };
    function panelHTML(c, i) {
      const place = (c.location && c.location.trim()) ? c.location : c.label;
      const handle = IS_ADMIN ? `<span class="drag-handle" title="Drag to rearrange">⠿</span>` : '';
      const senderBtn = c.source === 'browser'
        ? `<button class="icon-btn" title="Open camera link — open this on the device that films"
             onclick="event.stopPropagation(); window.open('/sender/${c.id}','_blank')">
             <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></button>`
        : '';
      const controls = senderBtn + (IS_ADMIN
        ? `<button class="icon-btn" title="Edit camera" onclick="openEdit('${c.id}')">✎</button>
           <button class="icon-btn remove" title="Remove camera" onclick="removeCam('${c.id}')">×</button>`
        : '');
      return `<div class="panel enter" data-cam="${c.id}" style="--i:${i}">
        <div class="panel-head">${handle}${I.cam} ${place}<span class="status-pill offline" data-cam="${c.id}"><span class="sdot"></span><span class="stext">…</span></span>${controls}</div>
        <div class="panel-body" onclick="openFocus('${c.id}')"><img class="cam-snap" data-cam="${c.id}" alt="feed"></div>
      </div>`;
    }
    let lastCams = [];
    async function loadCameras() {
      let cams = [];
      try { cams = await (await fetch('/cameras')).json(); } catch (e) { return; }
      lastCams = cams;
      const grid = document.getElementById('grid');
      grid.innerHTML = cams.length
        ? cams.map((c, i) => panelHTML(c, i)).join('')
        : `<div class="grid-empty">
             <svg width="46" height="46" viewBox="0 0 24 24" fill="none"><path d="M4 9V6a2 2 0 0 1 2-2h3M15 4h3a2 2 0 0 1 2 2v3M20 15v3a2 2 0 0 1-2 2h-3M9 20H6a2 2 0 0 1-2-2v-3" stroke="#3a4557" stroke-width="1.6" stroke-linecap="round"/><circle cx="12" cy="12" r="2.4" fill="#3a4557"/></svg>
             <h3>No cameras yet</h3>
             <p>Add your webcam, any phone (via a link), or a CCTV camera to start watching for phones.</p>
             ${IS_ADMIN ? '<button class="cam-btn" onclick="openAdd()">+ Add your first camera</button>' : '<p style="color:#5b6675">Ask an admin to add a camera.</p>'}
           </div>`;
      // drop the entrance class once played, so drag re-parenting never replays it
      grid.querySelectorAll('.panel.enter').forEach(p =>
        p.addEventListener('animationend', () => p.classList.remove('enter'), { once:true }));
      if (IS_ADMIN && cams.length > 1) initSortable();
      // First run: the first time an admin opens the dashboard, walk them through setup
      if (IS_ADMIN && !localStorage.getItem('vigil_onboarded') && !obShownThisLoad
          && !document.getElementById('onboard').classList.contains('open')) {
        obShownThisLoad = true;
        openOnboard();
      }
    }
    let obShownThisLoad = false;

    // ---- First-run setup guide ----
    let obState = 0;
    const OB_STEPS = 4;
    function renderDots() {
      const d = document.getElementById('ob-dots');
      d.innerHTML = Array.from({length: OB_STEPS}, (_, i) =>
        `<i class="${i === obState ? 'on' : ''}"></i>`).join('');
      document.querySelectorAll('#onboard .step').forEach(s =>
        s.classList.toggle('on', +s.dataset.step === obState));
      document.getElementById('ob-back').style.display = obState === 0 ? 'none' : '';
      document.getElementById('ob-next').textContent = obState === OB_STEPS - 1 ? 'Add a camera →' : 'Next';
    }
    function openOnboard() { obState = 0; renderDots(); document.getElementById('onboard').classList.add('open'); }
    function closeOnboard() {
      document.getElementById('onboard').classList.remove('open');
      localStorage.setItem('vigil_onboarded', '1');
    }
    function obStep(delta) {
      obState = Math.max(0, Math.min(OB_STEPS - 1, obState + delta));
      renderDots();
    }
    function obNext() {
      if (obState === OB_STEPS - 1) { closeOnboard(); openAdd(); }
      else obStep(1);
    }

    // ---- Fluid drag-to-rearrange (admin only) ----
    // Grab anywhere on a panel's title bar. The card follows the pointer 1:1
    // on the compositor (transform-only, rigid — no lerp, no tilt);
    // siblings FLIP out of the way; release settles the card into its slot.
    function initSortable() {
      const grid = document.getElementById('grid');
      grid.classList.add('sortable');
      grid.querySelectorAll('.panel').forEach(p => {
        const head = p.querySelector('.panel-head');
        head.onpointerdown = e => {
          if (e.target.closest('.icon-btn') || e.target.closest('.status-pill')) return;
          startDrag(e, p, grid);
        };
      });
    }
    function startDrag(e, panel, grid) {
      if (e.button !== 0) return;
      e.preventDefault();
      const r0 = panel.getBoundingClientRect();
      const offX = e.clientX - r0.left, offY = e.clientY - r0.top;

      // leave a subtle "drop here" outline in the vacated slot
      const spacer = document.createElement('div');
      spacer.className = 'drag-spacer';
      spacer.style.width = r0.width + 'px'; spacer.style.height = r0.height + 'px';
      panel.after(spacer);
      grid.classList.add('reordering');
      panel.classList.add('dragging');
      Object.assign(panel.style, { position:'fixed', left:r0.left+'px', top:r0.top+'px',
        width:r0.width+'px', height:r0.height+'px', margin:'0', zIndex:30 });

      let px = e.clientX, py = e.clientY;         // live pointer (from events)
      let x = 0, y = 0;                           // rendered state
      let raf = 0, done = false, pending = false;

      // Hit-test against SETTLED slot rects (cached, re-measured only after a
      // mutation) — never against mid-animation positions, which oscillate.
      const cols = getComputedStyle(grid).gridTemplateColumns.split(' ').length;
      let slotRects = new Map([...grid.querySelectorAll('.panel:not(.dragging)')]
        .map(s => [s, s.getBoundingClientRect()]));

      // FLIP siblings only when the spacer actually changes slot — no thrash
      const flip = mutate => {
        const sibs = [...grid.querySelectorAll('.panel:not(.dragging)')];
        const first = new Map(sibs.map(s => [s, s.getBoundingClientRect()]));
        mutate();
        slotRects = new Map();
        sibs.forEach(s => {
          const f = first.get(s), l = s.getBoundingClientRect();
          slotRects.set(s, l);                     // settled rect, pre-animation
          const dx = f.left - l.left, dy = f.top - l.top;
          if (dx || dy) s.animate(
            [{ transform:`translate(${dx}px,${dy}px)` }, { transform:'none' }],
            { duration: 340, easing:'cubic-bezier(.22,.9,.3,1)' });
        });
      };

      // Decide before/after from the POINTER position (midpoint of the slot),
      // never from DOM order — an order-based rule inverts itself after every
      // insert and made the spacer flip back and forth on each mousemove.
      const hitTest = () => {
        let over = null, r = null;
        for (const [s, sr] of slotRects)
          if (px > sr.left && px < sr.right && py > sr.top && py < sr.bottom) { over = s; r = sr; break; }
        if (!over) return;
        const before = cols > 1 ? px < r.left + r.width / 2 : py < r.top + r.height / 2;
        if (before ? over.previousElementSibling !== spacer : over.nextElementSibling !== spacer)
          flip(() => before ? over.before(spacer) : over.after(spacer));
      };

      // One render per display frame. The card is RIGID: it tracks the
      // pointer 1:1 with no lerp, no rotation, no per-frame scale changes —
      // any of those reads as lag or wobble. Precision feels native.
      // Reorder hit-tests are coalesced to at most one per frame.
      const render = () => {
        x = px - offX - r0.left; y = py - offY - r0.top;
        panel.style.transform = `translate3d(${x}px,${y}px,0) scale(1.03)`;
        if (pending) { pending = false; hitTest(); }
        if (!done) raf = requestAnimationFrame(render);
      };
      raf = requestAnimationFrame(render);

      const move = ev => { px = ev.clientX; py = ev.clientY; pending = true; };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
        done = true; cancelAnimationFrame(raf);
        const commit = () => {
          panel.style.cssText = '';
          spacer.replaceWith(panel);
          panel.classList.remove('dragging');
          grid.classList.remove('reordering');
          saveOrder(grid);
        };
        if (document.hidden) { commit(); return; }   // no frames will run — settle instantly
        const d = spacer.getBoundingClientRect();
        const anim = panel.animate(
          [{ transform:`translate3d(${x}px,${y}px,0) scale(1.03)` },
           { transform:`translate3d(${d.left - r0.left}px,${d.top - r0.top}px,0) scale(1)` }],
          { duration: 300, easing:'cubic-bezier(.3,1.12,.35,1)' });  // crisp settle, hint of spring
        anim.onfinish = anim.oncancel = commit;
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
      window.addEventListener('pointercancel', up);
    }
    async function saveOrder(grid) {
      const order = [...grid.querySelectorAll('.panel')].map(p => p.dataset.cam).filter(Boolean);
      try {
        const r = await fetch('/cameras/reorder', { method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ order }) });
        lastCams = await r.json();
      } catch (e) {}
    }

    // ---- Fullscreen camera focus view (click a feed to expand) ----
    let focusId = null;
    function focusRect() {
      const w = Math.min(window.innerWidth - 72, (window.innerHeight - 130) * 16 / 9, 1360);
      const h = w * 9 / 16 + 46;
      return { left: (window.innerWidth - w) / 2, top: (window.innerHeight - h) / 2, w, h };
    }
    function setFocusCam(id, animate) {
      focusId = id;
      const c = lastCams.find(x => x.id === id);
      if (!c) return;
      document.getElementById('focus-title').textContent =
        (c.location && c.location.trim()) ? c.location : c.label;
      const img = document.getElementById('focus-img');
      img.dataset.cam = id;
      document.getElementById('focus-pill').dataset.cam = id;
      if (animate) { img.classList.remove('swap'); void img.offsetWidth; img.classList.add('swap'); }
    }
    function openFocus(id) {
      const grid = document.getElementById('grid');
      if (grid.classList.contains('reordering')) return;   // mid-drag: ignore the click
      const src = grid.querySelector(`.panel[data-cam="${id}"]`);
      if (!src) return;
      const r = src.getBoundingClientRect();
      const ov = document.getElementById('focus'), card = document.getElementById('focus-card');
      document.querySelectorAll('.focus-nav').forEach(b => b.style.display = lastCams.length > 1 ? '' : 'none');
      setFocusCam(id, false);
      card.style.transition = 'none';
      Object.assign(card.style, { left:r.left+'px', top:r.top+'px', width:r.width+'px', height:r.height+'px' });
      ov.classList.add('open');
      requestAnimationFrame(() => requestAnimationFrame(() => {
        card.style.transition = '';
        const t = focusRect();
        Object.assign(card.style, { left:t.left+'px', top:t.top+'px', width:t.w+'px', height:t.h+'px' });
      }));
    }
    function stepFocus(dir) {
      if (!lastCams.length) return;
      const ids = lastCams.map(c => c.id);
      const i = (ids.indexOf(focusId) + dir + ids.length) % ids.length;
      setFocusCam(ids[i], true);
    }
    function closeFocus() {
      if (focusId === null) return;
      const ov = document.getElementById('focus'), card = document.getElementById('focus-card');
      const src = document.querySelector(`#grid .panel[data-cam="${focusId}"]`);
      ov.classList.add('closing');
      if (src) {
        const r = src.getBoundingClientRect();
        Object.assign(card.style, { left:r.left+'px', top:r.top+'px', width:r.width+'px', height:r.height+'px' });
      }
      focusId = null;
      setTimeout(() => {
        ov.classList.remove('open', 'closing');
        card.style.cssText = '';
        document.getElementById('focus-img').dataset.cam = '';
        document.getElementById('focus-pill').dataset.cam = '';
      }, 340);
    }
    window.addEventListener('keydown', e => {
      if (focusId === null) return;
      if (e.key === 'Escape') closeFocus();
      if (e.key === 'ArrowRight') stepFocus(1);
      if (e.key === 'ArrowLeft') stepFocus(-1);
    });
    window.addEventListener('resize', () => {
      if (focusId === null) return;
      const t = focusRect(), card = document.getElementById('focus-card');
      Object.assign(card.style, { left:t.left+'px', top:t.top+'px', width:t.w+'px', height:t.h+'px' });
    });

    let editingId = null;
    function openCam(){ document.getElementById('cam-modal').classList.add('open'); }
    function closeCam(){ document.getElementById('cam-modal').classList.remove('open'); }
    function openAdd() {
      editingId = null;
      document.getElementById('cam-title').textContent = 'Add a camera';
      document.getElementById('cam-submit').textContent = 'Add camera';
      document.getElementById('cam-quick').style.display = '';
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
      document.getElementById('cam-quick').style.display = 'none';
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
    async function addBrowserCam() {
      const label = document.getElementById('cam-label').value.trim() || 'Device camera';
      const location = document.getElementById('cam-location').value.trim();
      const cam = await (await fetch('/cameras', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ label, location, source: 'browser' }) })).json();
      closeCam(); loadCameras();
      window.open('/sender/' + cam.id, '_blank');   // this tab becomes the camera
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
          new Notification('🚨 ' + (a.thing || 'Phone') + ' detected · ' + Math.round(a.confidence * 100) + '%',
            { body: '📍 ' + a.camera + '  ·  ' + a.time });
        }
      } catch (e) {}
    }

    // ---- Alerts ----
    let lastAlertsKey = '';
    async function loadAlerts() {
      // mid-drag: no DOM writes anywhere — they force layout and hitch the drag
      if (document.querySelector('.grid.reordering')) return;
      let data = [];
      try { data = await (await fetch('/alerts')).json(); } catch (e) { return; }
      const prevMax = lastAlertId, wasFirst = firstAlertLoad;
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
      // only touch the DOM when something actually changed (no flicker, no replayed animations)
      const key = data.map(a => a.id + ':' + a.status).join('|');
      if (key === lastAlertsKey) return;
      lastAlertsKey = key;
      if (data.length === 0) {
        box.innerHTML = '<div class="empty">No alerts yet.<br>Hold a phone up to a camera.</div>';
        return;
      }
      box.innerHTML = data.map(a => `
        <div class="alert ${a.status}${!wasFirst && a.id > prevMax ? ' new' : ''}">
          <img src="${a.image}">
          <div class="alert-info">
            <div class="alert-title">${a.thing || 'Phone'} detected · ${Math.round(a.confidence*100)}%</div>
            <div class="alert-cam">${I.pin}${a.camera}</div>
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
      // mid-drag: give the drag every frame; feeds resume the moment it ends
      if (document.querySelector('.grid.reordering')) return;
      document.querySelectorAll('img.cam-snap').forEach(img => {
        const id = img.dataset.cam;
        if (!id) return;
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
    setInterval(refreshSnapshots, 33);

    // ---- Per-camera online/offline status ----
    async function refreshStatus() {
      // mid-drag: the pills live inside the panels being dragged/FLIPped —
      // touching their text mid-drag forces layout and hitches the animation
      if (document.querySelector('.grid.reordering')) return;
      let st = {};
      try { st = await (await fetch('/camera_status')).json(); } catch (e) { return; }
      document.querySelectorAll('.status-pill').forEach(p => {
        const online = st[p.dataset.cam] === 'online';
        p.classList.toggle('online', online);
        p.classList.toggle('offline', !online);
        const el = p.querySelector('.stext'), txt = online ? 'LIVE' : 'OFFLINE';
        if (el.textContent !== txt) el.textContent = txt;   // write only on change
      });
    }
    setInterval(refreshStatus, 1500);
    refreshStatus();

    // ---- Overview stats ----
    function setStat(id, v) {
      const el = document.getElementById(id);
      if (el.textContent === String(v)) return;
      el.textContent = v;
      el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump');
    }
    async function loadStats() {
      try {
        const s = await (await fetch('/stats')).json();
        setStat('stat-cameras', s.cameras);
        setStat('stat-today', s.alerts_today);
        setStat('stat-pending', s.pending);
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
    <nav class="nav"><a href="/">Live Monitor</a><a href="/evidence" class="active">Evidence Log</a><a href="/display">Display</a>__ADMIN_NAV__</nav>
    <span class="userchip"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>__USERNAME__</span>
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
        <thead><tr><th>Photo</th><th>Detected</th><th>Date</th><th>Time</th><th>Location</th><th>Confidence</th><th>Status</th></tr></thead>
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
        body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#5b6675;padding:40px">No matching records.</td></tr>';
        return;
      }
      body.innerHTML = rows.map(r => `
        <tr>
          <td><img src="${r.image}"></td>
          <td>${r.thing || 'Phone'}</td>
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
  .add button { width:100%; background:#3ecf8e; color:#0e1116; border:none; padding:11px;
    border-radius:8px; font-weight:700; cursor:pointer; }
  .list { flex:1; min-width:320px; }
  .del { background:#2b3340; color:#f87171; border:none; padding:6px 12px; border-radius:6px; font-size:12px; cursor:pointer; }
</style></head>
<body>
  <header>
    __LOGO__<span class="logo">Vig<span>i</span>l</span>
    <nav class="nav"><a href="/">Live Monitor</a><a href="/evidence">Evidence Log</a><a href="/display">Display</a><a href="/users" class="active">Users</a><a href="/settings">Settings</a></nav>
    <span class="userchip"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>__USERNAME__</span>
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


# ---- Browser-camera sender page -------------------------------------------
SENDER_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — Camera sender</title>__STYLE__
<style>
  body { align-items:center; justify-content:center; }
  .sender { width:min(680px, 94vw); margin:auto; display:flex; flex-direction:column; gap:14px; }
  .s-head { display:flex; align-items:center; gap:10px; }
  .s-head h2 { font-size:17px; font-weight:700; }
  .s-pill { margin-left:auto; display:inline-flex; align-items:center; gap:6px; font-size:11px;
    font-weight:800; letter-spacing:.5px; padding:5px 12px; border-radius:20px;
    color:#94a3b8; background:rgba(148,163,184,.12); transition:all .3s var(--ease); }
  .s-pill .dot2 { width:7px; height:7px; border-radius:50%; background:#7a8595; }
  .s-pill.live { color:#3ecf8e; background:rgba(62,207,142,.12); }
  .s-pill.live .dot2 { background:#3ecf8e; box-shadow:0 0 8px #3ecf8e; animation:pulse 1.5s infinite; }
  .s-video { background:#000; border:1px solid #232a34; border-radius:14px; overflow:hidden;
    aspect-ratio:4/3; display:flex; align-items:center; justify-content:center; }
  .s-video video { width:100%; height:100%; object-fit:cover; }
  .s-msg { font-size:13.5px; color:#9aa4b2; line-height:1.6; text-align:center; }
  .s-msg b { color:#e6e9ef; }
  .s-err { color:#f87171; }
</style></head>
<body>
  <div class="sender">
    <div class="s-head">__LOGO__<h2>__CAM_NAME__</h2>
      <span class="s-pill" id="pill"><span class="dot2"></span><span id="ptext">STARTING…</span></span></div>
    <div class="s-video"><video id="v" autoplay playsinline muted></video></div>
    <p class="s-msg" id="msg">Keep this page open — this device is now a Vigil camera.<br>
      Its feed appears on the Live Monitor like any other camera.</p>
  </div>
  <script>
    const CAM_ID = "__CAM_ID__";
    const v = document.getElementById('v'), pill = document.getElementById('pill'),
          ptext = document.getElementById('ptext'), msg = document.getElementById('msg');
    const canvas = document.createElement('canvas');
    let sending = false;

    async function start() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia(
          { video: { facingMode: 'environment', width: { ideal: 1280 } }, audio: false });
        v.srcObject = stream;
      } catch (e) {
        pill.classList.remove('live'); ptext.textContent = 'NO CAMERA';
        msg.innerHTML = '<span class="s-err">Camera permission was denied.</span> ' +
          'Allow camera access for this site in your browser settings, then reload.';
        return;
      }
      try { await navigator.wakeLock.request('screen'); } catch (e) {}   // keep phone awake
      setInterval(shoot, 400);
    }
    async function shoot() {
      if (sending || v.videoWidth === 0) return;
      sending = true;
      const w = Math.min(v.videoWidth, 960), h = Math.round(w * v.videoHeight / v.videoWidth);
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(v, 0, 0, w, h);
      canvas.toBlob(async blob => {
        try {
          const r = await fetch('/push/' + CAM_ID, { method:'POST',
            headers:{'Content-Type':'image/jpeg'}, body: blob });
          const ok = r.ok;
          pill.classList.toggle('live', ok);
          ptext.textContent = ok ? 'LIVE' : 'RECONNECTING…';
        } catch (e) {
          pill.classList.remove('live'); ptext.textContent = 'RECONNECTING…';
        }
        sending = false;
      }, 'image/jpeg', 0.75);
    }
    start();
  </script>
</body></html>"""


@app.get("/sender/{camera_id}", response_class=HTMLResponse)
def sender_page(camera_id: str):
    source, place = _find_camera(camera_id)
    if source != "browser":
        return RedirectResponse("/")
    return (SENDER_HTML.replace("__STYLE__", STYLE).replace("__LOGO__", LOGO_MARK)
            .replace("__CAM_NAME__", place or "Camera").replace("__CAM_ID__", camera_id))


@app.get("/evidence", response_class=HTMLResponse)
def evidence_page(request: Request):
    user = getattr(request.state, "user", None) or {"username": "", "role": "invigilator"}
    return (EVIDENCE_HTML.replace("__STYLE__", STYLE).replace("__LOGO__", LOGO_MARK)
            .replace("__USERNAME__", user["username"])
            .replace("__ADMIN_NAV__", _admin_nav(user)))


# ---- Public landing website (shown at "/" when not signed in) -------------
LANDING_HTML = """<!doctype html>
<html lang="en" style="scroll-behavior:smooth"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — Local AI phone detection for exams & secure spaces</title>
<meta name="description" content="Vigil watches your camera feeds with on-device AI and raises an alert with photo evidence the moment a phone appears. Runs 100% on your computer — webcams, old phones, or CCTV. Set up in 2 minutes.">
<meta property="og:title" content="Vigil — the room is watching">
<meta property="og:description" content="On-premise vision intelligence. A phone appears — flagged, photographed, logged in under a second. Nothing leaves the building.">
<meta name="theme-color" content="#07090c">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="icon" href="/favicon.svg">
<style>
  :root { --ease:cubic-bezier(.22,.9,.3,1);
    --bg:#07090c; --panel:#0c1015; --line:rgba(255,255,255,.07); --line2:rgba(255,255,255,.12);
    --txt:#e8ebf1; --mut:#8b95a3; --dim:#525c6b; --grn:#3ecf8e; --red:#ef4444;
    --mono:'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
    --disp:'Space Grotesk','Inter',sans-serif; }
  * { box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent; }
  html,body { background:var(--bg); color:var(--txt); overflow-x:clip;
    font-family:'Inter',-apple-system,Segoe UI,Roboto,sans-serif; -webkit-font-smoothing:antialiased; }
  a, button { -webkit-tap-highlight-color:transparent; }
  ::selection { background:rgba(62,207,142,.28); }
  a { color:inherit; text-decoration:none; }
  h1,h2,h3 { font-family:var(--disp); }

  /* blueprint grid + grain over the whole page */
  .gridbg { position:fixed; inset:0; z-index:0; pointer-events:none;
    background-image:linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px),
                     linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
    background-size:64px 64px; opacity:.5;
    mask-image:radial-gradient(1600px 1400px at 50% -5%, #000 42%, rgba(0,0,0,.25) 78%, transparent 110%); }
  .grainbg { position:fixed; inset:0; z-index:0; pointer-events:none; opacity:.04; mix-blend-mode:overlay;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"); }

  .shell { position:relative; z-index:1; max-width:1120px; margin:0 auto; padding:0 28px; }

  /* ---- system bar ---- */
  .sysbar { position:relative; z-index:5; border-bottom:1px solid var(--line);
    font-family:var(--mono); font-size:10.5px; letter-spacing:.8px; color:var(--dim); }
  .sysbar .row { max-width:1120px; margin:0 auto; padding:9px 28px; display:flex; gap:26px; }
  .sysbar b { color:var(--grn); font-weight:500; }
  .sysbar .ok::before { content:'●'; color:var(--grn); margin-right:6px; font-size:8px; }
  .sysbar .right { margin-left:auto; display:flex; gap:26px; }
  @media (max-width:920px){ .sysbar .hidem { display:none; } }

  /* ---- nav ---- */
  .site-head { position:sticky; top:0; z-index:10; backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px);
    background:rgba(7,9,12,.72); border-bottom:1px solid transparent; transition:border-color .4s, background .4s; }
  .site-head.scrolled { border-color:var(--line); background:rgba(7,9,12,.9); }
  .site-head .row { display:flex; align-items:center; gap:30px; height:64px; max-width:1120px; margin:0 auto; padding:0 28px; }
  .brand { display:flex; align-items:center; gap:10px; font-weight:700; font-size:19px; font-family:var(--disp); }
  .brand svg { color:#6b7687; }
  .brand b span { color:var(--grn); }
  .site-nav { display:flex; gap:4px; margin-left:auto; }
  .site-nav a { font-family:var(--mono); font-size:10.5px; letter-spacing:1.4px; color:var(--mut);
    padding:8px 12px; transition:color .3s; }
  .site-nav a:hover { color:var(--txt); }
  .btn { display:inline-flex; align-items:center; justify-content:center; gap:9px; border-radius:6px;
    font-family:var(--mono); font-size:11.5px; font-weight:600; letter-spacing:1.2px;
    padding:13px 24px; cursor:pointer; border:none; transition:box-shadow .45s var(--ease), background .3s, border-color .3s; }
  .btn-grn { background:var(--grn); color:#07090c; box-shadow:0 4px 24px rgba(62,207,142,.22); }
  .btn-grn:hover { box-shadow:0 10px 44px rgba(62,207,142,.4); }
  .btn-ghost { background:transparent; color:var(--txt); border:1px solid var(--line2); }
  .btn-ghost:hover { border-color:rgba(255,255,255,.28); background:rgba(255,255,255,.03); }
  .site-head .btn { padding:9px 18px; font-size:10.5px; }

  /* ---- hero ---- */
  .hero { position:relative; padding:96px 0 84px; display:grid; grid-template-columns:1.04fr 1fr; gap:60px; align-items:center; }
  .hero-glow { position:absolute; right:-8%; top:0; width:660px; height:660px; pointer-events:none; z-index:0;
    background:radial-gradient(circle, rgba(62,207,142,.09) 0%, rgba(62,207,142,.03) 40%, transparent 68%);
    filter:blur(12px); }
  .hero > *:not(.hero-glow) { position:relative; z-index:1; }
  .kicker { font-family:var(--mono); font-size:10.5px; letter-spacing:2.4px; color:var(--grn); display:block; margin-bottom:26px; }
  .kicker::before { content:'// '; color:var(--dim); }
  h1 { font-size:clamp(40px,5.4vw,68px); line-height:1.02; letter-spacing:-0.03em; font-weight:700; }
  .hero p.sub { font-size:16px; color:var(--mut); line-height:1.7; margin:26px 0 34px; max-width:470px; }
  .hero p.sub b { color:var(--txt); font-weight:600; }
  .ctas { display:flex; gap:12px; flex-wrap:wrap; }
  .telemetry { display:flex; gap:0; margin-top:44px; border:1px solid var(--line); border-radius:8px;
    overflow:hidden; width:fit-content; }
  .telemetry div { font-family:var(--mono); font-size:10px; letter-spacing:1px; color:var(--dim);
    padding:12px 18px; border-right:1px solid var(--line); }
  .telemetry div:last-child { border-right:none; }
  .telemetry b { display:block; color:var(--txt); font-size:14px; letter-spacing:0; margin-bottom:3px; font-weight:600; }
  .telemetry .lat b { color:var(--grn); }

  /* evidence frame around the monitor mock */
  .evidence { position:relative; padding:20px; }
  .evidence::before, .evidence::after, .evidence .ck::before, .evidence .ck::after { content:'';
    position:absolute; width:22px; height:22px; border:1.5px solid var(--line2); }
  .evidence::before { top:0; left:0; border-right:none; border-bottom:none; }
  .evidence::after  { top:0; right:0; border-left:none; border-bottom:none; }
  .evidence .ck::before { bottom:0; left:0; border-right:none; border-top:none; }
  .evidence .ck::after  { bottom:0; right:0; border-left:none; border-top:none; }
  .ev-meta { position:absolute; top:-9px; left:34px; background:var(--bg); padding:0 10px;
    font-family:var(--mono); font-size:9.5px; letter-spacing:1.6px; color:var(--dim); }
  .ev-time { position:absolute; bottom:-8px; right:34px; background:var(--bg); padding:0 10px;
    font-family:var(--mono); font-size:9.5px; letter-spacing:1.2px; color:var(--dim); }
  .ev-time b { color:var(--grn); font-weight:500; }

  .mock { background:rgba(13,17,23,.82); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px);
    border:1px solid rgba(255,255,255,.08); border-radius:12px; overflow:hidden;
    box-shadow:0 60px 120px -20px rgba(0,0,0,.7), 0 30px 60px -30px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.07);
    will-change:transform; }
  .mock-bar { display:flex; align-items:center; gap:7px; padding:11px 14px; border-bottom:1px solid var(--line); }
  .mock-bar i { width:9px; height:9px; border-radius:50%; background:#1e2631; }
  .mock-bar span { font-family:var(--mono); font-size:9.5px; letter-spacing:1.4px; color:var(--dim); margin-left:8px; }
  .mock-bar em { margin-left:auto; font-style:normal; font-family:var(--mono); font-size:9px; font-weight:600;
    color:var(--grn); letter-spacing:1px; animation:pulse 1.6s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
  .mock-body { display:grid; grid-template-columns:1fr 150px; gap:10px; padding:12px; }
  .mock-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  .tile { background:#0a0e13; border:1px solid #161d26; border-radius:8px; overflow:hidden;
    transition:border-color .4s, box-shadow .4s; }
  .tile .t-head { display:flex; align-items:center; font-family:var(--mono); font-size:8px; letter-spacing:.6px;
    color:#77828f; padding:6px 9px; border-bottom:1px solid #141a22; }
  .tile .t-head b { margin-left:auto; color:var(--grn); font-size:7.5px; letter-spacing:1px; }
  .t-view { position:relative; height:86px; overflow:hidden; background:linear-gradient(165deg,#10161e 0%,#0a0e13 70%); }
  .t-view .desk { position:absolute; bottom:10px; width:34%; height:25px; border-radius:6px 6px 0 0; background:#151c26; }
  .t-view .desk::after { content:''; position:absolute; top:-15px; left:50%; transform:translateX(-50%);
    width:15px; height:15px; border-radius:50%; background:#1c2530; }
  .t-view .d1 { left:9%; } .t-view .d2 { right:9%; }
  .scan { position:absolute; left:0; right:0; height:30px; top:-36px;
    background:linear-gradient(180deg,transparent,rgba(62,207,142,.07) 65%,rgba(62,207,142,.26));
    animation:scan 3.6s linear infinite; }
  @keyframes scan { to { top:110%; } }
  .bbox { position:absolute; top:16px; left:15%; width:32px; height:44px; border:1.5px solid var(--red);
    border-radius:3px; opacity:0; transform:scale(.75); box-shadow:0 0 16px rgba(239,68,68,.45); }
  .bbox::after { content:'PHONE 0.93'; position:absolute; top:-14px; left:-2px; font-family:var(--mono);
    font-size:6.5px; font-weight:600; letter-spacing:.4px; color:#fff; background:var(--red); padding:1.5px 4px; border-radius:2px; white-space:nowrap; }
  .tile.hit { border-color:rgba(239,68,68,.6); box-shadow:0 0 0 1px rgba(239,68,68,.32), 0 0 26px rgba(239,68,68,.14); }
  .tile.hit .bbox { opacity:1; transform:scale(1); transition:all .3s var(--ease); }
  .mock-side { background:#0a0e13; border:1px solid #161d26; border-radius:8px; padding:9px; overflow:hidden; }
  .ms-head { font-family:var(--mono); font-size:8px; letter-spacing:1.6px; color:#77828f; margin-bottom:8px; }
  .ms-card { display:flex; gap:7px; background:#0f151d; border:1px solid rgba(239,68,68,.28);
    border-radius:6px; padding:6px; margin-bottom:7px; animation:msIn .5s var(--ease); }
  @keyframes msIn { from { opacity:0; transform:translateX(22px); } }
  .ms-card .ph { width:20px; height:26px; border-radius:3px; background:linear-gradient(150deg,#26303f,#12181f); flex-shrink:0; }
  .ms-card div b { display:block; font-family:var(--mono); font-size:7.5px; color:var(--txt); letter-spacing:.3px; }
  .ms-card div span { font-family:var(--mono); font-size:6.5px; color:#77828f; }


  /* ---- sections: numbered spec-sheet ---- */
  section { padding:110px 0; position:relative; }
  .sec-head { display:flex; align-items:baseline; gap:18px; border-bottom:1px solid var(--line);
    padding-bottom:18px; margin-bottom:8px; }
  .sec-no { font-family:var(--mono); font-size:11px; letter-spacing:2px; color:var(--grn); }
  h2 { font-size:clamp(28px,3.4vw,44px); letter-spacing:-0.02em; font-weight:700; }
  .sec-sub { color:var(--mut); font-size:15px; line-height:1.7; max-width:560px; margin-top:22px; }

  /* capability ledger rows */
  .ledger { margin-top:26px; }
  .cap-row { display:grid; grid-template-columns:64px 250px 1fr; gap:26px; align-items:baseline;
    padding:26px 10px; border-bottom:1px solid var(--line); position:relative; transition:background .4s; }
  .cap-row::before { content:''; position:absolute; left:0; top:0; bottom:0; width:2px; background:var(--grn);
    transform:scaleY(0); transition:transform .4s var(--ease); transform-origin:top; }
  .cap-row:hover { background:rgba(255,255,255,.015); }
  .cap-row:hover::before { transform:scaleY(1); }
  .cap-row .no { font-family:var(--mono); font-size:11px; color:var(--dim); letter-spacing:1px; }
  .cap-row h3 { font-size:18px; font-weight:600; letter-spacing:-.01em; }
  .cap-row p { font-size:14px; color:var(--mut); line-height:1.65; }
  @media (max-width:920px){ .cap-row { grid-template-columns:1fr; gap:8px; } }

  /* detection timeline */
  .timeline { display:grid; grid-template-columns:repeat(4,1fr); gap:0; margin-top:64px; position:relative; }
  .timeline::before { content:''; position:absolute; top:5px; left:2%; right:2%; height:1px; background:var(--line2); }
  .t-node { position:relative; padding:34px 26px 0 0; }
  .t-node::before { content:''; position:absolute; top:0; left:0; width:11px; height:11px; border-radius:50%;
    background:var(--bg); border:2px solid var(--dim); transition:border-color .5s, box-shadow .5s; }
  .t-node .ts { font-family:var(--mono); font-size:11px; letter-spacing:1px; color:var(--grn); display:block; margin-bottom:10px; }
  .t-node h3 { font-size:15.5px; font-weight:600; margin-bottom:8px; letter-spacing:.2px; }
  .t-node p { font-size:13px; color:var(--mut); line-height:1.6; }
  .t-node.alarm .ts { color:var(--red); }
  .timeline.in .t-node::before { border-color:var(--grn); box-shadow:0 0 12px rgba(62,207,142,.5); }
  .timeline.in .t-node.alarm::before { border-color:var(--red); box-shadow:0 0 12px rgba(239,68,68,.5); }
  .timeline.in .t-node:nth-child(1)::before { transition-delay:.1s; } .timeline.in .t-node:nth-child(1) { transition-delay:.1s; }
  .timeline.in .t-node:nth-child(2)::before { transition-delay:.5s; }
  .timeline.in .t-node:nth-child(3)::before { transition-delay:.9s; }
  .timeline.in .t-node:nth-child(4)::before { transition-delay:1.3s; }
  @media (max-width:920px){ .timeline { grid-template-columns:1fr; gap:30px; } .timeline::before { display:none; } }

  /* deployment spec sheet */
  .spec { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:40px; }
  .spec-col { border:1px solid var(--line); border-radius:12px; background:var(--panel); padding:30px;
    transition:border-color .5s var(--ease), box-shadow .5s var(--ease); }
  .spec-col:hover { border-color:var(--line2); box-shadow:0 24px 60px -24px rgba(0,0,0,.55); }
  .spec-col .sc-head { font-family:var(--mono); font-size:10px; letter-spacing:2px; color:var(--grn); margin-bottom:22px; }
  .spec-row { display:flex; gap:14px; padding:13px 0; border-bottom:1px solid var(--line); font-size:14px; }
  .spec-row:last-child { border-bottom:none; }
  .spec-row .k { font-family:var(--mono); font-size:10.5px; letter-spacing:1px; color:var(--dim); min-width:36px; padding-top:2px; }
  .spec-row div b { color:var(--txt); font-weight:600; display:block; margin-bottom:2px; }
  .spec-row div span { color:var(--mut); font-size:13px; line-height:1.55; }
  @media (max-width:920px){ .spec { grid-template-columns:1fr; } }
  .note { display:flex; gap:12px; align-items:flex-start; margin-top:22px; background:rgba(62,207,142,.05);
    border:1px solid rgba(62,207,142,.18); border-radius:10px; padding:16px 18px; font-size:13.5px;
    color:var(--mut); line-height:1.6; }
  .note b { color:var(--txt); }
  .note .nico { color:var(--grn); flex-shrink:0; margin-top:1px; }

  /* privacy doctrine */
  .doctrine h2 { font-size:clamp(30px,4vw,52px); max-width:720px; }
  .doctrine h2 em { font-style:normal; color:var(--grn); }
  .ledge { margin-top:52px; border-top:1px solid var(--line); }
  .ledge div { display:grid; grid-template-columns:280px 1fr; gap:20px; padding:16px 8px;
    border-bottom:1px solid var(--line); font-family:var(--mono); font-size:11.5px; letter-spacing:1.4px; }
  .ledge .k { color:var(--dim); }
  .ledge .v { color:var(--grn); }
  @media (max-width:920px){ .ledge div { grid-template-columns:1fr; gap:4px; } }

  /* faq */
  .faq { max-width:760px; margin-top:26px; }
  .qa { border-bottom:1px solid var(--line); }
  .qa button { width:100%; display:flex; align-items:center; gap:18px; text-align:left; background:none; border:none;
    color:var(--txt); font-size:15.5px; font-weight:600; font-family:'Inter',sans-serif; padding:22px 4px; cursor:pointer; }
  .qa button .qno { font-family:var(--mono); font-size:10.5px; color:var(--dim); letter-spacing:1px; }
  .qa button i { margin-left:auto; font-style:normal; color:var(--grn); font-size:18px; transition:transform .4s var(--ease); }
  .qa.open button i { transform:rotate(45deg); }
  .qa .a { max-height:0; overflow:hidden; transition:max-height .45s var(--ease); }
  .qa .a p { padding:0 4px 22px 44px; font-size:14px; color:var(--mut); line-height:1.7; }

  /* setups / download cards (shared) */
  .setups { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-top:36px; }
  .setup-c { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:26px;
    transition:border-color .5s var(--ease), box-shadow .5s var(--ease); }
  .setup-c:hover { border-color:rgba(62,207,142,.26); box-shadow:0 24px 60px -24px rgba(0,0,0,.55); }
  .setup-c .ico { width:38px; height:38px; border-radius:9px; background:#131a23; color:var(--grn);
    display:flex; align-items:center; justify-content:center; }
  .setup-c h3 { font-size:15.5px; margin:14px 0 8px; font-weight:600; }
  .setup-c p { font-size:13.5px; color:var(--mut); line-height:1.7; }
  .setup-c code { background:#0a0e13; border:1px solid var(--line); padding:2px 7px; border-radius:5px;
    color:var(--grn); font-family:var(--mono); font-size:11.5px; }
  @media (max-width:920px){ .setups { grid-template-columns:1fr; } }

  /* final */
  .final { text-align:center; padding:130px 0 120px; }
  .final h2 { font-size:clamp(32px,4.4vw,56px); }
  .final .sec-sub { margin:20px auto 0; }
  .final .ctas { justify-content:center; margin-top:36px; }
  footer { border-top:1px solid var(--line); position:relative; z-index:1; }
  footer .frow { display:flex; align-items:center; gap:14px; max-width:1120px; margin:0 auto; padding:26px 28px;
    font-family:var(--mono); font-size:10.5px; letter-spacing:1px; color:var(--dim); }
  footer .frow a:hover { color:var(--txt); }
  footer .right { margin-left:auto; display:flex; gap:22px; }

  .reveal { opacity:0; transform:translateY(20px); transition:opacity .9s var(--ease), transform .9s var(--ease);
    transition-delay:var(--d,0s); }
  .reveal.in { opacity:1; transform:none; }
  @media (max-width:920px){
    .hero { grid-template-columns:1fr; padding-top:56px; gap:44px; }
    .site-nav { display:none; }
    .site-head .btn { margin-left:auto; }
    .telemetry { flex-wrap:wrap; } .telemetry div { border-top:1px solid var(--line); }
  }

  /* ---- phones: a designed layout, not a squeezed one ---- */
  @media (max-width:640px){
    .shell { padding:0 20px; }
    .sysbar .row { padding:8px 20px; gap:14px; }
    .sysbar .right { display:none; }
    .site-head .row { height:56px; padding:0 20px; gap:16px; }
    .brand { font-size:17px; }
    section { padding:72px 0; }
    .sec-head { padding-bottom:14px; }
    .sec-sub { font-size:14px; margin-top:18px; }

    .hero { padding:44px 0 64px; gap:40px; }
    .hero-glow { width:380px; height:380px; right:-30%; top:-4%; }
    .hero p.sub { font-size:15px; margin:22px 0 28px; }
    .kicker { margin-bottom:20px; }
    .ctas { flex-direction:column; align-items:stretch; }
    .ctas .btn { width:100%; padding:15px 24px; }

    .telemetry { display:grid; grid-template-columns:1fr 1fr; width:100%; margin-top:36px; }
    .telemetry div { border:none; border-bottom:1px solid var(--line); padding:13px 16px; }
    .telemetry div:nth-child(odd) { border-right:1px solid var(--line); }
    .telemetry div:nth-child(n+3) { border-bottom:none; }

    .evidence { padding:14px; }
    .ev-meta { left:24px; } .ev-time { right:24px; }
    .mock-body { grid-template-columns:1fr; }
    .mock-side { min-height:78px; }

    .cap-row { grid-template-columns:32px 1fr; gap:6px 14px; padding:22px 4px; }
    .cap-row .no { padding-top:3px; }
    .cap-row p { grid-column:2; }

    .timeline { margin-top:44px; gap:36px; }
    .timeline::before { display:block; left:5px; right:auto; top:6px; bottom:6px; width:1px; height:auto; }
    .t-node { padding:0 0 0 34px; }
    .t-node::before { top:3px; }

    .spec { margin-top:32px; }
    .spec-col { padding:24px 20px; }
    .setups { margin-top:28px; }
    .setup-c { padding:22px 20px; }
    .note { padding:14px 16px; font-size:13px; }

    .ledge { margin-top:40px; }
    .qa button { font-size:14.5px; gap:12px; padding:20px 2px; }
    .qa .a p { padding:0 2px 20px 28px; }

    .final { padding:96px 0 88px; }
    footer .frow { flex-direction:column; align-items:flex-start; gap:12px; padding:24px 20px; }
    footer .frow a { white-space:nowrap; }
    footer .right { margin-left:0; gap:8px 18px; flex-wrap:wrap; }
  }
</style></head>
<body>
<div class="gridbg" aria-hidden="true"></div>
<div class="grainbg" aria-hidden="true"></div>

<div class="sysbar"><div class="row">
  <span><b>VIGIL</b> v1.0</span>
  <span class="ok">SYSTEM OPERATIONAL</span>
  <span class="hidem">MODE: <b>100% ON-PREMISE</b></span>
  <div class="right">
    <span class="hidem">LOCAL TIME <b id="sysclock">--:--:--</b></span>
    <span>UPLINK: NONE REQUIRED</span>
  </div>
</div></div>

<div class="site-head" id="site-head"><div class="row">
  <a class="brand" href="/">__LOGO__<b>Vig<span>i</span>l</b></a>
  <nav class="site-nav">
    <a href="#capabilities">CAPABILITIES</a><a href="#detection">DETECTION</a>
    <a href="#deployment">DEPLOYMENT</a><a href="#privacy">PRIVACY</a><a href="#faq">FAQ</a>
  </nav>
  <a class="btn btn-grn" href="/login">OPEN DASHBOARD</a>
</div></div>

<main class="shell">
  <section class="hero">
    <div class="hero-glow" aria-hidden="true"></div>
    <div>
      <span class="kicker reveal in">ON-PREMISE VISION INTELLIGENCE</span>
      <h1 class="reveal in" style="--d:.06s">The room<br>is watching.</h1>
      <p class="sub reveal in" style="--d:.12s">Vigil turns the cameras you already own into unblinking AI
        observers. A phone appears — it's <b>flagged, photographed and logged in under a second</b>.
        Runs entirely on one machine. Nothing leaves the building.</p>
      <div class="ctas reveal in" style="--d:.18s">
        <a class="btn btn-grn" href="/login">OPEN THE DASHBOARD</a>
        <a class="btn btn-ghost" href="#deployment">RUN A PILOT</a>
      </div>
      <div class="telemetry reveal in" style="--d:.24s">
        <div class="lat"><b>~0.9s</b>DETECT → ALERT</div>
        <div><b>0</b>UPLOADS</div>
        <div><b>∞</b>CAMERAS</div>
        <div><b>LOCAL</b>EVIDENCE</div>
      </div>
    </div>
    <div class="evidence reveal in" style="--d:.2s"><span class="ck"></span>
      <span class="ev-meta">LIVE FEED — EXAM HALL B</span>
      <span class="ev-time"><b id="evclock">--:--:--</b> · CAM 03</span>
      <div class="mock">
        <div class="mock-bar"><i></i><i></i><i></i><span>VIGIL — LIVE MONITOR</span><em>● REC</em></div>
        <div class="mock-body">
          <div class="mock-grid">
            <div class="tile"><div class="t-head">ROW 1 · FRONT<b>LIVE</b></div>
              <div class="t-view"><span class="desk d1"></span><span class="desk d2"></span><div class="bbox"></div><div class="scan"></div></div></div>
            <div class="tile"><div class="t-head">ROW 3 · LEFT<b>LIVE</b></div>
              <div class="t-view"><span class="desk d1"></span><span class="desk d2"></span><div class="bbox"></div><div class="scan" style="animation-delay:-1.2s"></div></div></div>
            <div class="tile"><div class="t-head">ROW 5 · BACK<b>LIVE</b></div>
              <div class="t-view"><span class="desk d1"></span><span class="desk d2"></span><div class="bbox"></div><div class="scan" style="animation-delay:-2.1s"></div></div></div>
            <div class="tile"><div class="t-head">CORRIDOR · A<b>LIVE</b></div>
              <div class="t-view"><span class="desk d1"></span><span class="desk d2"></span><div class="bbox"></div><div class="scan" style="animation-delay:-.6s"></div></div></div>
          </div>
          <div class="mock-side"><div class="ms-head">ALERTS</div><div id="ms-list"></div></div>
        </div>
      </div>
    </div>
  </section>

  <section id="capabilities">
    <div class="sec-head reveal"><span class="sec-no">01 / CAPABILITIES</span></div>
    <h2 class="reveal" style="--d:.05s">Built like infrastructure.<br>Not an app with a gimmick.</h2>
    <div class="ledger">
      <div class="cap-row reveal"><span class="no">01</span><h3>Real-time detection</h3>
        <p>A fine-tuned neural model scans every frame of every feed — full frame plus zoomed tiles for
        distant, half-hidden phones. A raised phone is flagged in about a second.</p></div>
      <div class="cap-row reveal"><span class="no">02</span><h3>Evidence chain</h3>
        <p>Every detection is stored with the photo, camera, location tag, timestamp, confidence and the
        reviewer's verdict. A searchable record your institution can stand behind.</p></div>
      <div class="cap-row reveal"><span class="no">03</span><h3>Any camera</h3>
        <p>RTSP CCTV, webcams, or any phone's browser via a link — no app to install. Unlimited feeds
        monitored simultaneously on one machine.</p></div>
      <div class="cap-row reveal"><span class="no">04</span><h3>Display wall</h3>
        <p>A fullscreen monitoring wall built for the invigilation desk — with an unmissable on-screen
        alarm, flash and tone when something is found.</p></div>
      <div class="cap-row reveal"><span class="no">05</span><h3>Instant relay</h3>
        <p>Optional Telegram dispatch sends the photo and location straight to staff phones — the tap on
        the shoulder for invigilators walking the aisles.</p></div>
      <div class="cap-row reveal"><span class="no">06</span><h3>Human in command</h3>
        <p>Admin and invigilator roles. Every alert requires a human confirm or dismiss — the AI flags,
        your people decide. Watch targets are configurable beyond phones.</p></div>
    </div>
  </section>

  <section id="detection">
    <div class="sec-head reveal"><span class="sec-no">02 / DETECTION SEQUENCE</span></div>
    <h2 class="reveal" style="--d:.05s">From glance to evidence<br>in under a second.</h2>
    <div class="timeline reveal" id="tl">
      <div class="t-node"><span class="ts">T+0.00s</span><h3>Frame captured</h3>
        <p>Every camera is sampled continuously — watched or not.</p></div>
      <div class="t-node"><span class="ts">T+0.40s</span><h3>Neural pass</h3>
        <p>Full frame and overlapping zoom tiles scanned by the fine-tuned model.</p></div>
      <div class="t-node alarm"><span class="ts">T+0.90s</span><h3>Alert raised</h3>
        <p>Photo, location, confidence logged. Dashboard, wall and phones notified.</p></div>
      <div class="t-node"><span class="ts">HUMAN</span><h3>Confirm or dismiss</h3>
        <p>An invigilator rules on the alert. The verdict joins the evidence chain.</p></div>
    </div>
  </section>

  <section id="deployment">
    <div class="sec-head reveal"><span class="sec-no">03 / DEPLOYMENT</span></div>
    <h2 class="reveal" style="--d:.05s">One machine. One hour.<br>No IT project.</h2>
    <p class="sec-sub reveal" style="--d:.08s">Built for institutions to trial on their own — no vendor
      on site, no procurement cycle, no integration work. Your exam team can have a real hall under
      watch before lunch.</p>
    <div class="spec">
      <div class="spec-col reveal"><div class="sc-head">SITE REQUIREMENTS</div>
        <div class="spec-row"><span class="k">R1</span><div><b>One computer</b><span>Any modern Mac or Windows PC in the hall or control room.</span></div></div>
        <div class="spec-row"><span class="k">R2</span><div><b>Your existing cameras</b><span>RTSP from the NVR, webcams, or spare phones via a link.</span></div></div>
        <div class="spec-row"><span class="k">R3</span><div><b>No cloud account</b><span>Runs offline. Internet only needed for optional phone alerts.</span></div></div>
        <div class="spec-row"><span class="k">R4</span><div><b>~30 minutes</b><span>From download to a live wall of feeds.</span></div></div>
      </div>
      <div class="spec-col reveal" style="--d:.08s"><div class="sc-head">PILOT PROTOCOL — 10 CAMERAS</div>
        <div class="spec-row"><span class="k">P1</span><div><b>Install</b><span>One download, one double-click, create the admin login.</span></div></div>
        <div class="spec-row"><span class="k">P2</span><div><b>Connect cameras</b><span>Up to 10 feeds is a comfortable single-machine pilot. Tag each location.</span></div></div>
        <div class="spec-row"><span class="k">P3</span><div><b>Run a mock exam</b><span>Invigilators confirm or dismiss each alert as it lands.</span></div></div>
        <div class="spec-row"><span class="k">P4</span><div><b>Review the evidence</b><span>Catches, false alarms per exam, response time — then decide.</span></div></div>
      </div>
    </div>
    <div class="note reveal"><span class="nico"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg></span>
      <span><b>What convinces committees:</b> detections caught vs. missed, false alarms per exam, and whether
      alerts reached invigilators faster than walking the aisles. Vigil logs all three for you.</span></div>
  </section>

  <section id="privacy" class="doctrine">
    <div class="sec-head reveal"><span class="sec-no">04 / PRIVACY DOCTRINE</span></div>
    <h2 class="reveal" style="--d:.05s">Footage never leaves<br>the building. <em>Ever.</em></h2>
    <div class="ledge reveal" style="--d:.1s">
      <div><span class="k">PROCESSING</span><span class="v">ON DEVICE — LOCAL GPU/CPU</span></div>
      <div><span class="k">STORAGE</span><span class="v">LOCAL DISK ONLY</span></div>
      <div><span class="k">INTERNET</span><span class="v">NOT REQUIRED</span></div>
      <div><span class="k">EVIDENCE OWNERSHIP</span><span class="v">YOURS — FULL STOP</span></div>
    </div>
  </section>

  <section id="faq">
    <div class="sec-head reveal"><span class="sec-no">05 / QUESTIONS</span></div>
    <h2 class="reveal" style="--d:.05s">Quick answers.</h2>
    <div class="faq">
      <div class="qa reveal"><button><span class="qno">Q1</span>Does it need an internet connection?<i>+</i></button>
        <div class="a"><p>No. Detection, the dashboard and the evidence log all run locally. Internet is only used
        if you turn on Telegram phone alerts.</p></div></div>
      <div class="qa reveal"><button><span class="qno">Q2</span>Is it only for phones?<i>+</i></button>
        <div class="a"><p>No — phones are the first target. In Settings → "Watch for", pick or type what matters:
        laptop, bag, book, bottle, person and more. Fully custom targets can be added with training.</p></div></div>
      <div class="qa reveal"><button><span class="qno">Q3</span>How many cameras can it watch?<i>+</i></button>
        <div class="a"><p>As many as your computer can decode — every configured camera is monitored all the time,
        whether or not it's on screen. Ten feeds is a comfortable single-machine pilot.</p></div></div>
      <div class="qa reveal"><button><span class="qno">Q4</span>Where is the evidence stored?<i>+</i></button>
        <div class="a"><p>In a local folder and database on the machine running Vigil — photo, time, camera,
        location, confidence and the reviewer's verdict for every alert.</p></div></div>
      <div class="qa reveal"><button><span class="qno">Q5</span>What happens at the moment of detection?<i>+</i></button>
        <div class="a"><p>The dashboard beeps and shows the photo and location; the Display wall flashes an alarm;
        and if enabled, Telegram sends the photo to staff phones — all within about a second.</p></div></div>
    </div>
  </section>

  <section class="final">
    <span class="kicker reveal">DEPLOY VIGIL</span>
    <h2 class="reveal" style="--d:.05s">Put a vigilant eye<br>on every room.</h2>
    <p class="sec-sub reveal" style="--d:.1s">Sign in to your control room, or set Vigil up on the computer in the room you want to watch.</p>
    <div class="ctas reveal" style="--d:.15s">
      <a class="btn btn-grn" href="/login">OPEN THE DASHBOARD</a>
      <a class="btn btn-ghost" href="#deployment">READ THE PILOT PROTOCOL</a>
    </div>
  </section>
</main>

<footer><div class="frow">
  <a class="brand" href="/" style="font-size:14px">__LOGO__<b>Vig<span>i</span>l</b></a>
  <span>/ ON-PREMISE VISION INTELLIGENCE</span>
  <div class="right">
    <a href="#deployment">PILOT</a>
    <a href="/login">SIGN IN</a>
  </div>
</div></footer>

<script>
  // reveal on scroll
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
  }), { threshold:.12 });
  document.querySelectorAll('.reveal:not(.in), .timeline').forEach(el => io.observe(el));

  // header hairline on scroll
  const head = document.getElementById('site-head');
  addEventListener('scroll', () => head.classList.toggle('scrolled', scrollY > 8), { passive:true });

  // live clocks (system bar + evidence frame)
  function tick() {
    const t = new Date().toLocaleTimeString('en-GB');
    const a = document.getElementById('sysclock'), b = document.getElementById('evclock');
    if (a) a.textContent = t; if (b) b.textContent = t;
  }
  tick(); setInterval(tick, 1000);

  // FAQ accordion
  document.querySelectorAll('.qa button').forEach(b => b.onclick = () => {
    const qa = b.parentElement, a = qa.querySelector('.a'), open = qa.classList.contains('open');
    document.querySelectorAll('.qa.open').forEach(o => { o.classList.remove('open'); o.querySelector('.a').style.maxHeight = 0; });
    if (!open) { qa.classList.add('open'); a.style.maxHeight = a.scrollHeight + 'px'; }
  });

  // staged detections on the monitor
  const tiles = [...document.querySelectorAll('.tile')];
  const msList = document.getElementById('ms-list');
  const spots = ['ROW 1 · FRONT','ROW 3 · LEFT','ROW 5 · BACK','CORRIDOR · A'];
  let ti = 1;
  function strike() {
    const i = ti % tiles.length; ti += 2 + (ti % 3);
    const t = tiles[i];
    t.classList.add('hit');
    const card = document.createElement('div');
    card.className = 'ms-card';
    card.innerHTML = `<span class="ph"></span><div><b>PHONE · 0.${88 + (i * 3) % 10}</b><span>${spots[i]}</span></div>`;
    msList.prepend(card);
    while (msList.children.length > 3) msList.lastChild.remove();
    setTimeout(() => t.classList.remove('hit'), 2400);
  }
  setTimeout(strike, 1400);
  setInterval(strike, 4200);

  // gentle parallax tilt on the evidence frame
  if (matchMedia('(pointer:fine)').matches) {
    const mock = document.querySelector('.mock');
    let tx = 0, ty = 0, cxr = 0, cyr = 0, tiltOn = false;
    setTimeout(() => { mock.style.transition = 'none'; tiltOn = true; }, 1400);
    addEventListener('mousemove', e => {
      const r = mock.getBoundingClientRect();
      const inRange = Math.abs(e.clientX - (r.left + r.width/2)) < r.width * 1.1 &&
                      Math.abs(e.clientY - (r.top + r.height/2)) < r.height * 1.4;
      tx = inRange ? ((e.clientX - (r.left + r.width/2)) / r.width) * -3 : 0;
      ty = inRange ? ((e.clientY - (r.top + r.height/2)) / r.height) * 2 : 0;
    }, { passive: true });
    (function tilt() {
      if (tiltOn) {
        cyr += (tx - cyr) * 0.07; cxr += (ty - cxr) * 0.07;
        mock.style.transform = `perspective(1300px) rotateY(${(-cyr).toFixed(2)}deg) rotateX(${cxr.toFixed(2)}deg)`;
      }
      requestAnimationFrame(tilt);
    })();
  }
</script>
</body></html>"""


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
  .auth button { width:100%; background:#3ecf8e; color:#0e1116; border:none; padding:12px;
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
  .save-row button { background:#3ecf8e; color:#0e1116; border:none; padding:11px 24px;
    border-radius:8px; font-weight:700; cursor:pointer; }
  .saved { background:rgba(62,207,142,.15); color:#3ecf8e; font-size:13px; padding:10px 12px; border-radius:8px; margin-bottom:16px; }
  .sec { border-top:1px solid #232a34; margin:22px 0 16px; padding-top:16px; font-size:13px; color:#9aa4b2; font-weight:700; }
</style></head>
<body>
  <header>
    __LOGO__<span class="logo">Vig<span>i</span>l</span>
    <nav class="nav"><a href="/">Live Monitor</a><a href="/evidence">Evidence Log</a><a href="/display">Display</a><a href="/users">Users</a><a href="/settings" class="active">Settings</a></nav>
    <span class="userchip"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>__USERNAME__</span>
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
    if request.query_params.get("watch") == "unknown":
        banner += ('<div class="saved" style="background:rgba(234,179,8,.15);color:#eab308">'
                   "That target isn't something the current models recognise — kept the previous one. "
                   'Custom targets (caps, uniforms, faces…) can be added with fine-tuning.</div>')
    checked = "checked" if g["TILING"] else ""
    body = f"""
      <h2>Detection settings</h2>
      <div class="sub">Accuracy vs. speed. Changes apply live — no restart needed.</div>
      {banner}
      <form method="post" action="/settings">
        <div class="sec" style="margin-top:0">What Vigil watches for</div>
        <div class="field">
          <label>Watch for</label>
          <div class="hint">Pick a preset or type anything the general model knows (80 everyday objects —
          laptop, backpack, book, bottle, umbrella, person…). <b>Phone</b> uses Vigil's fine-tuned exam
          model; other targets switch to the general model automatically. Applies live to every camera.</div>
          <input list="watch-options" name="watch_target" value="{g['WATCH_TARGET']}" style="width:340px" placeholder="phone">
          <datalist id="watch-options">
            <option value="phone"></option><option value="laptop"></option>
            <option value="backpack"></option><option value="handbag"></option>
            <option value="book"></option><option value="bottle"></option>
            <option value="umbrella"></option><option value="person"></option>
            <option value="knife"></option><option value="scissors"></option>
          </datalist>
        </div>

        <div class="sec">Detection tuning</div>
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
    watch_target: str = Form("phone"),
):
    old_model = MODEL_NAME
    old_watch = WATCH_TARGET
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
        "WATCH_TARGET": (watch_target.strip().lower() or "phone"),
    })
    if MODEL_NAME != old_model:
        try:
            reload_model()
        except Exception:
            save_settings({"MODEL_NAME": old_model})       # bad model -> revert
    watch_flag = ""
    try:
        if not apply_watch_target():                       # unknown target -> revert
            save_settings({"WATCH_TARGET": old_watch})
            apply_watch_target()
            watch_flag = "&watch=unknown"
    except Exception:
        save_settings({"WATCH_TARGET": old_watch})
        watch_flag = "&watch=unknown"
    return RedirectResponse(f"/settings?saved=1{watch_flag}", status_code=303)


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
# ---- Display / Live Monitoring wall (for showing on a screen) -------------
DISPLAY_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — Live Monitoring</title>__STYLE__
<style>
  body { overflow:hidden; }
  .disp-head { display:flex; align-items:center; gap:16px; padding:12px 22px;
    background:#0b0e12; border-bottom:1px solid #232a34; }
  .disp-title { font-size:12px; letter-spacing:2.5px; text-transform:uppercase; color:#9aa4b2; }
  .disp-online { margin-left:auto; font-size:13px; color:#9aa4b2; }
  .disp-online b { color:#3ecf8e; font-size:15px; }
  .disp-clock { font-size:13px; color:#9aa4b2; font-variant-numeric:tabular-nums; }
  .disp-btn { background:#1c222b; color:#c4ccd8; border:1px solid #2b3340; padding:7px 13px;
    border-radius:8px; font-size:13px; text-decoration:none; cursor:pointer; }
  .disp-btn:hover { color:#fff; border-color:#3a4557; }
  .wall { flex:1; display:grid; gap:8px; padding:9px; background:#000; min-height:0; }
  .tile { position:relative; background:#0a0d11; border-radius:10px; overflow:hidden;
    display:flex; align-items:center; justify-content:center; border:1px solid #1a2028; }
  .tile img { width:100%; height:100%; object-fit:contain; }
  .tile .label { position:absolute; left:10px; bottom:10px; display:flex; align-items:center; gap:8px;
    background:rgba(8,11,15,.75); padding:6px 12px; border-radius:20px; font-size:13px; font-weight:600; }
  .tile .sdot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
  .tile .sdot.online { background:#3ecf8e; box-shadow:0 0 8px #3ecf8e; }
  .tile .sdot.offline { background:#7a8595; }
  .wall-empty { grid-column:1/-1; align-self:center; justify-self:center; color:#5b6675; text-align:center; }
  .flash { position:fixed; inset:0; pointer-events:none; z-index:90; box-shadow: inset 0 0 0 0 rgba(239,68,68,0);
    transition: box-shadow .25s; }
  .flash.on { box-shadow: inset 0 0 140px 10px rgba(239,68,68,.5); }
  .pop { position:fixed; top:78px; left:50%; transform:translate(-50%,-160%);
    display:flex; align-items:center; gap:16px; background:#1b1512; border:1px solid #ef4444;
    box-shadow:0 16px 50px rgba(239,68,68,.4); border-radius:16px; padding:14px 22px 14px 14px;
    z-index:100; opacity:0; visibility:hidden; max-width:92vw;
    transition: transform .4s cubic-bezier(.2,.9,.3,1.25), opacity .3s, visibility .3s; }
  .pop.show { transform:translate(-50%,0); opacity:1; visibility:visible; }
  .pop img { width:66px; height:84px; object-fit:cover; border-radius:9px; background:#000; flex-shrink:0; }
  .pop .big { font-size:18px; font-weight:800; color:#fff; letter-spacing:.3px; }
  .pop .meta { font-size:13.5px; color:#f2b6b6; margin-top:4px; }
</style></head>
<body>
  <div class="disp-head">
    <span class="brand">__LOGO__<span class="logo">Vig<span>i</span>l</span></span>
    <span class="disp-title">Live Monitoring</span>
    <span class="disp-online" id="online">–</span>
    <span class="disp-clock" id="clock"></span>
    <button class="disp-btn" onclick="fs()">⤢ Fullscreen</button>
    <a class="disp-btn" href="/">Exit</a>
  </div>
  <div class="wall" id="wall"></div>
  <div class="flash" id="flash"></div>
  <div class="pop" id="pop">
    <img id="pop-img" alt="">
    <div><div class="big" id="pop-title">Phone detected</div><div class="meta" id="pop-meta"></div></div>
  </div>
  <script>
    const $ = id => document.getElementById(id);
    function fs(){ if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen().catch(()=>{}); }
    setInterval(()=>{ $('clock').textContent = new Date().toLocaleTimeString(); }, 1000);

    async function loadWall() {
      let cams = [];
      try { cams = await (await fetch('/cameras')).json(); } catch(e){ return; }
      const wall = $('wall');
      if (!cams.length) { wall.innerHTML = '<div class="wall-empty">No cameras configured yet.</div>'; return; }
      const cols = Math.ceil(Math.sqrt(cams.length));
      const rows = Math.ceil(cams.length / cols);
      wall.style.gridTemplateColumns = 'repeat(' + cols + ', 1fr)';
      wall.style.gridTemplateRows = 'repeat(' + rows + ', 1fr)';
      wall.innerHTML = cams.map(c => {
        const place = (c.location && c.location.trim()) ? c.location : c.label;
        return '<div class="tile"><img class="wsnap" data-cam="' + c.id + '">' +
               '<span class="label"><span class="sdot offline" data-cam="' + c.id + '"></span>' + place + '</span></div>';
      }).join('');
    }
    function refreshSnaps() {
      document.querySelectorAll('img.wsnap').forEach(img => {
        fetch('/snapshot/' + img.dataset.cam + '?t=' + Date.now())
          .then(r => r.ok ? r.blob() : null).then(b => {
            if (!b) return; const u = URL.createObjectURL(b); const p = img.dataset.url;
            img.src = u; img.dataset.url = u; if (p) URL.revokeObjectURL(p);
          }).catch(()=>{});
      });
    }
    async function refreshStatus() {
      let st = {}; try { st = await (await fetch('/camera_status')).json(); } catch(e){ return; }
      let on = 0, tot = 0;
      document.querySelectorAll('.sdot').forEach(d => {
        tot++; const online = st[d.dataset.cam] === 'online'; if (online) on++;
        d.classList.toggle('online', online); d.classList.toggle('offline', !online);
      });
      $('online').innerHTML = '<b>' + on + '</b> / ' + tot + ' cameras online';
    }

    let lastId = 0, first = true, popTimer = null;
    function beep(){ try { const c = new (window.AudioContext||window.webkitAudioContext)();
      const o = c.createOscillator(), g = c.createGain(); o.connect(g); g.connect(c.destination);
      o.type='sine'; o.frequency.value=880; g.gain.value=.12; o.start(); o.stop(c.currentTime+.25);
      } catch(e){} }
    function showPop(a) {
      $('pop-img').src = a.image;
      $('pop-title').textContent = '🚨 ' + (a.thing || 'Phone') + ' detected · ' + Math.round(a.confidence*100) + '%';
      $('pop-meta').textContent = '📍 ' + a.camera + '     ·     ' + a.time;
      $('pop').classList.add('show'); $('flash').classList.add('on'); beep();
      setTimeout(()=>$('flash').classList.remove('on'), 800);
      clearTimeout(popTimer);
      popTimer = setTimeout(()=>$('pop').classList.remove('show'), 6500);
    }
    async function pollAlerts() {
      let data = []; try { data = await (await fetch('/alerts')).json(); } catch(e){ return; }
      if (data.length) {
        const newest = data[0];
        if (!first && newest.id > lastId && newest.status === 'pending') showPop(newest);
        lastId = Math.max(lastId, newest.id);
      }
      first = false;
    }

    loadWall().then(refreshStatus);
    setInterval(refreshSnaps, 33);
    setInterval(refreshStatus, 1500);
    setInterval(pollAlerts, 1500);
    pollAlerts();
  </script>
</body></html>"""


@app.get("/display", response_class=HTMLResponse)
def display_page():
    return DISPLAY_HTML.replace("__STYLE__", STYLE).replace("__LOGO__", LOGO_MARK)


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
