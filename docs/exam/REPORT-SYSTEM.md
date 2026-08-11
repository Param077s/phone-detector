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
               created_at, closed_at, require_signin(bool),
               starts_at, ends_at, duration_min          -- the exam itself (v12)

participants   id, exam_id, user_id, name,
               status('ok'|'warn'|'alert'|'offline'),   -- live presence only
               joined_at, last_seen

events         id, exam_id, participant_id,
               kind(text), severity('info'|'warn'|'alert'),   -- derived from ALERT_KINDS, never typed
               at(timestamptz), meta(jsonb),
               review('confirmed'|'dismissed'|'discuss'|null)

exam_notes     id, exam_id, owner, at, text      -- teacher's own observations

finding_notes  id, exam_id, participant_id, kind,
               author('student'|'teacher'), body(<=400), at
               -- one per (participant, kind, author): a statement and an outcome
```

Notes:

- `events` is append-only from the student's side. Students can insert their own events
  and read their own back; only the exam owner can **update** `review`.
- `review = 'discuss'` requires migration **v9**. Until it is applied the column only
  accepts `'confirmed'|'dismissed'`, and the findings document says so in place rather
  than failing silently.
- `starts_at` / `ends_at` are **the exam**, as distinct from the room. `created_at` is
  when the teacher made the room — often twenty minutes early — and using it as the exam
  window meant settling-in fidgeting counted like exam-time behaviour. See §5.12.
- `meta` now carries exactly two things: the calibration quality record on a `calibrated`
  event (§4.3) and the detector's confidence on a `phone` event (§4.4).

### 2.1 Migrations

| | what it adds | required by |
|---|---|---|
| v6 | `events.review` + owner-update policy | Confirm / Dismiss |
| v7 | `exam_notes` table | invigilator notes |
| v8 | `exams` on the realtime publication | instant close/reopen |
| v9 | widens `events_review_check` to allow `'discuss'` | the third verdict |
| v10 | `exam_notes.participant_id` + a student read policy | a note reaching the student it's about |
| v11 | **security**: splits `participants_student_write`, owner-only DELETE, identity trigger | stops a student erasing their own flags |
| v12 | `starts_at`, `ends_at`, `duration_min` on exams | a real start and a real end |
| v13 | `exams.timezone` | the record reads the same hour to everyone (§5.13) |
| v14 | `finding_notes` table | the student answers, and a discussion has an outcome (§5.14) |

Every surface degrades gracefully when a migration hasn't been run — the note field
simply doesn't appear, the third verdict reports that it isn't available, and so on.

**Liveness and coverage (§4.6, §5.15) needed no migration.** `events.kind` is free text
and `meta` is `jsonb`, so two new kinds and two new `meta` shapes are purely additive.
Nothing in the database changed to ship them.

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

## 4. The thirteen event kinds

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
| `still_frame` | Nothing moved | alert | face and irises both below the movement floor **and zero blinks** | 90 s | 60 s |
| `inactive` | Sat without moving | warn | the same stillness, but they **are** blinking | 5 min | 5 min |
| `calibrated` | (not a flag) | info | calibration finished — carries quality in `meta` | — | once |
| `coverage` | (not a flag) | info | cumulative `{seen, total}` seconds of monitoring | — | every 5 min |

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

It is used in four places now.

**It discounts the evidence it undermines.** Saying "weak camera setup" beside a finding
and then scoring it as though the camera were fine is half an answer. Gaze and face flags
— the ones that depend on seeing someone clearly — are multiplied by a trust factor:

```
solid 1.0        fair 0.7        weak 0.45
```

Discrete kinds are untouched: a phone at 0.6 confidence is still a phone however poor the
lighting. Worked example — 24 look-aways in an hour scores 10.5 (alert) on a solid setup,
7.3 (warn) on fair, 4.7 (warn) on weak. Same behaviour, differently trustworthy evidence.

A **missing** `calibrated` record returns trust 1.0, deliberately. If an absent record
bought a discount, suppressing it would be the cheapest way to lower your own score; it is
handled as "no data" (§5.4) instead, which is strictly worse for the student than a real
calibration would have been.

**It is shown before the exam starts**, in the room, as a line: *"2 cameras could be
better before you start."* This is the only moment the problem can actually be fixed — a
tilted screen or a closed blind costs a teacher thirty seconds and prevents every false
flag that setup would have produced. Before, calibration quality surfaced only afterwards,
as a caveat, which told the teacher something useful at the exact point they could no
longer act on it.

**And it caveats what is left**, as the evidence-quality segment of a finding (§5.6) and
the note in a live popup.

**A teacher can answer it.** The discount is the machine saying it isn't sure it saw
clearly; upholding a finding is a person answering exactly that, so upheld events are
scored at full weight and the discount stays on everything still unread (§5.10). It only
ever restores — full weight is the ceiling.

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

### 4.6 Stillness: a person, or a picture of one

Every kind above this one fires when something **crosses a threshold**. That left the
system's largest hole: a photograph taped over the webcam crosses nothing. Neither does a
paused video, nor an empty chair with a face in shot. All of them scored **zero** and were
filed in "finished clear", typographically identical to a student who sat the whole exam.

The only way to catch that is to measure what does **not** happen.

These exams are taken *on* the laptop, so the student is looking at the screen and their
head barely moves — a head-motion test alone would flag every focused reader. What a
screen reader always has is **moving eyes** and **involuntary blinks**. So:

- per frame, the movement since the previous frame is accumulated for the head
  (`nx`, `ny`, `noseGap`) and separately for the irises (`gazeX`, `gazeY`);
- blinking frames are excluded from the gaze figure — a closing eyelid drags the iris
  landmark a long way and would read as looking around;
- blinks are counted once each, on the way down.

One measurement, and the **blink count decides what it means**:

| | movement | blinks | reads as |
|---|---|---|---|
| `still_frame` | below floor | **none in 90 s** | not a live person in front of the camera |
| `inactive` | below floor | some | a live person who is doing nothing |

Ninety seconds is far longer than anyone holds a blink, which is what makes the split
safe. `still_frame` is an **alert** and is in `SERIOUS_KINDS` — for as long as it lasts we
are not monitoring anybody, and it is the one flag a teacher can settle by looking up at
the room. It re-fires every 60 s while the picture stays frozen, so it is in
`REFIRE_KINDS` and a photo left there for an hour compresses to one thing that happened
for an hour, exactly like a phone held in view.

`inactive` is weight **0.4** and ambient. It is a neutral observation, worded as one
(*"Present, but nothing happened"*), and at that weight an entire still hour registers
without ever approaching an accusation.

**A window we mostly could not see is not stillness.** Both tests require the window to be
at least half full of real samples; a face that was absent produces no samples and raises
nothing here. That is a coverage fact and it is counted as one (§5.15).

**The headline says what was measured and stops.** A photograph, a paused video, an empty
chair and a frozen camera driver are indistinguishable from landmarks alone, and naming
one of them would be answering, on the reader's behalf, the exact question they have to
go and answer themselves.

**Both floors are first guesses**, and the honest limit of this feature. They are shown
live in the room's debug panel as `MOVING` (mean gaze movement, mean head movement, blink
count over the window) so they can be set against a real webcam, which is the only place
the true scale of these numbers exists. Until that is done, expect to tune them.

**A looped video defeats this**, deliberately and knowingly. It has real motion and real
blinks. Catching it needs autocorrelation over the movement series to find the loop point
— computable from the same samples, not built.

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

It returns `{ roster, students, moments, findings, clear, thin, coverage, unverified,
poorSetups, review, startT, endT }`.

`calibrated` and `coverage` are the two rows that describe the **monitoring** rather than
the student. They are held in one place — `INFO_KINDS`, with an `isFlag()` beside it — so
that a row about how well we could see can never be scored as something somebody did.

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
second_face 5   phone 5   virtual_cam 5   still_frame 5
left_exam   4
monitor_hidden 3   camera_off 3
face_absent 1.5
look_away   1   head_down 1
eyes_down   0.4   inactive 0.4
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

The unit is the **moment**, not the student. A finding is one of three things:

- a **room-wide moment** (§5.2), or
- a **pair moment** (§5.16) — two students, repeatedly, at the same times, or
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
3. Standfirst: `Five findings.` + muted `Two upheld and three still to review. Twenty
   students finished clear.` The middle sentence is how much of this document a person has
   stood behind — `None reviewed yet.` before anyone has, and absent when nothing was
   flagged. A signature under a document nobody has read means something different from one
   under a document read end to end, and the page used to look identical either way.
4. **Findings**, each exactly two lines: number · headline · verdict chip, then one grey
   line of `who · when · how many · evidence quality`.
5. A compact list of the students who finished clear, then — when there are any — the
   students **watched only partly** (§5.15), each with their coverage percentage.
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
| **Upheld** | `confirmed` | the events are scored at **full weight** — the calibration discount (§4.3) comes off, because a person has answered the question it hedges |
| **Set aside** | `dismissed` | the events stop counting; the student can return to the clear list |
| **To discuss** | `discuss` | none — scores exactly like an unreviewed flag |

**What upholding is worth.** Setting a flag aside removed it from the score; upholding one
used to do nothing at all, so a report read end to end scored exactly like one nobody had
opened. Agreeing with the machine was the only verdict with no consequence.

It could not simply *add* weight. A person saying "yes, that happened" does not make it a
worse thing to have done, and a score that climbed because someone pressed a button would
be an accusation the evidence never supported (design constraint 4).

What a person **can** answer is the machine's own doubt. The trust discount exists because
a weak camera makes gaze and face flags unreliable — we can see that something happened,
but not well enough to be sure. A teacher upholding that finding has looked at precisely
that question. So an upheld event is scored at full weight and the discount stays on
everything still unread.

This can only ever **restore what uncertainty took away**. Full weight is the ceiling;
there is no multiplier above 1. Three consequences follow, all intended:

- a **solid** setup is unmoved by review — nothing was discounted, so there is nothing to
  give back;
- **discrete** kinds (phone, second face, …) are never trust-discounted, so upholding a
  phone finding changes no number. What it changes is the document's account of itself;
- upholding can **promote something into the document**. A weak-setup student's gaze flags
  can sit below `FINDING_SCORE` and appear only in the full record; confirming them there
  can carry them over the bar and onto the findings page. That is the right way round — a
  human said the poor camera didn't change what they saw.

`trust` is folded into each event's weight rather than multiplied over the total, so
different events in one score can carry different trust. With nothing upheld every term
scales by the same constant, so the arithmetic is identical to before any review.

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

### 5.12 When an exam starts and ends

Before v12 an exam had no beginning. `created_at` was when the room was made and
`closed_at` was whenever someone remembered to press Close, and the report called that
span "the exam". Three things followed from that: settling-in flags counted exactly like
exam-time ones, an exam nobody closed monitored people forever, and no two exams were
comparable because neither span meant the same thing.

- A duration is chosen at creation (30 min … 3 hours, or no limit).
- **Start exam** stamps `starts_at`, and `ends_at = starts_at + duration`.
- Events before `starts_at` stay in the record but are **excluded from the reading** —
  they are settling-in, not exam behaviour, and they no longer count against anyone.
- Each student's scoring window (§5.3) is clipped to the exam, so twenty minutes of
  sitting around before the start can no longer dilute a rate.
- **Every teacher surface passes the same window.** The findings document, the full record
  and a student's own view all hand `starts_at`/`ends_at` to `readExam`, and all fetch
  `last_seen` so a window ends where the student actually left. Sharing the reading
  function is not enough on its own — see §7.12.

**The end enforces itself.** This is a static site with no background job, so nothing can
flip the row at the right moment. `examOver()` derives it from the clock — an exam is over
when the teacher closed it *or* `ends_at` has passed — and whichever surface notices first
writes `status='closed'` opportunistically. The student's room checks the same thing every
4 s and stops monitoring on its own, so a teacher who walks away without pressing anything
no longer leaves students monitored indefinitely.

Exams recorded **before v12** have no `starts_at`, so every surface falls back to
`created_at`/`closed_at` and reads exactly as it always did. Nothing already recorded is
reinterpreted.

While an exam is still running, the findings document says so — `from 14:05, still running`
— instead of printing `14:05–16:05`. The planned end is a fact about the future, and a
document that states it as though it had happened is not a record of anything.

### 5.13 What hour it says

A `timestamptz` is an instant; the hour it *displays* as is a choice, and the browser was
making that choice from wherever the reader happened to be sitting. A teacher marking from
another timezone — or, far more often, whoever the PDF was forwarded to — read every flag
shifted by hours with nothing on the page saying so. Two people could look at the same
record and disagree about when something happened.

- The teacher's IANA zone (`Asia/Kolkata`) is stamped on the exam at creation (v13).
- `useTimezone()` is called once per page after the exam loads; `clock`, `clockRange`,
  `clockSec` and `dateLong` all format in it. There is no other clock in the app —
  `report.html`'s compact rows go through `clockSec` too.
- A short zone label (`times in BST`) is appended **only when the reader's own zone shows a
  different wall clock for that instant**. The test is the rendered time, not the zone's
  name, so `Asia/Calcutta` reading an `Asia/Kolkata` exam says nothing — they are the same
  place — and DST is handled by asking about the moment rather than the rule.
- No `timezone` (every exam before v13, or a name the browser doesn't know) falls back to
  the reader's own zone, which is exactly how this behaved before.

---

### 5.14 The other person in the exam

Until v14 only one of them could write. A student could read every flag against them and
had no way to say the phone was a calculator; and `discuss` — a verdict whose entire
meaning is *"I need to talk to this person first"* — had nowhere to record what the
conversation concluded, so a teacher could either leave it on `discuss` forever or flip it
and lose the reason.

One table answers both. A note hangs off **(participant, kind)** — the same unit a
student-level finding is built from — so it lands beside the thing it is about.

- **One note per finding per author**, enforced by a unique index. A student states their
  case once and may edit or withdraw it; a teacher records one outcome. It is a record,
  not a thread, and it cannot become an argument.
- **The student writes** on their own activity page (`report.html?as=student`), one line
  per kind they were flagged for. Their words are **printed under that finding in the
  document, attributed** — if a report reaches a hearing, the person it is about has been
  heard in it.
- **A statement on a kind that never reached the findings bar** still surfaces, under
  *Also said* in the teacher's student popup. Words written to be read must not disappear
  because the machine scored them low.
- **The teacher writes the outcome** from the same popup, and only once a verdict exists —
  before that there is nothing to have concluded, and an empty box against every finding
  would be exactly the chrome this document avoids.
- **`author` is pinned by RLS in both directions.** A student cannot file a note as the
  teacher, and the owner cannot author words in a student's name.
- **A student may delete their own statement.** v11 stops them destroying *evidence*; this
  is the opposite thing — their own voluntary words — and someone who thinks better of what
  they wrote should not be held to a first draft.
- **The outcome is not shown to the student.** It may name a next step or a conclusion not
  yet delivered. v10's addressed `exam_notes` are the deliberate channel for anything a
  teacher means them to read.
- `at` is stamped by a database trigger, not accepted from the browser — backdating your
  own statement is otherwise one line in a console.

**Known limit:** students join as anonymous guests unless `require_signin` is on, so a
statement can carry no verified identity into a filed document. The document attributes it
to the name they typed. That is a property of guest join, not of this feature, but it is
worth knowing before the report is relied on.

### 5.15 How much of the exam we actually watched

Every other number in this document is a **numerator**. How many flags, how many findings,
how many students finished clear. None of them mean anything without the share of the exam
we had eyes on, and until now the document had no denominator anywhere on the page.

So a student whose camera faced a wall for half the exam read **exactly like** one who
behaved. Both were flagged zero times; both were filed as clear. "Finished clear" is the
strongest sentence in this document — it is the one a student would want quoted — and it
was being printed about people we had barely watched.

- The device counts it, where the truth is. Every detection tick adds its own elapsed time
  to `total`; only ticks that actually resolved a face add to `seen`. A camera switched
  off, a stalled feed and a student out of frame all stop `seen` climbing while `total`
  keeps going — all three mean we were not watching, and all three now say so.
- The counters are **cumulative**, written every 5 minutes and once more at the end, so
  any window can be measured by differencing the two rows that bracket it.
- `coverage` is an **info** row like `calibrated`, written with a direct insert rather than
  `emit()` — a record *about* the monitoring must never push the student's status to warn.

Three things read it:

1. **The standfirst states the document's own reliability**: *"Watched for 94% of the exam
   on average, two under 80%."* Said in one clause, and only when there is something to
   say — a room watched 99%+ throughout says nothing, because that is chrome.
2. **`clear` requires it.** A student is only "finished clear" with nothing flagged **and**
   coverage at or above `COVERAGE_FLOOR` (80%).
3. **A third list**, between "finished clear" and "no monitoring data": *Watched only
   partly*, naming each student with their percentage. They are not accused and they are
   not cleared, because neither is supportable — they are described.

**Unknown coverage reads exactly as before.** Every exam recorded before this shipped has
no `coverage` rows, so `coverageOf` returns `null`, `thin` is false, and those students
remain clear. An old report may not grow a new complaint about its students.

**Known limit:** the counters start when monitoring begins, not when the teacher presses
Start. If the exam starts less than 5 minutes after a student joins there is no row to use
as the window's baseline, so their settling-in minutes — usually well-monitored — are
included, which nudges coverage slightly **up**. It is the wrong direction for honesty and
it is bounded by one write interval.

### 5.16 Two students, repeatedly, at the same moments

Room-wide moments need 60% of the roster, which makes them structurally blind to the
commonest shape of copying: **exactly two people**. Two is never a room. It is also what a
human invigilator spots from the front of the hall — *those two keep looking up together*
— and what no report has ever been able to say.

Computed entirely from events that already exist. No new detection, no schema change.

- Each student's episodes (§5.5) are taken from their **`own`** events — anything a
  room-wide moment already explains is excluded, or a whole room looking up at a door
  would mint a pair out of every two people in it.
- Two episodes of the same kind are "together" when their spans touch within
  `PAIR_TOL_MS` (30 s).
- A moment shared by more than `PAIR_MAX_CLUSTER` (25%) of the room is skipped. A crowd is
  a property of the room, not of any two people standing in it.
- The comparison is **same-kind only**. "Both looked away" is a claim; "one looked away
  while the other's camera went off" is noise.

**A raw count of togethers would report the two most fidgety people in the room, every
time.** Two students who each drift off thirty times an hour will coincide often for no
reason at all. So what counts is the excess over their own rates: two intervals dropped at
random into a shared window `W` overlap with probability `(durA + durB + 2·tol)/W`, so
`nA·nB` of them meet that many times. The document prints that as *"chance predicts two"*
— a first-order estimate, called one, never dressed up as a probability.

#### The trap this fell into first, and the guard that came out of it

The first working version reported **eleven pairs in a room where nobody had done
anything**, every one of them wearing a confident-looking multiple like "9.6× chance".

Twenty students is **190 pairs**. Ask 190 questions at once and a few come back looking
remarkable for no reason — four coincidences against an expectation of 0.4 is nine times
chance and means nothing, because *something* had to come top. That is the multiple
comparisons problem, and it is the exact failure that would have ended this feature's
credibility on its first real exam: name a quarter of the class, and nobody believes the
one pair that mattered.

So the bar rises with the number of questions asked. `poissonAtLeast(together, expected)`
is the chance of seeing this many coincidences if the two of them had nothing to do with
each other, and it must survive being multiplied by the number of pairs tested:

```
p × tests ≤ PAIR_ALPHA (0.05)
```

Worked, from the test suite:

| | together | expected | lift | p | tests | reported |
|---|---|---|---|---|---|---|
| a real pair | 9 | 1.7 | 5.4× | 7.2e-5 | 1 | **yes** |
| a coincidence | 4 | 0.42 | 9.6× | 9.0e-4 | 91 | no — `0.082 > 0.05` |

The effect-size floors (`PAIR_MIN = 4`, `PAIR_LIFT = 3`) stay as well: a large enough
sample makes trivial differences significant, and a pair that is real but tiny is not a
finding.

#### What it must never become

**Co-occurrence is not evidence of collusion.** Two friends sitting by the same door,
under the same window, or next to the same noisy radiator produce this pattern honestly
and repeatedly. This is the most accusatory thing the system can print, and it is built to
be quiet rather than clever:

- **It changes nobody's score.** Their own flags are already counted once against each of
  them; counting them again because of who else was flagged that second would be scoring a
  student for another student's behaviour. It is a finding — a thing put in front of a
  person to decide — and nothing else. A regression test asserts every score is identical
  with pair findings suppressed.
- **It does not affect the clear list**, for the same reason.
- **The headline says what was counted and stops.** No wording in the system contains
  "cheating", "copying" or "collusion", and a test asserts it.
- **The finding carries its own caution, in print**: *"Two students flagging together is a
  reason to look, not a conclusion."* The printed copy travels to people who were never in
  the room, so the caution has to travel with it.
- It is a **key finding** (§5.8), so it is never compressed into the appendix. It is the
  one thing on the page a teacher could not have worked out from the tiles.

**Known limit:** a pair finding has no outcome field. Notes hang off `(participant, kind)`
(§5.14), so a finding with two names on it would have to pick one of them, or collide with
that student's own finding of the same kind. The verdict — which is the action that
matters — works normally. Recording what the conversation concluded needs a key of its own.

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

4. ~~Calibration quality is measured but unused.~~ **Addressed** (§4.3): it discounts the
   gaze and face flags it undermines, and it is surfaced in the room before Start, when
   the setup can still be fixed. Still open: the trust factors are three round numbers
   chosen by judgement, not measured against real webcams.

5. ~~The time axis isn't the exam.~~ **Addressed** by v12 (§5.12): an exam has a real
   start and end, pre-start flags are excluded, and each student's window is clipped to
   it. Still open: the full record's own strip is gone, but exams created before v12 keep
   the old fuzzy window forever.

6. ~~`confirm` does nothing numerically.~~ **Addressed** (§5.10): upholding takes the
   calibration discount off the events behind a finding, and the standfirst says how much of
   the document a person has stood behind. Still open: it moves nothing on a solid setup or
   on a discrete kind, because there was no doubt to resolve in either — for those, review
   changes only what the page *says*. Whether that is enough is a question for the first
   real exam. "To discuss" still scores as unreviewed, by design.

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

10. ~~No student voice.~~ **Addressed** by v14 (§5.14). The student writes one line
    against any kind they were flagged for, and it is printed under that finding in the
    document, attributed. A verdict gains an outcome field, so "To discuss" stops leading
    nowhere. Still open, and deliberate: a guest student's words carry no verified
    identity into a filed record (`require_signin` is the only lever), and the teacher's
    outcome is not shown to the student — v10's addressed `exam_notes` remain the channel
    for anything meant for them to read.

11. ~~Times render in the viewer's local timezone, not the exam's.~~ **Addressed** by v13
    (§5.13): the exam's zone is stamped at creation and every surface formats in it, with a
    zone label shown only when the reader would otherwise misread the clock. Still open:
    exams created before v13 have no zone and keep reading in the viewer's, and
    `history.html`'s list of exams is still viewer-local (it spans many exams, so there is
    no single right zone for it).

12. ~~The interpretation layer is duplicated.~~ **Addressed** — `report.html` reads
    through `exam-core.js` now. Only layout and its own clock formatting are local, so
    the two surfaces can no longer disagree about a score, an episode or a label.

    **This claim was wrong for a while, and it is worth remembering why.** Sharing the
    function was not enough: `report.html` called it with different *arguments* — no
    `startsAt`/`endsAt`, and a roster fetched without `last_seen`. So it read the whole
    sitting where the document read exam time, and it dated every window from the last
    event instead of when the student actually left. On a room opened twenty minutes
    early, one student came out **11.25 alert** on the full record and **1.5 quiet** on
    the findings document — the exact disagreement this item claims is impossible, from
    one shared function. One reading means one set of inputs too.

13. ~~The full record can't see the third verdict.~~ **Addressed** with the same change —
    it shows "to discuss" and counts it as reviewed.

14. ~~The findings document isn't live.~~ **Wrong when written, and fixed since.** All three
    surfaces poll (live 2 s, findings 2 s, full record 5 s) and refresh on `visibilitychange`.
    What was actually missing was any sign that a *running* exam hadn't finished — the header
    printed its planned end as a completed range. It now says `still running` (§5.12).

15. ~~Severity vs weight are two parallel concepts.~~ **Addressed** — `severity` was typed by
    hand at each of `room.js`'s ten emit calls while `ALERT_KINDS` in the core decided what
    every reading surface treated as serious. They agreed only because nobody had got one
    wrong yet. `severity` is derived from `ALERT_KINDS` now, so a kind cannot be serious in
    the database and ordinary in the report. Verified against the old hand-written table:
    zero rows change. Still open: rows written before this keep whatever they were given —
    which, since nothing had drifted yet, is the same answer.

16. ~~Nothing fires when nothing happens.~~ **Addressed** (§4.6, §5.15) — this was the
    structural version of items 1–15: every kind fired on a threshold crossing, so a
    photograph over the webcam, an empty chair, or a camera pointed at a wall all scored
    zero and were filed as "finished clear". Stillness is now measured, and coverage is
    counted and printed. Still open, and the honest limits of it:
    - **The two movement floors are guesses**, like `AMBIENT_BUDGET_PER_HOUR` before them.
      They are exposed live in the debug panel (`MOVING`) precisely so they can be set
      against a real webcam, and they have never seen one.
    - **A looped video still defeats the liveness test** — it has real motion and real
      blinks. Autocorrelation over the same movement series would find the loop; unbuilt.
    - `COVERAGE_FLOOR = 0.8` is a round number chosen by judgement.
    - Coverage's window baseline is imprecise for exams that start within 5 minutes of a
      student joining (§5.15).

17. ~~No pairwise analysis.~~ **Addressed** (§5.16) — two students who keep flagging
    together, far more often than their own rates predict, are a finding now, with the
    bar rising by the number of pairs tested so a room of coincidences names nobody.
    Still open, and the things to watch on the first real exam:
    - `PAIR_TOL_MS`, `PAIR_MIN`, `PAIR_LIFT` and `PAIR_ALPHA` are four more constants
      chosen by judgement. The statistical *shape* is right; the numbers are untested.
    - **Same-kind only.** One student looking away while the other puts their head down
      is invisible to this, and may well be the more realistic shape of copying.
    - The overlap estimate assumes episodes fall independently across the window. Flags
      cluster in real exams (everyone fidgets more in the last ten minutes), which
      inflates `expected` a little and makes it slightly conservative — the safe
      direction, but not a modelled one.
    - **No outcome field** on a pair finding (§5.16).
    - Seating is unknown to Vigil, and it is the single fact that would most change how
      one of these should be read.

18. **The room is never used as its own baseline.** `AMBIENT_BUDGET_PER_HOUR` is a global
    constant guessing at what a normal glance rate is, while every exam ships with a
    control group sitting in it. Scoring against the room's own median per kind would
    self-calibrate, and would make paper and on-screen exams work without configuration.
    It needs a floor, or a wholly compromised room normalises itself clean.

19. **Rough paper work is not declared.** These are on-screen exams where students may do
    rough work on paper, which is exactly what `eyes_down` looks like. Its weight is
    already the lowest in the set (0.4) for that reason, but a "rough paper allowed"
    checkbox at exam creation would let it be discounted further when the teacher has
    sanctioned it — one field, and a whole class of false flags goes away.

---

## 8. What a good proposal looks like

We're most interested in changes that make the report **easier to act on**, not
richer in data. The report should let a teacher answer, in under a minute:

- Who actually needs my attention?
- Is this one bad stretch, or a pattern?
- Was this a room-wide moment or this student alone?
- How confident should I be, given how good their camera setup was?
- What do I do next, and what do I hand over if this escalates?
