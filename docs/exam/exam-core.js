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
  head_down: "Looked down", look_away: "Looked away", face_absent: "Face not visible",
  second_face: "Second face detected", phone: "Phone detected", camera_off: "Camera off",
  monitor_hidden: "Camera not readable", left_exam: "Left the exam page", virtual_cam: "Virtual camera",
  calibrated: "Calibrated",
};

// the short lowercase phrase a live tile wears — a glance, not a sentence
export const PHRASES = {
  phone: "phone", second_face: "second face", virtual_cam: "virtual camera",
  camera_off: "camera off", monitor_hidden: "camera gap", left_exam: "left the page",
  face_absent: "face not visible", look_away: "eyes off screen", head_down: "head down",
};

// the headline a finding wears in the document — describes, never accuses
export const HEADLINES = {
  phone: "A phone was in view", second_face: "Someone else was in frame",
  virtual_cam: "A virtual camera was in use", camera_off: "The camera was off",
  monitor_hidden: "Vigil could not read the camera", left_exam: "Left the exam page",
  face_absent: "Face out of view", look_away: "Eyes off screen, repeatedly",
  head_down: "Head down, repeatedly",
};

// the same moment, when it belonged to the room rather than one student
export const ROOM_HEADLINES = {
  look_away: "The room looked away at once", head_down: "The room looked down at once",
  face_absent: "The room dropped out of view at once", phone: "Phones in view across the room",
  second_face: "Second faces across the room", monitor_hidden: "Cameras unreadable across the room",
  camera_off: "Cameras went off across the room",
};

export const ALERT_KINDS = new Set(["second_face", "phone", "camera_off", "monitor_hidden", "left_exam", "virtual_cam"]);
// worth interrupting an invigilator mid-exam for — the live room shows only these
export const SERIOUS_KINDS = new Set(["phone", "second_face", "virtual_cam"]);
// unchanged from the live report — this is not a scoring redesign
export const WEIGHT = { second_face: 5, phone: 5, virtual_cam: 5, left_exam: 4, monitor_hidden: 3, camera_off: 3, face_absent: 1.5, look_away: 1, head_down: 1 };

export const label = k => LABELS[k] || k;
export const headline = k => HEADLINES[k] || label(k);
export const roomHeadline = k => ROOM_HEADLINES[k] || ("The room flagged at once — " + label(k).toLowerCase());
export const phrase = (k, n) => (PHRASES[k] || label(k).toLowerCase()) + (n > 1 ? ", " + n + " times" : "");

// ── time ────────────────────────────────────────────────────────────────────
export const t = iso => (iso instanceof Date ? iso : new Date(iso)).getTime();
export const clock = x => new Date(x).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
// 11:01–11:42 PM — the meridiem, where the locale has one, is said once
export function clockRange(a, b) {
  const A = clock(a), B = clock(b);
  const m = A.match(/\s?([AP]\.?M\.?)$/i);
  return (m && B.toUpperCase().endsWith(m[1].toUpperCase()) ? A.slice(0, m.index) : A) + "–" + B;
}
export const clockSec = x => new Date(x).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const dateLong = x => new Date(x).toLocaleDateString([], { day: "numeric", month: "long", year: "numeric" });
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

export function readExam(participants, events, opts = {}) {
  const roster = (participants || []).slice().sort((a, b) => t(a.joined_at) - t(b.joined_at));
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
    let score = 0; const counts = {};
    // the score — and so the tile's colour and the clear list — ignores set-aside flags
    own.filter(e => e.review !== "dismissed").forEach(e => {
      score += (WEIGHT[e.kind] || 1); counts[e.kind] = (counts[e.kind] || 0) + 1;
    });
    const eps = episodesOf(evs);
    const top = Object.entries(counts).sort((a, b) => (WEIGHT[b[0]] || 1) * b[1] - (WEIGHT[a[0]] || 1) * a[1])[0];
    // The live room only ever shows red, and only for the things a teacher would
    // walk over for. Looking away is not one of them — it would paint half the room
    // amber and teach the teacher to ignore colour entirely.
    const serious = own.some(e => e.review !== "dismissed" && SERIOUS_KINDS.has(e.kind));
    return {
      p, calib, events: evs, live, own, episodes: eps, counts, score, serious,
      band: score >= 10 ? "alert" : score >= FINDING_SCORE ? "warn" : "quiet",
      lastAt: evs.length ? t(evs[evs.length - 1].at) : null,
      phrase: top ? phrase(top[0], top[1]) : "",
    };
  });

  // FINDINGS — the document's unit. A room-wide moment counts once for the room;
  // a student's flags of one kind, taken together, count once for them.
  const findings = moments.map(m => ({
    kind: m.kind, room: true, events: m.events, ids: m.ids, review: m.review,
    startT: m.startT, endT: m.endT, count: m.count, people: m.people,
    headline: roomHeadline(m.kind),
    who: m.people.size + " of " + roster.length + " students",
    score: m.events.reduce((s, e) => s + (WEIGHT[e.kind] || 1), 0),
    quality: evidenceQuality(m.events, null),
  }));

  for (const s of students) {
    const byKind = new Map();
    for (const e of s.own) {                   // events the room already speaks for are skipped
      if (!byKind.has(e.kind)) byKind.set(e.kind, []);
      byKind.get(e.kind).push(e);
    }
    for (const [kind, evs] of byKind) {
      const score = evs.length * (WEIGHT[kind] || 1);
      if (score < FINDING_SCORE) continue;     // below the bar it is not a finding
      findings.push({
        kind, room: false, student: s, events: evs, ids: evs.map(e => e.id).filter(Boolean),
        review: verdictOf(evs), startT: t(evs[0].at), endT: t(evs[evs.length - 1].at),
        count: evs.length, headline: headline(kind), who: s.p.name, score,
        quality: evidenceQuality(evs, s.calib),
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
  const clear = students.filter(s => !named.has(s.p.id) && s.score === 0);

  const allT = (events || []).map(e => t(e.at)).filter(Boolean);
  return {
    roster, students, moments, findings, clear,
    startT: allT.length ? Math.min(...allT) : null,
    endT: allT.length ? Math.max(...allT) : null,
  };
}
