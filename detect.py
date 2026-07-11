"""
Layer 0 — Phone Detector (proof of concept)
============================================

What this does, in one line:
    Watch the webcam -> if YOLO sees a phone -> draw a box, shout an alert,
    and save a cropped photo of the phone into the "alerts" folder.

This is the smallest possible version of our whole product. Everything big
(cameras, seats, dashboards, universities) is just this same idea, scaled up.

Read the comments top-to-bottom and you'll understand exactly what happens.
Press the 'q' key on the video window to quit.
"""

import cv2                      # OpenCV: grabs frames from the webcam + draws on them
import time                     # so we don't save 30 photos per second
import os                       # to make the "alerts" folder
from datetime import datetime   # for timestamped filenames
from ultralytics import YOLO    # this is YOLO — our "eyes"


# ---------------------------------------------------------------------------
# SETTINGS you can safely play with (change a number, re-run, see what happens)
# ---------------------------------------------------------------------------
CONFIDENCE     = 0.40     # how sure YOLO must be (0.0 - 1.0). Lower = more sensitive
                          # but more false alarms. Higher = stricter, misses more.
PHONE_CLASS    = 67       # in YOLO's built-in list of things it knows, 67 = "cell phone"
ALERT_COOLDOWN = 2        # seconds to wait between saved alert photos
ALERTS_FOLDER  = "alerts" # where cropped photos of detected phones get saved


# ---------------------------------------------------------------------------
# SETUP (runs once when you start the program)
# ---------------------------------------------------------------------------

# Make a folder to store the cropped photos (does nothing if it already exists)
os.makedirs(ALERTS_FOLDER, exist_ok=True)

# Load YOLO's "brain". The first time you run this, it downloads a small file
# (~5 MB) and saves it. After that, it loads instantly and works fully offline.
print("Loading YOLO... (first run downloads the model, ~5 MB, then it's saved)")
model = YOLO("yolo11n.pt")

# Open the webcam. 0 = your built-in camera. If you have several, try 1, 2, ...
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("Could not open the webcam. Is it connected and is camera access allowed?")
    raise SystemExit

print("Running! Hold a phone up to the camera. Press 'q' in the window to quit.")
last_alert_time = 0   # remembers when we last saved a photo


# ---------------------------------------------------------------------------
# THE MAIN LOOP (repeats many times per second, forever, until you press 'q')
# ---------------------------------------------------------------------------
while True:

    # 1) Grab one photo (frame) from the webcam
    ok, frame = cap.read()
    if not ok:
        break  # camera stopped giving us frames

    # 2) Ask YOLO: "find only phones (class 67) in this frame, above our confidence"
    #    'verbose=False' just keeps the terminal quiet.
    results = model(frame, classes=[PHONE_CLASS], conf=CONFIDENCE, verbose=False)

    # 3) Go through each phone YOLO found (there might be zero, one, or several)
    for box in results[0].boxes:

        # The four corners of the rectangle around the phone
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        confidence = float(box.conf[0])

        # Crop just the phone area out of the CLEAN frame (before we draw on it)
        crop = frame[y1:y2, x1:x2].copy()

        # Draw a green box + label on the live video so we can SEE the detection
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"PHONE {confidence:.0%}", (x1, max(y1 - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # ----- THIS is the "alert" part (our product in miniature) -----
        # Only fire an alert every few seconds, not on every single frame.
        now = time.time()
        if now - last_alert_time > ALERT_COOLDOWN and crop.size > 0:
            last_alert_time = now
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{ALERTS_FOLDER}/phone_{stamp}.jpg"
            cv2.imwrite(filename, crop)                       # save the evidence photo
            print(f"[ALERT] Phone detected ({confidence:.0%}) -> saved {filename}")

    # 4) Show the live window (with any boxes drawn on it)
    cv2.imshow("Layer 0 - Phone Detector  (press q to quit)", frame)

    # 5) If the 'q' key is pressed, stop
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


# ---------------------------------------------------------------------------
# CLEAN UP when we quit
# ---------------------------------------------------------------------------
cap.release()
cv2.destroyAllWindows()
print("Stopped. Check the 'alerts' folder for the phone photos it saved.")
