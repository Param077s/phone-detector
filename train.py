"""
train.py — fine-tune YOLO on YOUR labeled phone dataset.
========================================================

This is the real, permanent accuracy fix: it teaches the model your actual
phones and (just as important) that faces / lips / logos are NOT phones.

Before running you need a LABELLED dataset in YOLO format with a data.yaml
(see FINETUNING.md — a free tool like Roboflow makes this in minutes).

Usage:
    python train.py                      # uses dataset/data.yaml
    python train.py path/to/data.yaml    # or point it anywhere

When it finishes it prints the path to the best model, e.g.
    runs/detect/train/weights/best.pt
Put that path into MODEL_NAME at the top of app.py and restart — done.
"""

import sys
from ultralytics import YOLO

data = sys.argv[1] if len(sys.argv) > 1 else "dataset/data.yaml"

# Start from the pretrained medium model and specialise it on your data.
model = YOLO("yolo11m.pt")

# device: 'mps' uses the Mac GPU; ultralytics falls back to CPU if needed.
try:
    import torch
    device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
except Exception:
    device = "cpu"

print(f"Fine-tuning on {data}  (device: {device})")
results = model.train(
    data=data,
    epochs=60,
    imgsz=640,
    patience=15,        # stop early if it stops improving
    device=device,
)

print("\nDone! Your fine-tuned model is at the 'best.pt' path shown above.")
print("Set MODEL_NAME in app.py to that path and restart Vigil.")
