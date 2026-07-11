# Fine-tuning Vigil (the real fix for false positives)

The pretrained model learned "phone" from clean internet photos, so it sometimes
confuses **lips, logos, hands, door handles** for phones. The permanent fix is
**fine-tuning**: showing YOLO a few hundred photos from *your own setup*, with the
phones marked — and crucially, letting it see faces/objects that are **not** phones.

This is the single biggest accuracy jump you can make.

---

## ⚡ Fastest path — NO manual labeling (recommended)

`build_dataset.py` builds the whole dataset automatically. You just capture two
short clips; the labels are generated for you.

```bash
source venv/bin/activate

python build_dataset.py phone      # hold/move a phone in view;  Ctrl+C to stop (~100 shots)
python build_dataset.py nophone    # show your FACE, mouth, hands, objects — NO phone;  Ctrl+C
python build_dataset.py finish     # writes dataset/data.yaml

python train.py dataset/data.yaml  # fine-tune (I can run this part for you)
```

Then set `MODEL_NAME` in `app.py` to the `best.pt` path it prints, and restart.

- The **no-phone** clip is the magic: it teaches the model your face/mouth are NOT
  phones, which is exactly what stops the false alarms you saw.
- Point at your phone camera instead of the webcam with
  `VIGIL_CAMERA="http://192.168.1.5:8080/video"` before the command.

That's it. The manual-labeling route below still exists if you ever want maximum
control, but the fast path above is enough to fix the false positives.

---

## Manual route (maximum control)

### Step 1 — Collect photos (5–10 min)

```bash
source venv/bin/activate

# from the Mac webcam:
python collect.py

# ...or from your phone / IP camera:
VIGIL_CAMERA="http://192.168.1.5:8080/video" python collect.py
```

While it runs:
- Show a phone at **many angles, distances, in a hand, on a desk, tilted, partly hidden.**
- ALSO capture lots of **non-phone** scenes: your **face and mouth**, hands, wallet,
  calculator, the room. These "negatives" are what stop the false alarms.

Aim for **200–500 images**. They're saved to `dataset/images/`. Press Ctrl+C to stop.

---

## Step 2 — Label them (the one manual part)

Use a **free** labelling tool — easiest is **Roboflow** (web, no install):

1. Create a free project at roboflow.com → "Object Detection".
2. Upload everything from `dataset/images/`.
3. Draw a box around **every phone**. On face/mouth/object photos, draw **nothing**
   (those become negatives automatically). Use ONE class, name it `phone`.
4. Generate → **Export** → format **"YOLOv11"** (or "YOLOv8") → download the zip.
5. Unzip it into this folder so you have `dataset/data.yaml`, `dataset/train/`, etc.

(Prefer offline tools? **LabelImg** or **CVAT** work the same way — export YOLO format.)

Tips for a good model:
- More variety > more quantity. Different lighting, angles, people.
- Include ~30% pure-negative images (faces/objects, no phone) — this is what kills
  the lips/mouth false positives.

---

## Step 3 — Train

```bash
python train.py dataset/data.yaml
```

It fine-tunes for a while (faster on the Mac GPU). When done it prints a path like:

```
runs/detect/train/weights/best.pt
```

---

## Step 4 — Use your model

Open `app.py`, set:

```python
MODEL_NAME = "runs/detect/train/weights/best.pt"
```

Restart Vigil. (The app auto-detects the `phone` class, so nothing else to change.)

That's it — Vigil now runs on a model trained for *your* cameras and conditions,
and the lips/logo/door-handle false alarms should largely disappear.

---

## How much does it help?

- Pretrained model: good on clear phones, occasional weird false positives.
- Fine-tuned on ~300 of your images: sharply better on *your* angles, and it learns
  your specific false-alarm objects are not phones.

Redo Steps 1–3 anytime with more images to keep improving it.
