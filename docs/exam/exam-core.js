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
  calibrated: "Calibrated",
};

// the short lowercase phrase a live tile wears — a glance, not a sentence
export const PHRASES = {
  phone: "phone", second_face: "second face", virtual_cam: "virtual camera",
  camera_off: "camera off", monitor_hidden: "camera gap", left_exam: "left the page",
  face_absent: "face not visible", look_away: "eyes off screen", head_down: "head down",
  eyes_down: "eyes on the desk",
};

// the headline a finding wears in the document — describes, never accuses
export const HEADLINES = {
  phone: "A phone was in view", second_face: "Someone else was in frame",
  virtual_cam: "A virtual camera was in use", camera_off: "The camera was off",
  monitor_hidden: "Vigil could not read the camera", left_exam: "Left the exam page",
  face_absent: "Face out of view", look_away: "Eyes off screen, repeatedly",
  head_down: "Head down, repeatedly", eyes_down: "Eyes on the desk, repeatedly",
};

// the same moment, when it belonged to the room rather than one student
export const ROOM_HEADLINES = {
  look_away: "The room looked away at once", head_down: "The room looked down at once",
  face_absent: "The room dropped out of view at once", phone: "Phones in view across the room",
  eyes_down: "The room looked at their desks at once",
  second_face: "Second faces across the room", monitor_hidden: "Cameras unreadable across the room",
  camera_off: "Cameras went off across the room",
};

export const ALERT_KINDS = new Set(["second_face", "phone", "camera_off", "monitor_hidden", "left_exam", "virtual_cam"]);
// worth interrupting an invigilator mid-exam for — the live room shows only these
export const SERIOUS_KINDS = new Set(["phone", "second_face", "virtual_cam"]);
export const WEIGHT = { second_face: 5, phone: 5, virtual_cam: 5, left_exam: 4, monitor_hidden: 3, camera_off: 3, face_absent: 1.5, look_away: 1, head_down: 1, eyes_down: 0.4 };

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
export const AMBIENT_KINDS = new Set(["look_away", "head_down", "face_absent", "eyes_down"]);
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
export const REFIRE_KINDS = new Set(["phone", "second_face"]);
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
    if (e.kind === "calibrated") continue;
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

// ── evidence quality ────────────────────────────────────────────────────────
// Only the phone detector produces a real confidence number. Everything else is
// rule-based and must say so rather than borrow a number it never computed.
export function evidenceQuality(events, calib) {
  const scores = events.map(e => e.meta && typeof e.meta.score === "number" ? e.meta.score : null).filter(s => s != null);
  if (scores.length) return "detector " + Math.round(scores.reduce((a, b) => a + b, 0) / scores.length * 100) + "% confident";
  if (calib && calib.grade && calib.grade !== "solid") return calib.grade + " camera setup";
  return "no confidence value";
}

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
  "Medium — repeated flags worth a look. Low — a handful of glances. " +
  "Clear — nothing was recorded against them.";
export const riskBand = s =>
  s.score >= 10 ? "high" : s.score >= FINDING_SCORE ? "medium" : s.score > 0 ? "low"
    : s.unverified ? "unverified" : "clear";
export const bandLabel = k => (RISK_BANDS.find(b => b.key === k) || {}).label || k;
export function bandCounts(students) {
  const c = { high: 0, medium: 0, low: 0, clear: 0, unverified: 0 };
  for (const s of students || []) c[riskBand(s)]++;
  return c;
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
export const keyFinding = f =>
  !!f && (f.room || SERIOUS_KINDS.has(f.kind) || (f.student && riskBand(f.student) === "high"));

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
  if (examStartT) events = (events || []).filter(e => e.kind === "calibrated" || t(e.at) >= examStartT);
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
  const flagEvents = (events || []).filter(e => e.kind !== "calibrated");
  const moments = roomMoments(flagEvents, roster.length, opts);
  const inRoomMoment = new Set(moments.flatMap(m => m.events.map(e => e.id)));

  const students = roster.map(p => {
    const all = byP.get(p.id) || [];
    const calib = all.filter(e => e.kind === "calibrated").map(e => e.meta || {}).pop() || null;
    const evs = all.filter(e => e.kind !== "calibrated");
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
      p, calib, unverified, trust, events: evs, live, own, episodes: eps, counts, score, serious, windowMs, said,
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
  const clear = students.filter(s => !named.has(s.p.id) && s.score === 0 && !s.unverified);
  // said separately from "clear", because it is the opposite of a clean result
  const unverified = students.filter(s => s.unverified);

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
    roster, students, moments, findings, clear, unverified, poorSetups, review,
    startT: allT.length ? Math.min(...allT) : null,
    endT: allT.length ? Math.max(...allT) : null,
  };
}
