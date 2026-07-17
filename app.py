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
import sys

# Quiet OpenCV/FFmpeg so a disconnected camera doesn't flood the terminal.
# (must be set before cv2 is imported)
os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
# Bound network I/O so a dead IP camera's open/read can't hang forever (which
# would hold the capture lock and stall other cameras). 5s, in microseconds;
# prefer TCP for RTSP so half-open streams fail cleanly.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|timeout;5000000")

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
import queue
from datetime import datetime

import cv2
import numpy as np
from ultralytics import YOLO
import vlm                                   # optional AI "second look" (Ollama)
from fastapi import FastAPI, Response, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from fastapi.responses import (StreamingResponse, HTMLResponse, FileResponse,
                               RedirectResponse, JSONResponse)

try:
    cv2.setLogLevel(0)     # extra-quiet OpenCV (belt and braces with the env vars above)
except Exception:
    pass

# OpenCV's FFmpeg backend is NOT thread-safe when a capture is opened or torn
# down while ANOTHER capture is being read: the open/close mutates FFmpeg's
# global av_option/registration state that the concurrent read walks, and it
# segfaults in av_opt_find2 (seen when an IP camera is added while other feeds
# are live). A single global lock on opens alone is not enough — a read on one
# camera still races an open on another. So we use a read/write lock: frame
# grabs are shared READERS (run concurrently with each other); opening or
# releasing a capture is an exclusive WRITER that briefly pauses all reads.
# Opens/closes are rare, so reads only stall for a moment.
class _CaptureRWLock:
    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False
        self._writers_waiting = 0          # writer priority: opens never starve

    def acquire_read(self):
        with self._cond:
            while self._writer or self._writers_waiting > 0:
                self._cond.wait()
            self._readers += 1

    def release_read(self):
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def acquire_write(self):
        with self._cond:
            self._writers_waiting += 1
            while self._writer or self._readers > 0:
                self._cond.wait()
            self._writers_waiting -= 1
            self._writer = True

    def release_write(self):
        with self._cond:
            self._writer = False
            self._cond.notify_all()


_capture_lock = _CaptureRWLock()


class MJPEGCapture:
    """Pure-Python MJPEG-over-HTTP reader (IP Webcam app, most MJPEG cameras).
    A drop-in stand-in for cv2.VideoCapture, used when FFmpeg can't open an
    http(s) source — FFmpeg is picky about multipart streams; this isn't."""
    CHUNK = 16384

    def __init__(self, url):
        self.url = url
        self._resp = None
        self._buf = b""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Vigil"})
            self._resp = urllib.request.urlopen(req, timeout=2.5)   # dead camera fails fast
            ctype = self._resp.headers.get("Content-Type", "")
            if "multipart" not in ctype and "image" not in ctype:
                self._resp.close()
                self._resp = None
        except Exception:
            self._resp = None

    def isOpened(self):
        return self._resp is not None

    def read(self):
        if self._resp is None:
            return False, None
        try:
            # Scan the byte stream for a complete JPEG (SOI .. EOI) — this works
            # with any multipart framing without parsing part headers.
            for _ in range(400):                        # hard cap ≈ 6 MB per frame
                soi = self._buf.find(b"\xff\xd8")
                eoi = self._buf.find(b"\xff\xd9", soi + 2) if soi != -1 else -1
                if soi != -1 and eoi != -1:
                    jpg = self._buf[soi:eoi + 2]
                    self._buf = self._buf[eoi + 2:]
                    frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        continue                        # corrupt part — keep scanning
                    return True, frame
                chunk = self._resp.read(self.CHUNK)
                if not chunk:
                    break
                self._buf += chunk
                if len(self._buf) > 8_000_000:          # runaway garbage — bail out
                    break
        except Exception:
            pass
        self.release()
        return False, None

    def release(self):
        if self._resp is not None:
            try:
                self._resp.close()
            except Exception:
                pass
            self._resp = None

    def set(self, *a, **k):                             # VideoCapture API no-op
        return False


def _ffmpeg_options_for(src):
    """Per-protocol FFmpeg options. The old global env var applied RTSP options
    to every URL — harmless for RTSP, but it broke some HTTP (IP Webcam) opens."""
    if isinstance(src, str) and src.startswith("rtsp"):
        return "rtsp_transport;tcp|stimeout;2500000|timeout;2500000"
    return "timeout;2500000"


def open_capture(src):
    """Open a capture as an exclusive writer (no reads run during it).
    Webcam index -> AVFoundation; URLs -> FFmpeg; http(s) MJPEG -> Python fallback."""
    _capture_lock.acquire_write()
    try:
        if isinstance(src, str):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _ffmpeg_options_for(src)
            cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(src)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # don't queue stale frames
        except Exception:
            pass
        # FFmpeg couldn't open an http(s) source (typical for the IP Webcam app's
        # multipart stream). Try the tolerant Python MJPEG reader, and also the
        # app's usual paths if the user pasted the bare address.
        if isinstance(src, str) and src.startswith(("http://", "https://")) and not cap.isOpened():
            cap.release()
            candidates = [src]
            bare = src.rstrip("/")
            if not bare.endswith(("/video", "/videofeed", "/mjpeg", "/stream")):
                candidates += [bare + "/video", bare + "/videofeed"]
            for url in candidates:
                mj = MJPEGCapture(url)
                if mj.isOpened():
                    return mj
            return MJPEGCapture(src)                # dead handle; reader will retry
        return cap
    finally:
        _capture_lock.release_write()


def read_capture(cap, ffmpeg=True):
    """Grab a frame. Only real FFmpeg cv2 captures walk the fragile global
    av_option state, so ONLY they take the read lock (and thus wait during
    another camera's open). Webcams (AVFoundation) and the pure-Python
    MJPEGCapture never touch that state — they read WITHOUT the lock, so a dead
    network camera reconnecting can never freeze a live webcam. This was the
    '3-second freeze' bug: one offline camera stalled every live feed."""
    if not ffmpeg or isinstance(cap, MJPEGCapture):
        return cap.read()
    _capture_lock.acquire_read()
    try:
        return cap.read()
    finally:
        _capture_lock.release_read()


def release_capture(cap):
    """Tear a capture down as an exclusive writer (no reads run during it)."""
    if cap is None:
        return
    _capture_lock.acquire_write()
    try:
        cap.release()
    finally:
        _capture_lock.release_write()


def _prewarm_ffmpeg():
    """Trigger OpenCV's one-time global FFmpeg registration NOW, at startup on the
    main thread, before any camera threads exist — so it can never fire mid-read."""
    try:
        _capture_lock.acquire_write()
        try:
            cv2.VideoCapture("vigil://prewarm", cv2.CAP_FFMPEG).release()
        finally:
            _capture_lock.release_write()
    except Exception:
        pass


_prewarm_ffmpeg()


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

# Writable data lives in VIGIL_DATA_DIR when set (used by the packaged desktop
# app, which can't write inside its own read-only bundle). Defaults to "." so
# running from source behaves exactly as before.
_DATA_DIR      = os.environ.get("VIGIL_DATA_DIR", "").strip() or "."
os.makedirs(_DATA_DIR, exist_ok=True)
DB_PATH        = os.path.join(_DATA_DIR, "evidence.db")
EVIDENCE_DIR   = os.path.join(_DATA_DIR, "evidence")
CAMERAS_CONFIG = os.path.join(_DATA_DIR, "cameras.json")

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

# --- AI "second look" (optional) -------------------------------------------
# After YOLO flags an alert, a LOCAL vision model (via Ollama) looks at the photo
# to (1) write a plain-English description and (2) drop obvious false alarms.
# Off by default so installs without Ollama are unaffected. Turn on in Settings.
VLM_ENABLED = False          # master switch for the AI second look
VLM_MODEL   = "llava"        # Ollama vision model: llava · moondream · qwen2.5vl
VLM_VERIFY  = True           # also DROP alerts the AI says aren't the target (#3)

# Google Sign-In — baked in so every download shows a working "Sign in with
# Google" button with ZERO setup. A web client ID is public by design (it ships
# in the page anyway), so embedding it is safe. Self-hosters on their own domain
# can override with the GOOGLE_CLIENT_ID env var. NOTE: Google only trusts
# localhost/127.0.0.1 origins for a local app — so the button works on the Vigil
# computer, and phones/other devices use password login (that's why both exist).
GOOGLE_CLIENT_ID = os.getenv(
    "GOOGLE_CLIENT_ID",
    "260397873178-9nba8p04abo4vmnnthtd82dfkp97t3lo.apps.googleusercontent.com")

SETTINGS_FILE = "settings.json"
TUNABLE = ["MODEL_NAME", "CONFIDENCE", "REQUIRED_HITS", "ALERT_COOLDOWN", "IMG_SIZE",
           "TILING", "TILE_COLS", "TILE_ROWS", "TILE_OVERLAP", "TILE_IMGSZ",
           "TELEGRAM_TOKEN", "TELEGRAM_CHAT_IDS", "WATCH_TARGET",
           "VLM_ENABLED", "VLM_MODEL", "VLM_VERIFY"]


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


def _sync_vlm():
    """Push the current VLM_* settings into the vlm module (startup + on save)."""
    g = globals()
    vlm.configure(enabled=g["VLM_ENABLED"], model=g["VLM_MODEL"], verify=g["VLM_VERIFY"])


_apply_saved_settings()
_apply_env_settings()
_sync_vlm()

# Public HTTPS address other networks can reach Vigil at — set by the tunnel
# launcher (Vigil-Public), e.g. https://xxxx.trycloudflare.com. It lets you hand
# a camera link to someone who is NOT on your Wi-Fi: their phone/laptop opens the
# link, allows its camera, and streams into your wall — no app install. Detection
# still runs here, locally; the tunnel only relays the connection. Blank = camera
# links use whatever address the browser is already on (same-network only).
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

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
                # Collapse exact duplicates (same label+location+source). Repeated
                # "add webcam" clicks while it looked broken piled up identical
                # entries that then fought over the device.
                seen, out = set(), []
                for c in data:
                    key = (c.get("label"), c.get("location", ""), c.get("source"))
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(c)
                return out
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


def _prewarm_webcam():
    """macOS: the camera-permission dialog can ONLY be shown from the main
    thread — Vigil's camera threads can never trigger it, so the webcam
    silently failed on machines that hadn't granted permission yet. Opening
    the webcam once HERE (import runs on the main thread) makes macOS ask
    properly; after that, background opens are authorized and just work."""
    if sys.platform != "darwin":
        return
    if not any(c.get("source", "").isdigit() for c in cameras):
        return
    try:
        cap = cv2.VideoCapture(0)
        cap.release()
    except Exception:
        pass


_prewarm_webcam()


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


def _camera_enabled(cam_id):
    """Paused cameras keep ALL their details but don't connect or detect —
    so 50 exam cameras don't auto-start tomorrow when there's no exam."""
    with cameras_lock:
        for c in cameras:
            if c["id"] == cam_id:
                return c.get("enabled", True)
    return False


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
        # v1.3: Google Sign-In — google accounts have an email and no password
        for stmt in ("ALTER TABLE users ADD COLUMN email TEXT",
                     "ALTER TABLE users ADD COLUMN auth TEXT DEFAULT 'password'"):
            try:
                c.execute(stmt)
            except sqlite3.OperationalError:
                pass
        # v1.4: audit trail — WHO confirmed/dismissed each alert, and when
        for stmt in ("ALTER TABLE alerts ADD COLUMN reviewed_by TEXT DEFAULT ''",
                     "ALTER TABLE alerts ADD COLUMN reviewed_at TEXT DEFAULT ''"):
            try:
                c.execute(stmt)
            except sqlite3.OperationalError:
                pass
        # v1.2: AI second-look description (older installs get the column added here)
        try:
            c.execute("ALTER TABLE alerts ADD COLUMN description TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass


def _store_alert(jpg_bytes, confidence, camera, status="pending", dt=None, thing="Phone",
                 description=""):
    dt = dt or datetime.now()
    with _db() as c:
        cur = c.execute(
            "INSERT INTO alerts (created_at, date, time, confidence, camera, image_file, status, thing, description)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (dt.isoformat(), dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S"),
             round(confidence, 2), camera, "", status, thing, description or ""))
        alert_id = cur.lastrowid
        fname = os.path.join(EVIDENCE_DIR, f"alert_{alert_id}_{dt.strftime('%Y%m%d_%H%M%S')}.jpg")
        with open(fname, "wb") as f:
            f.write(jpg_bytes)
        c.execute("UPDATE alerts SET image_file = ? WHERE id = ?", (fname, alert_id))
    return alert_id


def _set_alert_description(alert_id, description):
    with _db() as c:
        c.execute("UPDATE alerts SET description = ? WHERE id = ?", (description or "", alert_id))


def _delete_alert(alert_id):
    """Remove an alert the AI vetoed as a false positive (row + its photo)."""
    with _db() as c:
        row = c.execute("SELECT image_file FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        c.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    if row and row["image_file"]:
        try:
            os.remove(row["image_file"])
        except OSError:
            pass


def _row_to_dict(r):
    try:
        thing = r["thing"] or "Phone"
    except (IndexError, KeyError):
        thing = "Phone"
    try:
        description = r["description"] or ""
    except (IndexError, KeyError):
        description = ""
    try:
        reviewed_by, reviewed_at = r["reviewed_by"] or "", r["reviewed_at"] or ""
    except (IndexError, KeyError):
        reviewed_by, reviewed_at = "", ""
    return {
        "id": r["id"], "time": r["time"], "date": r["date"],
        "confidence": r["confidence"], "camera": r["camera"],
        "status": r["status"], "image": f"/evidence/image/{r['id']}",
        "thing": thing, "description": description,
        "reviewed_by": reviewed_by, "reviewed_at": reviewed_at,
    }


init_db()


# ---------------------------------------------------------------------------
# ACCOUNTS & LOGIN
# ---------------------------------------------------------------------------
SECRET_FILE = os.path.join(_DATA_DIR, "secret.key")


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
        rows = c.execute("SELECT username, role, created_at, auth FROM users ORDER BY id").fetchall()
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


def create_google_user(email, role="invigilator"):
    """A Google account: the email IS the identity — no password stored."""
    email = email.strip().lower()
    if "@" not in email:
        return False, "That doesn't look like an email address."
    try:
        with _db() as c:
            c.execute("INSERT INTO users (username, pw_hash, salt, role, created_at, email, auth)"
                      " VALUES (?,?,?,?,?,?,?)",
                      (email, None, None, role, datetime.now().isoformat(), email, "google"))
        return True, None
    except sqlite3.IntegrityError:
        return False, "That account already exists."


def find_user_by_email(email):
    email = (email or "").strip().lower()
    with _db() as c:
        row = c.execute("SELECT username, role FROM users WHERE lower(email) = ? OR lower(username) = ?",
                        (email, email)).fetchone()
    return {"username": row["username"], "role": row["role"]} if row else None


def verify_user(username, password):
    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if not row or not row["pw_hash"] or not row["salt"]:   # google accounts have no password
        return None
    if _hash_pw(password, row["salt"]) == row["pw_hash"]:
        return {"username": row["username"], "role": row["role"]}
    return None


def verify_google_token(credential):
    """Check a Google ID token with Google and return its claims, or None.
    Server-side verification — the browser can't be trusted to say who it is."""
    try:
        url = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(credential)
        with urllib.request.urlopen(url, timeout=10) as r:
            claims = json.loads(r.read().decode())
    except Exception:
        return None
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        return None                                        # not actually issued by Google
    if claims.get("aud") != GOOGLE_CLIENT_ID:              # token minted for another app
        return None
    if claims.get("email_verified") not in (True, "true"):
        return None
    return claims


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


def _alert_caption(thing, confidence, camera_label, description=""):
    caption = (f"🚨 {thing} detected · {round(confidence * 100)}%\n"
               f"📍 {camera_label}\n🕐 {datetime.now().strftime('%H:%M:%S')}")
    if description:
        caption += f"\n👁 {description}"
    return caption


# --- AI review queue: the vision model runs HERE, on its own thread, so it never
#     blocks detection or the video pipeline (that was the source of the lag). The
#     alert is saved instantly; the worker then fills in the description and drops
#     false positives a moment later. One worker = the model runs one-at-a-time,
#     so it can't pile up and saturate the GPU. -------------------------------
_vlm_queue = queue.Queue(maxsize=64)


def _vlm_worker():
    while True:
        try:
            alert_id, ctx_jpg, photo_jpg, confidence, camera_label, thing = _vlm_queue.get()
        except Exception:
            continue
        try:
            verdict = vlm.describe_and_verify(ctx_jpg, thing)
            if verdict and verdict.get("present") is False:
                _delete_alert(alert_id)            # false positive — remove it
                print(f"[vlm] alert #{alert_id} vetoed on {camera_label}: no {thing}")
                continue
            description = (verdict or {}).get("description", "") or ""
            if description:
                _set_alert_description(alert_id, description)
            send_telegram_alert(photo_jpg, _alert_caption(thing, confidence, camera_label, description))
        except Exception as e:
            print(f"[vlm] worker error on #{alert_id}: {type(e).__name__}: {e}")


threading.Thread(target=_vlm_worker, daemon=True).start()


def maybe_add_alert(crop, confidence, camera_label, camera_id, context=None):
    now = time.time()
    with _cooldown_lock:
        if now - _last_alert_time.get(camera_id, 0) < ALERT_COOLDOWN or crop.size == 0:
            return
        _last_alert_time[camera_id] = now
    ok, buf = cv2.imencode(".jpg", crop)
    if not ok:
        return
    jpg = buf.tobytes()
    thing = TARGET_NAME

    # Save immediately so the alert shows with ZERO delay — the video never waits
    # on the AI. Description starts empty and gets filled in by the worker.
    alert_id = _store_alert(jpg, confidence, camera_label, status="pending",
                            thing=thing, description="")

    if vlm.is_enabled():
        # Hand the heavy review to the background worker. Send the WIDER context
        # frame (whole scene), not the tight crop — the model describes a scene
        # reliably but returns nothing on a cropped-in phone.
        ctx = context if (context is not None and getattr(context, "size", 0)) else crop
        okc, cbuf = cv2.imencode(".jpg", ctx)
        try:
            _vlm_queue.put_nowait((alert_id, cbuf.tobytes() if okc else jpg, jpg,
                                   confidence, camera_label, thing))
            return                                 # worker will Telegram (with description)
        except queue.Full:
            pass                                   # backed up — fall through to Telegram now
    send_telegram_alert(jpg, _alert_caption(thing, confidence, camera_label))


def _placeholder(text):
    img = np.full((480, 640, 3), 32, dtype=np.uint8)
    lines = text.split("\n")
    y = 240 - (len(lines) - 1) * 16
    for line in lines:
        cv2.putText(img, line, (30, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (170, 170, 170), 2)
        y += 32
    return img


# --- Background camera reader: always keeps the NEWEST frame (low latency) ---
class CameraStream:
    """Reads a camera in its own thread and holds only the latest frame, so the
    viewer never falls behind the live action (no lag build-up)."""
    def __init__(self, source):
        self.source = source
        # Webcams (AVFoundation) don't share FFmpeg's fragile global state, so
        # their reads skip the capture lock and never wait on another camera's
        # open — a dead network camera can't freeze the live webcam.
        self.is_ffmpeg = not str(source).isdigit()
        self.frame = None
        self.running = True
        self.lock = threading.Lock()
        self.cap = None
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _open(self):
        return open_capture(_resolve_source(self.source))   # serialised FFmpeg open

    def _reader(self):
        self.cap = self._open()                     # open IN this thread (thread-safe)
        fails = 0
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(min(15.0, 1.0 + 2.0 * fails))    # back off a dead camera fast
                fails += 1
                self.cap = self._open()
                continue
            ok, f = read_capture(self.cap, ffmpeg=self.is_ffmpeg)
            if not ok:                                  # stream dropped / camera off
                fails += 1
                with self.lock:
                    self.frame = None
                release_capture(self.cap)               # exclusive: pauses FFmpeg reads
                time.sleep(min(15.0, 2.0 * fails))      # back off hard — a dead camera retries rarely
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
            release_capture(self.cap)               # exclusive: pauses reads
        except Exception:
            pass


streams = {}                       # source -> {"stream": CameraStream, "refs": set(camera_ids)}
streams_lock = threading.Lock()


def _get_stream(camera_id, source):
    """One shared CameraStream per SOURCE. Ten tiles showing webcam '0' used to
    open the device ten times — macOS gives the device to one handle and the
    rest show nothing. Now they all read the same stream."""
    with streams_lock:
        # drop this camera from any other source it used to point at
        for src, entry in list(streams.items()):
            if src != source and camera_id in entry["refs"]:
                entry["refs"].discard(camera_id)
                if not entry["refs"]:
                    entry["stream"].stop()
                    del streams[src]
        entry = streams.get(source)
        if entry is None:
            entry = {"stream": CameraStream(source), "refs": set()}
            streams[source] = entry
        entry["refs"].add(camera_id)
        return entry["stream"]


def _release_stream(camera_id):
    """Detach a camera from its shared stream; stop the stream when unused."""
    with streams_lock:
        for src, entry in list(streams.items()):
            if camera_id in entry["refs"]:
                entry["refs"].discard(camera_id)
                if not entry["refs"]:
                    entry["stream"].stop()
                    del streams[src]


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
                    maybe_add_alert(frame[y1:y2, x1:x2].copy(), cf, label, self.camera_id,
                                    context=frame)
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
snapshots_cond = threading.Condition(snapshots_lock)   # wakes /stream pushers
snapshot_seq = {}                  # camera_id -> monotonically increasing frame no.


def _store_snapshot(camera_id, jpg_bytes):
    """Publish a camera's newest frame and wake every live /stream connection."""
    with snapshots_cond:
        snapshots[camera_id] = jpg_bytes
        snapshot_seq[camera_id] = snapshot_seq.get(camera_id, 0) + 1
        snapshots_cond.notify_all()
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
        last_browser_seq = -1
        was_paused = False
        while self.running:
            source, label = _find_camera(self.camera_id)
            if source is None:                          # camera removed
                break

            # Paused: release the camera/network connection, skip detection, and
            # idle cheaply. All details stay saved; resume picks up instantly.
            if not _camera_enabled(self.camera_id):
                if not was_paused:
                    _release_stream(self.camera_id)
                    with status_lock:
                        camera_status[self.camera_id] = "paused"
                    ok, buf = cv2.imencode(".jpg", _placeholder("Paused\nPress the play button to resume"),
                                           [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                    if ok:
                        _store_snapshot(self.camera_id, buf.tobytes())
                    was_paused = True
                time.sleep(0.3)
                continue
            was_paused = False

            is_webcam = source.isdigit()
            is_browser = source == "browser"

            if is_browser:
                # Frames are pushed by a device's browser via POST/WS /push/<id>
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
                        _store_snapshot(self.camera_id, buf.tobytes())
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
                    _store_snapshot(self.camera_id, buf.tobytes())
                time.sleep(0.02)                        # ~50fps re-emit so the wall keeps up
                continue

            # Webcams and URL cameras both read the SHARED stream for their source,
            # so any number of tiles can show the same device without fighting over it.
            frame = _get_stream(self.camera_id, source).read()

            if frame is None:
                with status_lock:
                    camera_status[self.camera_id] = "offline"
                if is_webcam:
                    msg = "Webcam not available\nCheck System Settings >\nPrivacy & Security > Camera"
                else:
                    msg = "Connecting to camera..."
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
                _store_snapshot(self.camera_id, buf.tobytes())
            time.sleep(0.008)   # run near the camera's native frame rate (~30fps); no disk cost

        # cleanup when the camera is removed or stopped
        _release_stream(self.camera_id)
        with detectors_lock:
            d = detectors.pop(self.camera_id, None)
        if d is not None:
            d.stop()
        with snapshots_cond:
            snapshots.pop(self.camera_id, None)
            snapshot_seq.pop(self.camera_id, None)
            snapshots_cond.notify_all()          # let /stream connections notice removal
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
_PUBLIC = {"/login", "/setup", "/logout", "/favicon.svg", "/auth/google"}
# API paths that should return 401 (not redirect) when not authed
_API_PREFIXES = ("/alerts", "/cameras", "/evidence/list", "/evidence/image", "/snapshot", "/stream", "/camera_status", "/push", "/api")


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path

    # First run: no accounts yet -> force the create-admin setup page
    # (/auth/google stays reachable so "Sign in with Google" can bootstrap the admin)
    if user_count() == 0:
        if path == "/setup" or path == "/auth/google":
            return await call_next(request)
        return RedirectResponse("/setup")

    if path in _PUBLIC:
        return await call_next(request)

    user = current_user(request)
    if not user:
        if path == "/":   # visitors get the public website; the app stays behind login
            return HTMLResponse(LANDING_HTML.replace("__LOGO__", LOGO_MARK))
        # Shared device-camera links work with NO account — that's the whole point
        # of handing someone off your network a link. The camera id is an
        # unguessable token, so we allow ONLY the sender page and its frame upload,
        # and ONLY when the id maps to a real browser camera. Anything else still
        # needs login. (Order matters: this must run before the /push 401 below.)
        if path.startswith("/sender/") or path.startswith("/push/"):
            cam_id = path.split("/", 2)[2] if path.count("/") >= 2 else ""
            src, _ = _find_camera(cam_id)
            if src == "browser":
                return await call_next(request)
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


# Security response headers on every response. Added after auth_gate, so it is
# the OUTERMOST middleware and stamps headers even on the auth gate's early
# returns (redirects, 401s). CSP keeps 'unsafe-inline' because the UI relies on
# inline styles/handlers, but still blocks arbitrary external script/resource
# loads; the allow-listed origins are only what Google Sign-In and the landing
# fonts need.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://accounts.google.com https://apis.google.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "connect-src 'self' https://accounts.google.com https://oauth2.googleapis.com; "
    "frame-src https://accounts.google.com; "
    "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    h.setdefault("Content-Security-Policy", _CSP)
    return resp


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


@app.get("/stream/{camera_id}")
def stream(camera_id: str):
    """Live MJPEG stream — ONE persistent connection that pushes each new frame
    the instant it exists, instead of the dashboard fetching 30 snapshots/sec
    per camera. This is what makes the wall smooth over WiFi and tunnels."""
    _get_producer(camera_id)                            # make sure it's running

    def gen():
        last = -1
        while True:
            with snapshots_cond:
                if snapshot_seq.get(camera_id, 0) == last:
                    snapshots_cond.wait(timeout=1.0)
                data = snapshots.get(camera_id)
                seq = snapshot_seq.get(camera_id, 0)
            if data is None or seq == last:             # timed out with nothing new
                if _find_camera(camera_id)[0] is None:  # camera was removed
                    return
                continue
            last = seq
            yield (b"--vigilframe\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=vigilframe",
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
    # The sender pipelines several uploads at once, so a slower one can arrive
    # after a newer frame. X-Seq is the sender's monotonic frame number — decode
    # and store only if it's newer than what we already hold, so live view and
    # detection never step backwards to an older frame.
    try:
        seq = int(request.headers.get("X-Seq", "0"))
    except ValueError:
        seq = 0
    if seq:
        with browser_frames_lock:
            prev = browser_frames.get(camera_id)
        if prev is not None and prev[1] >= seq:
            return {"ok": True, "stale": True}
    frame = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return JSONResponse({"error": "bad frame"}, status_code=400)
    with browser_frames_lock:
        prev = browser_frames.get(camera_id)
        if seq and prev is not None and prev[1] >= seq:   # a newer frame won the race
            return {"ok": True, "stale": True}
        browser_frames[camera_id] = (frame, seq if seq else next(_push_seq), time.time())
    _get_producer(camera_id)
    return {"ok": True}


@app.websocket("/ws/push/{camera_id}")
async def ws_push(camera_id: str, ws: WebSocket):
    """Sender pages push JPEG frames over ONE WebSocket instead of a POST per
    frame — far less per-frame overhead, which is most of the shared-link lag.
    Auth mirrors /push: the unguessable id must map to a real browser camera
    (the HTTP auth middleware doesn't run for websockets)."""
    if _find_camera(camera_id)[0] != "browser":
        await ws.close(code=4404)
        return
    await ws.accept()
    try:
        while True:
            body = await ws.receive_bytes()
            if not body or len(body) > 3_000_000:
                continue
            if _find_camera(camera_id)[0] != "browser":     # camera removed mid-stream
                break
            frame = await run_in_threadpool(
                cv2.imdecode, np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            # WebSocket messages arrive in order, so the server's own counter is
            # a valid monotonic sequence — no X-Seq dance needed.
            with browser_frames_lock:
                browser_frames[camera_id] = (frame, next(_push_seq), time.time())
            _get_producer(camera_id)
    except (WebSocketDisconnect, RuntimeError):
        pass


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
                if "enabled" in payload:
                    c["enabled"] = bool(payload["enabled"])
                _save_cameras()
                return c
    return {"ok": False}


@app.post("/cameras/pause_all")
def pause_all_cameras():
    """After the exams: one click parks every camera (details kept) so nothing
    auto-connects or detects until you resume. Survives restarts."""
    with cameras_lock:
        for c in cameras:
            c["enabled"] = False
        _save_cameras()
        return list(cameras)


@app.post("/cameras/resume_all")
def resume_all_cameras():
    with cameras_lock:
        for c in cameras:
            c["enabled"] = True
        _save_cameras()
        return list(cameras)


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
def update_alert(alert_id: int, action: str, request: Request):
    if action not in ("confirm", "dismiss"):
        return {"ok": False}
    new_status = "confirmed" if action == "confirm" else "dismissed"
    # Audit trail: stamp WHO decided and WHEN — this is what makes the evidence
    # log defensible when a student disputes an alert later.
    user = getattr(request.state, "user", None) or {}
    with _db() as c:
        c.execute("UPDATE alerts SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
                  (new_status, user.get("username", ""),
                   datetime.now().strftime("%H:%M:%S"), alert_id))
    return {"ok": True}


# ---------------------------------------------------------------------------
# PREMIUM DESKTOP UI  (additive — the original UI at "/" is untouched)
#
# The redesigned interface lives in ./web and is served at /app as static
# files that call the SAME JSON APIs defined above. No detection/AI code is
# involved. These three read-only JSON endpoints back the new Users/Settings
# screens (the old HTML pages remain the source of truth for writes).
# Auth is enforced by the same middleware; "/api" is in _API_PREFIXES so an
# unauthenticated call returns 401 JSON (the SPA then bounces to /login).
# ---------------------------------------------------------------------------
def _require_admin(request):
    u = getattr(request.state, "user", None) or current_user(request)
    if not u:
        return None, JSONResponse({"error": "unauthorized"}, status_code=401)
    if u["role"] != "admin":
        return None, JSONResponse({"error": "admin only"}, status_code=403)
    return u, None


@app.get("/api/me")
def api_me(request: Request):
    u = getattr(request.state, "user", None) or current_user(request)
    if not u:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"username": u["username"], "role": u["role"],
            "desktop": os.environ.get("VIGIL_DESKTOP") == "1",
            "version": VIGIL_VERSION}


@app.get("/api/users")
def api_users(request: Request):
    _, err = _require_admin(request)
    if err:
        return err
    with _db() as c:
        rows = c.execute(
            "SELECT username, role, created_at, auth, email FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/settings")
def api_settings(request: Request):
    _, err = _require_admin(request)
    if err:
        return err
    return current_settings()


# ---- Updates --------------------------------------------------------------
# Bump this on every release (it's what Check for updates compares against).
VIGIL_VERSION = "1.1.2"
_UPDATE_REPO = "Param077s/vigil"


def _version_tuple(v):
    nums, cur = [], ""
    for ch in str(v):
        if ch.isdigit():
            cur += ch
        elif cur:
            nums.append(int(cur)); cur = ""
    if cur:
        nums.append(int(cur))
    return tuple(nums) or (0,)


@app.get("/api/update-check")
def api_update_check():
    """Ask GitHub for the latest release and compare to this build. Done
    server-side so it isn't blocked by the page's Content-Security-Policy."""
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/releases/latest" % _UPDATE_REPO,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "Vigil"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return JSONResponse(
            {"error": "Couldn't reach the update server. Check your connection."},
            status_code=502)
    latest = (data.get("tag_name") or "").lstrip("vV")
    url = data.get("html_url") or "https://github.com/%s/releases/latest" % _UPDATE_REPO
    return {"current": VIGIL_VERSION, "latest": latest, "url": url,
            "update_available": bool(latest) and _version_tuple(latest) > _version_tuple(VIGIL_VERSION)}


# Serve the redesigned app. html=True makes /app -> web/index.html; hash
# routing keeps every screen under /app/ (no server routes to add per screen).
# VIGIL_WEB_DIR lets the packaged app point at web/ inside its bundle.
_WEB_DIR = os.environ.get("VIGIL_WEB_DIR", "").strip() or \
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if os.path.isdir(_WEB_DIR):
    app.mount("/app", StaticFiles(directory=_WEB_DIR, html=True), name="app")


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
  /* Drag-to-reorder — slot-based transform engine (see JS) */
  .grid.sortable .panel-head { cursor:grab; user-select:none; touch-action:none; }
  .grid.sortable .panel-head:active { cursor:grabbing; }
  /* Siblings only need their CSS transition disabled so the JS spring owns
     their transform. Do NOT force-promote them with will-change/contain:
     N video panels each on an isolated layer, with the dragged card's big
     soft shadow sweeping across them, is what made the siblings shimmer.
     Only the dragged card gets a dedicated layer. */
  .grid.reordering .panel { transition:none; }
  .grid.reordering .panel:hover { box-shadow:none; border-color:#232a34; }
  .grid.reordering .panel-body img { transform:none !important; }
  .panel.dragging { transition:none !important; cursor:grabbing; z-index:40; will-change:transform;
    box-shadow:0 24px 60px rgba(0,0,0,.5), 0 0 0 1px rgba(62,207,142,.28); border-color:#3a4557; }
  .panel.dragging .cam-snap { pointer-events:none; }
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
  .drag-handle { cursor:grab; color:#5b6675; line-height:0;
    padding:0 4px 0 0; margin-right:-2px; user-select:none; touch-action:none;
    transition:color .15s, transform .2s cubic-bezier(.3,1.4,.4,1); }
  .drag-handle:hover { color:#3ecf8e; transform:scale(1.18); }
  .drag-handle:active { cursor:grabbing; }
  /* Direction pad — hover the ✥ handle, click arrows to walk a camera around.
     It behaves like a remote: it stays under your cursor while the panel
     travels, so repeated clicks step it across the grid. */
  #dpad { position:fixed; z-index:80; display:grid;
    grid-template-columns:repeat(3,28px); grid-template-rows:repeat(3,28px); gap:2px;
    padding:7px; background:rgba(15,20,27,.9);
    backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px);
    border:1px solid rgba(255,255,255,.1); border-radius:14px;
    box-shadow:0 18px 50px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.06);
    opacity:0; transform:scale(.86) translateY(-5px); transform-origin:top left;
    pointer-events:none;
    transition:opacity .15s var(--ease), transform .22s cubic-bezier(.3,1.45,.4,1),
      left .46s cubic-bezier(.32,1.1,.36,1), top .46s cubic-bezier(.32,1.1,.36,1); }
  #dpad.open { opacity:1; transform:none; pointer-events:auto; }
  #dpad button { border:none; background:transparent; border-radius:9px; color:#8b95a3;
    display:flex; align-items:center; justify-content:center; cursor:pointer; padding:0;
    transition:background .15s, color .15s, transform .18s cubic-bezier(.3,1.4,.4,1); }
  #dpad button:hover { background:rgba(62,207,142,.16); color:#3ecf8e; transform:scale(1.15); }
  #dpad button:active { transform:scale(.9); }
  #dpad button[hidden] { display:none; }
  #dpad .dp-up { grid-area:1/2; } #dpad .dp-left { grid-area:2/1; }
  #dpad .dp-right { grid-area:2/3; } #dpad .dp-down { grid-area:3/2; }
  #dpad .dp-c { grid-area:2/2; display:flex; align-items:center; justify-content:center; }
  #dpad .dp-c i { width:5px; height:5px; border-radius:50%; background:#3ecf8e;
    box-shadow:0 0 8px rgba(62,207,142,.8); }
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
  .status-pill.paused { color:#eab308; background:rgba(234,179,8,.12); }
  .status-pill.paused .sdot { background:#eab308; }
  .panel.paused .panel-body { opacity:.55; }
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
  .alert-desc { font-size:12px; color:#c4ccd8; line-height:1.35; margin:2px 0; font-style:italic; }
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
       <code>/video</code>. Real CCTV? Use the <b>RTSP builder</b> below — it makes the
       link from the camera's IP + login. (Same network required.)</p>
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
    <button class="btn-ghost" id="rtsp-toggle" style="width:100%;border:none;border-radius:8px;padding:10px 0;
        font-size:13px;font-weight:600;cursor:pointer;margin-bottom:8px"
        onclick="const b=document.getElementById('rtsp-builder');
                 b.style.display = b.style.display==='none' ? 'block' : 'none';">
      CCTV / NVR camera? Build the RTSP link ▾</button>
    <div id="rtsp-builder" style="display:none;background:#0e1116;border:1px solid #2b3340;border-radius:10px;
         padding:14px;margin-bottom:12px">
      <p style="font-size:12px;color:#9aa4b2;margin-bottom:10px">Fill what the CCTV admin gives you —
        Vigil builds the link. For an <b>NVR</b> (recorder), use the NVR's address and pick the channel.</p>
      <label>Brand / system</label>
      <select id="rtsp-brand" style="width:100%;background:#151a21;border:1px solid #2b3340;color:#e6e9ef;
          padding:10px 12px;border-radius:8px;font-size:13px;margin-bottom:12px" onchange="rtspBuild()">
        <option value="hik">Hikvision (camera or NVR)</option>
        <option value="dahua">Dahua / Amcrest / CP Plus</option>
        <option value="reolink">Reolink</option>
        <option value="tapo">TP-Link / Tapo</option>
        <option value="uniview">Uniview</option>
        <option value="generic">Other / not sure (ONVIF generic)</option>
        <option value="custom">Custom path…</option>
      </select>
      <div style="display:grid;grid-template-columns:2fr 1fr;gap:8px">
        <div><label>Camera / NVR address (IP)</label><input id="rtsp-ip" placeholder="192.168.1.50" oninput="rtspBuild()"></div>
        <div><label>Port</label><input id="rtsp-port" placeholder="554" oninput="rtspBuild()"></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        <div><label>Username</label><input id="rtsp-user" placeholder="admin" oninput="rtspBuild()"></div>
        <div><label>Password</label><input id="rtsp-pass" placeholder="••••••" oninput="rtspBuild()"></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        <div><label>Channel (NVR: camera no.)</label><input id="rtsp-chan" value="1" oninput="rtspBuild()"></div>
        <div><label>Quality</label>
          <select id="rtsp-sub" style="width:100%;background:#151a21;border:1px solid #2b3340;color:#e6e9ef;
              padding:10px 12px;border-radius:8px;font-size:13px;margin-bottom:12px" onchange="rtspBuild()">
            <option value="sub" selected>Substream — smooth (recommended)</option>
            <option value="main">Main stream — full resolution (heavy)</option>
          </select></div>
      </div>
      <div id="rtsp-custom-row" style="display:none"><label>Custom path (after the address)</label>
        <input id="rtsp-path" placeholder="/Streaming/Channels/102" oninput="rtspBuild()"></div>
      <p style="font-size:11.5px;color:#5b6675;margin:0">The link appears in the Stream URL box above —
        then press Add camera. Special characters in passwords are encoded automatically.</p>
    </div>
    <div class="modal-actions">
      <button class="btn-primary" id="cam-submit" onclick="submitCam()">Add camera</button>
      <button class="btn-ghost" onclick="closeCam()">Cancel</button>
    </div>
  </div>
</div>

<div class="modal-bg" id="share-modal" onclick="if(event.target===this) closeShare()">
  <div class="modal">
    <h3>Share <span id="share-name">camera</span></h3>
    <p id="share-note"></p>
    <label>Camera link</label>
    <input id="share-link" readonly onclick="this.select()">
    <div class="modal-actions" style="margin-top:12px">
      <button class="btn-primary" id="share-copy" onclick="copyShareLink()">Copy link</button>
      <button class="btn-ghost" onclick="openShareHere()">Open on this device</button>
    </div>
    <div class="modal-actions" style="margin-top:8px">
      <button class="btn-ghost" onclick="closeShare()">Done</button>
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
    <button class="cam-btn" id="pause-all-btn" style="background:#2b3340;color:#c4ccd8;display:none">⏸ Pause all</button>
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
    const PUBLIC_URL = "__PUBLIC_URL__";   // public https address (set by Vigil-Public), else ""
    const I = {
      cam: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h9A1.5 1.5 0 0 1 15 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 3 16.5z"/><path d="m15 10.5 4.55-2.6A1 1 0 0 1 21 8.77v6.46a1 1 0 0 1-1.45.87L15 13.5z"/></svg>',
      pin: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0"/><circle cx="12" cy="10" r="3"/></svg>'
    };
    function panelHTML(c, i) {
      const place = (c.location && c.location.trim()) ? c.location : c.label;
      const handle = IS_ADMIN ? `<span class="drag-handle" title="Drag to move — hover for arrows">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2v20M2 12h20M9 5l3-3 3 3M9 19l3 3 3-3M5 9 2 12l3 3M19 9l3 3-3 3"/></svg></span>` : '';
      const senderBtn = c.source === 'browser'
        ? `<button class="icon-btn" title="Share this camera — send the link to any device, on any network"
             onclick="event.stopPropagation(); openShare('${c.id}')">
             <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/></svg></button>`
        : '';
      const on = c.enabled !== false;
      const pauseBtn = IS_ADMIN
        ? `<button class="icon-btn" title="${on ? 'Pause — keeps all details, stops connecting & detecting' : 'Resume this camera'}"
             onclick="event.stopPropagation(); toggleCam('${c.id}', ${on ? 'false' : 'true'})">${on ? '⏸' : '▶'}</button>`
        : '';
      const controls = senderBtn + pauseBtn + (IS_ADMIN
        ? `<button class="icon-btn" title="Edit camera" onclick="openEdit('${c.id}')">✎</button>
           <button class="icon-btn remove" title="Remove camera" onclick="removeCam('${c.id}')">×</button>`
        : '');
      return `<div class="panel enter${on ? '' : ' paused'}" data-cam="${c.id}" style="--i:${i}">
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
      updatePauseAllBtn();
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

    // ---- Slot-based drag engine (admin only) — Apple-caliber reorder ----
    // The DOM is NEVER mutated during a drag. At grab we freeze every panel's
    // slot geometry once; the dragged card and every sibling stay in normal
    // flow and are moved with translate3d() only. Logical order lives in an
    // in-memory index; the DOM reorders exactly once, on drop, with every
    // transform cleared in the same frame so nothing jumps.
    //
    //   • Dragged card: rigid, tracks the pointer 1:1 (no lerp, no tilt).
    //   • Siblings: each eases toward a target offset with a retargetable
    //     spring (exponential integrator) — new targets steer the existing
    //     motion, they never cancel/restart an animation.
    //   • Insertion: the card's centre picks the nearest fixed slot, with
    //     45%-of-a-slot distance hysteresis — direction-agnostic, so tremor
    //     or hovering can never oscillate a neighbour.
    //   • Auto-scroll near the grid edges; geometry stays valid because the
    //     card tracks the viewport pointer and slot deltas are scroll-invariant.
    function initSortable() {
      const grid = document.getElementById('grid');
      console.log('%cVigil drag engine: slot-v3 (no-cache)', 'color:#3ecf8e;font-weight:600');
      grid.classList.add('sortable');
      grid.querySelectorAll('.panel').forEach(p => {
        const head = p.querySelector('.panel-head');
        head.onpointerdown = e => {
          if (e.target.closest('.icon-btn') || e.target.closest('.status-pill')) return;
          startDrag(e, p, grid);
        };
        const hd = p.querySelector('.drag-handle');
        if (hd) hd.onpointerenter = () => {
          if (!grid.classList.contains('reordering')) dpShow(p);
        };
      });
      grid.onscroll = dpHide;                    // rects shift under the pad
    }

    function startDrag(e, dragEl, grid) {
      if (e.button !== 0) return;
      e.preventDefault();
      dpHide();                                  // free-drag takes over from the pad
      try { e.target.setPointerCapture(e.pointerId); } catch (_) {}

      const gridRect = grid.getBoundingClientRect();
      const sx0 = grid.scrollLeft, sy0 = grid.scrollTop;
      const cx0 = e.clientX, cy0 = e.clientY;      // pointer at grab
      const panels = [...grid.querySelectorAll('.panel')];
      const n = panels.length;
      const dragIndex = panels.indexOf(dragEl);

      // --- Freeze slot geometry ONCE (content coords). Never measured again. ---
      const slot = panels.map(p => {
        const r = p.getBoundingClientRect();
        const left = r.left - gridRect.left + grid.scrollLeft;
        const top  = r.top  - gridRect.top  + grid.scrollTop;
        return { left, top, cx: left + r.width / 2, cy: top + r.height / 2 };
      });
      const span = (() => { const r = dragEl.getBoundingClientRect(); return Math.min(r.width, r.height); })();

      // --- Sibling spring state: transform offset from each panel's own home ---
      const others = panels.filter(p => p !== dragEl);
      const homeIdx = new Map(panels.map((p, i) => [p, i]));   // panel -> its own slot
      const cur = new Map(others.map(p => [p, { x: 0, y: 0 }]));  // rendered offset
      const tgt = new Map(others.map(p => [p, { x: 0, y: 0 }]));  // desired offset

      grid.classList.add('reordering');
      dragEl.classList.add('dragging');

      // insIndex = the physical slot the card currently occupies (0..n-1).
      // dragIndex is the identity insertion. Each sibling's target slot follows.
      let insIndex = dragIndex;
      const retarget = () => {
        others.forEach((p, rank) => {
          const targetSlot = rank < insIndex ? rank : rank + 1;
          const from = slot[homeIdx.get(p)], to = slot[targetSlot];
          const t = tgt.get(p); t.x = to.left - from.left; t.y = to.top - from.top;
        });
      };

      // Card centre (content coords) -> nearest fixed slot, with distance
      // hysteresis: a settled slot only yields when another is closer by >45%
      // of a slot. Direction-agnostic (true Euclidean), so no axis oscillation.
      const card = { x: 0, y: 0, s: 1.03 };
      const chooseIndex = () => {
        const ccx = slot[dragIndex].cx + card.x, ccy = slot[dragIndex].cy + card.y;
        let best = insIndex, bestD = Infinity, curD = Infinity;
        for (let k = 0; k < n; k++) {
          const d = Math.hypot(slot[k].cx - ccx, slot[k].cy - ccy);
          if (k === insIndex) curD = d;
          if (d < bestD) { bestD = d; best = k; }
        }
        if (best !== insIndex && curD - bestD > 0.45 * span) { insIndex = best; retarget(); }
      };

      let pointerX = cx0, pointerY = cy0, edge = 0;
      let phase = 'drag', raf = 0, last = performance.now();
      const TAU_SIB = 90, TAU_CARD = 55;           // ms glide constants

      const frame = now => {
        const dt = Math.min(40, now - last); last = now;
        const aS = 1 - Math.exp(-dt / TAU_SIB);

        if (phase === 'drag') {
          if (edge) grid.scrollTop += edge * dt / 16;
          // card follows the viewport pointer 1:1; + any auto-scroll delta so it
          // stays under the finger even as content scrolls beneath it.
          card.x = (pointerX - cx0) + (grid.scrollLeft - sx0);
          card.y = (pointerY - cy0) + (grid.scrollTop  - sy0);
          card.s += (1.03 - card.s) * aS;
          chooseIndex();
        } else {
          const aC = 1 - Math.exp(-dt / TAU_CARD);
          card.x += (cardTgtX - card.x) * aC;
          card.y += (cardTgtY - card.y) * aC;
          card.s += (1 - card.s) * aC;
        }
        dragEl.style.transform = `translate3d(${card.x}px,${card.y}px,0) scale(${card.s.toFixed(4)})`;

        let settled = phase === 'settle';
        others.forEach(p => {
          const c = cur.get(p), t = tgt.get(p);
          c.x += (t.x - c.x) * aS; c.y += (t.y - c.y) * aS;
          if (Math.abs(t.x - c.x) > 0.3 || Math.abs(t.y - c.y) > 0.3) settled = false;
          p.style.transform = `translate3d(${c.x}px,${c.y}px,0)`;
        });

        if (phase === 'settle') {
          if (Math.abs(cardTgtX - card.x) > 0.3 || Math.abs(cardTgtY - card.y) > 0.3) settled = false;
          if (settled) { commit(); return; }
        }
        raf = requestAnimationFrame(frame);
      };
      raf = requestAnimationFrame(frame);

      const move = ev => {
        pointerX = ev.clientX; pointerY = ev.clientY;
        const EDGE = 64, SPEED = 14;               // auto-scroll ramp near edges
        if (ev.clientY < gridRect.top + EDGE)
          edge = -SPEED * Math.min(1, (gridRect.top + EDGE - ev.clientY) / EDGE);
        else if (ev.clientY > gridRect.bottom - EDGE)
          edge = SPEED * Math.min(1, (ev.clientY - (gridRect.bottom - EDGE)) / EDGE);
        else edge = 0;
      };

      let cardTgtX = 0, cardTgtY = 0;
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
        edge = 0;
        cardTgtX = slot[insIndex].left - slot[dragIndex].left;   // scroll-invariant delta
        cardTgtY = slot[insIndex].top  - slot[dragIndex].top;
        phase = 'settle';
        if (document.hidden) { cancelAnimationFrame(raf); commit(); }   // no frames will run
      };

      let committed = false;
      function commit() {
        if (committed) return; committed = true;   // pointerup + pointercancel can both fire
        cancelAnimationFrame(raf);
        // The ONE and only DOM mutation: reorder to the in-memory order, then
        // clear every transform in the same frame. Because each element is
        // visually already at its new slot, clearing produces zero movement.
        const ordered = others.slice();
        ordered.splice(insIndex, 0, dragEl);
        const frag = document.createDocumentFragment();
        ordered.forEach(p => { p.style.transform = ''; frag.appendChild(p); });
        dragEl.classList.remove('dragging');
        dragEl.style.cssText = '';
        grid.appendChild(frag);
        grid.classList.remove('reordering');
        saveOrder(grid);
      }

      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
      window.addEventListener('pointercancel', up);
    }
    // ---- Direction pad: hover the ✥ handle, click arrows to nudge a camera ----
    // Arrows adapt to where the panel sits (corner = 2, edge = 3, interior = 4).
    // The pad STAYS STUCK TO the camera it controls: press an arrow and the pad
    // glides along with the camera to its new slot, so the arrows always belong
    // to the camera you're moving and you can keep tapping to walk it across the
    // wall. It fades out when the cursor leaves its neighbourhood.
    const CHEV = d => { const r = { up:180, right:270, down:0, left:90 }[d];
      return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="transform:rotate(${r}deg)"><path d="m6 9 6 6 6-6"/></svg>`; };
    const dpad = document.createElement('div');
    dpad.id = 'dpad';
    dpad.innerHTML = `<button class="dp-up" data-dir="up" title="Move up">${CHEV('up')}</button>
      <button class="dp-left" data-dir="left" title="Move left">${CHEV('left')}</button>
      <span class="dp-c"><i></i></span>
      <button class="dp-right" data-dir="right" title="Move right">${CHEV('right')}</button>
      <button class="dp-down" data-dir="down" title="Move down">${CHEV('down')}</button>`;
    document.body.appendChild(dpad);
    let dpPanel = null, dpBusy = false;

    function dpCols() {                          // columns from the grid's computed
      const g = document.getElementById('grid'); // track list — layout truth, immune
      const v = getComputedStyle(g).gridTemplateColumns.split(' ').filter(Boolean);
      return Math.max(1, v.length);              // to mid-animation transforms
    }
    function dpUpdate() {                        // show only the arrows that exist here
      const ps = [...document.querySelectorAll('#grid .panel')];
      const i = ps.indexOf(dpPanel), n = ps.length, C = dpCols();
      if (i < 0) { dpHide(); return; }
      const ok = { up: i - C >= 0, down: i + C < n, left: i % C > 0, right: i % C < C - 1 && i + 1 < n };
      dpad.querySelectorAll('button').forEach(b => b.hidden = !ok[b.dataset.dir]);
    }
    // place the pad next to a handle rect. glide=false snaps (fresh open, no
    // slide-in from a stale spot); glide=true lets the CSS left/top transition
    // carry it — used when it follows a camera to its new slot.
    const PAD = 104;                            // fixed 3x3 pad; reading offsetWidth
    function dpPlace(hr, glide) {                // on first open mismeasured badly
      const w = PAD, h = PAD;
      const L = Math.max(8, Math.min(innerWidth  - w - 8, hr.left - 12));
      const T = Math.max(8, Math.min(innerHeight - h - 8, hr.bottom + 8));
      if (!glide) dpad.style.transition = 'none';
      dpad.style.left = L + 'px'; dpad.style.top = T + 'px';
      if (!glide) { void dpad.offsetWidth; dpad.style.transition = ''; }  // reflow, restore CSS
    }
    function dpShow(panel) {
      const wasOpen = dpad.classList.contains('open');
      dpPanel = panel;
      dpUpdate();
      if (!dpPanel) return;
      dpPlace(panel.querySelector('.drag-handle').getBoundingClientRect(), wasOpen);
      if (!wasOpen) dpad.classList.add('open');
    }
    function dpHide() { dpad.classList.remove('open'); dpPanel = null; }

    addEventListener('pointermove', ev => {      // fade when cursor leaves the neighbourhood
      if (!dpPanel || dpBusy) return;
      const R = 26;
      const near = b => b && ev.clientX > b.left - R && ev.clientX < b.right + R &&
                        ev.clientY > b.top - R && ev.clientY < b.bottom + R;
      const hd = dpPanel.querySelector('.drag-handle');
      if (!near(dpad.getBoundingClientRect()) && !near(hd && hd.getBoundingClientRect()))
        dpHide();
    }, { passive: true });

    dpad.addEventListener('click', ev => {
      const btn = ev.target.closest('button');
      if (btn && !dpBusy && dpPanel) dpSwap(btn.dataset.dir);
    });

    function dpSwap(dir) {
      const grid = document.getElementById('grid');
      const ps = [...grid.querySelectorAll('.panel')];
      const i = ps.indexOf(dpPanel), C = dpCols();
      const j = dir === 'up' ? i - C : dir === 'down' ? i + C : dir === 'left' ? i - 1 : i + 1;
      if (i < 0 || j < 0 || j >= ps.length) return;
      const a = dpPanel, b = ps[j];
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const mark = document.createElement('i');  // swap a and b in the DOM
      a.replaceWith(mark); b.replaceWith(a); mark.replaceWith(b);
      const na = a.getBoundingClientRect(), nb = b.getBoundingClientRect();
      // handle rect at a's NEW slot, captured before any transform is applied
      const nh = a.querySelector('.drag-handle').getBoundingClientRect();
      const dax = ra.left - na.left, day = ra.top - na.top;
      const dbx = rb.left - nb.left, dby = rb.top - nb.top;
      dpBusy = true; a.style.zIndex = 30;        // traveller rides above
      dpPlace(nh, true);                          // pad glides along with the camera
      const EASE = 'cubic-bezier(.32,1.16,.35,1)';
      const anim = a.animate(
        [{ transform: `translate(${dax}px,${day}px) scale(1)` },
         { transform: `translate(${dax/2}px,${day/2}px) scale(1.04)`, offset: .45 },
         { transform: 'translate(0,0) scale(1)' }],
        { duration: 480, easing: EASE });
      b.animate(
        [{ transform: `translate(${dbx}px,${dby}px) scale(1)` },
         { transform: `translate(${dbx/2}px,${dby/2}px) scale(.985)`, offset: .5 },
         { transform: 'translate(0,0) scale(1)' }],
        { duration: 480, easing: EASE });
      const clear = () => { a.style.zIndex = ''; dpBusy = false; };
      anim.onfinish = anim.oncancel = clear;
      setTimeout(clear, 560);                    // safety: never wedge the pad
      dpUpdate();                                // arrows adapt to the new spot
      saveOrder(grid);
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
      if (img.dataset.looping !== '1') { img.dataset.looping = '1'; pollFeed(img); }  // start its feed loop
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

    // ---- Share a device-camera link (works across networks via Vigil-Public) ----
    let shareId = null;
    function shareLinkFor(id){
      const base = (PUBLIC_URL && PUBLIC_URL.length) ? PUBLIC_URL : location.origin;
      return base + '/sender/' + id;
    }
    function openShare(id){
      shareId = id;
      const cam = (lastCams || []).find(x => x.id === id);
      document.getElementById('share-name').textContent =
        (cam && (cam.location || cam.label)) ? (cam.location || cam.label) : 'camera';
      document.getElementById('share-link').value = shareLinkFor(id);
      const remote = !!(PUBLIC_URL && PUBLIC_URL.length);
      document.getElementById('share-note').innerHTML = remote
        ? 'Send this link to anyone, on <b>any network</b>. They open it on the device that should film, allow the camera, and it appears on your wall live.'
        : 'This link works on <b>your Wi-Fi only.</b> To let someone on another network film, start Vigil with <code>Vigil-Public</code> — it makes a secure public link.';
      document.getElementById('share-modal').classList.add('open');
    }
    function closeShare(){ document.getElementById('share-modal').classList.remove('open'); }
    async function copyShareLink(){
      const inp = document.getElementById('share-link');
      try { await navigator.clipboard.writeText(inp.value); }
      catch(e){ inp.select(); try { document.execCommand('copy'); } catch(_){} }
      const b = document.getElementById('share-copy'), t = b.textContent;
      b.textContent = 'Copied ✓';
      setTimeout(() => { b.textContent = t; }, 1400);
    }
    function openShareHere(){ if (shareId) window.open('/sender/' + shareId, '_blank'); }
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
    // ---- CCTV / RTSP link builder --------------------------------------
    // Composes the correct rtsp:// URL for the common CCTV brands so nobody
    // has to memorise stream paths. NVR channels: Hikvision channel N sub-
    // stream = N*100+2 (102, 202...), Dahua-style = ?channel=N&subtype=1.
    function rtspBuild() {
      const brand = document.getElementById('rtsp-brand').value;
      document.getElementById('rtsp-custom-row').style.display = brand === 'custom' ? 'block' : 'none';
      const ip   = document.getElementById('rtsp-ip').value.trim();
      if (!ip) return;
      const port = document.getElementById('rtsp-port').value.trim() || '554';
      const user = document.getElementById('rtsp-user').value.trim();
      const pass = document.getElementById('rtsp-pass').value;
      const chan = parseInt(document.getElementById('rtsp-chan').value.trim() || '1', 10) || 1;
      const sub  = document.getElementById('rtsp-sub').value === 'sub';
      let path;
      if      (brand === 'hik')     path = '/Streaming/Channels/' + (chan * 100 + (sub ? 2 : 1));
      else if (brand === 'dahua')   path = '/cam/realmonitor?channel=' + chan + '&subtype=' + (sub ? 1 : 0);
      else if (brand === 'reolink') path = '/h264Preview_' + String(chan).padStart(2, '0') + (sub ? '_sub' : '_main');
      else if (brand === 'tapo')    path = sub ? '/stream2' : '/stream1';
      else if (brand === 'uniview') path = '/media/video' + (sub ? 2 : 1);
      else if (brand === 'custom')  path = document.getElementById('rtsp-path').value.trim() || '/';
      else                          path = sub ? '/onvif2' : '/onvif1';
      if (path && path[0] !== '/') path = '/' + path;
      const cred = user ? encodeURIComponent(user) + (pass ? ':' + encodeURIComponent(pass) : '') + '@' : '';
      document.getElementById('cam-input').value = 'rtsp://' + cred + ip + ':' + port + path;
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
      // don't silently stack up identical webcam tiles from repeat clicks
      let cams = [];
      try { cams = await (await fetch('/cameras')).json(); } catch (e) {}
      if (cams.some(c => c.source === '0')) {
        alert('This computer\\'s webcam is already added - it\\'s on your wall.');
        closeCam(); return;
      }
      await fetch('/cameras', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ label: "Mac webcam", location: "", source: '0' }) });
      closeCam(); loadCameras();
    }
    async function addBrowserCam() {
      const label = document.getElementById('cam-label').value.trim() || 'Device camera';
      const location = document.getElementById('cam-location').value.trim();
      const cam = await (await fetch('/cameras', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ label, location, source: 'browser' }) })).json();
      closeCam(); await loadCameras();
      openShare(cam.id);   // choose: send the link to a device, or open it here
    }
    async function removeCam(id) {
      await fetch('/cameras/' + id, { method:'DELETE' });
      loadCameras();
    }
    async function toggleCam(id, enable) {
      await fetch('/cameras/' + id, { method:'PUT', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ enabled: enable }) });
      loadCameras();
    }
    async function toggleAll() {
      // pause everything if anything is running; otherwise resume everything
      const anyOn = lastCams.some(c => c.enabled !== false);
      await fetch(anyOn ? '/cameras/pause_all' : '/cameras/resume_all', { method:'POST' });
      loadCameras();
    }
    function updatePauseAllBtn() {
      const b = document.getElementById('pause-all-btn');
      if (!b) return;
      if (!lastCams.length) { b.style.display = 'none'; return; }
      b.style.display = '';
      const anyOn = lastCams.some(c => c.enabled !== false);
      b.textContent = anyOn ? '⏸ Pause all' : '▶ Resume all';
      b.title = anyOn
        ? 'Exams over? Park every camera — details are kept, nothing connects or detects until you resume.'
        : 'Reconnect and resume detection on every camera.';
    }
    if (IS_ADMIN) {
      document.getElementById('cam-btn').onclick = openAdd;
      document.getElementById('pause-all-btn').onclick = toggleAll;
    } else {
      document.getElementById('cam-btn').style.display = 'none';
      document.getElementById('pause-all-btn').style.display = 'none';
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
            ${a.description ? `<div class="alert-desc">👁 ${a.description}</div>` : ''}
            <div class="alert-cam">${I.pin}${a.camera}</div>
            <div class="alert-time">${a.time}</div>
            ${a.status === 'pending'
              ? `<div class="alert-actions">
                   <button class="confirm" onclick="act(${a.id},'confirm')">Confirm</button>
                   <button class="dismiss" onclick="act(${a.id},'dismiss')">Dismiss</button>
                 </div>`
              : `<div class="badge ${a.status}">${a.status}${a.reviewed_by ? ' · ' + a.reviewed_by : ''}</div>`}
          </div>
        </div>`).join('');
    }
    async function act(id, action) {
      try { await fetch(`/alerts/${id}/${action}`, { method:'POST' }); } catch (e) {}
      loadAlerts();
    }
    setInterval(loadAlerts, 1500);
    loadAlerts();

    // ---- Live camera feeds (snapshot polling) ----
    // Each tile fetches the latest annotated JPEG on a loop. Short requests that
    // COMPLETE and free the connection — unlike a permanent MJPEG stream, which
    // holds a socket open forever and (past the browser's ~6-per-host limit)
    // freezes the tab on "loading". One in-flight fetch per tile = no pile-up.
    function pollFeed(img) {
      const id = img.dataset.cam;
      if (!id || !document.contains(img)) { img.dataset.looping = ''; return; }
      fetch('/snapshot/' + id + '?t=' + Date.now())
        .then(r => r.ok ? r.blob() : null)
        .then(blob => {
          if (blob) {
            const url = URL.createObjectURL(blob);
            const prev = img.dataset.url;
            img.src = url; img.dataset.url = url;
            if (prev) URL.revokeObjectURL(prev);
          }
        }).catch(() => {})
        .finally(() => setTimeout(() => pollFeed(img), 40));   // ~25fps, next only after this one lands
    }
    function refreshSnapshots() {
      // start ONE polling loop per tile; it self-sustains until the tile is gone
      document.querySelectorAll('img.cam-snap').forEach(img => {
        if (img.dataset.cam && img.dataset.looping !== '1') {
          img.dataset.looping = '1';
          pollFeed(img);
        }
      });
    }
    setInterval(refreshSnapshots, 500);

    // ---- Per-camera online/offline status ----
    async function refreshStatus() {
      // mid-drag: the pills live inside the panels being dragged/FLIPped —
      // touching their text mid-drag forces layout and hitches the animation
      if (document.querySelector('.grid.reordering')) return;
      let st = {};
      try { st = await (await fetch('/camera_status')).json(); } catch (e) { return; }
      document.querySelectorAll('.status-pill').forEach(p => {
        const s = st[p.dataset.cam];
        p.classList.toggle('online', s === 'online');
        p.classList.toggle('paused', s === 'paused');
        p.classList.toggle('offline', s !== 'online' && s !== 'paused');
        const el = p.querySelector('.stext'),
              txt = s === 'online' ? 'LIVE' : (s === 'paused' ? 'PAUSED' : 'OFFLINE');
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
        <thead><tr><th>Photo</th><th>Detected</th><th>AI description</th><th>Date</th><th>Time</th><th>Location</th><th>Confidence</th><th>Status</th></tr></thead>
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
        body.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#5b6675;padding:40px">No matching records.</td></tr>';
        return;
      }
      body.innerHTML = rows.map(r => `
        <tr>
          <td><img src="${r.image}"></td>
          <td>${r.thing || 'Phone'}</td>
          <td style="max-width:240px;color:#c4ccd8;font-style:italic">${r.description || '<span style=\"color:#5b6675;font-style:normal\">—</span>'}</td>
          <td>${r.date}</td>
          <td>${r.time}</td>
          <td>${r.camera}</td>
          <td>${Math.round(r.confidence*100)}%</td>
          <td><span class="badge ${r.status}">${r.status}</span>
            ${r.reviewed_by ? `<div style="font-size:11px;color:#5b6675;margin-top:4px">by <b style="color:#9aa4b2">${r.reviewed_by}</b> · ${r.reviewed_at}</div>` : ''}</td>
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
        <label>Sign-in type</label>
        <select name="auth" id="u-auth" onchange="
            const g = this.value === 'google';
            document.getElementById('u-pw').style.display = g ? 'none' : '';
            document.getElementById('u-pw-l').style.display = g ? 'none' : '';
            document.getElementById('u-pw').required = !g;
            document.getElementById('u-name-l').textContent = g ? 'Google email' : 'Username';
            document.getElementById('u-name').placeholder = g ? 'name@gmail.com' : '';">
          <option value="password">Password — works offline</option>
          <option value="google">Google — signs in with their Google account</option>
        </select>
        <label id="u-name-l">Username</label><input name="username" id="u-name" required>
        <label id="u-pw-l">Password</label><input name="password" id="u-pw" type="password" required>
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
    # In the native desktop app the redesigned UI (/app) is home. Every login
    # path (password, Google, first-run setup) lands on "/", so redirecting here
    # sends the desktop window straight into /app. The browser launcher leaves
    # VIGIL_DESKTOP unset and keeps this classic dashboard as the fallback UI.
    if os.environ.get("VIGIL_DESKTOP") == "1":
        return RedirectResponse("/app/")
    user = getattr(request.state, "user", None) or {"username": "", "role": "invigilator"}
    html = (DASHBOARD_HTML
            .replace("__STYLE__", STYLE).replace("__LOGO__", LOGO_MARK)
            .replace("__CAMERA_MODAL__", CAMERA_MODAL)
            .replace("__USERNAME__", user["username"])
            .replace("__ADMIN_NAV__", _admin_nav(user))
            .replace("__PUBLIC_URL__", PUBLIC_URL)
            .replace("__IS_ADMIN__", "true" if user["role"] == "admin" else "false"))
    # The dashboard is inline HTML+JS that changes with every app update. Never
    # let a browser serve a stale copy from cache — always fetch the live one.
    return HTMLResponse(html, headers={"Cache-Control": "no-store, max-age=0"})


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
      loop();
    }
    // Frames go over ONE WebSocket when possible (lowest latency — no per-frame
    // HTTP round trip). If the socket can't connect (old proxy, odd network) we
    // fall back to the pipelined POST uploader. bufferedAmount is the backlog
    // guard: when the link can't keep up we skip frames instead of growing lag.
    const CAPTURE_MS = 40;         // ~25 captures/sec ceiling
    const MAX_INFLIGHT = 3;
    const WS_MAX_BUFFER = 300000;  // ~2 frames — beyond this, skip instead of queue
    let inflight = 0, seq = Date.now();
    let ws = null, wsOpen = false, wsDead = false;

    function connectWS() {
      try {
        ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://')
                           + location.host + '/ws/push/' + CAM_ID);
        ws.binaryType = 'arraybuffer';
        ws.onopen  = () => { wsOpen = true;  setLive(true); };
        ws.onclose = ws.onerror = () => {
          const was = wsOpen; wsOpen = false;
          if (!was) { wsDead = true; return; }         // never connected → POST mode
          setLive(false); setTimeout(connectWS, 1000); // drop mid-run → reconnect
        };
      } catch (e) { wsDead = true; }
    }
    function setLive(ok) {
      pill.classList.toggle('live', ok);
      ptext.textContent = ok ? 'LIVE' : 'RECONNECTING…';
    }
    function loop() {
      if (v.videoWidth > 0) {
        if (wsOpen) { if (ws.bufferedAmount < WS_MAX_BUFFER) shoot(); }
        else if (wsDead && inflight < MAX_INFLIGHT) shoot();
      }
      setTimeout(loop, CAPTURE_MS);
    }
    function shoot() {
      // 640px @ 0.6 quality = small frame that uploads fast over cellular; the
      // detector runs at IMG_SIZE anyway, so more pixels wouldn't help accuracy.
      const w = Math.min(v.videoWidth, 640), h = Math.round(w * v.videoHeight / v.videoWidth);
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(v, 0, 0, w, h);
      const mySeq = ++seq;
      canvas.toBlob(blob => {
        if (!blob) return;
        if (wsOpen) {
          blob.arrayBuffer().then(buf => { if (wsOpen) { ws.send(buf); setLive(true); } });
          return;
        }
        inflight++;
        fetch('/push/' + CAM_ID, { method:'POST',
            headers:{ 'Content-Type':'image/jpeg', 'X-Seq': String(mySeq) }, body: blob })
          .then(r => setLive(r.ok))
          .catch(() => setLive(false))
          .finally(() => { inflight--; });
      }, 'image/jpeg', 0.6);
    }
    connectWS();
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
<html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil — __TITLE__</title>
<link rel="icon" href="/favicon.svg">
<style>
  :root{--bg:#0B0D10;--surface:#111419;--surface-2:#161A20;--border:#21262E;
    --border-strong:#2C333D;--text:#E8EBEF;--text-2:#A4ADB8;--text-3:#6C7580;
    --text-4:#464E58;--accent:#2FB37D;--accent-hover:#38C489;--danger:#E05D4A;
    --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,sans-serif;}
  *{box-sizing:border-box;margin:0}
  html,body{height:100%}
  body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px;
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    -webkit-font-smoothing:antialiased}
  .brand{display:flex;align-items:center;gap:10px;margin-bottom:26px;animation:in .5s cubic-bezier(.2,.6,.2,1)}
  .brand svg{width:30px;height:30px}
  .brand b{font-size:20px;font-weight:600;letter-spacing:-.01em}
  .auth{background:var(--surface);border:1px solid var(--border);border-radius:16px;
    padding:28px;width:372px;max-width:92vw;box-shadow:0 18px 48px rgba(0,0,0,.5);
    animation:in .5s cubic-bezier(.2,.6,.2,1) .05s backwards}
  @keyframes in{from{opacity:0;transform:translateY(8px)}}
  .auth h2{font-size:18px;font-weight:600;letter-spacing:-.01em}
  .auth .sub{font-size:13px;color:var(--text-3);margin:6px 0 20px;line-height:1.5}
  .auth label{display:block;font-size:12px;font-weight:500;color:var(--text-2);margin:0 0 6px 2px}
  .auth input{width:100%;background:var(--surface-2);border:1px solid var(--border-strong);
    color:var(--text);padding:0 12px;height:38px;border-radius:8px;font-size:14px;margin-bottom:14px;
    transition:border-color .15s,box-shadow .15s}
  .auth input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(47,179,125,.14)}
  .auth input::placeholder{color:var(--text-4)}
  .auth button.primary{width:100%;background:var(--accent);color:#04120C;border:none;height:40px;
    border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;margin-top:2px;transition:background .15s}
  .auth button.primary:hover{background:var(--accent-hover)}
  .err{background:rgba(224,93,74,.12);color:var(--danger);font-size:13px;
    padding:9px 12px;border-radius:8px;margin-bottom:14px}
  .foot{margin-top:22px;color:var(--text-3);font-size:12px;display:flex;align-items:center;gap:7px}
  .foot .d{width:6px;height:6px;border-radius:50%;background:var(--accent)}
</style></head>
<body>
  <div class="brand"><svg viewBox="0 0 24 24" fill="none"><rect width="24" height="24" rx="7" fill="#161A20"/><path d="M6 10V7.5A1.5 1.5 0 0 1 7.5 6H10M14 6h2.5A1.5 1.5 0 0 1 18 7.5V10M18 14v2.5a1.5 1.5 0 0 1-1.5 1.5H14M10 18H7.5A1.5 1.5 0 0 1 6 16.5V14" stroke="#6C7580" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="12" r="2.6" fill="#2FB37D"/></svg><b>Vigil</b></div>
  <form class="auth" method="post" action="__ACTION__">
    <h2>__HEADING__</h2>
    <div class="sub">__HINT__</div>
    __ERROR__
    <div class="err" id="gerr" style="display:none"></div>
    __GOOGLE__
    <label>Username</label>
    <input name="username" autofocus autocomplete="username" placeholder="Your username">
    <label>Password</label>
    <input name="password" type="password" autocomplete="current-password" placeholder="••••••••">
    <button class="primary" type="submit">__BUTTON__</button>
  </form>
  <div class="foot"><span class="d"></span> On-device AI · runs entirely on this machine</div>
</body></html>"""

# Google Sign-In block (only rendered when a client ID is configured).
# The button comes from Google's own script; its callback hands us an ID token
# that /auth/google verifies WITH GOOGLE server-side before opening a session.
GOOGLE_BTN = """
      <div id="g_id_onload" data-client_id="__GCID__" data-callback="onGoogle" data-auto_select="false"></div>
      <div class="g_id_signin" data-type="standard" data-theme="filled_black" data-size="large"
           data-text="__GTEXT__" data-shape="rectangular" data-logo_alignment="left" data-width="298"></div>
      <div style="display:flex;align-items:center;gap:10px;margin:16px 0 14px;color:var(--text-3);font-size:11.5px">
        <span style="flex:1;height:1px;background:var(--border)"></span>or
        <span style="flex:1;height:1px;background:var(--border)"></span></div>
      <script src="https://accounts.google.com/gsi/client" async></script>
      <script>
        function onGoogle(resp) {
          fetch('/auth/google', { method:'POST', headers:{'Content-Type':'application/json'},
                                  body: JSON.stringify({ credential: resp.credential }) })
            .then(r => r.json().then(j => ({ ok: r.ok, j })))
            .then(({ ok, j }) => {
              if (ok) { location.href = '/'; return; }
              const e = document.getElementById('gerr');
              e.textContent = (j && j.error) || 'Google sign-in failed.';
              e.style.display = 'block';
            })
            .catch(() => {
              const e = document.getElementById('gerr');
              e.textContent = 'Google sign-in failed - check your connection.';
              e.style.display = 'block';
            });
        }
      </script>"""


def _google_ok_for(request):
    """Google only trusts localhost/127.0.0.1 origins for this app, so the button
    would just error on a phone opening Vigil over WiFi (a LAN IP). Show it only
    where it actually works; everyone else sees clean password login."""
    if not GOOGLE_CLIENT_ID.strip():
        return False
    # The packaged desktop app runs on a random loopback port inside an embedded
    # WebKit view — Google rejects both (unregistered origin + embedded-webview
    # OAuth block), so the button can never work there. Hide it; password login
    # is the reliable path in the desktop app.
    if os.environ.get("VIGIL_DESKTOP") == "1":
        return False
    host = (request.headers.get("host") or "").split(":")[0].lower()
    return host in ("localhost", "127.0.0.1")


def _auth_page(title, heading, hint, action, button, error="", google_text="signin_with",
               allow_google=False):
    err = f'<div class="err">{error}</div>' if error else ""
    google = ""
    if allow_google and GOOGLE_CLIENT_ID.strip():
        google = GOOGLE_BTN.replace("__GCID__", GOOGLE_CLIENT_ID.strip()).replace("__GTEXT__", google_text)
    return (AUTH_TEMPLATE.replace("__STYLE__", STYLE).replace("__LOGO__", LOGO_MARK).replace("__TITLE__", title)
            .replace("__HEADING__", heading).replace("__HINT__", hint)
            .replace("__ACTION__", action).replace("__BUTTON__", button)
            .replace("__ERROR__", err).replace("__GOOGLE__", google))


_COOKIE_KW = dict(httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    if user_count() > 0:
        return RedirectResponse("/login")
    g = _google_ok_for(request)
    hint = ("This first account manages cameras and other users. "
            + ("Use Google, or create a username and password below." if g else ""))
    return _auth_page("Setup", "Create the admin account", hint,
                      "/setup", "Create admin", google_text="continue_with", allow_google=g)


@app.post("/setup")
def setup_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if user_count() > 0:
        return RedirectResponse("/login", status_code=303)
    ok, err = create_user(username, password, role="admin")
    if not ok:
        return HTMLResponse(_auth_page("Setup", "Create the admin account",
                            "This first account manages cameras and other users.",
                            "/setup", "Create admin", err,
                            allow_google=_google_ok_for(request)), status_code=400)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("vigil_session", _sign(username.strip()), **_COOKIE_KW)
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if user_count() == 0:
        return RedirectResponse("/setup")
    g = _google_ok_for(request)
    hint = "Use your Google account, or a local username." if g else "Enter your credentials."
    return _auth_page("Login", "Sign in to Vigil", hint, "/login", "Sign in", allow_google=g)


# --- Brute-force throttle -------------------------------------------------
# In-memory per-IP failure counter. Matters most when Vigil is shared over a
# LAN (--host 0.0.0.0): PBKDF2 already makes each guess expensive; this caps
# the rate so an attacker on the same WiFi can't grind the login.
_login_fails = {}                      # ip -> [failure timestamps]
_login_lock = threading.Lock()
_LOGIN_WINDOW = 300                    # seconds
_LOGIN_MAX = 8                         # failures allowed per window per IP


def _client_ip(request):
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return fwd or (request.client.host if request.client else "?")


def _login_throttled(ip):
    now = time.time()
    with _login_lock:
        recent = [t for t in _login_fails.get(ip, []) if now - t < _LOGIN_WINDOW]
        _login_fails[ip] = recent
        return len(recent) >= _LOGIN_MAX


def _note_login_fail(ip):
    with _login_lock:
        _login_fails.setdefault(ip, []).append(time.time())


def _clear_login_fails(ip):
    with _login_lock:
        _login_fails.pop(ip, None)


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = _client_ip(request)
    if _login_throttled(ip):
        return HTMLResponse(_auth_page("Login", "Sign in to Vigil", "Enter your credentials.",
                            "/login", "Sign in", "Too many attempts. Wait a few minutes and try again.",
                            allow_google=_google_ok_for(request)), status_code=429)
    u = verify_user(username, password)
    if not u:
        _note_login_fail(ip)
        return HTMLResponse(_auth_page("Login", "Sign in to Vigil", "Enter your credentials.",
                            "/login", "Sign in", "Invalid username or password.",
                            allow_google=_google_ok_for(request)), status_code=401)
    _clear_login_fails(ip)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("vigil_session", _sign(u["username"]), **_COOKIE_KW)
    return resp


@app.post("/auth/google")
async def auth_google(request: Request):
    """Google Sign-In: verify the ID token with Google, then map its email to a
    Vigil account. First user ever becomes the admin (same rule as /setup);
    after that an admin must add your email on the Users page first."""
    if not GOOGLE_CLIENT_ID.strip():
        return JSONResponse({"error": "Google Sign-In isn't configured."}, status_code=400)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    claims = verify_google_token(str(payload.get("credential", "")))
    if not claims:
        return JSONResponse({"error": "Google couldn't verify that sign-in."}, status_code=401)
    email = (claims.get("email") or "").strip().lower()
    if not email:
        return JSONResponse({"error": "Google returned no email address."}, status_code=401)
    user = find_user_by_email(email)
    if user is None:
        if user_count() == 0:                            # bootstrap: first account = admin
            ok, err = create_google_user(email, role="admin")
            if not ok:
                return JSONResponse({"error": err}, status_code=400)
            user = find_user_by_email(email)
        else:
            return JSONResponse({"error": f"{email} isn't authorized yet - ask your admin "
                                          "to add it on the Users page."}, status_code=403)
    resp = JSONResponse({"ok": True, "username": user["username"], "role": user["role"]})
    resp.set_cookie("vigil_session", _sign(user["username"]), **_COOKIE_KW)
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
        via = ' <span style="color:#5b6675;font-size:11px">· Google</span>' \
              if (u.get("auth") == "google") else ""
        out.append(f'<tr><td>{u["username"]}{via}</td>'
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
def users_add(username: str = Form(...), password: str = Form(""), role: str = Form("invigilator"),
              auth: str = Form("password")):
    role = "admin" if role == "admin" else "invigilator"
    if auth == "google":
        create_google_user(username, role)               # username field holds the email
    else:
        create_user(username, password, role)
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
    vlm_checked = "checked" if g["VLM_ENABLED"] else ""
    vlm_verify_checked = "checked" if g["VLM_VERIFY"] else ""
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

        <div class="sec">AI second look (optional) — smarter alerts</div>
        <div class="field">
          <div class="hint">After a detection, a <b>local</b> vision model looks at the photo to
          (1) write a plain-English description of the scene and (2) drop obvious false alarms.
          Runs 100% on this computer — nothing leaves the building. Needs
          <a href="https://ollama.com" target="_blank">Ollama</a> running with a vision model
          pulled: <code>ollama pull llava</code> (or <code>moondream</code> for a lighter one).</div>
        </div>
        <div class="field toggle">
          <input type="checkbox" name="vlm_enabled" {vlm_checked}>
          <label>Enable AI second look</label>
        </div>
        <div class="field">
          <label>Vision model</label>
          <div class="hint">Ollama model name: <b>llava</b> (balanced) · <b>moondream</b> (fastest, lighter) · <b>qwen2.5vl</b> (sharper). Pull it first with <code>ollama pull &lt;name&gt;</code>.</div>
          <input type="text" name="vlm_model" value="{g['VLM_MODEL']}" style="width:340px" placeholder="llava">
        </div>
        <div class="field toggle">
          <input type="checkbox" name="vlm_verify" {vlm_verify_checked}>
          <label>Also drop false alarms the AI rejects</label>
        </div>
        <div class="field">
          <div class="hint">With this on, if the AI is confident the photo is <i>not</i> a {g['WATCH_TARGET']}
          (a remote, wallet, book…), the alert is suppressed. Turn off to only add descriptions and
          never discard a detection.</div>
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
    vlm_enabled: str = Form(None),
    vlm_model: str = Form("llava"),
    vlm_verify: str = Form(None),
):
    old_model = MODEL_NAME
    old_watch = WATCH_TARGET
    save_settings({
        "VLM_ENABLED": vlm_enabled is not None,
        "VLM_MODEL": (vlm_model.strip() or "llava"),
        "VLM_VERIFY": vlm_verify is not None,
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
    _sync_vlm()                                    # push VLM_* into the vlm module
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
    function pollFeed(img) {
      if (!img.dataset.cam || !document.contains(img)) { img.dataset.looping = ''; return; }
      fetch('/snapshot/' + img.dataset.cam + '?t=' + Date.now())
        .then(r => r.ok ? r.blob() : null).then(b => {
          if (b) { const u = URL.createObjectURL(b); const p = img.dataset.url;
                   img.src = u; img.dataset.url = u; if (p) URL.revokeObjectURL(p); }
        }).catch(()=>{})
        .finally(() => setTimeout(() => pollFeed(img), 40));
    }
    function refreshSnaps() {
      // one self-sustaining snapshot-poll loop per tile (short requests that free
      // the socket — no permanent stream connections to exhaust the browser)
      document.querySelectorAll('img.wsnap').forEach(img => {
        if (img.dataset.cam && img.dataset.looping !== '1') {
          img.dataset.looping = '1'; pollFeed(img);
        }
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

    loadWall().then(refreshStatus).then(refreshSnaps);
    setInterval(refreshSnaps, 500);
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
