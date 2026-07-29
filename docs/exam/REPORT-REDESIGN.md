# Vigil Exams — report redesign, agreed build spec

Design agreed 29 July 2026 after several rejected directions. **Read
`REPORT-SYSTEM.md` first** for how the current system works; this file is only the
redesign we're building.

Two surfaces, deliberately different species:

| | Live (during the exam) | Downloadable (after) |
|---|---|---|
| Shape | **The room** — a grid of student tiles | **One page of findings** |
| Job | Glance, ambient awareness | Read once, decide, sign, file |
| Unit | The student | The moment |
| Voice | UI, sans-serif | Document, serif prose + sans data |
| Replaces | `live.html` tile wall | `report.html` print view |

---

## Directions that were tried and REJECTED — do not revisit

1. **Dashboard / cockpit** — metric card grids, lane timelines, filters, search,
   priority queue as its own screen, an "exam overview" landing page.
   Verdict: *"airplane cockpit"*. Too dense, too many instruments.
2. **Lane-based evidence timeline** (one horizontal lane per event kind).
   Verdict: rejected outright — *"i do not like the time line"*.
3. **The exam as a chronological story** (times down the left, narration on the right).
   Verdict: *"no story something else"*.
4. **The verdict page** (big sentence, then students with a paragraph each).
   Not rejected, but not chosen — superseded by the room + findings split.
5. **A document full of prose** — the first version of the downloadable report had a
   summary paragraph, a prose paragraph per finding, four metadata rows each, and a
   policy note. Verdict: *"too much to read"*.

**The consistent signal across every round: less.** When in doubt, cut words, cut
chrome, cut numbers. Whitespace over borders. A sentence over a statistic.

---

## Surface 1 — Live: the room

Replaces the current tile wall in `live.html`.

### Layout
- Header: `AI AND ML · LIVE · 41 MINUTES IN` (small, faint, letterspaced), then
  `Your room` (24px/500) with `10 quiet · 2 worth a look` beside it in muted.
- Grid: `repeat(4, minmax(0,1fr))`, `gap: 9px`. Tiles are white, `border-radius: 10px`,
  `padding: 14px 12px`, `border: 1.5px solid transparent`.
- **Quiet tile** = name only, in `--faint` (#a6a8ad). Nothing else. This is most of
  the room and it must look calm and unimportant.
- **Flagged tile** = `border-color` is the semantic colour (alert #d83a3f / warn
  #b7791f), name in full ink at 500, plus one short lowercase phrase underneath
  (`phone, 3 times` / `left window, 4×`) in the matching dark text colour
  (#a32d2d / #854f0b).
- Hover: `transform: translateY(-2px)`, 180ms `cubic-bezier(.2,.7,.2,1)`.
- Bottom: a single line for the room-wide moment + a "See it" action.

### Tile → popup morph (FLIP)
Prototyped and working. The popup must appear to *be* the tile growing:

1. Fill the popup's content first.
2. `transition: none`; set popup `transform: none`, `opacity: 1`; measure both
   `getBoundingClientRect()` of popup and of the clicked tile.
3. Set `transform: translate(tileLeft-popLeft, tileTop-popTop) scale(tileW/popW, tileH/popH)`
   with `transform-origin: 0 0`, and inner content `opacity: 0`.
4. Force reflow, restore `transition` (340ms `cubic-bezier(.2,.7,.2,1)`), set
   `transform: none` and content `opacity: 1` (content fades ~200ms, a beat behind
   the shape — this is what makes it feel fluid rather than janky).
5. Close reverses it, then hides at the end.
6. Backdrop: `rgba(243,242,239,.72)`, 280ms fade. Click backdrop or Esc closes.

Note: in the real page use `position: fixed` for the backdrop/popup (the widget
prototype avoided it only because of iframe height rules).

### Popup content — about NOW, not the whole exam
- Coloured dot + name (21px/500), then `Phone detected · a moment ago` in muted.
- `SO FAR` label, then newest-first rows: `time` (muted, 44px min-width) + what.
- Setup caveat line only when calibration was not solid.
- One action: **Add a note**. No confirm/dismiss — reviewing is a post-exam job and
  must not pull the teacher into paperwork mid-invigilation.
- Quiet students open too and say `Looking at screen · settled since 11:01`.

### Live behaviour (agreed)
- Tiles update live, but **slowly and softly** — ~600ms fade, never flashing.
- If something happens elsewhere while a popup is open: **nothing interrupts**. The
  tile behind changes quietly; the teacher sees it on close. No toasts, no focus steal.

---

## Surface 2 — Downloadable: one page of findings

Replaces the print/PDF view. The unit is the **moment**, not the student — this is the
key idea. A room-wide event is a first-class finding sitting alongside a phone.

### Structure (in order, nothing else)
1. Letterhead rule: Vigil mark + `EXAM INTEGRITY REPORT` right-aligned.
2. Exam title (27px/500), then one grey line: `UXY2TE · 28 July 2026 · 11:01–11:42 PM · 24 students`.
3. Standfirst, 19px: `Three findings.` + muted `Twenty-two students finished clear.`
4. **Findings.** Each is exactly two lines:
   - `01` (faint) · headline (17px/500) · verdict chip right-aligned
   - one grey 14px line: `who · when · how many · evidence quality`
   - ~32px gap between findings.
5. One-line privacy statement above a hairline.
6. Sign-off: three columns — `REVIEWED BY` / `SIGNATURE` / `DATE`, each a 1px black
   top rule with an 11px letterspaced label.

### Verdict chips
`Upheld` (red tint), `Set aside` (neutral), `To discuss` (amber).

### Typography
Serif (`--font-voice` equivalent) is reserved for any prose; sans for data and labels.
The lean version has almost no prose — that's intentional.

### Detail
Per-episode timings go to an **appendix page**, never on page one. Most readers will
never turn to it, which is correct.

### Open, undecided
- Whether to name the 22 clear students (leaning: compact name list at the end).
- Exam-level document by default, plus "download just this student" filtered to their
  findings.

---

## Data work required

1. **Room-wide moment detection — the highest-value item, no schema change.**
   Group all events by `(kind, minute)` across the exam; when a single minute contains
   the same kind for a large share of participants (start with ≥60% and ≥5 students),
   emit a room-wide finding. It must be dismissible in one action that sets
   `review='dismissed'` on every underlying event. This is what makes finding 02
   possible and it is computed entirely from data that already exists.

2. **Persist the phone detector score (one line, additive).** `detectPhone()` in
   `room.js` already computes `c.score` and throws it away. Store it as
   `meta: { score }` on the `phone` event. Without it, any "confidence" shown anywhere
   is fabricated — unacceptable in a document meant for disciplinary use. Everything
   else stays rule-based and must honestly say it has no confidence value.

3. **Three-state review** needs a migration — the column currently only accepts
   `'confirmed'|'dismissed'`:
   ```sql
   alter table public.events drop constraint if exists events_review_check;
   alter table public.events add constraint events_review_check
     check (review in ('confirmed','dismissed','discuss'));
   ```
   Map to `Upheld` / `Set aside` / `To discuss`.

Migrations `schema_v7.sql` (invigilator notes) and `schema_v8.sql` (realtime exam
status) are written but **may not have been run yet** — check before relying on
`exam_notes` or instant close/reopen.

---

## Constraints (unchanged, non-negotiable)

- No video, audio or images ever leave the student's device. The report can never show
  footage or stills.
- Detection thresholds must never be loosenable by a student.
- Do not change the detection engine, event generation, scoring, or the privacy model.
  This is a UI/UX redesign on top of the existing pipeline.
- Palette stays Vigil's: paper `#f3f2ef`, card `#fff`, ink `#0c0d10`, muted `#7a7d84`,
  faint `#a6a8ad`, ok `#1f9d63`, warn `#b7791f`, alert `#d83a3f`. Colour is semantic
  only — everything else is monochrome.
- Static site + Supabase. No SSR, no background jobs.

---

## Build order

1. Live room + tile morph in `live.html` (visual only, existing data).
2. Room-wide moment detection (shared helper, used by both surfaces).
3. Downloadable one-page findings document.
4. Three-state review + the phone-score line.

Keep the existing screens working until each replacement is verified — don't swap them
out mid-flight.
