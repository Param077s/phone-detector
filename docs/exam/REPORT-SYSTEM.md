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

It is used in three places now.

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

11. ~~Times render in the viewer's local timezone, not the exam's.~~ **Addressed** by v13
    (§5.13): the exam's zone is stamped at creation and every surface formats in it, with a
    zone label shown only when the reader would otherwise misread the clock. Still open:
    exams created before v13 have no zone and keep reading in the viewer's, and
    `history.html`'s list of exams is still viewer-local (it spans many exams, so there is
    no single right zone for it).

12. ~~The interpretation layer is duplicated.~~ **Addressed** — `report.html` reads
    through `exam-core.js` now. Only layout and its own clock formatting are local, so
    the two surfaces can no longer disagree about a score, an episode or a label.

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

---

## 8. What a good proposal looks like

We're most interested in changes that make the report **easier to act on**, not
richer in data. The report should let a teacher answer, in under a minute:

- Who actually needs my attention?
- Is this one bad stretch, or a pattern?
- Was this a room-wide moment or this student alone?
- How confident should I be, given how good their camera setup was?
- What do I do next, and what do I hand over if this escalates?
