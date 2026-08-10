// Vigil Exams — the shared reading of an exam's events.
//
// Both surfaces are built from this file: the live room (live.html) and the
// findings document (findings.html). Nothing here talks to the network, and
// nothing here changes detection — it only decides how existing events read.
//
// The unit the document cares about is the MOMENT, not the student. A moment
// is either one student's run of the same flag, or the whole room flagging at
// once. Both are first-class here.

export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ── vocabulary ──────────────────────────────────────────────────────────────
export const LABELS = {
  head_down: "Looked down", look_away: "Looked away", eyes_down: "Eyes on the desk",
  face_absent: "Face not visible",
  second_face: "Second face detected", phone: "Phone detected", camera_off: "Camera off",
  monitor_hidden: "Camera not readable", left_exam: "Left the exam page", virtual_cam: "Virtual camera",
  still_frame: "Nothing moved", inactive: "Sat without moving",
  calibrated: "Calibrated", coverage: "Coverage",
};

// Rows that describe the MONITORING rather than the student. They are never
// flags, never scored, and never counted as anything anyone did — but they are
// also the two rows that say how much the rest of the record is worth.
export const INFO_KINDS = new Set(["calibrated", "coverage"]);
export const isFlag = e => e && !INFO_KINDS.has(e.kind);

// the short lowercase phrase a live tile wears — a glance, not a sentence
export const PHRASES = {
  phone: "phone", second_face: "second face", virtual_cam: "virtual camera",
  camera_off: "camera off", monitor_hidden: "camera gap", left_exam: "left the page",
  face_absent: "face not visible", look_away: "eyes off screen", head_down: "head down",
  eyes_down: "eyes on the desk", still_frame: "nothing moving", inactive: "not moving",
};

// the headline a finding wears in the document — describes, never accuses
export const HEADLINES = {
  phone: "A phone was in view", second_face: "Someone else was in frame",
  virtual_cam: "A virtual camera was in use", camera_off: "The camera was off",
  monitor_hidden: "Vigil could not read the camera", left_exam: "Left the exam page",
  face_absent: "Face out of view", look_away: "Eyes off screen, repeatedly",
  head_down: "Head down, repeatedly", eyes_down: "Eyes on the desk, repeatedly",
  // Says what was measured and stops. What it MEANS — a photograph, a paused
  // video, an empty chair, or a camera that froze — is exactly the question a
  // person has to answer, and a headline that guessed would be answering it for
  // them with evidence that cannot tell those apart.
  still_frame: "Nothing in the picture moved",
  inactive: "Present, but nothing happened",
};

// the same moment, when it kept happening to the same two people. It says what
// was counted and it stops there — what it MEANS is the entire question the
// teacher has to go and answer, and two friends by the same door produce this
// exact pattern honestly.
export const PAIR_HEADLINES = {
  look_away: "Two students looked away together, repeatedly",
  eyes_down: "Two students looked down together, repeatedly",
  head_down: "Two students put their heads down together, repeatedly",
  face_absent: "Two students left the frame together, repeatedly",
  phone: "Two students had phones in view at the same moments",
  second_face: "Two students had someone else in frame at the same moments",
  monitor_hidden: "Two cameras went unreadable at the same moments",
  camera_off: "Two cameras went off at the same moments",
  inactive: "Two students went still at the same moments",
  still_frame: "Two pictures stopped moving at the same moments",
};
export const pairHeadline = k =>
  PAIR_HEADLINES[k] || ("Two students flagged together, repeatedly — " + label(k).toLowerCase());

// the same moment, when it belonged to the room rather than one student
export const ROOM_HEADLINES = {
  look_away: "The room looked away at once", head_down: "The room looked down at once",
  face_absent: "The room dropped out of view at once", phone: "Phones in view across the room",
  eyes_down: "The room looked at their desks at once",
  second_face: "Second faces across the room", monitor_hidden: "Cameras unreadable across the room",
  camera_off: "Cameras went off across the room",
  still_frame: "Nothing moved anywhere in the room", inactive: "The room went still at once",
};

export const ALERT_KINDS = new Set(["second_face", "phone", "camera_off", "monitor_hidden", "left_exam", "virtual_cam", "still_frame"]);
// worth interrupting an invigilator mid-exam for — the live room shows only these.
// `still_frame` earns its place: for as long as it lasts we are not monitoring
// anybody, and it is the one flag a teacher can settle by looking up at the room.
export const SERIOUS_KINDS = new Set(["phone", "second_face", "virtual_cam", "still_frame"]);
export const WEIGHT = { second_face: 5, phone: 5, virtual_cam: 5, still_frame: 5, left_exam: 4, monitor_hidden: 3, camera_off: 3, face_absent: 1.5, look_away: 1, head_down: 1, eyes_down: 0.4, inactive: 0.4 };

// ── how a score is built ────────────────────────────────────────────────────
// Two kinds of flag behave completely differently over time, and treating them
// the same is what used to turn a long exam red.
//
// AMBIENT flags accumulate simply because a person sat there for two hours.
// Eleven glances away across two hours is what ordinary people do; the same
// eleven in ten minutes is a pattern. So ambient flags are scored as a RATE.
//
// Everything else is discrete. A phone is a phone whether the exam ran forty
// minutes or three hours, so those are scored absolutely and never divided by
// duration — that would quietly hide the most serious thing in the room.
// `inactive` is ambient for the same reason the others are: it is a fact about a
// stretch of time, so twelve of them in a three-hour exam is a description of a
// quiet afternoon, not twelve times the finding.
export const AMBIENT_KINDS = new Set(["look_away", "head_down", "face_absent", "eyes_down", "inactive"]);
// ambient weight-points per hour that read as ordinary; score counts the excess
export const AMBIENT_BUDGET_PER_HOUR = 4;
// nobody is judged on a rate measured over two minutes
export const MIN_WINDOW_MS = 20 * 60 * 1000;

// Whether repeats should compress depends on WHY a kind repeats.
//
// `phone` and `second_face` re-fire every 15 s for as long as the thing is there,
// so eight events is one phone held for two minutes — duration, not repetition,
// and it must not score eight times over.
//
// `look_away` and `head_down` are edge-triggered: the student has to return to
// baseline before another can fire. Eleven of those really are eleven separate
// drifts, and compressing them would let the worst behaviour score the least.
// `still_frame` re-fires every 60 s while the picture stays frozen, so a photo
// left in front of the camera for an hour is ONE thing that happened for an hour
// — the same shape as a phone held in view, and compressed the same way.
export const REFIRE_KINDS = new Set(["phone", "second_face", "still_frame"]);
export const episodePoints = (kind, count) => {
  const w = WEIGHT[kind] || 1, n = Math.max(1, count);
  return REFIRE_KINDS.has(kind) ? w * (1 + Math.log2(n)) : w * n;
};

// ── how much to trust what we saw ───────────────────────────────────────────
// Calibration already grades the setup and the report already says "weak camera
// setup" beside a finding. Saying it and then scoring as though it were solid is
// half an answer: a student flagged twenty times for looking away on a setup we
// admitted was poor is much weaker evidence than the same on a good one.
//
// Only the gaze and face flags are discounted — they are the ones that depend on
// seeing someone clearly. A phone at 0.6 confidence is still a phone.
//
// NOTE the missing-record case returns 1, deliberately. If an absent `calibrated`
// event bought a discount, suppressing it would become the cheapest way to lower
// your own score. No record means no discount; it is handled as "no data" instead.
export const CALIB_TRUST = { solid: 1, fair: 0.7, weak: 0.45 };
export function trustOf(calib) {
  if (!calib || !calib.grade) return 1;
  return CALIB_TRUST[calib.grade] ?? 1;
}

// ── what upholding a flag is worth ──────────────────────────────────────────
// Setting a flag aside removed it from the score. Upholding one did nothing at
// all, so a report a teacher had read end to end scored exactly like one nobody
// had opened. Agreeing with the machine was the only verdict with no consequence.
//
// It could not simply add weight: a person saying "yes, that happened" does not
// make it a worse thing to have done, and a score that climbed because someone
// pressed a button would be an accusation the evidence never supported.
//
// What a person CAN answer is the machine's own doubt. The trust discount exists
// because a weak camera makes gaze and face flags unreliable evidence — we can
// see something happened but not well enough to be sure. A teacher upholding that
// finding has looked at exactly that question and answered it. So an upheld event
// is scored at full weight, and the discount stays on everything still unread.
//
// This can only ever restore what uncertainty took away. Full weight is the
// ceiling; there is no multiplier above 1, and a solid setup — nothing discounted
// — is unmoved by review. Confirmation resolves doubt; it cannot manufacture it.
export const upheld = e => e && e.review === "confirmed";

// Score a set of episodes against how long that student was actually monitored.
// Ambient flags are a rate; the rate used is the WORSE of the whole sitting and
// the busiest stretch in it, so a frantic two minutes isn't averaged into
// nothing by two calm hours around it.
//
// `trust` is folded into each event's weight rather than multiplied over the
// total, so that an upheld event can carry a different one. With nothing upheld
// the two are identical — every term scales by the same constant — so this is the
// same arithmetic it has always been until somebody reviews something.
export function scoreEpisodes(eps, windowMs, trust = 1) {
  let discrete = 0;
  const amb = [];
  for (const ep of eps) {
    if (!AMBIENT_KINDS.has(ep.kind)) { discrete += episodePoints(ep.kind, ep.count); continue; }
    const w = WEIGHT[ep.kind] || 1;
    for (const e of ep.events) amb.push({ at: t(e.at), w: w * (upheld(e) ? 1 : trust) });
  }
  if (!amb.length) return discrete;
  const hours = Math.max(MIN_WINDOW_MS, windowMs || 0) / 3600000;
  let perHour = amb.reduce((sum, x) => sum + x.w, 0) / hours;
  amb.sort((a, b) => a.at - b.at);
  const spanHours = MIN_WINDOW_MS / 3600000;
  for (let i = 0; i < amb.length; i++) {
    let sum = 0;
    for (let j = i; j < amb.length && amb[j].at - amb[i].at <= MIN_WINDOW_MS; j++) sum += amb[j].w;
    perHour = Math.max(perHour, sum / spanHours);
  }
  return discrete + perHour / AMBIENT_BUDGET_PER_HOUR;
}

export const label = k => LABELS[k] || k;
export const headline = k => HEADLINES[k] || label(k);
export const roomHeadline = k => ROOM_HEADLINES[k] || ("The room flagged at once — " + label(k).toLowerCase());
export const phrase = (k, n) => (PHRASES[k] || label(k).toLowerCase()) + (n > 1 ? ", " + n + " times" : "");

// ── time ────────────────────────────────────────────────────────────────────
export const t = iso => (iso instanceof Date ? iso : new Date(iso)).getTime();

// Every clock string on every surface is the EXAM's local time, not the reader's.
//
// A timestamp is an instant; the hour it reads as is a choice, and the browser
// was quietly making that choice from wherever the reader happened to be. A
// teacher marking from another timezone — or, more often, anyone opening the PDF
// they were sent — saw "10:14" against an exam that ran at 15:44, with nothing on
// the page saying so. Two people could read the same record and disagree about
// when it happened, which is not a thing a record may do.
//
// The zone is stamped on the exam when it is created (v13). Without it we fall
// back to the reader's own zone, which is exactly how this behaved before, so
// exams created before the migration read as they always did.
let TZ = null;
export function useTimezone(tz) {
  TZ = tz && (() => { try { new Intl.DateTimeFormat([], { timeZone: tz }); return true; } catch { return false; } })()
    ? tz : null;
  return TZ;
}
export const timezone = () => TZ;
const zoned = o => (TZ ? { ...o, timeZone: TZ } : o);

// "GMT+5:30" — said only when the reader would otherwise misread the clock.
// Stating the obvious on every report would be chrome; saying nothing when the
// times have shifted under someone is the bug.
//
// The test is whether the two zones show the same wall clock for this instant,
// NOT whether they have the same name: a browser reporting Asia/Calcutta and an
// exam stamped Asia/Kolkata are the same place, and captioning that would be a
// warning about nothing. Comparing the rendered time also gets DST right for
// free, since it asks about the moment rather than the rule.
export function tzNote(at) {
  if (!TZ) return "";
  const when = new Date(at == null ? Date.now() : at);
  const shown = o => new Intl.DateTimeFormat([], o).format(when);
  const opts = { dateStyle: "short", timeStyle: "short" };
  if (shown(opts) === shown({ ...opts, timeZone: TZ })) return "";
  const part = new Intl.DateTimeFormat([], { timeZone: TZ, timeZoneName: "short" })
    .formatToParts(when).find(p => p.type === "timeZoneName");
  return "times in " + (part ? part.value : TZ);
}

export const clock = x => new Date(x).toLocaleTimeString([], zoned({ hour: "2-digit", minute: "2-digit" }));
// 11:01–11:42 PM — the meridiem, where the locale has one, is said once
export function clockRange(a, b) {
  const A = clock(a), B = clock(b);
  const m = A.match(/\s?([AP]\.?M\.?)$/i);
  return (m && B.toUpperCase().endsWith(m[1].toUpperCase()) ? A.slice(0, m.index) : A) + "–" + B;
}
export const clockSec = x => new Date(x).toLocaleTimeString([], zoned({ hour: "2-digit", minute: "2-digit", second: "2-digit" }));
export const dateLong = x => new Date(x).toLocaleDateString([], zoned({ day: "numeric", month: "long", year: "numeric" }));
export function ago(x) {
  const s = Math.max(0, Math.round((Date.now() - t(x)) / 1000));
  if (s < 45) return "a moment ago";
  const m = Math.round(s / 60);
  if (m < 60) return m + " min ago";
  const h = Math.round(m / 60);
  return h + (h === 1 ? " hour ago" : " hours ago");
}
export function spanTxt(a, b) {
  const s = Math.max(1, Math.round((b - a) / 1000));
  if (s < 60) return s + " s";
  const m = Math.round(s / 60);
  return m + " min";
}
// twenty-two students finished clear — words read better than digits in prose
const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
  "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen", "Twenty",
  "Twenty-one", "Twenty-two", "Twenty-three", "Twenty-four", "Twenty-five", "Twenty-six", "Twenty-seven",
  "Twenty-eight", "Twenty-nine", "Thirty"];
export const word = n => (n >= 0 && n < WORDS.length ? WORDS[n] : String(n));

// ── presence ────────────────────────────────────────────────────────────────
// The heartbeat is every 6 s and runs on a Worker clock, so it no longer misses
// beats when the student's tab is in the background. That means this window can be
// tight: 15 s is two and a half beats of slack, and a student who closes the tab
// also fires an explicit offline beacon, so leaving shows up almost at once.
export const PRESENCE_MS = 15000;
export function isOnline(p) {
  if (!p) return false;
  if (p.status === "offline") return false;   // they told us they were going
  return (Date.now() - t(p.last_seen)) < PRESENCE_MS;
}

// ── when an exam actually ran ───────────────────────────────────────────────
// starts_at/ends_at arrive with migration v12. Everything here falls back to the
// old created_at/closed_at behaviour when they are absent, so exams recorded
// before v12 read exactly as they always did.
export function examWindow(exam) {
  if (!exam) return { startT: null, endT: null, planned: false };
  const startT = exam.starts_at ? t(exam.starts_at) : (exam.created_at ? t(exam.created_at) : null);
  const endT = exam.ends_at ? t(exam.ends_at)
    : exam.closed_at ? t(exam.closed_at) : null;
  return { startT, endT, planned: !!exam.starts_at };
}
// An exam is over when the teacher closed it OR its time simply ran out. This is
// a static site with no background job, so nothing can flip the row at the right
// moment — the end has to be derived from the clock, and persisted opportunistically
// by whichever teacher surface happens to be open.
export function examOver(exam) {
  if (!exam) return false;
  if (exam.status === "closed") return true;
  return !!exam.ends_at && Date.now() >= t(exam.ends_at);
}
// "the exam is under way" — a real start that has passed. An exam with no
// starts_at has not been started (or predates v12); examPending tells them apart
// from a finished one. Both are false here, which is the safe answer for a caller
// that just wants to know whether exam time is running.
export function examStarted(exam) {
  if (!exam || !exam.starts_at) return false;
  return Date.now() >= t(exam.starts_at) && !examOver(exam);
}
// created, shared, waiting for the teacher to press Start
export const examPending = exam => !!exam && exam.status === "open" && !exam.starts_at;
export function msLeft(exam) {
  if (!exam || !exam.ends_at) return null;
  return Math.max(0, t(exam.ends_at) - Date.now());
}
export function countdown(ms) {
  if (ms == null) return "";
  const m = Math.floor(ms / 60000), h = Math.floor(m / 60);
  if (h) return h + "h " + String(m % 60).padStart(2, "0") + "m left";
  if (m) return m + (m === 1 ? " minute left" : " minutes left");
  return Math.ceil(ms / 1000) + "s left";
}

// ── episodes: one student's consecutive same-kind flags ─────────────────────
export const EP_GAP = 90_000;
export function episodesOf(evs) {
  const eps = [];
  for (const e of evs) {
    const ts = t(e.at), last = eps[eps.length - 1];
    if (last && last.kind === e.kind && ts - last.endT <= EP_GAP) { last.events.push(e); last.endT = ts; }
    else eps.push({ kind: e.kind, startT: ts, endT: ts, events: [e] });
  }
  for (const ep of eps) {
    ep.count = ep.events.length;
    ep.ids = ep.events.map(e => e.id).filter(Boolean);
    ep.alert = ALERT_KINDS.has(ep.kind);
    ep.review = verdictOf(ep.events);
  }
  return eps;
}

// a group of events reads as reviewed only when every event agrees
export function verdictOf(evs) {
  if (!evs.length) return null;
  const first = evs[0].review || null;
  return evs.every(e => (e.review || null) === first) ? first : null;
}

// ── room-wide moments ───────────────────────────────────────────────────────
// If most of the room flags the same way inside the same minute, that is almost
// certainly the room — a door, an announcement, the invigilator walking past —
// and not a dozen students deciding to cheat simultaneously. Computed entirely
// from events that already exist; no schema change, no new detection.
export const ROOM_SHARE = 0.6;   // share of the roster that must flag together
export const ROOM_MIN = 5;       // …and never fewer than this many students

export function roomMoments(events, rosterSize, opts = {}) {
  const share = opts.share ?? ROOM_SHARE, min = opts.min ?? ROOM_MIN;
  if (!rosterSize || rosterSize < min) return [];
  const buckets = new Map();
  for (const e of events) {
    if (!isFlag(e)) continue;
    const minute = Math.floor(t(e.at) / 60000);
    const key = e.kind + "|" + minute;
    let b = buckets.get(key);
    if (!b) buckets.set(key, b = { kind: e.kind, minute, people: new Set(), events: [] });
    b.people.add(e.participant_id);
    b.events.push(e);
  }
  const hits = [...buckets.values()]
    .filter(b => b.people.size >= min && b.people.size / rosterSize >= share)
    .sort((a, b) => a.kind.localeCompare(b.kind) || a.minute - b.minute);

  // a moment that straddles a minute boundary is still one moment
  const out = [];
  for (const b of hits) {
    const last = out[out.length - 1];
    if (last && last.kind === b.kind && b.minute - last.lastMinute <= 1) {
      last.lastMinute = b.minute;
      b.people.forEach(p => last.people.add(p));
      last.events.push(...b.events);
    } else {
      out.push({ kind: b.kind, minute: b.minute, lastMinute: b.minute, people: new Set(b.people), events: [...b.events] });
    }
  }
  for (const m of out) {
    m.events.sort((a, b) => t(a.at) - t(b.at));
    m.startT = t(m.events[0].at);
    m.endT = t(m.events[m.events.length - 1].at);
    m.count = m.events.length;
    m.ids = m.events.map(e => e.id).filter(Boolean);
    m.share = m.people.size / rosterSize;
    m.review = verdictOf(m.events);
  }
  return out.sort((a, b) => a.startT - b.startT);
}

// ── two students, over and over, at the same moment ─────────────────────────
// Room-wide moments need 60% of the roster, which makes them structurally blind
// to the commonest shape of copying: EXACTLY TWO people, repeatedly, together.
// Two is never a room and never a coincidence worth a finding on its own — but
// two who keep doing the same thing within half a minute of each other, far more
// often than their own rates predict, is the thing a human invigilator notices
// from the front of the hall and no report has ever been able to say.
//
// Everything here is computed from events that already exist. No new detection,
// no schema change, nothing extra sent from anybody's laptop.
//
// READ THE WARNING IN §5.16 BEFORE CHANGING ANY OF THIS. Co-occurrence is not
// evidence of collusion — two friends sitting by the same door look exactly like
// this — and it is the most accusatory thing this system can print. Everything
// below is tuned to be quiet rather than clever: it reports what it counted and
// what chance predicts, and it never once uses the word.
export const PAIR_TOL_MS = 30_000;    // "at the same moment", generously read
export const PAIR_MIN = 4;            // fewer togethers than this is noise at any ratio
export const PAIR_LIFT = 3;           // …and it must be this many times what chance predicts
export const PAIR_MAX_CLUSTER = 0.25; // a moment shared by more of the room than this is not a pair
export const PAIR_ALPHA = 0.05;       // …and we still expect to be wrong about this often, per exam

// P(X ≥ k) for a Poisson with mean λ. Small k and small λ here, so the naive sum
// is exact enough and there is no library to reach for in a static site.
export function poissonAtLeast(k, lambda) {
  if (k <= 0) return 1;
  if (!(lambda > 0)) return 0;
  let term = Math.exp(-lambda), cdf = term;
  for (let i = 1; i < k; i++) { term *= lambda / i; cdf += term; }
  return Math.max(0, Math.min(1, 1 - cdf));
}

// Episodes overlap when their spans touch, allowing for one being a little late.
const near = (a, b, tol) => a.startT - tol <= b.endT && b.startT - tol <= a.endT;

export function pairMoments(students, opts = {}) {
  const tol = opts.tol ?? PAIR_TOL_MS, minTogether = opts.pairMin ?? PAIR_MIN;
  const lift = opts.lift ?? PAIR_LIFT;
  if (!students || students.length < 3) return [];   // two students ARE the room
  const maxCluster = Math.max(2, Math.floor(students.length * (opts.maxCluster ?? PAIR_MAX_CLUSTER)));

  // one flat list of episodes per kind, so co-occurrence is a sweep rather than
  // a comparison of every student against every other
  const byKind = new Map();
  const stats = new Map();          // student|kind → { n, dur }
  for (const s of students) {
    // `own` skips anything a room-wide moment already speaks for — otherwise the
    // whole room looking up at a door would make a pair of every two people in it
    const usable = s.own.filter(e => e.review !== "dismissed");
    for (const ep of episodesOf(usable)) {
      if (!byKind.has(ep.kind)) byKind.set(ep.kind, []);
      byKind.get(ep.kind).push({ ...ep, s });
      const k = s.p.id + "|" + ep.kind;
      const st = stats.get(k) || { n: 0, dur: 0 };
      st.n++; st.dur += ep.endT - ep.startT;
      stats.set(k, st);
    }
  }

  const pairs = new Map();
  for (const [kind, eps] of byKind) {
    eps.sort((a, b) => a.startT - b.startT);
    for (let i = 0; i < eps.length; i++) {
      // everything that could still overlap episode i, in start order
      const cluster = [];
      for (let j = i + 1; j < eps.length && eps[j].startT - tol <= eps[i].endT; j++)
        if (eps[j].s !== eps[i].s && near(eps[i], eps[j], tol)) cluster.push(eps[j]);
      // a moment shared by a crowd is a property of the room, not of any two
      // people in it — and it would otherwise mint a pair for every couple in it
      if (cluster.length + 1 > maxCluster) continue;
      for (const o of cluster) {
        const [a, b] = eps[i].s.p.id < o.s.p.id ? [eps[i].s, o.s] : [o.s, eps[i].s];
        const key = a.p.id + "|" + b.p.id + "|" + kind;
        let p = pairs.get(key);
        if (!p) pairs.set(key, p = { a, b, kind, together: 0, events: [], startT: Infinity, endT: 0 });
        p.together++;
        p.events.push(...eps[i].events, ...o.events);
        p.startT = Math.min(p.startT, eps[i].startT, o.startT);
        p.endT = Math.max(p.endT, eps[i].endT, o.endT);
      }
    }
  }

  // HOW OFTEN CHANCE ALONE WOULD HAVE DONE THIS. Two students who each drift off
  // twenty times in an hour will land together sometimes for no reason at all,
  // and a raw count of togethers would report the two most fidgety people in the
  // room every single time. What matters is the excess over their own rates.
  //
  // Two intervals dropped at random into a shared window W overlap with
  // probability (durA + durB + 2·tol)/W, so nA·nB of them meet that many times.
  // It is a first-order estimate and is called one — the finding says "chance
  // predicts one", never a probability it cannot stand behind.
  const cand = [];
  for (const p of pairs.values()) {
    const sa = stats.get(p.a.p.id + "|" + p.kind), sb = stats.get(p.b.p.id + "|" + p.kind);
    if (!sa || !sb) continue;
    const W = Math.max(MIN_WINDOW_MS, Math.min(
      p.a.winTo ?? 0, p.b.winTo ?? 0) - Math.max(p.a.winFrom ?? 0, p.b.winFrom ?? 0));
    if (!(W > 0)) continue;
    const expected = sa.n * sb.n * ((sa.dur / sa.n) + (sb.dur / sb.n) + 2 * tol) / W;
    cand.push({ ...p, expected, lift: p.together / Math.max(expected, 1e-9),
      pv: poissonAtLeast(p.together, expected) });
  }

  // EVERY PAIR IN THE ROOM IS A SEPARATE QUESTION, AND WE ASK ALL OF THEM AT ONCE.
  // Twenty students is a hundred and ninety pairs. Ask a hundred and ninety
  // questions and a handful come back looking remarkable for no reason at all —
  // four coincidences against an expectation of half a one is nine times chance
  // and means nothing, because something had to come top.
  //
  // A first cut of this reported eleven pairs in a room where nobody had done
  // anything, all of them wearing a confident-looking multiple. That is the
  // failure that would end this feature's credibility on its first real exam:
  // name a quarter of the class and no one believes the one pair that mattered.
  //
  // So the bar rises with the number of questions asked. `pv` is the chance of
  // seeing this many togethers if the two of them had nothing to do with each
  // other; it has to survive being multiplied by the number of pairs we tested.
  // The effect-size floors stay as well — a big enough sample makes trivial
  // differences significant, and a pair that is real but tiny is not a finding.
  const tests = Math.max(1, cand.length);
  const out = [];
  for (const p of cand) {
    if (p.together < minTogether) continue;
    if (!(p.together >= p.expected * lift)) continue;
    if (p.pv * tests > (opts.alpha ?? PAIR_ALPHA)) continue;
    // One episode can overlap two of the other student's, so the same event
    // arrives twice. Deduped and put in time order here, because the appendix
    // groups these into runs and would otherwise list a moment twice and date
    // the runs from whichever student happened to be swept first.
    const seenId = new Set();
    const events = p.events
      .filter(e => (e.id == null ? true : !seenId.has(e.id) && seenId.add(e.id)))
      .sort((x, y) => t(x.at) - t(y.at));
    out.push({
      kind: p.kind, pair: true, room: false, people: new Set([p.a.p.id, p.b.p.id]),
      a: p.a, b: p.b, together: p.together, expected: p.expected, lift: p.lift,
      pv: p.pv, tests,
      startT: p.startT, endT: p.endT, count: p.together,
      events, ids: events.map(e => e.id).filter(Boolean),
      review: verdictOf(events),
    });
  }
  return out.sort((x, y) => x.pv - y.pv || y.together - x.together);
}

// ── evidence quality ────────────────────────────────────────────────────────
// Only the phone detector produces a real confidence number. Everything else is
// rule-based and must say so rather than borrow a number it never computed.
export function evidenceQuality(events, calib) {
  const scores = events.map(e => e.meta && typeof e.meta.score === "number" ? e.meta.score : null).filter(s => s != null);
  if (scores.length) return "detector " + Math.round(scores.reduce((a, b) => a + b, 0) / scores.length * 100) + "% confident";
  if (calib && calib.grade && calib.grade !== "solid") return calib.grade + " camera setup";
  return "no confidence value";
}

// ── how much of the exam we actually watched ────────────────────────────────
// The report was all numerator. "Nothing was flagged" is a very different claim
// depending on whether we watched someone for the whole exam or for nine minutes
// of it, and the document had no way to say which — a student whose camera faced
// a wall came out reading exactly like one who behaved.
//
// The device writes cumulative {seen, total} seconds every few minutes, so any
// window can be measured by differencing the two rows that bracket it.
//
// Returns null when there is nothing to read, and that is the important case:
// every exam recorded before this shipped has no coverage rows at all, so every
// surface must treat "unknown" as "carry on exactly as before" rather than as a
// bad result. An old report may not grow a new complaint about its students.
export const COVERAGE_FLOOR = 0.8;   // below this, "finished clear" is not a claim we can make
export function coverageOf(events, from, to) {
  const rows = (events || []).filter(e => e.kind === "coverage" && e.meta &&
    typeof e.meta.seen === "number" && typeof e.meta.total === "number")
    .sort((a, b) => t(a.at) - t(b.at));
  if (!rows.length) return null;
  // the counters are cumulative from the moment monitoring began, so the window
  // is the difference between the last row inside it and the last one before it
  const base = rows.filter(r => from == null || t(r.at) <= from).pop();
  const end = rows.filter(r => to == null || t(r.at) <= to).pop();
  if (!end || end === base) return null;
  const seen = end.meta.seen - (base ? base.meta.seen : 0);
  const total = end.meta.total - (base ? base.meta.total : 0);
  if (!(total > 0)) return null;
  return Math.max(0, Math.min(1, seen / total));
}
export const coveragePct = c => (c == null ? null : Math.round(c * 100));

// ── the exam, read ──────────────────────────────────────────────────────────
// One pass that both surfaces share: per-student events, calibration, score,
// episodes, plus the room-wide moments and the findings that come out of them.
export const FINDING_SCORE = 4;   // the report's existing "medium" bar

// ── the class at a glance ───────────────────────────────────────────────────
// A hundred students is not a list anybody reads. It is a shape: how many
// finished clear, how many are worth a word, how many are worth a hearing. Both
// surfaces draw that shape now, and they must not arrive at different numbers
// for the same room — so a student's band is decided once, here.
//
// Every student lands in exactly one band and none lands in no band, which is
// what lets the bar be drawn as a proportion of the class rather than as five
// numbers that happen to sit near each other.
//
// `unverified` is tested LAST but matters most: a student who never completed
// setup scores zero for the same reason an absent one does, and letting that
// read as "clear" is the one thing this summary could say that isn't true.
// `short` is what a bar wears under it; `label` is the same thing said inline
// in a sentence. Four of these are drawn even at zero — "0 high risk" is the
// best news a report can carry and a chart that hid it would only ever show
// bad news. `unverified` appears only when it happened, because a column
// labelled "no data" reading zero is a question nobody asked.
export const RISK_BANDS = [
  { key: "high", label: "high risk", short: "High risk", always: true },
  { key: "medium", label: "medium risk", short: "Medium", always: true },
  { key: "low", label: "low risk", short: "Low", always: true },
  { key: "clear", label: "clear", short: "Clear", always: true },
  { key: "unverified", label: "no data", short: "No data" },
];
// what the four words actually mean, for a reader who is not the invigilator
export const BAND_KEY =
  "High risk — a phone, a second face, or a pattern serious enough to sit down with the student. " +
  "Medium — repeated flags worth a look. No risk — nothing, or a glance or two across the " +
  "whole sitting, which is what ordinary people do.";
export const riskBand = s =>
  s.score >= 10 ? "high" : s.score >= FINDING_SCORE ? "medium" : s.score > 0 ? "low"
    : s.unverified ? "unverified" : "clear";
export const bandLabel = k => (RISK_BANDS.find(b => b.key === k) || {}).label || k;

// The counts as a row of chips, for a list where a bar chart will not fit.
// Zero bands are dropped here, unlike the graph: a list row is scanned, not
// studied, and "0 high · 0 medium · 0 low · 12 clear" makes a teacher read four
// things to learn one. When nothing was flagged it says so in as many words.
export function bandChips(counts, opts = {}) {
  const shown = RISK_BANDS.filter(b => counts[b.key] > 0);
  if (!shown.length) return "";
  if (shown.length === 1 && shown[0].key === "clear")
    return '<span class="bd none">' + counts.clear + ' student' +
      (counts.clear === 1 ? "" : "s") + ' · nothing flagged</span>';
  return shown.map(b => '<span class="bd ' + b.key + '"><i></i><b>' + counts[b.key] + '</b> ' +
    (opts.short ? b.short.toLowerCase() : b.label) + '</span>').join("");
}
export function bandCounts(students) {
  const c = { high: 0, medium: 0, low: 0, clear: 0, unverified: 0 };
  for (const s of students || []) c[riskBand(s)]++;
  return c;
}

// ── the three bands a report is READ in ─────────────────────────────────────
// Five bands are what the score produces. Three are what a person is shown.
//
// "Low" — a couple of glances across two hours — is not a risk anybody acts on,
// and giving it its own column made the reader weigh a distinction that changes
// nothing. It reads as no risk. Three bars can be read from the back of a room;
// five have to be studied.
//
// `unverified` is deliberately OUTSIDE the three rather than folded into "no
// risk". A student who never completed setup is not low risk, they are
// unmeasured, and calling that a clean result is the one thing this summary
// could say that isn't true. They are counted and named beside the chart.
export const REPORT_BANDS = [
  { key: "high", label: "High risk" },
  { key: "medium", label: "Medium" },
  { key: "none", label: "No risk" },
];
export function reportBand(s) {
  const b = riskBand(s);
  return b === "high" ? "high" : b === "medium" ? "medium" : b === "unverified" ? null : "none";
}
// worst first, then by name — the order a teacher works down
export function splitByBand(students) {
  const out = { high: [], medium: [], none: [], unverified: [] };
  for (const s of students || []) out[reportBand(s) || "unverified"].push(s);
  for (const k of ["high", "medium", "none", "unverified"])
    out[k].sort((a, b) => b.score - a.score || a.p.name.localeCompare(b.p.name));
  return out;
}

// The chart's markup, built once. Layout normally lives in the page, but this
// figure is the report — two hand-copied versions of it would drift, and the
// day they disagreed about a class is the day neither can be trusted.
// `interactive` false drops everything that implies you may press it, which is
// what the printed copy needs.
export function chartHtml(byBand, opts = {}) {
  const counts = REPORT_BANDS.map(b => (byBand[b.key] || []).length);
  const total = counts.reduce((a, b) => a + b, 0);
  if (!total) return "";
  const raw = Math.max(...counts) / 4 || 1;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) || 10 * mag;
  const top = Math.max(step, Math.ceil(Math.max(...counts) / step) * step);
  let ticks = "", lines = "";
  for (let v = 0; v <= top + 1e-6; v += step) {
    const pct = (1 - v / top) * 100, d = (v / top) * 0.25;
    ticks += '<span style="top:' + pct + '%;animation-delay:' + d + 's">' + v + '</span>';
    lines += '<div class="vline" style="top:' + pct + '%;animation-delay:' + d + 's"></div>';
  }
  const sel = opts.selected;
  const col = (b, i) => {
    const n = (byBand[b.key] || []).length;
    const inner = '<span class="vbar ' + b.key + '" data-h="' + (n / top * 100) + '" data-n="' + n + '">' +
      '<span class="vn">' + (opts.interactive === false ? n : 0) + '</span>' +
      '<span class="vp">' + Math.round(n / total * 100) + '%</span></span>';
    return opts.interactive === false
      ? '<span class="vcol">' + inner + '</span>'
      : '<button type="button" class="vcol' + (sel === b.key ? " on" : "") + '" data-band="' + b.key +
        '" aria-pressed="' + (sel === b.key) + '" aria-label="' + n + ' ' + b.label.toLowerCase() +
        '">' + inner + '</button>';
  };
  return '<div class="vchart"><div class="vy">' + ticks + '</div><div>' +
    '<div class="vplot">' + lines + '<div class="vbars">' + REPORT_BANDS.map(col).join("") + '</div></div>' +
    '<div class="vlabels">' + REPORT_BANDS.map(b =>
      '<span data-band="' + b.key + '"' + (sel === b.key ? ' class="on"' : '') + '>' + b.label + '</span>'
    ).join("") + '</div></div></div>';
}

// ── when it happened, for one student ───────────────────────────────────────
// Eight columns across their time in the room, a count over each and a clock
// time under each. A column is red when something serious fell in that stretch,
// so severity is the colour of the bar rather than a second bar stacked inside
// it — which is what made the earlier version something you decoded rather than
// read. Hovering a column says exactly what it contains, empty ones included.
//
// The report and the live room draw the same figure from this one function. A
// student's record must not look like two different afternoons depending on
// which page you opened it from.
export const WHEN_COLS = 8;
export function whenChart(s, opts = {}) {
  const from = t(s.p.joined_at);
  // WHERE THEIR TIME ENDS. `last_seen` is the honest answer, but exams recorded
  // before it was written have none — and falling straight through to "now"
  // stretched a two-hour sitting across every day since, piling every flag into
  // the first column and leaving seven empty ones. A chart that confident and
  // that wrong is worse than no chart.
  //
  // So: the last thing we actually saw them do, then the exam's own end, and
  // only then the clock. A student still sitting in a running exam has neither
  // of the first two and genuinely does run to now.
  let to = s.p.last_seen ? t(s.p.last_seen) : (s.lastAt || opts.end || opts.now || Date.now());
  if (opts.end) to = Math.min(to, opts.end);
  const span = Math.max(60000, to - from);
  if (!s.events.length)
    return '<div class="wnone">Nothing was flagged between ' + clock(from) + ' and ' + clock(to) + '.</div>';
  // Fewer columns for a short sitting. Eight labels all reading the same minute
  // would look precise and say nothing, which is worse than being coarse.
  const N = Math.max(3, Math.min(WHEN_COLS, Math.floor(span / 120000)));
  const slice = span / N;
  const bins = Array.from({ length: N }, () => ({ n: 0, alert: false, kinds: {} }));
  for (const e of s.events) {
    const i = Math.max(0, Math.min(N - 1, Math.floor((t(e.at) - from) / span * N)));
    bins[i].n++;
    if (ALERT_KINDS.has(e.kind)) bins[i].alert = true;
    bins[i].kinds[e.kind] = (bins[i].kinds[e.kind] || 0) + 1;
  }
  const max = Math.max(1, ...bins.map(b => b.n));
  const cols = bins.map((b, i) => {
    const what = Object.entries(b.kinds).sort((x, y) => y[1] - x[1])
      .map(([k, c]) => c + " " + label(k).toLowerCase()).join(", ");
    return '<div class="wcol' + (b.n ? "" : " zero") + '" title="' +
      esc(clock(from + i * slice) + "–" + clock(from + (i + 1) * slice) + " · " +
          (b.n ? what : "nothing flagged")) + '">' +
      '<span class="wn">' + (b.n || "") + '</span>' +
      '<span class="wbar' + (b.alert ? " alert" : "") + '" data-h="' + (b.n / max * 100) + '"></span></div>';
  }).join("");
  return '<div class="wcols">' + cols + '</div><div class="wx">' +
    bins.map((b, i) => '<span>' + clock(from + i * slice) + '</span>').join("") + '</div>' +
    (bins.some(b => b.alert)
      ? '<div class="wkey"><i></i>a phone or a second face was seen in that stretch</div>' : '');
}

// The flag chips under the chart — every kind they were flagged for, worst
// first, the serious ones wearing red.
export function kindChips(s) {
  const kinds = Object.entries(s.counts || {}).sort((a, b) => b[1] - a[1]);
  if (!kinds.length) return "";
  return '<div class="kinds">' + kinds.map(([k, n]) =>
    '<span class="kd ' + (ALERT_KINDS.has(k) ? "alert" : "") + '"><b>' + n + '</b> ' +
    esc(label(k)) + '</span>').join("") + '</div>';
}

// ── what a summary may not leave out ────────────────────────────────────────
// A filed document that runs to nine pages is read by nobody, and a summary
// that drops the serious thing is worse than no summary at all. So the document
// keeps these in full and compresses everything else to a line — the reader can
// open the full record for the rest, and the line tells them it is there.
//
// Room-wide moments are in this list even though they accuse no one. They are
// what EXCUSES a whole room, and a summary that dropped them would read as
// harsher than the evidence behind it.
// A pair finding belongs on page one whatever kind it is built from. Its weight
// is not in the kind — two people looking away together nine times is a weaker
// flag repeated than one phone, and a much better reason to go and talk to
// somebody — and compressing it to a line in the appendix would bury the one
// thing here a teacher could not have worked out from the tiles.
export const keyFinding = f =>
  !!f && (f.room || f.pair || SERIOUS_KINDS.has(f.kind) || (f.student && riskBand(f.student) === "high"));

// ── what the two of them said about a finding ───────────────────────────────
// A note hangs off (participant, kind) — the same unit a student-level finding is
// built from — so it lands beside the thing it is about rather than in a pile at
// the end. One per author (v14 enforces it): the student states their case once
// and may edit it, the teacher records one outcome. A record, not a thread.
export const noteKey = (pid, kind) => pid + "|" + kind;
export function notesByFinding(notes) {
  const m = new Map();
  for (const n of (notes || [])) {
    const k = noteKey(n.participant_id, n.kind);
    if (!m.has(k)) m.set(k, {});
    m.get(k)[n.author] = n;
  }
  return m;
}

export function readExam(participants, events, opts = {}) {
  const notes = notesByFinding(opts.notes);
  const roster = (participants || []).slice().sort((a, b) => t(a.joined_at) - t(b.joined_at));
  // Flags raised before the teacher pressed Start are settling-in, not exam
  // behaviour. They stay in the record; they simply stop being held against
  // anyone. (No starts_at — a pre-v12 exam — and nothing is excluded.)
  const examStartT = opts.startsAt ? t(opts.startsAt) : null;
  const examEndT = opts.endsAt ? t(opts.endsAt) : null;
  if (examStartT) events = (events || []).filter(e => !isFlag(e) || t(e.at) >= examStartT);
  const byP = new Map(roster.map(p => [p.id, []]));
  for (const e of (events || [])) {
    if (!byP.has(e.participant_id)) byP.set(e.participant_id, []);
    byP.get(e.participant_id).push(e);
  }
  for (const list of byP.values()) list.sort((a, b) => t(a.at) - t(b.at));

  // The room is read first, because a flag that belonged to the whole room
  // should not be held against the one student sitting in it.
  // Set-aside events are read here too: a finding that was considered and set
  // aside has to stay on the document wearing its verdict, or it isn't a record.
  const flagEvents = (events || []).filter(isFlag);
  const moments = roomMoments(flagEvents, roster.length, opts);
  const inRoomMoment = new Set(moments.flatMap(m => m.events.map(e => e.id)));

  const students = roster.map(p => {
    const all = byP.get(p.id) || [];
    const calib = all.filter(e => e.kind === "calibrated").map(e => e.meta || {}).pop() || null;
    const evs = all.filter(isFlag);
    const live = evs.filter(e => e.review !== "dismissed");   // set-aside flags stop counting
    const own = evs.filter(e => !inRoomMoment.has(e.id));     // what is theirs alone, verdict aside
    const counts = {};
    // the score — and so the tile's colour and the clear list — ignores set-aside flags
    const counted = own.filter(e => e.review !== "dismissed");
    counted.forEach(e => { counts[e.kind] = (counts[e.kind] || 0) + 1; });
    // How long THIS student was actually monitored — their own window, not the
    // room's. Falling back to "now" when last_seen is missing would stretch the
    // window across days for an old exam and quietly zero out every ambient
    // score, so the last thing we actually saw them do is a better end than now.
    const lastEvT = evs.length ? t(evs[evs.length - 1].at) : null;
    let from = t(p.joined_at), to = p.last_seen ? t(p.last_seen) : (lastEvT || Date.now());
    // clip to the exam itself — sitting in the room for twenty minutes before it
    // started is not monitored time, and counting it would dilute every rate
    if (examStartT) from = Math.max(from, examStartT);
    if (examEndT) to = Math.min(to, examEndT);
    const windowMs = Math.min(12 * 3600000, Math.max(0, to - from));
    // the share of that window we actually had a face in view for — null on any
    // exam recorded before the device started counting, which reads as before
    const coverage = coverageOf(all, examStartT, examEndT);
    const trust = trustOf(calib);
    const score = scoreEpisodes(episodesOf(counted), windowMs, trust);
    const eps = episodesOf(evs);
    const top = Object.entries(counts).sort((a, b) => (WEIGHT[b[0]] || 1) * b[1] - (WEIGHT[a[0]] || 1) * a[1])[0];
    // The live room only ever shows red, and only for the things a teacher would
    // walk over for. Looking away is not one of them — it would paint half the room
    // amber and teach the teacher to ignore colour entirely.
    const serious = own.some(e => e.review !== "dismissed" && SERIOUS_KINDS.has(e.kind));
    // Every monitored student writes a `calibrated` event at setup. Its ABSENCE
    // means setup never completed or nothing this laptop sent ever arrived —
    // which is also exactly what blocking Vigil's writes looks like. Either way
    // "clear" would be a lie: we have no evidence about them at all.
    const unverified = !calib;
    // every kind they were flagged for, with whatever they have said about it —
    // the student's own view offers a line against each of these, whether or not
    // it ever reached the findings bar
    const said = new Map();
    for (const kind of new Set(evs.map(e => e.kind)))
      said.set(kind, (notes.get(noteKey(p.id, kind)) || {}).student || null);
    return {
      p, calib, unverified, trust, coverage, events: evs, live, own, episodes: eps, counts, score, serious, windowMs, said,
      winFrom: from, winTo: to,   // the pair test needs the window two students shared
      // watched, but not enough of the time to call the result clean
      thin: coverage != null && coverage < COVERAGE_FLOOR,
      band: score >= 10 ? "alert" : score >= FINDING_SCORE ? "warn" : "quiet",
      lastAt: evs.length ? t(evs[evs.length - 1].at) : null,
      phrase: top ? phrase(top[0], top[1]) : "",
    };
  });

  // ── exams recorded before calibration existed ─────────────────────────────
  // "No data" means we watched for a setup record and never got one. On an exam
  // run before Vigil wrote calibration records at all, that is true of everyone
  // — so it distinguishes nobody, and it turns every old report into a wall of
  // "no data" where it used to say "clear". It would be reporting the age of the
  // build as a fact about the students.
  //
  // The test is deliberately narrow. Nobody calibrated AND somebody's flags did
  // arrive: writes plainly worked, so the missing records are the build's, not a
  // student blocking us. An exam where nothing arrived at all keeps its "no
  // data", because there we genuinely have none.
  if (!students.some(s => s.calib) && students.some(s => s.events.length))
    for (const s of students) s.unverified = false;

  // The band a student is counted under, decided once so the chart, the tiles and
  // the document can never put the same person in two places.
  for (const s of students) s.risk = riskBand(s);

  // FINDINGS — the document's unit. A room-wide moment counts once for the room;
  // a student's flags of one kind, taken together, count once for them.
  const findings = moments.map(m => ({
    kind: m.kind, room: true, events: m.events, ids: m.ids, review: m.review,
    startT: m.startT, endT: m.endT, count: m.count, people: m.people,
    headline: roomHeadline(m.kind),
    who: m.people.size + " of " + roster.length + " students",
    // a room-wide moment is one moment, however many students were in it — but a
    // bigger share of the room is a stronger finding
    score: episodePoints(m.kind, m.people.size),
    quality: evidenceQuality(m.events, null),
  }));

  // TWO PEOPLE, REPEATEDLY. Read after the room, from what the room did not
  // already explain, and it changes NOBODY'S SCORE. Their own flags are already
  // counted once against each of them; counting them again because of who else
  // was flagged at that second would be scoring a student for another student's
  // behaviour, which is the one thing a number here must never do. This is a
  // finding — a thing put in front of a person to decide — and nothing else.
  const pairs = pairMoments(students, opts);
  for (const m of pairs) {
    findings.push({
      kind: m.kind, pair: true, room: false, events: m.events, ids: m.ids, people: m.people,
      review: m.review, startT: m.startT, endT: m.endT, count: m.together,
      headline: pairHeadline(m.kind),
      who: m.a.p.name + " and " + m.b.p.name,
      score: episodePoints(m.kind, m.together),
      // carried onto the finding so the arithmetic behind it can be inspected
      // without re-deriving it — the pilot run-sheet asks for exactly these
      expected: m.expected, lift: m.lift, pv: m.pv, tests: m.tests,
      // The finding states what was counted against what chance predicts, and
      // that is all. It is a real ratio over real counts — not a probability,
      // not a confidence, and §5.6's rule holds: we do not print numbers we did
      // not compute, and we do not dress up the ones we did.
      quality: m.expected < 0.5
        ? "chance predicts under one"
        : "chance predicts " + word(Math.round(m.expected)).toLowerCase(),
    });
  }

  for (const s of students) {
    const byKind = new Map();
    for (const e of s.own) {                   // events the room already speaks for are skipped
      if (!byKind.has(e.kind)) byKind.set(e.kind, []);
      byKind.get(e.kind).push(e);
    }
    for (const [kind, evs] of byKind) {
      // the same scale the band uses, so "a finding" and "what moved the colour"
      // can never disagree
      const score = scoreEpisodes(episodesOf(evs.filter(e => e.review !== "dismissed")), s.windowMs, s.trust)
        || scoreEpisodes(episodesOf(evs), s.windowMs, s.trust);
      if (score < FINDING_SCORE) continue;     // below the bar it is not a finding
      const said = notes.get(noteKey(s.p.id, kind)) || {};
      findings.push({
        kind, room: false, student: s, events: evs, ids: evs.map(e => e.id).filter(Boolean),
        review: verdictOf(evs), startT: t(evs[0].at), endT: t(evs[evs.length - 1].at),
        count: evs.length, headline: headline(kind), who: s.p.name, score,
        quality: evidenceQuality(evs, s.calib),
        // what the student said about it, and what the conversation concluded
        said: said.student || null, outcome: said.teacher || null,
      });
    }
  }
  findings.sort((a, b) => b.score - a.score || a.startT - b.startT);
  findings.forEach((f, i) => { f.n = String(i + 1).padStart(2, "0"); });

  // a finding that was set aside no longer keeps its student off the clear list —
  // that consequence is the whole point of giving a verdict
  const named = new Set(findings
    .filter(f => !f.room && f.student && f.review !== "dismissed")
    .map(f => f.student.p.id));
  // "Finished clear" is the strongest sentence in the document — it is the one a
  // student would want quoted — so it has to be a claim we can actually stand
  // behind. Nothing flagged, AND enough of the exam watched to mean it. Someone
  // we only saw for half the sitting is not clear and is not accused; they are
  // listed as what they are, which is barely watched.
  const clear = students.filter(s => !named.has(s.p.id) && s.score === 0 && !s.unverified && !s.thin);
  // said separately from "clear", because it is the opposite of a clean result
  const unverified = students.filter(s => s.unverified);
  const thin = students.filter(s => s.thin && !s.unverified);
  // what the document can say about its own reliability, in one line
  const seen = students.map(s => s.coverage).filter(c => c != null);
  const coverage = seen.length
    ? { mean: seen.reduce((a, b) => a + b, 0) / seen.length, thin: thin.length, n: seen.length }
    : null;

  // setups worth walking over and fixing, while there is still time to fix them
  const poorSetups = students
    .filter(x => x.calib && x.calib.grade && x.calib.grade !== "solid")
    .map(x => ({ p: x.p, grade: x.calib.grade, reason: (x.calib.reasons || [])[0] || "" }));

  // How much of this document a person has actually stood behind. The findings and
  // the score alone can't say it: an unread report and one read end to end and
  // agreed with look identical on the page, and it is the second that a signature
  // at the bottom is supposed to mean.
  const review = {
    total: findings.length,
    upheld: findings.filter(f => f.review === "confirmed").length,
    aside: findings.filter(f => f.review === "dismissed").length,
    discuss: findings.filter(f => f.review === "discuss").length,
  };
  review.unread = review.total - review.upheld - review.aside - review.discuss;
  review.read = review.total - review.unread;

  const allT = (events || []).map(e => t(e.at)).filter(Boolean);
  return {
    roster, students, moments, findings, clear, unverified, thin, coverage, poorSetups, review,
    startT: allT.length ? Math.min(...allT) : null,
    endT: allT.length ? Math.max(...allT) : null,
  };
}
