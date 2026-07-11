# Installing Vigil (no coding needed)

Vigil watches your cameras and alerts you when it spots a phone. Setup is one
double-click — Vigil installs everything it needs the first time.

---

## Mac

1. **Double-click `Vigil.command`.**
   - The first time, macOS may say *"unidentified developer."* Right-click the
     file → **Open** → **Open**. You only do this once.
2. First run: it downloads and installs Vigil's components (~2 GB, 5–15 minutes,
   **one time only** — keep the window open).
3. Your browser opens to Vigil automatically.
4. The first screen asks you to **create an admin account** — that's you. Done.

Every time after, just double-click `Vigil.command` and it opens instantly.

## Windows

1. **Double-click `Vigil-Windows.bat`.**
   - If Windows SmartScreen warns, click **More info → Run anyway**.
2. If it says Python is missing, it opens the download page — install Python and
   **tick "Add Python to PATH"**, then run it again.
3. First run installs components (~2 GB, one time). Then your browser opens.
4. Create your **admin account** on the first screen.

## Linux

Run `./Vigil-Linux.sh` in a terminal (it self-installs the first time).

---

## Using Vigil

- **Add a camera** (admin): click **+ Add camera**, give it a name + location, and
  either leave the address blank (to use this computer's webcam) or paste a camera
  URL. Phone as a test camera? Install the **IP Webcam** app and use the URL it
  shows plus `/video` (phone and computer must be on the same WiFi).
- **Alerts** appear on the right when a phone is detected — with a photo and the
  location. Click **Confirm** or **Dismiss**.
- **Evidence Log** keeps a searchable history of everything.
- **Users** (admin): add invigilators — they see the feeds and alerts but can't
  change the camera setup.

## Requirements

- A computer with a webcam or network cameras.
- Python 3 (the installer points you to it if it's missing).
- ~3 GB free disk space, and internet for the one-time setup.
- Works best on a machine with a decent GPU (Apple Silicon Macs are great).

## Tips

- To **stop** Vigil, close the window it opened (or press Control-C in it).
- Everything runs **on your own computer** — your video never leaves the building.
- To fine-tune accuracy for your cameras, see `FINETUNING.md`.
