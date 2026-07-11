"""
collect.py — grab training photos from a camera to build a fine-tuning dataset.
================================================================================

Fine-tuning = teaching YOLO what a phone looks like IN YOUR REAL SETUP, so it
stops confusing lips / logos / door handles for phones. To do that we first need
photos from your actual cameras. This script saves them.

How to use:
    1. (Optional) point it at your phone/IP camera instead of the webcam:
           VIGIL_CAMERA="http://192.168.1.5:8080/video" python collect.py
       Otherwise it uses the Mac webcam.
    2. Move a phone around in view — different angles, distances, in a hand, on a
       desk. ALSO capture lots of NON-phone scenes: your face, mouth, hands,
       objects. Those "negatives" are what teach it NOT to false-alarm.
    3. Press Ctrl+C when you have a few hundred images.
    4. Label them and train (see FINETUNING.md).

Images are saved to  dataset/images/.
"""

import os
import time
import cv2

SOURCE = os.getenv("VIGIL_CAMERA", "0")     # "0" = webcam, or a stream URL
OUT_DIR = "dataset/images"
EVERY = 0.8                                  # seconds between saved frames

os.makedirs(OUT_DIR, exist_ok=True)
src = int(SOURCE) if SOURCE.isdigit() else SOURCE
cap = cv2.VideoCapture(src)

print(f"Capturing from {SOURCE} every {EVERY}s -> {OUT_DIR}/")
print("Show a phone at many angles/distances, AND capture non-phone scenes (face, hands, objects).")
print("Press Ctrl+C to stop.\n")

count, last = 0, 0.0
try:
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.2)
            continue
        now = time.time()
        if now - last >= EVERY:
            last = now
            count += 1
            path = os.path.join(OUT_DIR, f"img_{int(now)}_{count}.jpg")
            cv2.imwrite(path, frame)
            print(f"saved {path}")
except KeyboardInterrupt:
    pass
finally:
    cap.release()
    print(f"\nDone. {count} images in {OUT_DIR}/. Next: label them (see FINETUNING.md).")
