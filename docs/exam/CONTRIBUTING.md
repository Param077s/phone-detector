# Vigil Exams — contributor guide (web app)

This is the **exam web app**: the thing students and teachers use in the browser at
`phone-detector-one.vercel.app/exam/`. It's plain HTML + JavaScript with a Supabase
backend and in-browser AI. **No build step, no framework, no Python.** If you can run
a static file server and open a browser, you can work on it.

> The camera AI runs 100% in the student's browser (MediaPipe). **Video never leaves
> the device** — only tiny JSON events (a flag, a heartbeat) go to Supabase. Keep it
> that way; it's the whole privacy promise.

---

## 1. Run it locally (2 minutes)

```bash
git clone https://github.com/Param077s/phone-detector.git
cd phone-detector/docs
python3 -m http.server 8534
```

Then open **http://localhost:8534/exam/**.

- The camera works on `localhost` (browsers treat it as a secure context), so you can
  test the student monitor fully.
- It talks to the **live Supabase** (the anon key in `sb.js` is public by design — the
  database's Row-Level Security enforces all the rules). **There are no secrets to set
  up.** You're editing the same backend as production, so create throwaway exams for
  testing and close them when done.
- Optional: `node --check <file>` to syntax-check JS before committing (see §5).

---

## 2. The map — what each file does (`docs/exam/`)

| File | What it is |
|---|---|
| `index.html` | Landing / role picker + **join** flow (student Google or guest; teacher sign-in). |
| `console.html` | **Teacher console** — create / list / close exams, "require sign-in" toggle, share QR. |
| `live.html` | **Teacher live room** — the tile grid, Start/Close, live alerts + click-a-tile drill-down. |
| `findings.html` | **The findings document** — the one page a teacher reads and files. Verdicts are set here. |
| `report.html` | **The full record** — every flag for every student, CSV / PDF. Also the student's own view. |
| `room.html` + `room.js` | **Student monitor** — all the MediaPipe detection lives in `room.js`. |
| `history.html` | "Your exams" — everything you ran or took. |
| `exam-core.js` | **The shared reading** — labels, weights, episodes, scoring, room moments, time. Both teacher surfaces read through this; nothing here touches the network. |
| `sb.js` | Shared Supabase client + helpers (`fetchExam`, `esc`, …). |
| `style.css` | Shared design tokens + components. **Edit here to reskin everything.** |
| `/vendor/mediapipe/` | Vendored ML runtime + models (face landmarker, object/phone detector). Offline-safe. |

`REPORT-SYSTEM.md` is the long-form account of how events become a report — read it
before changing anything about scoring, findings or verdicts.

The database lives in **`../../supabase/schema*.sql`** (see §4).

---

## 3. How the detection works (`room.js`)

Each student's browser runs MediaPipe on their webcam and emits small events:

- **look_away** — eyes drift outside an allowed radius around their calibrated centre (iris tracking).
- **head_down** — head physically tilts down.
- **face_absent / second_face** — no face / more than one face.
- **phone** — a phone in view (object detector, slower cadence).
- **camera_off / monitor_hidden / left_exam / virtual_cam** — integrity signals (camera killed, Vigil hidden/closed, fake camera).

Thresholds are **baked defaults** in the `CFG` object at the top of `room.js`. There's a
live tuning panel at `?e=…&debug`, but it's **owner-only** (a student can't open it to
loosen detection — that's deliberate anti-tamper; don't undo it).

---

## 4. The database (Supabase)

- Project ref: `czvxhfbwpmqafpeehayd`. Tables: `exams`, `participants`, `events`.
- **RLS is the security boundary.** A teacher owns their exams and sees everything in them;
  a student can only read/write their own rows. Two tables never reference each other's RLS
  directly — we use `SECURITY DEFINER` helper functions (`is_in_exam`, `find_open_exam`) to
  avoid infinite-recursion policy errors.
- Schema + migrations are in **`supabase/schema.sql` → `schema_v13.sql`**, applied **by hand**
  in the Supabase SQL editor, in order. **Never auto-apply DB changes** — write a new
  `schema_vN.sql`, hand it over as copy-paste SQL, and it gets run manually. A file existing
  in `supabase/` never means it has been run.
- **Make code degrade gracefully so a page still works before its migration is applied.**
  Postgres rejects an entire `select` for one unknown column, so a new column can white-screen
  every page until the SQL is pasted in. Two patterns already in use: read through
  `fetchExam()` in `sb.js` (asks for the optional columns, retries without them), and write
  new columns in their own `update` after the insert, wrapped in `try {} catch {}`
  (see `console.html`'s create flow — `require_signin`, `duration_min`, `timezone`).

---

## 5. Conventions

- **Plain modules.** Each page has one `<script type="module">`; `room.js` is the only
  standalone module. No bundler, no npm install.
- **Check before you commit — one command:**

  ```bash
  node tools/check-exam.mjs
  ```

  It parses every page's `<script type="module">` body *and* resolves every
  `exam-core.js` / `sb.js` name a page uses against the names it actually imports, in both
  directions (used-but-not-imported, imported-but-unused). `node --check` alone cannot do the
  second half: it only parses, so a page that calls `examOver()` without importing it passes
  cleanly and then throws in front of a teacher. That has already happened — a string
  replacement missed the import line in two files and `--check` said yes twice.
- **Role = ownership/context, never auth type.** Teacher vs student is decided by who owns the
  exam (`exam.owner === uid`) and how you arrived (`?as=student` / `vg_role`). Don't bring back
  `is_anonymous`/has-email role checks — that was the bug that dumped students on the console.
- **Stay self-contained.** Everything is vendored (no runtime CDN calls); keep it offline-safe.
- **One fact, one place.** Anything both a page and the core could know — a label, a weight,
  how serious a kind is, what an exam's clock reads — belongs in `exam-core.js` and is derived
  everywhere else. Two surfaces that can disagree about the same exam eventually will.
- **Match the surrounding style** — same naming, same terse comment density.

---

## 6. Ship it

`docs/**` **auto-deploys to Vercel** on push to `origin/main` (~1 minute). Because `main`
deploys straight to production, **work on a branch and open a PR** so `main` stays deployable:

```bash
git checkout -b feature/your-thing
# ...edit, syntax-check, commit...
git push -u origin feature/your-thing
gh pr create --fill
```

After it merges + deploys, verify against the live URL
(`https://phone-detector-one.vercel.app/exam/`).

---

## 7. Quick end-to-end test

Two browser windows — **normal = teacher**, **incognito = student** (separate identity):

1. Teacher: create an exam (give it a duration), copy the code. Student: `…/exam/?code=CODE` →
   Join as guest → let calibration finish.
2. Teacher: press **Start exam**. Flags raised before this point stay in the record but leave
   the reading, so raise a couple either side of it and check they land differently.
3. Student: look far to the side, look **down** (that's `eyes_down`, not `look_away`), wave a
   **phone** for a few seconds, get a **second face** in frame, minimise the window.
4. Teacher **Live room**: tiles change colour + the **alerts feed** fills; click a tile → drill-down.
5. Teacher **Findings**: set a verdict → the score and the clear list move. While the exam is
   running the header says "still running" rather than printing an end that hasn't happened.
6. Teacher **Full record**: the same bands and the same episodes as the findings document — if
   those two ever disagree, that's the bug.

---

## 8. Gotchas

- Camera needs **https or localhost** — a plain-IP `http://` origin won't get the webcam.
- A **background browser tab freezes** the detection loop — that's *why* hiding Vigil is itself
  a flag (`monitor_hidden`). Vigil is meant to sit **visible beside** the exam.
- Supabase **Realtime respects RLS**, so a student's live subscription only gets their own rows.
- The MediaPipe models are a few MB, vendored under `/vendor/mediapipe/` — don't delete them.
