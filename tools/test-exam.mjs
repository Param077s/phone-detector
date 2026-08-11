#!/usr/bin/env node
// Vigil Exams — the behaviour tests for the reading layer.
//
//   node tools/test-exam.mjs
//
// `check-exam.mjs` proves the pages parse and their imports line up. It cannot
// tell you that a photograph taped over a webcam produces a finding, or that a
// pair of ordinary neighbours does not. This does.
//
// Everything here runs against the REAL modules — `exam-core.js` directly, and
// `room.js` through a small set of browser shims — so a test passing is a
// statement about the shipped code and not about a copy of it that drifted.
//
// The three sections mirror the three things a wrong answer would cost:
//
//   1. READING     — an old exam must read exactly as it always did, and a
//                    student we barely watched must not be called clear.
//   2. LIVENESS    — a photo must be caught; a student concentrating on their
//                    screen must not be. The second half matters more.
//   3. PAIRS       — the most accusatory thing this system can print, and the
//                    one that first shipped naming eleven innocent couples.
//
// Several assertions here look like they are testing nothing (a score that
// stays the same, a headline that omits a word). Those are the ones to keep.
// They pin down promises the report makes to the person it is written about,
// and nothing in the type system or the parser will notice them going.

import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";

const EXAM = join(dirname(fileURLToPath(import.meta.url)), "..", "docs", "exam");
const core = await import(pathToFileURL(join(EXAM, "exam-core.js")).href);
const {
  readExam, pairMoments, coverageOf, keyFinding, isFlag,
  ALERT_KINDS, SERIOUS_KINDS, AMBIENT_KINDS, REFIRE_KINDS, WEIGHT, poissonAtLeast,
} = core;

let failed = 0, ran = 0;
const ok = (name, pass, detail) => {
  ran++; if (!pass) failed++;
  console.log((pass ? "  ✓ " : "  ✗ ") + name + (detail ? "   [" + detail + "]" : ""));
};
const section = s => console.log("\n" + s);

// ── fixtures ────────────────────────────────────────────────────────────────
const T0 = Date.parse("2026-08-08T10:00:00Z");
const at = sec => new Date(T0 + sec * 1000).toISOString();
const START = at(0), END = at(3600);
let seq = 0;
const person = (name, i, from = 0, to = 3600) =>
  ({ id: "p" + i, name, joined_at: at(from), last_seen: at(to), status: "ok" });
const ev = (pid, kind, sec, meta) =>
  ({ id: "e" + (++seq), participant_id: pid, kind, at: at(sec), meta: meta || null, review: null });
const calib = (pid, grade = "solid") =>
  ev(pid, "calibrated", 0, { grade, reasons: grade === "solid" ? [] : ["low light"] });
// cumulative coverage counters, exactly as the device writes them
const coverage = (pid, frac, upto = 3600) => {
  const out = [];
  for (let s = 300; s <= upto; s += 300) out.push(ev(pid, "coverage", s, { seen: Math.round(s * frac), total: s }));
  return out;
};
// a deterministic scatter — Math.random would make a failure unreproducible
const scatter = seed => { let s = seed; return () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648; };

// ════════════════════════════════════════════════════════════════════════════
section("Reading an exam");
{
  const roster = ["Aisha", "Ben", "Cleo", "Dev", "Eve", "Finn"].map((n, i) => person(n, i));
  const e = roster.map(p => calib(p.id));
  e.push(...coverage("p0", 0.99));   // Aisha  — watched throughout, nothing flagged
  e.push(...coverage("p1", 0.55));   // Ben    — nothing flagged, but half unwatched
  e.push(...coverage("p2", 0.98));   // Cleo   — a photo over the camera
  for (let k = 0; k < 20; k++) e.push(ev("p2", "still_frame", 1200 + k * 60, { seconds: 90 }));
  e.push(...coverage("p3", 0.97));   // Dev    — present but idle
  for (let k = 0; k < 6; k++) e.push(ev("p3", "inactive", 600 + k * 300, { seconds: 300 }));
  e.push(...coverage("p4", 0.96));   // Eve    — a phone
  for (let k = 0; k < 8; k++) e.push(ev("p4", "phone", 1800 + k * 15, { score: 0.71, frames: 4 }));
  // Finn has no coverage rows at all — an exam recorded before the device counted

  const r = readExam(roster, e, { startsAt: START, endsAt: END });
  const byName = n => r.students.find(s => s.p.name === n);
  const clear = n => r.clear.some(s => s.p.name === n);

  ok("a photo over the camera becomes a finding", byName("Cleo").risk === "high" &&
    r.findings.some(f => f.student === byName("Cleo")),
    "score " + byName("Cleo").score.toFixed(1));
  ok("…where before it scored zero and read as clear", !clear("Cleo"));
  ok("nothing flagged + barely watched is NOT clear", !clear("Ben") && byName("Ben").score === 0,
    "coverage " + Math.round(byName("Ben").coverage * 100) + "%");
  ok("…it is named as watched only partly", r.thin.some(s => s.p.name === "Ben"));
  ok("nothing flagged + well watched IS clear", clear("Aisha"));
  ok("an exam with no coverage rows reads as it always did",
    clear("Finn") && byName("Finn").coverage == null);
  ok("an idle student registers without being accused", byName("Dev").risk !== "high",
    "score " + byName("Dev").score.toFixed(2));
  ok("coverage and calibration are never flags",
    !isFlag({ kind: "coverage" }) && !isFlag({ kind: "calibrated" }));
  ok("coverage of nothing is unknown, not zero", coverageOf([], null, null) === null);
  ok("the document states its own reliability",
    r.coverage != null && r.coverage.thin === 1 && r.coverage.n === 5);
}

// ════════════════════════════════════════════════════════════════════════════
section("Liveness — the real detector in room.js");
{
  // room.js is a browser module. Rewrite its two browser-only imports, shim the
  // globals it touches at load, and drive the actual doLiveness/countCoverage.
  const src = readFileSync(join(EXAM, "room.js"), "utf8")
    .replace(/^import \{ sb.*$/m,
      "const sb={from:()=>({insert:async()=>{},update:()=>({eq:()=>({eq:async()=>{}})})})}," +
      "SUPABASE_URL=\"\",SUPABASE_ANON=\"\";")
    .replace(/^import \{ FaceLandmarker.*$/m, "const FaceLandmarker={},ObjectDetector={},FilesetResolver={};")
    .replace(/^import \{ ALERT_KINDS, INFO_KINDS \} from "\/exam\/exam-core\.js";$/m,
      "import { ALERT_KINDS, INFO_KINDS } from " + JSON.stringify(pathToFileURL(join(EXAM, "exam-core.js")).href) + ";")
    .replace(/^async function emit\(kind, meta\) \{$/m,
      "export const emitted=[];\nasync function emit(kind, meta) { emitted.push({kind,meta,t:globalThis._now});")
    + "\nexport { CFG, sig, doLiveness, cov, countCoverage };\n";

  globalThis._now = 0;
  globalThis.location = { search: "?e=x", hash: "" };
  globalThis.localStorage = { getItem: () => null, setItem: () => {} };
  globalThis.document = { getElementById: () => null, addEventListener: () => {}, hidden: false };
  globalThis.window = globalThis;
  globalThis.Worker = class { postMessage() {} terminate() {} };
  globalThis.Blob = class {};
  globalThis.URL.createObjectURL = () => "blob:x";
  Object.defineProperty(globalThis, "performance", { value: { now: () => globalThis._now }, configurable: true });

  const tmp = join(tmpdir(), "vigil-room-under-test-" + process.pid + ".mjs");
  writeFileSync(tmp, src);
  let M; try { M = await import(pathToFileURL(tmp).href); } finally { try { unlinkSync(tmp); } catch {} }
  const { CFG, sig, doLiveness, cov, countCoverage, emitted } = M;

  // Drive a synthetic frame stream. `gaze`/`head` are how much moves between
  // frames; blinkEvery is the gap between blinks (0 = never blinks, i.e. not a
  // living person in front of the camera).
  let clock = 0;
  const feed = (seconds, { gaze, head, blinkEvery, faces = 1 }) => {
    let nx = 0.5, ny = 0.5, nose = 0.30, gx = 0.5, gy = 0.5, sign = 1, next = clock + blinkEvery;
    const end = clock + seconds * 1000;
    while (clock < end) {
      clock += CFG.DETECT_MS; globalThis._now = clock;
      sign = -sign;                            // jitter, so a still face does not drift away
      nx += sign * head / 3; ny += sign * head / 3; nose += sign * head / 3;
      gx += sign * gaze / 2; gy += sign * gaze / 2;
      let blink = false;
      if (blinkEvery && clock >= next) { blink = true; next = clock + blinkEvery; }
      const mx = faces
        ? { faces, nx, ny, noseGap: nose, gazeX: gx, gazeY: gy }
        : { faces: 0, nx: null, ny: null, noseGap: null, gazeX: null, gazeY: null };
      doLiveness(mx, clock, blink); countCoverage(mx, clock);
    }
  };
  const fresh = () => {
    sig.live.samples.length = 0; sig.live.prev = null;
    sig.live.stillFired = 0; sig.live.idleFired = 0;
    clock += 3600_000;                          // well past every cooldown
    return emitted.length;
  };
  const since = (i, k) => emitted.slice(i).filter(x => x.kind === k).length;

  let i = fresh(); feed(200, { gaze: 0, head: 0, blinkEvery: 0 });
  ok("a photo raises still_frame", since(i, "still_frame") >= 1, since(i, "still_frame") + " raised");
  ok("…and is not mistaken for an idle person", since(i, "inactive") === 0);

  i = fresh(); feed(400, { gaze: 0.02, head: 0.0004, blinkEvery: 4000 });
  ok("a student concentrating on the screen is NOT flagged",
    since(i, "still_frame") === 0 && since(i, "inactive") === 0,
    "head barely moves; eyes and blinks are what save them");

  i = fresh(); feed(400, { gaze: 0.0005, head: 0.0002, blinkEvery: 4000 });
  ok("motionless but blinking reads as idle", since(i, "inactive") >= 1);
  ok("…and is never called a photo", since(i, "still_frame") === 0);

  i = fresh(); feed(600, { gaze: 0, head: 0, blinkEvery: 0 });
  const n = since(i, "still_frame");
  ok("a photo left up for ten minutes respects its cooldown", n >= 6 && n <= 11,
    n + " events, not one per frame");

  i = fresh(); feed(300, { gaze: 0, head: 0, blinkEvery: 0, faces: 0 });
  ok("an absent face is a coverage fact, not stillness",
    since(i, "still_frame") === 0 && since(i, "inactive") === 0);

  const seen = cov.seen / cov.total;
  ok("coverage falls when nobody is in frame", seen > 0.5 && seen < 0.98,
    Math.round(seen * 100) + "% of ticks resolved a face");
  ok("coverage is written as a record, never as a flag",
    emitted.every(e => e.kind !== "coverage"), "record() not emit() — cannot push a warn status");
}

// ════════════════════════════════════════════════════════════════════════════
section("Pair synchrony");
{
  const names = ["Aisha", "Ben", "Cleo", "Dev"].concat(Array.from({ length: 16 }, (_, i) => "S" + (i + 5)));
  const roster = names.map((n, i) => person(n, i));
  const e = roster.map(p => calib(p.id));
  // Aisha & Ben — ten look-aways each, always within eight seconds
  for (let k = 0; k < 10; k++) { const s = 200 + k * 300; e.push(ev("p0", "look_away", s), ev("p1", "look_away", s + 8)); }
  // Cleo & Dev — very fidgety, thirty each, ten of which coincide. Their RAW
  // count of togethers beats Aisha & Ben's; their own rates predict it.
  for (let k = 0; k < 30; k++) {
    e.push(ev("p2", "look_away", 100 + k * 110));
    e.push(ev("p3", "look_away", k < 10 ? 107 + k * 110 : 155 + k * 110));
  }
  const rnd = scatter(7);
  for (let i = 4; i < roster.length; i++)
    for (let k = 0; k < 5; k++) e.push(ev("p" + i, "look_away", Math.floor(rnd() * 3500)));
  // and one genuine room-wide moment — everybody, inside one minute
  roster.forEach((p, i) => e.push(ev(p.id, "face_absent", 1800 + i)));

  const r = readExam(roster, e, { startsAt: START, endsAt: END });
  const pf = r.findings.filter(f => f.pair);
  const named = (a, b) => pf.some(f => f.who === a + " and " + b || f.who === b + " and " + a);

  ok("two students moving together are found", named("Aisha", "Ben"),
    pf[0] ? pf[0].count + " together, chance predicts " + pf[0].expected.toFixed(1) : "none");
  ok("two merely fidgety students are not", !named("Cleo", "Dev"),
    "they coincided MORE often; their own rates predicted it");
  ok("a room-wide moment mints no pairs", !pf.some(f => f.kind === "face_absent"));
  ok("a pair finding is never buried in the appendix", pf.length > 0 && pf.every(keyFinding));
  ok("its events are deduped and in time order", pf.every(f =>
    new Set(f.ids).size === f.ids.length &&
    f.events.every((x, i, a) => i === 0 || Date.parse(a[i - 1].at) <= Date.parse(x.at))));
  ok("nothing anywhere names the behaviour",
    pf.every(f => !/cheat|collu|copy|suspic/i.test(f.headline + f.quality + f.who)));
  // THE ONE TO KEEP. Scoring a student for who else was flagged that second
  // would make them answerable for somebody else's behaviour.
  ok("it changes nobody's score", (() => {
    const off = readExam(roster, e, { startsAt: START, endsAt: END, alpha: 0 });
    return off.findings.every(f => !f.pair) &&
      off.students.every((s, i) => s.score === r.students[i].score);
  })());
  ok("two students are a room, not a pair", pairMoments(r.students.slice(0, 2)).length === 0);

  // ── the multiple-comparisons guard ────────────────────────────────────────
  // Five flags each over an hour means a pair is expected to coincide about 0.4
  // times, so FOUR coincidences reads as nine times chance — a big, confident
  // multiple built on four events. In a room of two dozen there are hundreds of
  // chances for some pair to do that, and the first version of this shipped
  // naming eleven of them.
  {
    const ros = Array.from({ length: 24 }, (_, i) => person("S" + i, i));
    const es = ros.map(p => calib(p.id));
    for (let k = 0; k < 4; k++) { const s = 300 + k * 700; es.push(ev("p0", "look_away", s), ev("p1", "look_away", s + 9)); }
    es.push(ev("p0", "look_away", 3300), ev("p1", "look_away", 200));
    const rr = scatter(99);
    for (let i = 2; i < ros.length; i++)
      for (let k = 0; k < 5; k++) es.push(ev("p" + i, "look_away", Math.floor(rr() * 3500)));

    const read = readExam(ros, es, { startsAt: START, endsAt: END });
    const naive = pairMoments(read.students, { alpha: 1 });   // effect-size floors only
    const top = naive[0];
    ok("four coincidences look damning on effect size alone",
      !!top && top.together === 4 && top.lift >= 3,
      top ? top.together + " vs " + top.expected.toFixed(2) + " expected · " + top.lift.toFixed(1) +
        "x · p=" + top.pv.toFixed(5) + " over " + top.tests + " pairs tested" : "none");
    ok("…and the guard names nobody", read.findings.filter(f => f.pair).length === 0);
  }
}

// ════════════════════════════════════════════════════════════════════════════
section("Vocabulary and weights");
{
  ok("still_frame is serious enough to interrupt an invigilator",
    ALERT_KINDS.has("still_frame") && SERIOUS_KINDS.has("still_frame") && WEIGHT.still_frame === 5);
  ok("inactive is the lowest weight in the set, with eyes_down",
    WEIGHT.inactive === 0.4 && AMBIENT_KINDS.has("inactive") && !ALERT_KINDS.has("inactive"));
  ok("a frozen picture compresses like a phone held in view", REFIRE_KINDS.has("still_frame"));
  ok("every kind has a weight and a headline", ["still_frame", "inactive"].every(k =>
    WEIGHT[k] != null && core.HEADLINES[k] && core.LABELS[k] && core.PHRASES[k]));
  ok("the Poisson tail is sane",
    poissonAtLeast(0, 5) === 1 && poissonAtLeast(4, 0.42) < 0.001 && poissonAtLeast(9, 1.7) < 1e-4);
}

console.log("\n" + (failed
  ? "  " + failed + " of " + ran + " failed."
  : "✓ " + ran + " behaviours hold."));
process.exit(failed ? 1 : 0);
