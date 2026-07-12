"""
build_dataset.py — build a fine-tuning dataset with ZERO manual labeling.
=========================================================================

The trick: you capture two kinds of clips and the labels are made automatically.

  1) PHONE clips    — hold a phone clearly in view. The current model auto-marks
                      where the phone is (you're holding one, so it's an easy call).
  2) NO-PHONE clips — show your FACE, MOUTH, hands, objects — with NO phone.
                      These become "negative" examples that teach the model your
                      face is NOT a phone. THIS is what fixes the false positives.

Usage (venv active, from the project folder):

    python build_dataset.py phone      # then hold/move a phone;  Ctrl+C to stop
    python build_dataset.py nophone    # then show face/objects;  Ctrl+C to stop
    python build_dataset.py finish     # splits the data + writes data.yaml

Then hand it back and training is one command:  python train.py dataset/data.yaml

Capturing from your phone/IP camera instead of the webcam:
    VIGIL_CAMERA="http://192.168.1.5:8080/video" python build_dataset.py nophone

Aim for ~100 phone shots and ~100 no-phone shots (varied angles/lighting).
"""

import os
import sys
import time
import glob
import random

import cv2

RAW_IMG = "dataset/_raw/images"
RAW_LBL = "dataset/_raw/labels"
SOURCE = os.getenv("VIGIL_CAMERA", "0")
LABEL_CONF = 0.45        # min confidence to auto-label a phone box


def _src():
    return int(SOURCE) if SOURCE.isdigit() else SOURCE


def capture(mode):
    os.makedirs(RAW_IMG, exist_ok=True)
    os.makedirs(RAW_LBL, exist_ok=True)

    model, phone_cls = None, 67
    if mode == "phone":
        from ultralytics import YOLO
        print("Loading model for auto-labeling...")
        model = YOLO("yolo11m.pt")
        phone_cls = next((i for i, n in model.names.items() if "phone" in str(n).lower()), 67)

    cap = cv2.VideoCapture(_src())
    hint = "Hold a phone clearly in view." if mode == "phone" else "Show face / mouth / hands / objects — NO phone."
    print(f"[{mode}] capturing from {SOURCE}. {hint}  Press Ctrl+C to stop.\n")

    n, last = 0, 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.2)
                continue
            now = time.time()
            if now - last < 0.7:
                continue
            last = now

            h, w = frame.shape[:2]
            lines = []
            if mode == "phone":
                res = model(frame, classes=[phone_cls], conf=LABEL_CONF, verbose=False)
                boxes = res[0].boxes
                if len(boxes) == 0:
                    continue                        # no phone found -> skip (keep labels clean)
                best = max(boxes, key=lambda b: float(b.conf[0]))   # the held phone
                x1, y1, x2, y2 = map(float, best.xyxy[0])
                xc, yc = ((x1 + x2) / 2) / w, ((y1 + y2) / 2) / h
                bw, bh = (x2 - x1) / w, (y2 - y1) / h
                lines.append(f"0 {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
            # nophone mode -> lines stays empty (a pure negative example)

            stamp = f"{mode}_{int(now)}_{n}"
            cv2.imwrite(f"{RAW_IMG}/{stamp}.jpg", frame)
            with open(f"{RAW_LBL}/{stamp}.txt", "w") as f:
                f.write("\n".join(lines))
            n += 1
            print(f"saved {stamp}  ({'phone labeled' if lines else 'negative'})")
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        print(f"\n[{mode}] done: {n} images saved.")


def finish():
    imgs = sorted(glob.glob(f"{RAW_IMG}/*.jpg"))
    if len(imgs) < 20:
        print(f"Only {len(imgs)} images so far — capture more first (aim for ~200 total).")
        return
    random.seed(0)
    random.shuffle(imgs)
    val_n = max(1, int(len(imgs) * 0.2))
    val = set(imgs[:val_n])

    for split in ("train", "val"):
        os.makedirs(f"dataset/images/{split}", exist_ok=True)
        os.makedirs(f"dataset/labels/{split}", exist_ok=True)

    for img in imgs:
        split = "val" if img in val else "train"
        base = os.path.splitext(os.path.basename(img))[0]
        os.replace(img, f"dataset/images/{split}/{base}.jpg")
        lbl = f"{RAW_LBL}/{base}.txt"
        if os.path.exists(lbl):
            os.replace(lbl, f"dataset/labels/{split}/{base}.txt")

    root = os.path.abspath("dataset")
    with open("dataset/data.yaml", "w") as f:
        f.write(f"path: {root}\ntrain: images/train\nval: images/val\nnames:\n  0: phone\n")

    print(f"\nDataset ready: {len(imgs) - val_n} train / {val_n} val images.")
    print("Now run:  python train.py dataset/data.yaml")


def _countdown(msg, secs=5):
    print("\n" + "=" * 60)
    print(msg)
    print("=" * 60)
    for i in range(secs, 0, -1):
        print(f"   starting in {i}…", end="\r", flush=True)
        time.sleep(1)
    print("   ▶ RECORDING NOW — keep going!            ")


def _phase(model, phone_cls, label_it, seconds, interval=0.3):
    """Capture one timed phase. label_it=True auto-labels the phone; else negative."""
    os.makedirs(RAW_IMG, exist_ok=True)
    os.makedirs(RAW_LBL, exist_ok=True)
    cap = cv2.VideoCapture(_src())
    for _ in range(10):                      # webcam warm-up
        cap.read()
    n, kept, last, t_end = 0, 0, 0.0, time.time() + seconds
    while time.time() < t_end:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05); continue
        now = time.time()
        if now - last < interval:
            continue
        last = now
        h, w = frame.shape[:2]
        lines = []
        if label_it:
            res = model(frame, classes=[phone_cls], conf=0.5, imgsz=640, verbose=False)
            boxes = res[0].boxes
            if len(boxes) == 0:
                remaining = int(t_end - now)
                print(f"   (no phone seen — hold it clearer)   {remaining}s left     ", end="\r")
                continue
            b = max(boxes, key=lambda x: float(x.conf[0]))
            x1, y1, x2, y2 = map(float, b.xyxy[0])
            lines.append(f"0 {((x1+x2)/2)/w:.6f} {((y1+y2)/2)/h:.6f} {(x2-x1)/w:.6f} {(y2-y1)/h:.6f}")
        stamp = f"{'phone' if label_it else 'neg'}_{int(now)}_{n}"
        cv2.imwrite(f"{RAW_IMG}/{stamp}.jpg", frame)
        open(f"{RAW_LBL}/{stamp}.txt", "w").write("\n".join(lines))
        n += 1; kept += 1
        remaining = int(t_end - now)
        print(f"   captured {kept} frames   {remaining}s left            ", end="\r")
    cap.release()
    print(f"\n   ✓ phase done — {kept} frames saved.")
    return kept


def guided():
    """One-click, timed, two-phase capture that auto-labels and finishes."""
    import shutil
    shutil.rmtree("dataset", ignore_errors=True)          # start fresh — no old/bad data
    from ultralytics import YOLO
    print("Loading the labeling model…")
    model = YOLO("yolo11x.pt")
    phone_cls = next((i for i, n in model.names.items() if "phone" in str(n).lower()), 67)

    _countdown("PHASE 1 of 2  —  HOLD YOUR PHONE UP.\n"
               "Move it around: near, far, tilted, in your hand, both sides of the frame,\n"
               "in different lighting. Keep the phone visible the whole time (~75s).", 6)
    p = _phase(model, phone_cls, label_it=True, seconds=75)

    _countdown("PHASE 2 of 2  —  PUT THE PHONE AWAY. Show EVERYTHING that is NOT a phone:\n"
               "your face, mouth, hands, the bed/headboard, books, remote, the room, empty desk.\n"
               "This is what teaches Vigil to stop false-alarming (~75s).", 6)
    ng = _phase(model, phone_cls, label_it=False, seconds=75)

    print(f"\nCaptured {p} phone frames + {ng} non-phone frames.")
    finish()
    print("\n" + "=" * 60)
    print("  ✓ ALL DONE. Go back to Claude and say: \"train it\"")
    print("=" * 60)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "guided":
        guided()
    elif mode in ("phone", "nophone"):
        capture(mode)
    elif mode == "finish":
        finish()
    else:
        print(__doc__)
