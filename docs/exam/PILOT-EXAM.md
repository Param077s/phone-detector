# Vigil Exams — pilot run-sheet

One session, about eight people, forty-five minutes. The point is not to demo the
software. The point is to **produce a report you already know the right answer to**, so
that eleven numbers currently set by judgement can be set by evidence instead.

> Not to be confused with `PILOT.md` at the repo root — that one is for the desktop CCTV
> product (doorway cameras, checkpoints). This is Vigil Exams, the browser app.

Read `REPORT-SYSTEM.md` §7 for what is actually unsettled. The short version is that
nobody has ever measured how often an ordinary student looks away, so every threshold
downstream of that is a guess wearing a decimal point.

---

## What this settles

| what you observe | which number it sets |
|---|---|
| median `look_away` per honest participant, per hour | `AMBIENT_BUDGET_PER_HOUR` (currently 4) |
| whether the planted photo raised `still_frame`, and how fast | `STILL_GAZE`, `STILL_HEAD` |
| whether anyone *not* holding a photo raised it | the same two, from the other side |
| whether the idle participant got `inactive` and **not** `still_frame` | the blink discriminator |
| whether the two ordinary neighbours were named as a pair | `PAIR_MIN`, `PAIR_LIFT`, `PAIR_ALPHA` |
| whether the two coordinated participants **were** named | the same, for sensitivity |
| `eyes_down` counts for the paper users vs everyone else | whether §7.19's paper checkbox is needed |
| reported coverage vs the minutes someone was really away | `COVERAGE_FLOOR`, and the counter itself |
| how many honest people landed in medium or high | `FINDING_SCORE`, the band edges |

If you get nothing else from the session, get the **first row**. Everything else in the
scoring model hangs off it.

---

## Before the day

### 1. Tune the liveness floors — required, 15 minutes

Do this first. If the floors are wrong the pilot will either flag everybody or nobody, and
you will learn nothing from the one feature that most needs learning about.

- [ ] Open a room you own with `&debug`: `…/exam/room.html?e=<your exam id>&debug`
- [ ] Sit and work normally for **2 minutes**. Write down the `MOVING` row: `gaze`, `head`.
- [ ] Hold a photo of a face to the camera for **2 minutes**. Write both down again.
- [ ] There should be a wide gap. Set `STILL_GAZE` and `STILL_HEAD` in `room.js` about a
      third of the way up from the photo values toward the working values.

You are tuning on **one** webcam here. The pilot then validates those floors across eight
different cameras, laptops and lighting conditions, which is the part you cannot fake.

### 2. Dry run — 10 minutes, the day before

A pilot that dies because sign-in broke wastes eight people's afternoon.

- [ ] Create an exam, join it from a second device, let it run 5 minutes, close it.
- [ ] Open the findings document. Confirm it renders, and that coverage appears.
- [ ] Confirm the exam's timezone is right (`v13` — it is stamped at creation).
- [ ] Check migrations up to **v14** are applied, or notes and verdicts will be missing.

### 3. Recruit

**Eight minimum.** Room-wide moments need 5 students, pair detection needs 3 in the
roster, and below eight the room-wide rule can trip on ordinary behaviour and swallow the
individual flags you are trying to measure. Ten is better.

Friends, siblings, classmates. They need a laptop with a webcam and a browser.

### 4. Prepare the materials

- [ ] A real thing for them to do for 45 minutes — a mock quiz, a past paper, anything
      with actual questions. **This matters.** People pretending to sit an exam do not
      move like people sitting an exam.
- [ ] Blank paper and pens for the two participants doing rough work.
- [ ] A printed photo of a face, or a second phone showing one full-screen.
- [ ] The observation log below, printed or on a second device.

---

## Roles

Give each person **one** instruction and nothing else. Most people are doing nothing
special, and that is the most valuable role in the room.

| # | role | what to tell them |
|---|---|---|
| 1–4 | **honest baseline** | "Just do the quiz normally." Nothing more. |
| 3 & 4 | …sitting **next to each other** | Nothing extra. They are the pair false-positive control. |
| 5 | **paper rough work** | "Use the paper for working out, as you normally would." |
| 6 | **the photo** | "At the 15-minute mark, tape the photo over your camera and leave for 10 minutes. Then take it down and carry on." |
| 7 | **the idle one** | "From minute 20, sit still and look at your screen without doing anything for 10 minutes. Don't stare — blink normally." |
| 8 | **away and phone** | "Step out of frame twice for about 3 minutes each. Once around minute 10, once around minute 35. And at minute 25, hold your phone up in view for a minute." |
| 9–10 | **the coordinated pair** *(optional but worth it)* | "Every few minutes, both of you look over at each other's screen at the same time." |

**Do not tell participants 1–5 what is being measured.** If they know you are counting
glances they will stop glancing, and the single most important number in the session is
what ordinary people do when nobody has told them anything.

Roles 6–10 can know exactly what they are doing — they are the planted ground truth, and
their job is to be unambiguous.

You are the **observer**, not a participant. You need both hands free.

---

## Consent — say this out loud before you start

Short, honest, thirty seconds:

> Everything the camera sees is processed on your own laptop. No video, no images and no
> audio ever leave your machine or reach me — only small notes like "looked away at
> 3:04". I'll show you your own report afterwards, and I'll delete the whole exam when
> we're done. You can stop and close the tab at any point.

That is all true of the product as built (`REPORT-SYSTEM.md` §1). If anyone is
uncomfortable, they take a non-camera role — reading out the quiz, keeping time.

---

## Running it

- [ ] Create the exam with a **45-minute** duration. Note the code.
- [ ] Everyone joins and completes setup. **Watch the setup-quality line** — it names the
      cameras that could be better *before* you start, which is the one moment it can be
      fixed. Fix them: open a blind, tilt a screen. Thirty seconds each.
- [ ] Note anyone whose setup still reads `fair` or `weak`. Write it in the log — their
      flags are discounted and you need to know which.
- [ ] Press **Start**. Note the wall-clock time. Everything below is minutes from Start.
- [ ] Keep the live room open in front of you for the whole session.

### The observation log

Time is minutes since Start. Fill this in **as it happens** — not from memory afterwards.
Ground truth is the entire value of the session.

```
min   who        what actually happened
────  ─────────  ──────────────────────────────────────────────
 00              exam started
 __   ________   ______________________________________________
 __   ________   ______________________________________________
```

Log every one of these, with the minute:

- each planted event starting and ending (photo on/off, away out/back, phone up/down)
- anything real that happens to the room — a door, a phone ringing, someone talking,
  the lights, a person walking past
- anyone who visibly leaves, fidgets a lot, or has trouble
- anything the **live room** shows you that surprises you, and what the person was
  actually doing at that moment

That last one is the highest-value line in the log. A red tile whose student was doing
nothing wrong is a false positive with a timestamp, which is the hardest thing to get and
the most useful.

- [ ] At the end, press **Close**, then thank everybody and let them go.

---

## Afterwards

Open the findings document, and read it **against your log**, in this order.

### 1. The honest baseline — the number that matters most

For participants 1–4 only, from the full record:

```
look_away count per person ÷ hours monitored  →  glances per hour
```

Take the **median**, not the mean. Then:

- `AMBIENT_BUDGET_PER_HOUR` should be roughly that median, in weight-points. `look_away`
  weighs 1, so a median of 9 glances an hour means the budget should be near 9, not 4.
- Sanity check the consequence: at the corrected budget, do participants 1–4 come out
  **quiet**? They should. If ordinary people land in medium, the budget is still too low.

### 2. The liveness floors

| check | expected | if not |
|---|---|---|
| participant 6 raised `still_frame` | yes, ~90 s after the photo went up | floors too low — raise `STILL_GAZE`/`STILL_HEAD` |
| participant 7 raised `inactive`, not `still_frame` | yes | the blink test is failing; check `BLINK_RATIO` against their setup |
| participants 1–5 raised neither | correct | floors too high — lower them, this is the bad failure |

The third row is the one to care about. A false `still_frame` is alert-severity and shows
red in the live room.

### 3. Pairs

- Were **3 & 4** — the ordinary neighbours — named as a pair? They must not be. If they
  were, raise `PAIR_MIN` or tighten `PAIR_ALPHA`.
- Were **9 & 10** named? If you ran that role and they were not, the thresholds are too
  strict to catch the thing they exist to catch. Check `pairMoments(read.students, {alpha:1})`
  in the console to see whether they were a candidate that the guard rejected, or never a
  candidate at all — those two say very different things.

### 4. Coverage

Participant 8 was away about 6 of 45 minutes, so their coverage should read near **87%**.
Compare. If it reads much lower, the counter is charging them for time they were present;
much higher and it is missing real absence.

Then: does 80% put anyone in "watched only partly" who obviously shouldn't be?

### 5. Paper

Compare participant 5's `eyes_down` count to participants 1–4. If it is several times
higher, §7.19's "rough paper allowed" checkbox is worth building. If it is similar,
`eyes_down` at 0.4 is already doing its job and you can drop the idea.

### 6. The document as a whole

Read it as if you were a head of department who was not there.

- Does the standfirst tell the truth about the session you just watched?
- Is finding 01 the thing you would have said was most worth attention?
- Is anyone named who shouldn't be? **Write down every one, with the minute** — false
  positives are the most valuable output of this whole exercise.
- Is anything missing that you saw with your own eyes?

---

## Scorecard

Fill this in the same day, while you still remember.

```
Participants:              ___     Setup solid / fair / weak:  ___ / ___ / ___
Median glances per hour:   ___     (→ AMBIENT_BUDGET_PER_HOUR)

Planted photo caught:      Y / N   after ___ s
False still_frame:         ___ people          ← must be 0
Idle person read as idle:  Y / N
Ordinary neighbours named: Y / N                ← must be N
Coordinated pair named:    Y / N / not run
Coverage error (P8):       ___ percentage points
Honest people in medium+:  ___ of 4            ← should be 0

Every false positive, with the minute and what they were really doing:
  ____________________________________________________________
  ____________________________________________________________

Would you show this report to a head of department?   Y / N
What would you fix first?  _________________________________
```

A good result is not a clean report. A good result is a report whose every line you can
explain from your log — including the wrong ones.

---

## After that

1. Apply the tuning. Every constant above lives in `room.js` (`CFG`) or `exam-core.js`,
   and every one of them is a one-line change.
2. Update `REPORT-SYSTEM.md` §7 — mark what is now measured rather than guessed, and say
   what it was measured against. A constant with a provenance is worth more than a
   constant with a good value.
3. Re-read the same exam's report after retuning. The reading layer is pure, so the old
   events re-score under the new numbers with nothing to re-run.
4. Then, and only then, is it worth putting in front of a real class.
