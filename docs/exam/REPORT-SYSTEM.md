# Vigil Exams — how the report system works today

A complete description of the current exam-integrity report: what we measure, how raw
signals become a verdict, and how that verdict is drawn on screen. Written to be read
cold, with no access to the codebase, by someone proposing improvements.

Everything below describes the **live production behaviour** as of 29 July 2026, after
the report redesign described in `REPORT-REDESIGN.md` was built. That file records the
design decisions and the directions that were rejected; this file records what exists.

---

## 1. Product context

Vigil Exams is a browser-based exam-integrity tool.

- A **teacher** creates an exam room and gets a 6-character code (e.g. `UXY2TE`).
- **Students** join with that code on their own laptop, in a normal browser tab.
- Each student's laptop runs computer-vision models **locally** (MediaPipe: a face
  landmarker + an object detector). Video is analysed on-device.
- **No video, audio, or images ever leave the student's machine.** Only tiny JSON
  "events" (a kind + a timestamp + occasionally a small `meta` object) and a presence
  status are sent to the server.
- The teacher watches **the room** live during the exam, then reads a one-page
  **findings document** afterwards.

This privacy property is the product's core promise, so any proposal that requires
uploading frames, video, or screenshots is off the table.

The findings document is the artefact that matters: it's what a teacher reads to decide
whether a student did something wrong, and potentially what gets shown at a disciplinary
hearing.

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
               review('confirmed'|'dismissed'|'discuss'|null)

exam_notes     id, exam_id, owner, at, text      -- teacher's own observations
```

Notes:

- `events` is append-only from the student's side. Students can insert their own events
  and read their own back; only the exam owner can **update** `review`.
- `review = 'discuss'` requires migration **v9**. Until it is applied the column only
  accepts `'confirmed'|'dismissed'`, and the findings document says so in place rather
  than failing silently.
- There is **no exam start/end timestamp for the monitoring window itself**. We have
  `created_at` and `closed_at` on the exam; the findings document uses those as its time
  window, while the full-record view still derives its time axis from the events (§5.9).
- `meta` now carries exactly two things: the calibration quality record on a `calibrated`
  event (§4.3) and the detector's confidence on a `phone` event (§4.4).

### 2.1 Migrations

| | what it adds | required by |
|---|---|---|
| v6 | `events.review` + owner-update policy | Confirm / Dismiss |
| v7 | `exam_notes` table | invigilator notes |
| v8 | `exams` on the realtime publication | instant close/reopen |
| v9 | widens `events_review_check` to allow `'discuss'` | the third verdict |

Every surface degrades gracefully when a migration hasn't been run — the note field
simply doesn't appear, the third verdict reports that it isn't available, and so on.

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

## 4. The eleven event kinds

An event is only written when a condition has **held continuously** for a hold time.
This is what stops a single noisy frame becoming a flag.

| kind | label shown | severity | fires when | hold | cooldown |
|---|---|---|---|---|---|
| `look_away` | Looked away | warn | gaze drift `off > 0.14`, sustained direction **not** downward | 1.2 s | resets when `off < 0.084` |
| `eyes_down` | Eyes on the desk | warn | the same drift, but sustained **downward** | 1.2 s | resets when `off < 0.084` |
| `head_down` | Looked down | warn | head pitch `drop > 0.14` | 3.5 s | resets when `drop < 0.08` |
| `face_absent` | Face not visible | warn | `faces == 0` | 5 s | — |
| `second_face` | Second face detected | alert | `faces >= 2` | 1.5 s | 15 s |
| `phone` | Phone detected | alert | ≥3 of the last 5 detection passes match /phone/ at ≥ 0.45, one of them ≥ 0.60 | ~1.4 s | 15 s |
| `camera_off` | Camera off | alert | video track ends / disabled | — | once per off-episode |
| `monitor_hidden` | Hid / left Vigil | alert | tab hidden ≥ 2 s (visibilitychange) | 2 s | 3 s |
| `left_exam` | Closed Vigil | alert | `pagehide` (sent as a keepalive beacon) | — | — |
| `virtual_cam` | Virtual camera | alert | camera label matches OBS/ManyCam/DroidCam/etc. | — | once at start |
| `calibrated` | (not a flag) | info | calibration finished — carries quality in `meta` | — | once |

Important nuances:

- `look_away`, `eyes_down` and `head_down` are **edge-triggered**: one event per episode
  of drifting, not one per frame. The student must return to baseline before it can fire
  again.
- `look_away` and `eyes_down` come from the **same** measurement at the same threshold —
  only the direction differs (§4.5). Splitting them changed no sensitivity and no volume
  of flags; it changed what each one is called and what it is worth.
- `phone` and `second_face` re-fire at most every 15 s while the condition persists, so a
  phone held for 2 minutes produces ~8 events, not one.
- `phone` requires **corroboration across passes**, not one confident frame (§4.4).
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

It still does **not affect scoring**. It is now surfaced in two places where it changes
how a reader should weigh a flag: as the caveat line in a live popup, and as the
evidence-quality segment of a finding (§5.6).

### 4.4 Phone detection: corroboration and confidence

The object detector is **generic** — it will call a wallet, a calculator or any dark
rectangle a phone often enough that a single confident frame means very little. But a
real phone in view is seen on pass after pass, while a false positive is sporadic. So a
`phone` event needs agreement across time, not one lucky frame:

- the detector runs every **700 ms**;
- a rolling window holds the last **5** passes;
- at least **3** of those must have matched at ≥ `0.45`;
- and at least one of them must have cleared **0.60**.

The window tolerates a dropped frame on a real phone without resetting the evidence, and
denies a case to one lucky frame on a wallet. It costs about a second of latency — a
phone is flagged after ~1.4 s of being visible rather than ~0.7 s.

The event carries the detector's own numbers:

```json
{ "score": 0.71, "frames": 4 }
```

`score` is the strongest confidence in the window; `frames` is how many passes agreed.
This is the **only real confidence number anywhere in the system.** Every other kind is
rule-based and has no confidence value; the report is required to say so rather than
invent one (§5.6).

### 4.5 Which way the eyes went

`off` is a radial distance, so it says how far the eyes drifted but not where to. Those
are very different facts. A drift **down** is, in almost every exam, the paper on the
desk. A drift **sideways** is a second screen, a neighbour's script, or a phone propped
beside the laptop.

Scoring them alike is what made an ordinary paper exam look suspicious, since reading
your own question sheet generated the same flag as staring at the next desk.

The horizontal and vertical components are accumulated across the 1.2 s hold — one noisy
frame must not decide it — and the flag is `eyes_down` when the downward component
dominates the sideways one by `GAZE_DOWN_RATIO` (1.2), otherwise `look_away`.

`eyes_down` carries weight **0.4**, the lowest in the set, against `look_away`'s 1. In a
paper exam it is close to what reading looks like, so it should register without
accumulating into an accusation. Both are ambient (§5.3), so both are scored as a rate.

The threshold and the hold are **unchanged**. This reclassifies flags; it does not raise
or lower how many are raised.

---

## 5. How events become the report

Two surfaces are the redesign — the live room and the findings document. A third, the
pre-redesign full record, is kept behind them as the underlying detail.

### 5.1 One shared reading

`exam-core.js` holds the whole interpretation layer. It talks to nothing — no network, no
DOM — so both surfaces read the same exam the same way and cannot drift apart.

`readExam(participants, events)` runs in this order, and the order matters:

1. `calibrated` events are separated out — they are context, never flags.
2. **Room-wide moments are found first** (§5.2).
3. Each student's **own** events are everything not absorbed by a room-wide moment.
4. Their **score** is the weighted sum over their own events, excluding `dismissed` ones.
5. **Findings** are built from the moments plus each student's own events (§5.4).

It returns `{ roster, students, moments, findings, clear, startT, endT }`.

### 5.2 Room-wide moments

If every student looks away at 11:18, that is almost certainly the room — a door, an
announcement, the invigilator walking past — and not fifteen people deciding to cheat
simultaneously. This was the system's biggest blind spot and it is computed entirely from
data that already existed.

- Group all events by `(kind, minute)` across the whole exam.
- A bucket becomes a room-wide moment when it contains **≥ 60 % of the roster** and
  **≥ 5 distinct students**. Exams smaller than 5 students never produce one.
- Adjacent minutes of the same kind merge, so a moment straddling 11:17:58 is one moment.

Consequences:

- Those events **stop counting toward the individual students' scores**, so a room-wide
  look-away no longer turns eighteen tiles amber.
- The moment becomes a **first-class finding** in the document, sitting beside a phone.
- Setting it aside is one action that writes `review = 'dismissed'` to every underlying
  event at once.

Thresholds are constants in `exam-core.js` (`ROOM_SHARE`, `ROOM_MIN`) and are not
configurable per exam.

### 5.3 Risk score and bands

Each kind still carries a fixed weight:

```
second_face 5   phone 5   virtual_cam 5
left_exam   4
monitor_hidden 3   camera_off 3
face_absent 1.5
look_away   1   head_down 1
```

What changed is that a score is no longer a plain sum, because a plain sum grows
with the length of the exam. Eleven glances away across two hours is what ordinary
people do; the same eleven in ten minutes is a pattern. With absolute bands at 4
and 10, a long exam pushed an entire class into the top band.

Flags are now split by how they behave over time:

- **Ambient** — `look_away`, `head_down`, `face_absent`. Scored as a **rate**, and
  the rate used is the *worse* of the whole sitting and the busiest 20 minutes in
  it, so a frantic two minutes isn't averaged into nothing by two calm hours
  around it. `AMBIENT_BUDGET_PER_HOUR = 4` weight-points per hour reads as
  ordinary; the score counts the excess.
- **Everything else** — scored absolutely, never divided by duration. A phone is a
  phone whether the exam ran forty minutes or three hours, and dividing would
  quietly hide the most serious thing in the room.

Repeats compress only where repetition is an artefact of the cooldown.
`phone` and `second_face` re-fire every 15 s for as long as the thing is visible,
so eight events is one phone held for two minutes — those compress
logarithmically. `look_away` and `head_down` are edge-triggered and must return to
baseline before firing again, so eleven of those really are eleven separate
drifts and they count linearly.

The window is per **student** (`joined_at` → `last_seen`), floored at 20 minutes so
nobody is judged on a rate measured over two, and capped at 12 hours so a missing
`last_seen` can't stretch the window across days and silently zero the score.

Bands are unchanged, and so is the meaning of the numbers at the edges:

```
score >= 10 → alert      score >= 4 → warn      score < 4 → quiet
```

Worked examples, all for one student:

| behaviour | exam | score | band |
|---|---|---|---|
| 11 glances, spread out | 2 h | 2.3 | quiet |
| 11 glances, spread out | 45 min | 4.5 | warn |
| 25 glances, spread out | 2 h | 3.8 | quiet |
| 11 glances in one 40 s burst | 2 h | 8.3 | warn |
| one phone episode (8 events) | 40 min | 20.0 | alert |
| one phone episode (8 events) | 3 h | 20.0 | alert |
| a single second face | 3 h | 5.0 | warn |

**`AMBIENT_BUDGET_PER_HOUR` is a guess.** The shape of the model is right — it is
duration-aware and burst-sensitive — but what a *normal* student's glance rate
actually is has never been measured, because Vigil has never run with a real
class. It is one constant in `exam-core.js` and should be retuned against the
first real exam's data.

The full-record view (§5.9) reads through the same core, so it inherits all of the
above. It keeps only its own four-word *vocabulary* for the same number
(`high / medium / low / clear` at 10, 4 and 0).

### 5.4 Findings — the document's unit

The unit is the **moment**, not the student. A finding is either:

- a **room-wide moment**, or
- one student's events **of a single kind**, taken together, whose raw weighted score
  reaches `FINDING_SCORE = 4` — the same bar as the old "medium" band.

Anything below that bar is not a finding and appears only in the full record. Findings
are sorted by score descending, then by time, and numbered `01`, `02`, … in that order,
so `01` is the thing that most needs reading.

Findings are built from **all** of a student's own events regardless of verdict, so a
finding that was considered and set aside stays on the page wearing its verdict. What a
verdict changes is the *score*, and therefore the clear list (§5.7).

### 5.5 Episodes (display-level grouping)

Consecutive events **of the same kind** whose gap is ≤ **90 seconds** merge into one
"episode":

```
04:24:36 look_away ┐
04:24:45 look_away ├─→ one episode: 4×, spanning 40 s
04:25:02 look_away │
04:25:16 look_away ┘
```

This grouping is computed at render time and **not persisted** — the 90 s constant is a
UI decision, not stored data. Episodes are what the findings appendix lists and what the
full record shows as one reviewable row. Scoring is still per **event**, not per episode.

### 5.6 Evidence quality

Each finding ends with one honest statement about how much weight its evidence carries.
There are exactly three possible answers, in priority order:

1. `detector 71% confident` — only when the underlying events carry real `meta.score`
   values, i.e. only for `phone`. The number is the mean of those scores.
2. `weak camera setup` / `fair camera setup` — when calibration was not solid.
3. `no confidence value` — everything else, said plainly.

**No confidence number is ever displayed that the system did not actually compute.** This
is a hard rule, not a preference: the document is meant to survive a disciplinary hearing.

### 5.7 Surface 1 — the live room (`live.html`)

What the teacher watches during the exam. Its job is ambient awareness, not analysis.

- Header: `AI AND ML · LIVE · 41 MINUTES IN` (small, faint, letterspaced), then
  `Your room` with `20 quiet · 4 worth a look` beside it.
- A 4-column grid of tiles. A **quiet** tile is a faint name and nothing else — this is
  most of the room and it is meant to look calm and unimportant. A **flagged** tile gets
  the semantic border colour, the name in full ink, and one short lowercase phrase
  (`phone, 8 times` / `eyes off screen, 4 times`). An offline tile dims and says so.
- Tiles are reconciled **in place** across redraws — classes and text change over a 600 ms
  fade, so the room never flashes and never re-flows under the teacher's eye.
- A single line at the bottom appears only when a room-wide moment exists, with a
  "See it" action.

**Tile → popup.** Pressing a tile morphs it into the popup (FLIP): the popup's content is
filled first, both rectangles are measured, the popup is parked scaled-and-translated onto
the tile with its content at `opacity: 0`, then released to identity over 340 ms with the
content fading in a beat behind. Closing reverses it. Backdrop is
`rgba(243,242,239,.72)`; backdrop click or Esc closes.

The popup is about **now**: live status (`Phone detected · a moment ago`, or
`Looking at screen · settled since 11:01` for a quiet student), the last few events
newest-first, a setup caveat only when calibration wasn't solid, and exactly one action —
**Add a note**. There is deliberately **no confirm/dismiss here**: reviewing is a
post-exam job and must not pull the teacher into paperwork mid-invigilation.

**Nothing interrupts.** If a flag lands elsewhere while a popup is open, the tile behind
it changes quietly and the teacher meets it on close. No toasts, no focus steal.

Invigilator notes are written from the popup (prefixed with the student's name) or from
"Note the room" in the header. Both land in `exam_notes` and appear in the full record.

> The old live wall — coloured status tiles plus a streaming "Live alerts" sidebar — was
> replaced by this. The sidebar is gone; a feed of red items fought the premise that
> nothing should interrupt.

### 5.8 Surface 2 — the findings document (`findings.html`)

What gets read once, decided, signed and filed. Teacher-only; a student who lands here is
sent to their own activity view instead.

Structure, in order, and nothing else:

1. Letterhead rule: Vigil mark + `EXAM INTEGRITY REPORT` right-aligned.
2. Exam title, then one grey line: `UXY2TE · 28 July 2026 · 11:01–11:42 PM · 24 students`.
   The window comes from `exams.created_at` → `closed_at`, so it is the real monitoring
   window; the meridiem is said once across the range.
3. Standfirst: `Five findings.` + muted `Twenty students finished clear.`
4. **Findings**, each exactly two lines: number · headline · verdict chip, then one grey
   line of `who · when · how many · evidence quality`.
5. A compact list of the students who finished clear.
6. A one-line privacy statement above a hairline.
7. Sign-off: `REVIEWED BY` / `SIGNATURE` / `DATE`, three 1px rules.
8. An **appendix** with per-episode timings, on its own printed page. Most readers will
   never turn to it, which is correct.

Serif is reserved for the little prose there is (standfirst, privacy line); everything
else is sans. "Download" calls `window.print()`; the print stylesheet drops the toolbar
and the picker, forces a page break before the appendix, and **hides unreviewed chips**
entirely — an absent chip is the honest mark for "not reviewed".

This page **does not subscribe to realtime.** It is a document; it reads the exam once
when opened.

### 5.9 Surface 3 — the full record (`report.html`)

The pre-redesign report, kept as the underlying record and reachable from the document as
"Full record". Nothing was removed from it. It still provides:

- per-student cards with risk bands, the shared **timeline strip** (whose axis is still
  first-flag → last-flag, padded, min 10 minutes — *not* the real exam duration),
- the auto-written sentence per student (*"Mostly phone detected — 14 times…"*),
- the three verdicts, though only Confirm/Dismiss can be *set* here (§5.10),
- Confirm / Dismiss on each episode with keyboard triage (`↑`/`↓`/`j`/`k`, `C`, `X`) and
  an `N of M reviewed` progress bar,
- invigilator notes as their own section,
- **CSV export** (`Student, Event, Count, Start, End, Review`, one row per episode plus
  note rows) — the findings document has no CSV,
- the **student view** (`?as=student`): their own card only, same strip, same episodes,
  same sentence, no review controls, no other students,
- live redraws while the exam is open (debounced 600 ms) on `events`, `participants`,
  `exam_notes` and the exam row.

Its "Save as PDF" button is now a **Findings** link; the browser's own print still works.

### 5.10 Review workflow

Three verdicts, mapped onto the `review` column:

| verdict | stored | effect on the score |
|---|---|---|
| **Upheld** | `confirmed` | none — a visual mark only |
| **Set aside** | `dismissed` | the events stop counting; the student can return to the clear list |
| **To discuss** | `discuss` | none — scores exactly like an unreviewed flag |

Set from the findings document by pressing a finding's chip, which writes the verdict to
**every event behind that finding** in one action — including all of a room-wide moment.
Nulling it back to unreviewed is offered in the same menu.

A set-aside finding **stays on the document** wearing its chip, but its student moves into
the "finished clear" list. That consequence is the point of giving a verdict.

`discuss` can only be set from the findings document. The full record's two buttons still
write only `confirmed`/`dismissed`, and it renders a `discuss` episode as unreviewed
(§7.13).

### 5.11 Live behaviour

While the exam is `open`, the live room subscribes to `participants`, `events` and the
exam row, and re-renders in place. It also re-renders every 15 s to re-evaluate presence
freshness (a student is "present" if `last_seen` is under 15 s old) and to advance the
`… MINUTES IN` clock. Closing the exam from the console flips the room to its
"Who was in" state with no reload.

---

## 6. Design constraints (please don't propose breaking these)

1. **No video/images off-device, ever.** The report can never show footage or stills.
2. Detection must not be loosenable by the student.
3. The visual language is a calm, light, monochrome "paper" aesthetic: near-white
   background, ink text, colour used sparingly and only semantically
   (green = ok, amber = warn, red = alert). No decorative colour.
4. Flags are **aids to human judgement**, never automated accusations. The wording must
   never assert cheating.
5. **Never display a confidence number that isn't real** (§5.6).
6. It must stay a static site + Supabase — no server-side rendering or background jobs.
7. The consistent design signal through many rounds was **less**: cut words, cut chrome,
   cut numbers. Whitespace over borders. `REPORT-REDESIGN.md` lists the directions that
   were tried and rejected — don't revisit them.

---

## 7. Known weaknesses / open questions

Where suggestions are most welcome. Items 3, 4 and 8 from the pre-redesign version are
now partly or wholly addressed and are marked as such.

1. ~~The risk score is an unnormalised sum.~~ **Addressed** (§5.3): ambient flags are
   scored as a rate over the student's own monitored window, discrete ones absolutely.
   Still open: the budget constant is an untested guess, and the full record has not
   been moved onto the new scale.

2. ~~Episodes are cosmetic; scoring is per-event.~~ **Addressed** (§5.3), but only where
   repetition is an artefact of the 15 s cooldown. Edge-triggered kinds still count
   linearly, which is deliberate — compressing them let the worst behaviour score least.

3. ~~No class-relative context.~~ **Addressed** by room-wide moments (§5.2). Still open:
   the 60 % / 5-student rule is a fixed guess, it only groups within a single minute
   (a slow ripple across three minutes won't trigger), and there is no notion of a room
   *baseline* — only of simultaneity.

4. ~~Calibration quality is measured but unused.~~ **Partly addressed**: a weak setup is
   now stated on the finding and caveated in the live popup. It still does **not**
   discount the gaze-based flags numerically, which is arguably where it belongs.

5. **The time axis isn't the exam** — in the full record. The findings document now uses
   `created_at → closed_at`, but that is the exam room's lifetime, not each student's
   monitored window; students join at arbitrary times.

6. **`confirm` does nothing numerically.** Upheld marks a flag as real but doesn't raise
   the score, so a reviewed report and an unreviewed one score the same. The same is now
   true of "To discuss" by design.

7. **Thresholds are global constants.** No per-exam sensitivity, no adaptation to webcam
   quality, no per-student normalisation. `FINDING_SCORE`, `ROOM_SHARE` and `ROOM_MIN`
   join the list.

8. ~~Phone detection's confidence is discarded / one frame is enough.~~ **Addressed** —
   the score is persisted and a flag now needs 3 of the last 5 passes to agree, one of
   them strong (§4.4). Still open: it remains a *generic* detector, so a phone-shaped
   object held steadily for two seconds will still be called a phone. Corroboration
   raises the bar; it does not make the model know what a phone is.

9. **Scale.** The findings document is short by construction, but the full record still
   renders everything into one DOM with no virtualisation, search, or filtering by kind.

10. **No student voice.** The student sees their activity but has no way to contest a
    flag, and there is no field to record the outcome of a conversation — which is
    precisely what "To discuss" leads to.

11. **Times render in the viewer's local timezone**, not the exam's — a teacher reviewing
    from another timezone sees shifted clock times.

12. ~~The interpretation layer is duplicated.~~ **Addressed** — `report.html` reads
    through `exam-core.js` now. Only layout and its own clock formatting are local, so
    the two surfaces can no longer disagree about a score, an episode or a label.

13. ~~The full record can't see the third verdict.~~ **Addressed** with the same change —
    it shows "to discuss" and counts it as reviewed.

14. **The findings document isn't live.** It reads once on open. For an exam still in
    progress that is arguably right, but there is no indication that what you're reading
    is a snapshot.

15. **Severity vs weight are two parallel concepts** (`severity` on the row, `WEIGHT` in
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
