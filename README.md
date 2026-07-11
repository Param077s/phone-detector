# Phone Detector — Layer 0

The tiniest working version of our exam-security idea.
It watches the webcam and, when it sees a phone, it draws a box around it,
prints an alert, and saves a cropped photo into the `alerts/` folder.

Everything big later (real cameras, seats, dashboards, universities) is just
this same idea, scaled up. Get this working first.

---

## What you need
- A computer with a webcam
- **Python 3** installed (check with: `python3 --version`)

---

## Setup (do this once, each person on their own machine)

Open a terminal **inside this folder**, then run these lines one by one:

```bash
# 1) Make a private workspace for this project's tools
python3 -m venv venv

# 2) Turn it on   (Mac/Linux)
source venv/bin/activate
#    (on Windows it's:  venv\Scripts\activate )

# 3) Install YOLO + the camera library (this is a biggish download, be patient)
pip install -r requirements.txt
```

## Run it

```bash
python detect.py
```

A window opens showing your webcam. **Hold a phone up to the camera.**
You should see a green box appear around it, an `[ALERT]` line in the terminal,
and a photo saved in the `alerts/` folder. Press **q** to quit.

---

## How the code works (read `detect.py` — it's fully commented)

The whole thing is a loop that repeats many times per second:

1. Grab one photo from the webcam.
2. Hand it to YOLO → YOLO says where any phones are.
3. For each phone: draw a box, and (every couple of seconds) save a cropped photo + print an alert.
4. Show the live window.
5. Repeat.

**YOLO is only the "eyes."** All the rest — the alert, the cropping, the saving —
is *our* code. That's the important lesson: the product is the logic we write
*around* YOLO, not YOLO itself.

### Things to try together (change a number, re-run, see the effect)
- `CONFIDENCE` — lower it to `0.25` (more sensitive) or raise to `0.6` (stricter).
- Point it at a calculator or wallet — does it false-alarm? (This is why real systems keep a human in the loop.)
- Move the phone far away — notice how detection gets harder at distance. (That's the camera-angle lesson from our plan.)

---

## Working as a team (both of us, equally)

We use **git + GitHub** so we both have the same code and can see each other's changes.

**One-time, one of us creates the shared repo:**
```bash
# after installing GitHub CLI, or create it on github.com in the browser
gh repo create phone-detector --private --source=. --push
```
Then add the other brother as a **collaborator** in the repo's Settings → Collaborators.

**Everyday routine (both of us):**
```bash
git pull            # get the latest before you start working
# ... make your changes ...
git add -A
git commit -m "what I changed"
git push            # share your changes
```

Rule of thumb: **pull before you start, push when you finish.** Tell each other
what you're working on so you don't edit the same lines at the same time.

---

## Troubleshooting
- **"Could not open the webcam"** on Mac → the terminal needs camera permission:
  System Settings → Privacy & Security → Camera → allow your terminal app. Then re-run.
- **Error mentioning `yolo11n.pt`** → replace it in `detect.py` with `yolov8n.pt` (an older but very stable model).
- **First run is slow** → it's downloading YOLO's model file once. After that it's fast.

---

## What's next (Layer 1)
Once this works, we point it at a real camera feed instead of the webcam, add a
location tag, send the alert to a phone instead of just saving a photo, and put
it on a small dashboard. Same core loop — just wired to the real world.
