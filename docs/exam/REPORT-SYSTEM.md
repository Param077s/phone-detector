# Vigil Exams — how the report system works today

A complete description of the current exam-integrity report: what we measure, how raw
signals become a verdict, and how that verdict is drawn on screen. Written to be read
cold, with no access to the codebase, by someone proposing improvements.

Everything below describes the **live production behaviour** as of 29 July 2026.

---

## 1. Product context

Vigil Exams is a browser-based exam-integrity tool.

- A **teacher** creates an exam room and gets a 6-character code (e.g. `UXY2TE`).
- **Students** join with that code on their own laptop, in a normal browser tab.
- Each student's laptop runs computer-vision models **locally** (MediaPipe: a face
  landmarker + an object detector). Video is analysed on-device.
- **No video, audio, or images ever leave the student's machine.** Only tiny JSON
  "events" (a kind + a timestamp) and a presence status are sent to the server.
- The teacher watches a live wall during the exam, then reads a **report** afterwards.

This privacy property is the product's core promise, so any proposal that requires
uploading frames, video, or screenshots is off the table.

The report is the artefact that matters: it's what a teacher reads to decide whether a
student did something wrong, and potentially what gets shown at a disciplinary hearing.

---

## 2. Data model (PostgreSQL / Supabase, row-level security enforced)

```
exams          id, code, title, owner(teacher), status('open'|'closed'),
               created_at, closed_at, require_signin(bool)

participants   id, exam_id, user_id, name,
               status('ok'|'warn'|'alert'|'offline'),   -- live presence only
               joined_at, last_seen

events         id, exam_id, participant_id,
               kind(text), severity('info'|'warn'|'alert'),
               at(timestamptz), meta(jsonb),
               review('confirmed'|'dismissed'|null)

exam_notes     id, exam_id, owner, at, text      -- teacher's own observations
```

Notes:

- `events` is append-only from the student's side. Students can insert their own events
  and read their own back; only the exam owner can **update** `review`.
- There is **no exam start/end timestamp** for the monitoring window itself. We have
  `created_at` and `closed_at` on the exam, but students join at arbitrary times, and
  the report currently derives its time axis from the events themselves (see §5.3).
- `meta` is currently used for exactly one thing: the calibration quality record (§4.3).

---

## 3. What the student's machine actually measures

At setup the student is calibrated for ~4.5 s. We record the median of:

- `baseline` — vertical nose position relative to the eye line (head pitch reference)
- `baseGazeX`, `baseGazeY` — where the irises sit when looking at the screen
- `baseOpen` — eye openness (used to ignore blinks)

Then, ~11× per second (`DETECT_MS: 90`), we compute for the current frame:

- `faces` — how many faces are visible
- `drop` = `baseline − noseGap` → how far the head has tilted **down** from calibration
- `off` = radial distance of the current gaze from the calibrated gaze centre
  (`hypot(gazeX − baseGazeX, gazeY − baseGazeY)`) → how far the **eyes** have drifted,
  in any direction
- `blink` — if eye openness < `0.55 ×` calibrated openness, gaze is ignored for that frame

A separate, slower object-detection pass (every 700 ms) looks for a phone.

---

## 4. The ten event kinds

An event is only written when a condition has **held continuously** for a hold time.
This is what stops a single noisy frame becoming a flag.

| kind | label shown | severity | fires when | hold | cooldown |
|---|---|---|---|---|---|
| `look_away` | Looked away | warn | gaze drift `off > 0.14` (radial, from calibration) | 1.2 s | resets when `off < 0.084` |
| `head_down` | Looked down | warn | head pitch `drop > 0.14` | 3.5 s | resets when `drop < 0.08` |
| `face_absent` | Face not visible | warn | `faces == 0` | 5 s | — |
| `second_face` | Second face detected | alert | `faces >= 2` | 1.5 s | 15 s |
| `phone` | Phone detected | alert | object detector class matches /phone/ with score ≥ 0.45 | 0.7 s | 15 s |
| `camera_off` | Camera off | alert | video track ends / disabled | — | once per off-episode |
| `monitor_hidden` | Hid / left Vigil | alert | tab hidden ≥ 2 s (visibilitychange) | 2 s | 3 s |
| `left_exam` | Closed Vigil | alert | `pagehide` (sent as a keepalive beacon) | — | — |
| `virtual_cam` | Virtual camera | alert | camera label matches OBS/ManyCam/DroidCam/etc. | — | once at start |
| `calibrated` | (not a flag) | info | calibration finished — carries quality in `meta` | — | once |

Important nuances:

- `look_away` and `head_down` are **edge-triggered**: one event per episode of drifting,
  not one per frame. The student must return to baseline before it can fire again.
- `phone` and `second_face` re-fire at most every 15 s while the condition persists, so a
  phone held for 2 minutes produces ~8 events, not one.
- Detection thresholds are **fixed constants**, identical for every student and room.
  (A debug tuning panel exists, but is available only to the exam's owner previewing
  their own room — students can never loosen detection.)

### 4.3 Calibration quality (`calibrated` event `meta`)

At the end of calibration we grade the setup and store:

```json
{ "grade": "solid" | "fair" | "weak",
  "reasons": ["low light", "eyes moving during setup", ...],
  "luma": 128, "frames": 45 }
```

Reasons are derived from: average image brightness (`luma < 60` = low light,
`> 235` = strong backlight), how many frames actually saw a face during calibration,
and how much the gaze wandered during calibration. `solid` = 0 reasons, `fair` = 1,
`weak` = 2+.

This is **currently informational only** — it is displayed but does not affect scoring.

---

## 5. How events become the report

### 5.1 Filtering

1. `calibrated` events are separated out — they are context, never flags.
2. Events with `review = 'dismissed'` are excluded from counts, risk score, and bands
   (but still render, struck through, so the record stays honest).

### 5.2 Risk score and bands

Each remaining event adds a fixed weight:

```
second_face 5   phone 5   virtual_cam 5
left_exam   4
monitor_hidden 3   camera_off 3
face_absent 1.5
look_away   1   head_down 1
```

Score is a **plain sum**. Bands:

```
score >= 10 → high      score >= 4 → medium
score  >  0 → low       score == 0 → clear
```

Students are sorted by score, descending. "Clear" students collapse into a single
summary row.

### 5.3 Episodes (display-level grouping)

Consecutive events **of the same kind** whose gap is ≤ **90 seconds** merge into one
"episode":

```
04:24:36 look_away ┐
04:24:45 look_away ├─→ one episode: 4×, spanning 40 s
04:25:02 look_away │
04:25:16 look_away ┘
```

An episode shows one row, and Confirm/Dismiss applies to **all** its underlying events at
once. This grouping is computed at render time and **not persisted** — the 90 s constant
is a UI decision, not stored data.

Note: the risk score is still computed **per event**, not per episode. Four glances in
40 s score 4, the same as four glances spread across an hour.

### 5.4 The timeline strip

Each student card has a horizontal strip:

- The **time window is shared across every student** in the exam, so strips line up and
  can be compared vertically.
- The window is derived from the **first and last event in the whole exam**, padded, with
  a minimum width of 10 minutes. It is *not* the real exam duration — if nobody flagged
  in the first 15 minutes, those minutes don't exist on the axis.
- Each event is a tick. Alert-severity ticks are red, warn ticks amber. Dismissed ticks
  fade to 22 % opacity.
- Episodes of 3 or more events also paint a soft shaded "burst" band behind the ticks.

### 5.5 The auto-written sentence

One plain-English line per student, generated from the episode set:

> Mostly **phone detected** — 14 times. The worst run was around **11:09 PM**.

Logic: find the most frequent event kind, report its total count, then either name the
time of its largest episode, or say "Spread out, with no single bad stretch" if no
episode has more than one event.

### 5.6 Review workflow

- Every episode has Confirm (✓) / Dismiss (✕).
- A sticky bar shows `N of M reviewed` with a progress bar.
- Keyboard triage: `↑`/`↓` (or `j`/`k`) move a highlight, `C` confirms, `X` dismisses,
  and the highlight advances automatically.
- Dismissing removes the events from the score, which can re-band the student and
  re-sort the list live.
- **Confirming currently has no scoring effect** — it is a visual mark only.

### 5.7 Other report sections

- **Setup badge** — a small chip on the student's card, shown **only when calibration was
  `fair` or `weak`**, with the reasons on hover. A solid setup shows nothing.
- **Invigilator notes** — the teacher can type timestamped observations during the live
  exam ("phone buzz, back left"). They appear as their own section in the report, beside
  the machine's flags, and in the CSV.
- **Exports** — CSV columns are `Student, Event, Count, Start, End, Review` (one row per
  episode, plus note rows). "Save as PDF" uses the browser print stylesheet, which hides
  the review buttons and appends a sign-off block (reviewed-by / signature / date) plus a
  line stating flags are aids to human judgement.

### 5.8 Two audiences, one engine

- **Teacher view** — all students, risk bands, review controls, notes, exports.
- **Student view** (`?as=student`) — their own card only: the same strip, same episodes,
  same narrative, no review controls, no notes, no other students. This is deliberate:
  the student sees exactly what the teacher sees about them.

### 5.9 Live behaviour

While the exam is `open`, the report subscribes to Postgres changes on `events`,
`participants`, `exam_notes` and the exam row itself, and redraws (debounced 600 ms). A
"Live" pill shows, and disappears the moment the teacher closes the exam.

---

## 6. Design constraints (please don't propose breaking these)

1. **No video/images off-device, ever.** The report can never show footage or stills.
2. Detection must not be loosenable by the student.
3. The visual language is a calm, light, monochrome "paper" aesthetic: near-white
   background, ink text, colour used sparingly and only semantically
   (green = ok, amber = warn, red = alert). No decorative colour.
4. Flags are **aids to human judgement**, never automated accusations. The wording must
   never assert cheating.
5. It must stay a static site + Supabase — no server-side rendering or background jobs.

---

## 7. Known weaknesses / open questions

These are the things we are least happy with, and where suggestions are most welcome.

1. **The risk score is an unnormalised sum.** A 3-hour exam accumulates far more points
   than a 45-minute one, but the band thresholds (4, 10) are absolute. Long exams will
   push everyone into "high". Should score be per-hour? Per-event-type capped?
   Duration-weighted?

2. **Episodes are cosmetic; scoring is per-event.** Four glances in 40 seconds probably
   means something different from four glances across an hour, but they score identically.
   Should the score be computed over episodes rather than events?

3. **No class-relative context.** If every student looked away at 11:18, that's almost
   certainly a room event (an announcement, a door) — not fifteen cheaters. The report
   has no notion of "normal for this room", so it can't tell an outlier from a crowd.

4. **Calibration quality is measured but unused.** A student flagged 20× for `look_away`
   on a `weak` setup is much weaker evidence than the same on a `solid` one. Should weak
   calibration discount the gaze-based flags, or at least visibly caveat the band?

5. **The time axis isn't the exam.** It spans first→last flag, so idle stretches vanish
   and two exams aren't comparable. We'd need a real monitoring start/end per student.

6. **`confirm` does nothing numerically.** It marks a flag as real but doesn't raise the
   score, so a reviewed report and an unreviewed one score the same.

7. **Thresholds are global constants.** No per-exam sensitivity, no adaptation to webcam
   quality, no per-student normalisation.

8. **Phone detection is a generic object detector at 0.45 confidence.** False positives
   (a dark rectangle, a wallet, a calculator) are plausible and would be indistinguishable
   from a real phone in the report.

9. **Scale.** Everything renders into one DOM at once; a 30-student exam with hundreds of
   episodes is a very long page with no virtualisation, no search, no filtering by kind.

10. **No student voice.** The student sees their report but has no way to contest a flag,
    and the teacher has no field to record the outcome of a conversation.

11. **Times render in the viewer's local timezone**, not the exam's — a teacher reviewing
    from another timezone sees shifted clock times.

12. **Severity vs weight are two parallel concepts** (`severity` on the row, `WEIGHT` in
    the client) that can drift apart.

---

## 8. What a good proposal looks like

We're most interested in changes that make the report **easier to act on**, not
richer in data. The report should let a teacher answer, in under a minute:

- Who actually needs my attention?
- Is this one bad stretch, or a pattern?
- Was this a room-wide moment or this student alone?
- How confident should I be, given how good their camera setup was?
- What do I do next, and what do I hand over if this escalates?
