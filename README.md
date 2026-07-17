# Vigil

AI phone-detection for exams and secure areas. Vigil watches your cameras (webcam,
phone, or CCTV), flags phones in real time, and alerts a person — with a cropped
photo and the location — for them to confirm. Everything runs on your own computer;
your video never leaves the building.

Vigil is a **native desktop app** — it opens in its own window. No Terminal, no
browser, no `localhost` to type.

## Install (no coding needed)

**Download it and open it:**

- **macOS** — download `Vigil.dmg`, open it, drag **Vigil** into **Applications**.
  First launch: **System Settings → Privacy & Security → Open Anyway** (a one-time
  step for unsigned apps).
- **Windows** — download `Vigil.zip`, unzip, run **Vigil.exe** (SmartScreen:
  **More info → Run anyway**).

First launch prepares the AI on-device, then asks you to create an **admin
account**. Full step-by-step: see [INSTALL.md](INSTALL.md).

**Check for updates** any time from **Settings → Updates**.

> Running from source instead? The `Vigil.command` (macOS) / `Vigil-Windows.bat` /
> `Vigil-Linux.sh` launchers set up a venv and run the server. To build the native
> app locally, see `desktop.py` + `vigil.spec` (PyInstaller). CI builds and signs
> installers in `.github/workflows/release.yml`.

## What it does

- **Live monitor** — many cameras at once, phones boxed in real time (with tiling
  for spotting phones far away).
- **Alerts** — a phone triggers an alert card with a cropped photo + location; a
  human clicks Confirm or Dismiss (the AI never accuses on its own).
- **Evidence log** — a searchable, timestamped history for disputes.
- **Accounts & roles** — admins manage cameras and users; invigilators just
  receive alerts.
- **Notifications** — an in-app notification centre groups new detections; alerts
  never interrupt the live view.
- **Fast to drive** — command palette (⌘K / Ctrl-K), keyboard shortcuts (press
  `?`), evidence multi-select + CSV export, light/dark themes.

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
