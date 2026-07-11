# Vigil

AI phone-detection for exams and secure areas. Vigil watches your cameras (webcam,
phone, or CCTV), flags phones in real time, and alerts a person — with a cropped
photo and the location — for them to confirm. Everything runs on your own computer;
your video never leaves the building.

## Install (no coding needed)

**Just double-click the launcher for your system** — it installs everything the
first time, then opens Vigil in your browser:

- **Mac:** `Vigil.command`
- **Windows:** `Vigil-Windows.bat`
- **Linux:** `./Vigil-Linux.sh`

First launch asks you to create an **admin account**. Full step-by-step: see
[INSTALL.md](INSTALL.md).

> Want to hand Vigil to someone else? Run `make-release.command` to build a
> shareable `Vigil.zip` — they unzip it and double-click the launcher.

## What it does

- **Live monitor** — many cameras at once, phones boxed in real time (with tiling
  for spotting phones far away).
- **Alerts** — a phone triggers an alert card with a cropped photo + location; a
  human clicks Confirm or Dismiss (the AI never accuses on its own).
- **Evidence log** — a searchable, timestamped history for disputes.
- **Accounts & roles** — admins manage cameras and users; invigilators just
  receive alerts.
- **Notifications** — a beep + desktop notification on each new detection.

## Cameras

Add a camera from **+ Add camera**: leave the address blank for this computer's
webcam, or paste a stream URL:
- **Phone (test):** the free **IP Webcam** app → `http://<phone-ip>:8080/video`
  (phone and computer on the same WiFi).
- **CCTV:** an `rtsp://…` URL from the camera.

## Accuracy

Vigil ships with a solid general model. To make it sharper for *your* cameras and
stop specific false alarms, fine-tune it on your own footage — see
[FINETUNING.md](FINETUNING.md).

## Tuning (top of `app.py`)

`CONFIDENCE`, `REQUIRED_HITS` (false-alarm control), `IMG_SIZE`, `TILING` /
`TILE_COLS` / `TILE_ROWS` (range vs speed), `MODEL_NAME` (which model to use).

## For developers

It's a FastAPI + Ultralytics YOLO + OpenCV app (`app.py`), SQLite for the evidence
log and users. Run directly with:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app:app --port 8000
```

Runs on Apple Silicon GPU (MPS) automatically when available.
