# Vigil — Pilot Playbook

How to run a real-world pilot of the self-hosted product. Goal: prove Vigil
catches real phones at a real checkpoint, learn where it struggles, and get
honest feedback from staff — with the least risk and effort.

---

## The one idea that decides success: placement

Vigil is only as good as what the camera can see. **Don't** try to spot phones
across a whole exam hall — that's the hardest possible case. **Do** put the camera
at a **chokepoint** where everyone passes close and the angle is good:

- the **doorway / entrance** to the exam block
- the **bag-drop** area
- a **corridor** everyone walks through
- the **exit** (to catch someone leaving mid-exam)

A phone 2 m from a doorway camera is easy. The same phone 15 m across a hall is
nearly impossible — for any system. Pick the close, busy, well-lit spot.

---

## Stage 0 — Dry run (at home, ~30 min, no permission needed)

Prove the whole loop works before involving anyone.

1. Run Vigil (`Vigil.command`), create your admin account.
2. Add your **Mac webcam** as one camera, and your **phone** (IP Webcam app) as a
   second — place the phone to mimic a "doorway" view of a spot 1–3 m away.
3. Walk past holding a phone at chest/face height. Confirm:
   - it detects and boxes the phone,
   - an **alert** appears with the cropped photo + location,
   - you can **Confirm / Dismiss**,
   - it shows up in the **Evidence Log**.
4. Tune (top of `app.py`, restart after changes):
   - too many false alarms → raise `CONFIDENCE` (0.5–0.6) or `REQUIRED_HITS` (4).
   - missing real phones → lower `CONFIDENCE` (0.4) ; keep `TILING = True` for range.

✅ Pass = it reliably flags a phone at your test checkpoint and ignores your face/hands.

---

## Stage 1 — One real checkpoint (at the uni, with permission)

Keep it tiny: **one camera, one location, one exam session.**

**Get permission first** (see the one-pager below). Then:

1. Put the Vigil computer near the checkpoint on the same network as the camera.
   - Easiest: use your **phone as the camera** (IP Webcam) aimed at the doorway,
     on the same WiFi/hotspot as the laptop — no need to touch uni CCTV yet.
   - Or, if allowed, add the uni camera's `rtsp://…` URL.
2. In Vigil: add the camera, name it + set the **location** (e.g. "Block A entrance").
3. Set the schedule in your head: run it only during the exam.
4. Give the invigilator the **alerts view** (log them in as an invigilator, or keep
   the dashboard on a screen they can glance at). Alerts beep + show the location.
5. Run the session. A human always confirms before anything official happens.

---

## Score it (simple scorecard)

Track these by hand during the pilot — this is your evidence it works:

| Metric | How to count |
|---|---|
| **Real phones caught** | phones actually present that Vigil flagged |
| **Missed** | phones a human saw that Vigil didn't |
| **False alarms** | Vigil flagged something that wasn't a phone |
| **Staff verdict** | did the invigilator find it helpful? (1 line each) |

Good pilot result ≠ perfect. It's: *caught most obvious phones, false alarms were
few and easy to dismiss, staff would use it again.*

---

## Getting permission (one-pager to bring)

Keep it short and honest. Tell them:

- **What it is:** software that watches an existing/temporary camera at a checkpoint
  and *alerts a staff member* if it thinks it sees a phone. It **does not** accuse
  or act on its own — a human decides.
- **Privacy:** it runs **on our own laptop**; **video stays on the device** and isn't
  uploaded anywhere. Only flagged snapshots are shown to the invigilator.
- **Scope:** one camera, one checkpoint, one session, as a test. Nothing on the
  university's systems is changed.
- **Ask:** permission to point a camera at [the doorway] during [exam] and have an
  invigilator try the alerts.

(Confirm your institution's rules on filming students. Exam halls are usually already
monitored, but get the green light in writing.)

---

## Demo without a live phone

To show the security office what it looks like before the real run, start Vigil in
demo mode — it seeds example alerts so the dashboard looks live:

```bash
VIGIL_DEMO=1 ./venv/bin/python -m uvicorn app:app --port 8000
```

---

## After the pilot

1. Look at the **scorecard** and the **Evidence Log** together.
2. Note *where* it missed (angle? distance? lighting?) — usually a placement fix.
3. If false alarms were tied to specific objects (a face, a badge), that's the
   signal to **fine-tune** on your own footage (`FINETUNING.md`) — the real fix.
4. Decide: expand to more checkpoints, or go for the cloud version (Phase C).

Start small, prove one checkpoint, then grow. One working doorway beats a
half-working hall every time.
