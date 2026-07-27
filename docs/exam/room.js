// Vigil Exams · student monitor — MediaPipe runs entirely on this device.
// Video/frames NEVER leave the laptop; only tiny events + presence go to Supabase.
import { sb, SUPABASE_URL, SUPABASE_ANON } from "/exam/sb.js";
import { FaceLandmarker, FilesetResolver } from "/vendor/mediapipe/vision_bundle.mjs";

const CFG = {
  DETECT_MS: 90, CALIB_MS: 4500,
  // Head tilted DOWN (nose vs eye-line)
  HEAD_ENTER: 0.14, HEAD_EXIT: 0.08, HEAD_HOLD_MS: 3500,
  // Eyes drift OUTSIDE the allowed circle around where they calibrated — any direction
  GAZE_RADIUS: 0.14, GAZE_HOLD_MS: 1200,
  BLINK_RATIO: 0.55,   // eye-openness below this fraction of the calibrated open = blink → ignore gaze
  // Presence
  ABSENT_HOLD_MS: 5000, SECOND_HOLD_MS: 1500, SECOND_COOLDOWN_MS: 15000,
  HEARTBEAT_MS: 6000, STATUS_MIN_MS: 1500,
};
// Debug tuning + saved overrides are for the TEACHER previewing their own room only.
// A real student must never be able to loosen or disable detection, so these are
// stashed here and applied ONLY after we confirm the viewer owns the exam (see boot).
let pendingCfg = null;
try { pendingCfg = JSON.parse(localStorage.getItem("vg_cfg") || "null"); } catch (e) {}
const DEBUG_REQUESTED = /(?:^|[?#&])debug/.test(location.search + location.hash);
let debugOn = false;   // becomes true only for the exam owner
let lastMx = { faces: 0, noseGap: null, gazeX: null, gazeY: null };
// canonical face-mesh indices
const NOSE_TIP = 1, EYE_L = 33, EYE_R = 263;
// eye corners for gaze (right eye = 33 outer / 133 inner; left eye = 362 inner / 263 outer)
const RE_OUT = 33, RE_IN = 133, LE_IN = 362, LE_OUT = 263;
// eyelid top/bottom for vertical gaze
const RE_TOP = 159, RE_BOT = 145, LE_TOP = 386, LE_BOT = 374;
// iris centres (present only on the 478-landmark model)
const IRIS_R = 468, IRIS_L = 473;
const $ = (id) => document.getElementById(id);
const show = (id) => ["s-calib","s-monitor","s-error","s-ended"].forEach(s => $(s).classList.toggle("hidden", s !== id));

const examId = new URLSearchParams(location.search).get("e");
let user = null, part = null;   // part = { id, name }
const state = {
  stream: null, landmarker: null, video: null, mode: null, running: false,
  lastDetect: 0, lastTs: 0, baseline: null, baseGazeX: null, baseGazeY: null, baseOpen: null,
  calibSamples: [], calibGX: [], calibGY: [], calibOpen: [], calibStart: 0,
  startedAt: 0, title: "Exam", lastStatus: "ok", lastStatusAt: 0,
  offNow: null, dropNow: null, offPeak: 0, dropPeak: 0, rec: null,   // rec = live capture for the debug panel
  token: null, calibRetries: 0, suspiciousCam: false,
};
const capt = { normal: null, away: null };   // captured peaks used to auto-suggest the eye radius

// ── Supabase writes (events + presence) ──────────────────────────────────────
async function emit(kind, severity) {
  try {
    await sb.from("events").insert({ exam_id: examId, participant_id: part.id, kind, severity });
  } catch (e) {}
  pushStatus(severity === "alert" ? "alert" : "warn", true);
}
async function pushStatus(status, force) {
  const now = performance.now();
  if (!force && status === state.lastStatus && now - state.lastStatusAt < 4000) return;
  if (now - state.lastStatusAt < CFG.STATUS_MIN_MS && status === state.lastStatus) return;
  state.lastStatus = status; state.lastStatusAt = now;
  try {
    await sb.from("participants").update({ status, last_seen: new Date().toISOString() })
      .eq("id", part.id).eq("user_id", user.id);
  } catch (e) {}
}

// ── Geometry ────────────────────────────────────────────────────────────────
function metrics(res) {
  const faces = res.faceLandmarks ? res.faceLandmarks.length : 0;
  if (!faces) return { faces: 0, noseGap: null, gazeX: null, gazeY: null, openness: null };
  const lm = res.faceLandmarks[0], L = lm[EYE_L], R = lm[EYE_R], N = lm[NOSE_TIP];
  const iod = Math.hypot(L.x - R.x, L.y - R.y) || 1e-6;
  const noseGap = (N.y - (L.y + R.y) / 2) / iod;
  // eye openness (lid gap / eye distance) — used to ignore blinks
  const openness = ((Math.abs(lm[RE_BOT].y - lm[RE_TOP].y) + Math.abs(lm[LE_BOT].y - lm[LE_TOP].y)) / 2) / iod;
  // iris gaze — only when the model gives iris landmarks (478-pt task model)
  let gazeX = null, gazeY = null;
  if (lm.length > IRIS_L) {
    const rI = lm[IRIS_R], lI = lm[IRIS_L];
    // horizontal: where the iris sits between the eye's two corners (~0.5 = centred)
    const rX = (rI.x - lm[RE_OUT].x) / ((lm[RE_IN].x - lm[RE_OUT].x) || 1e-6);
    const lX = (lI.x - lm[LE_IN].x) / ((lm[LE_OUT].x - lm[LE_IN].x) || 1e-6);
    gazeX = (rX + lX) / 2;
    // vertical: where the iris sits between the top/bottom lids (>0.5 = looking down)
    const rY = (rI.y - lm[RE_TOP].y) / ((lm[RE_BOT].y - lm[RE_TOP].y) || 1e-6);
    const lY = (lI.y - lm[LE_TOP].y) / ((lm[LE_BOT].y - lm[LE_TOP].y) || 1e-6);
    gazeY = (rY + lY) / 2;
  }
  return { faces, noseGap, gazeX, gazeY, openness };
}
const median = (a) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };

const sig = {
  head: { since: null, fired: false },
  absent: { since: null, fired: false },
  second: { since: null, lastFired: 0 },
  away: { since: null, fired: false },
  cam: { off: false },   // one camera_off event per off-episode, not one per heartbeat
};

function doMonitor(mx, now) {
  const haveFace = mx.faces >= 1 && state.baseline != null;

  // per-frame measurements (also feed the debug readout / recorder)
  const drop = (haveFace && mx.noseGap != null) ? (state.baseline - mx.noseGap) : null;
  const blink = state.baseOpen != null && mx.openness != null && mx.openness < CFG.BLINK_RATIO * state.baseOpen;
  const off = (haveFace && !blink && mx.gazeX != null && state.baseGazeX != null)
    ? Math.hypot(mx.gazeX - state.baseGazeX, mx.gazeY - state.baseGazeY) : null;   // radial eye drift, any direction
  state.dropNow = drop; state.offNow = off;
  if (drop != null) state.dropPeak = Math.max(state.dropPeak * 0.985, drop);
  if (off  != null) state.offPeak  = Math.max(state.offPeak  * 0.985, off);
  if (state.rec) { const v = state.rec.kind === "eye" ? off : drop; if (v != null) state.rec.max = Math.max(state.rec.max, v);
    if (now > state.rec.until) { const r = state.rec; state.rec = null; r.done(r.max); } }

  // HEAD DOWN — head physically tilted down (nose drops below the eye line)
  if (drop != null) {
    if (drop > CFG.HEAD_ENTER) {
      if (!sig.head.since) sig.head.since = now;
      if (now - sig.head.since > CFG.HEAD_HOLD_MS && !sig.head.fired) { emit("head_down", "warn"); sig.head.fired = true; }
    } else if (drop < CFG.HEAD_EXIT) { sig.head.since = null; sig.head.fired = false; }
  }
  // LOOK AWAY — eyes drift outside the allowed circle around the calibrated centre (L/R/up/down)
  if (off != null) {
    if (off > CFG.GAZE_RADIUS) {
      if (!sig.away.since) sig.away.since = now;
      if (now - sig.away.since > CFG.GAZE_HOLD_MS && !sig.away.fired) { emit("look_away", "warn"); sig.away.fired = true; }
    } else if (off < CFG.GAZE_RADIUS * 0.6) { sig.away.since = null; sig.away.fired = false; }
  }
  if (mx.faces === 0) {
    if (!sig.absent.since) sig.absent.since = now;
    if (now - sig.absent.since > CFG.ABSENT_HOLD_MS && !sig.absent.fired) { emit("face_absent", "warn"); sig.absent.fired = true; }
  } else { sig.absent.since = null; sig.absent.fired = false; }
  if (mx.faces >= 2) {
    if (!sig.second.since) sig.second.since = now;
    if (now - sig.second.since > CFG.SECOND_HOLD_MS && now - sig.second.lastFired > CFG.SECOND_COOLDOWN_MS) { emit("second_face", "alert"); sig.second.lastFired = now; }
  } else { sig.second.since = null; }
  paintStatus(mx, now);
}

function paintStatus(mx, now) {
  let cls = "ok", label = "Looking at screen";
  if (mx.faces === 0) { cls = "warn"; label = "Face not visible"; }
  else if (mx.faces >= 2) { cls = "alert"; label = "More than one face"; }
  else if (sig.head.fired) { cls = "warn"; label = "Looking down"; }
  else if (sig.away.fired) { cls = "warn"; label = "Looking away"; }
  $("rState").className = "v " + cls; $("rState").textContent = label;
  $("mDot").className = "dot " + cls;
  const secs = Math.floor((now - state.startedAt) / 1000);
  $("mSub").textContent = `Monitored · ${String(Math.floor(secs/60)).padStart(2,"0")}:${String(secs%60).padStart(2,"0")}`;
  pushStatus(cls, false);   // keep the teacher's tile in sync (throttled)
  lastMx = mx;
  if (debugOn) updateReadout();
}

// ── Live tuning (open the room with &debug) ──────────────────────────────────
// You don't have to read while you move: press Record, do the movement, and it
// reports the PEAK. "EYES" is the radial drift of your gaze from the calibrated
// centre (any direction); "HEAD" is a physical head tilt down.
function updateReadout() {
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  const flag = (id, on, txt) => { const e = $(id); if (e) { e.textContent = on ? txt : ""; e.className = "tflag" + (on ? " on" : ""); } };
  set("headNow", state.dropNow != null ? state.dropNow.toFixed(3) : "—");
  set("headPeak", state.dropPeak.toFixed(3));
  set("headLimit", CFG.HEAD_ENTER.toFixed(2));
  flag("headFlag", sig.head.fired, "● DOWN");
  if (lastMx.gazeX == null) { set("eyeNow", "no iris from model"); set("eyePeak", "—"); flag("eyeFlag", false, ""); return; }
  set("eyeNow", state.offNow != null ? state.offNow.toFixed(3) : "— blink");
  set("eyePeak", state.offPeak.toFixed(3));
  set("eyeLimit", CFG.GAZE_RADIUS.toFixed(2));
  flag("eyeFlag", sig.away.fired, "● AWAY");
}
function saveCfg() {
  localStorage.setItem("vg_cfg", JSON.stringify({
    GAZE_RADIUS: CFG.GAZE_RADIUS, GAZE_HOLD_MS: CFG.GAZE_HOLD_MS,
    HEAD_ENTER: CFG.HEAD_ENTER, HEAD_HOLD_MS: CFG.HEAD_HOLD_MS,
  }));
}
const TUNE_KEYS = ["GAZE_RADIUS", "GAZE_HOLD_MS", "HEAD_ENTER", "HEAD_HOLD_MS"];
function wireTune() {
  const t = $("tune"); if (!t) return;
  t.classList.remove("hidden");
  const bind = (sId, vId, key, mul, unit) => {
    const s = $(sId), v = $(vId); if (!s) return;
    s.value = CFG[key] / mul; v.textContent = (CFG[key] / mul).toFixed(mul === 1 ? 2 : 1) + unit;
    s.oninput = () => { CFG[key] = parseFloat(s.value) * mul; v.textContent = parseFloat(s.value).toFixed(mul === 1 ? 2 : 1) + unit; saveCfg(); };
  };
  bind("sGaze", "vGaze", "GAZE_RADIUS", 1, "");
  bind("sGazeHold", "vGazeHold", "GAZE_HOLD_MS", 1000, "s");
  bind("sHeadEnter", "vHeadEnter", "HEAD_ENTER", 1, "");
  bind("sHeadHold", "vHeadHold", "HEAD_HOLD_MS", 1000, "s");

  // ── guided capture: press, move, it records the peak — no live reading needed ──
  const caps = () => [$("recNormal"), $("recAway")];
  const runCapture = (which, btn, prompt) => {
    if (state.rec) return;
    const orig = btn.dataset.label || btn.textContent; btn.dataset.label = orig;
    caps().forEach(b => b && (b.disabled = true));
    $("tSuggest").classList.remove("hidden"); $("tSuggest").innerHTML = prompt;
    let left = 5; btn.textContent = "Recording… " + left + "s";
    const iv = setInterval(() => { left--; if (left > 0) btn.textContent = "Recording… " + left + "s"; }, 1000);
    state.rec = { kind: "eye", max: 0, until: performance.now() + 5000, done: (max) => {
      clearInterval(iv); btn.textContent = orig; caps().forEach(b => b && (b.disabled = false));
      capt[which] = max; showSuggest();
    } };
  };
  const showSuggest = () => {
    const el = $("tSuggest"); el.classList.remove("hidden");
    const n = capt.normal, a = capt.away;
    let msg = "";
    if (n != null) msg += "Normal peak <b>" + n.toFixed(3) + "</b>. ";
    if (a != null) msg += "Away peak <b>" + a.toFixed(3) + "</b>.";
    if (n != null && a != null) {
      let r = a > n ? n + 0.45 * (a - n) : n * 1.6;
      r = Math.max(0.05, Math.min(0.35, Math.round(r * 100) / 100));
      el.innerHTML = msg + '<br>Suggested eye radius <b>' + r.toFixed(2) +
        '</b> <button class="btn ink sm" id="applySug" type="button" style="margin-left:6px">Apply</button>';
      $("applySug").onclick = () => { CFG.GAZE_RADIUS = r; const s = $("sGaze"); if (s) s.value = r; $("vGaze").textContent = r.toFixed(2); saveCfg();
        el.innerHTML += ' <span style="color:var(--ok);font-weight:600">applied ✓</span>'; };
    } else { el.innerHTML = msg + '<br><span style="color:var(--faint)">Record both to get a suggested radius.</span>'; }
  };
  $("recNormal").onclick = () => runCapture("normal", $("recNormal"), "Look at your screen and read normally…");
  $("recAway").onclick = () => runCapture("away", $("recAway"), "Now glance away — sides, down, around…");

  $("tCopy").onclick = async () => {
    const out = {}; TUNE_KEYS.forEach(k => out[k] = CFG[k]);
    try { await navigator.clipboard.writeText(JSON.stringify(out));
      $("tCopy").textContent = "Copied ✓"; setTimeout(() => $("tCopy").textContent = "Copy settings", 1500); } catch (_) {}
  };
  $("tReset").onclick = () => { localStorage.removeItem("vg_cfg"); location.reload(); };
}

function doCalib(mx, now) {
  if (mx.faces >= 1 && mx.noseGap != null) {
    state.calibSamples.push(mx.noseGap);
    if (mx.gazeX != null) state.calibGX.push(mx.gazeX);
    if (mx.gazeY != null) state.calibGY.push(mx.gazeY);
    if (mx.openness != null) state.calibOpen.push(mx.openness);
  }
  $("calibBar").style.width = Math.min(100, ((now - state.calibStart) / CFG.CALIB_MS) * 100) + "%";
  if (now - state.calibStart >= CFG.CALIB_MS) {
    if (state.calibSamples.length < 5) { $("calibMsg").textContent = "Make sure your face is centred and well lit…"; state.calibStart = now; state.calibSamples = []; state.calibGX = []; state.calibGY = []; state.calibOpen = []; return; }
    state.baseline = median(state.calibSamples);
    state.baseGazeX = median(state.calibGX);
    state.baseGazeY = median(state.calibGY);
    state.baseOpen = median(state.calibOpen);
    // anti-gaming: don't let a student calibrate while looking at notes off to the side —
    // that would make "off-screen" read as neutral. Require eyes roughly centred, a few tries.
    if (state.baseGazeX != null && state.calibRetries < 3) {
      const gxOff = Math.abs(state.baseGazeX - 0.5), gyOff = Math.abs(state.baseGazeY - 0.5);
      if (gxOff > 0.20 || gyOff > 0.25) {
        state.calibRetries++;
        $("calibMsg").textContent = "Look straight at your screen so setup is accurate…";
        state.calibStart = now; state.calibSamples = []; state.calibGX = []; state.calibGY = []; state.calibOpen = [];
        return;
      }
    }
    startMonitoring(now);
  }
}

function loop() {
  if (!state.running) return;
  requestAnimationFrame(loop);
  const now = performance.now();
  if (now - state.lastDetect < CFG.DETECT_MS) return;
  state.lastDetect = now;
  let ts = now; if (ts <= state.lastTs) ts = state.lastTs + 1; state.lastTs = ts;
  let res; try { res = state.landmarker.detectForVideo(state.video, ts); } catch { return; }
  const mx = metrics(res);
  if (state.mode === "calib") doCalib(mx, now); else if (state.mode === "monitor") doMonitor(mx, now);
}

// ── Integrity: Vigil runs BESIDE the exam, so hiding/closing it is itself a flag ──
// (a background tab freezes detection, so a cheater who hides Vigil is caught by this)
let hiddenSince = 0, lastHiddenEmit = 0;
function onVisibility() {
  if (state.mode !== "monitor" && state.mode !== "calib") return;
  if (document.hidden) { hiddenSince = Date.now(); }
  else if (hiddenSince) {
    const secs = Math.round((Date.now() - hiddenSince) / 1000); hiddenSince = 0;
    if (secs >= 2 && state.mode === "monitor" && Date.now() - lastHiddenEmit > 3000) {
      lastHiddenEmit = Date.now();
      emit("monitor_hidden", "alert");
      showWarn(`Vigil was hidden for ${secs}s — that was recorded. Keep this window visible beside your exam.`);
    }
  }
}
function beaconEvent(kind, severity) {   // best-effort write that survives the page unloading
  if (!part || !state.token) return;
  try {
    fetch(SUPABASE_URL + "/rest/v1/events", {
      method: "POST", keepalive: true,
      headers: { "Content-Type": "application/json", apikey: SUPABASE_ANON, Authorization: "Bearer " + state.token },
      body: JSON.stringify({ exam_id: examId, participant_id: part.id, kind, severity }),
    });
  } catch (e) {}
}
function onPageHide() { if (state.mode === "monitor") beaconEvent("left_exam", "alert"); }
function setupIntegrity() {
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("pagehide", onPageHide);
  const wx = $("warnX"); if (wx) wx.onclick = () => $("warnBanner").classList.add("hidden");
}
let warnTimer = 0;
function showWarn(msg) {
  const b = $("warnBanner"); if (!b) return;
  $("warnText").textContent = msg; b.classList.remove("hidden");
  clearTimeout(warnTimer); warnTimer = setTimeout(() => b.classList.add("hidden"), 8000);
}
async function cacheToken() { try { const { data } = await sb.auth.getSession(); if (data.session) state.token = data.session.access_token; } catch (e) {} }

function startMonitoring(now) {
  state.mode = "monitor"; state.startedAt = now;
  $("monVid").srcObject = state.stream; $("monVid").play().catch(() => {});
  $("mTitle").textContent = state.title;
  show("s-monitor");
  pushStatus("ok", true);
  cacheToken();
  if (state.suspiciousCam) emit("virtual_cam", "alert");
  state.hbTimer = setInterval(() => {
    const track = state.stream && state.stream.getVideoTracks()[0];
    const camOn = track && track.readyState === "live" && track.enabled;
    if (!camOn) {
      $("monTag").textContent = "🔴 Camera is off";
      if (!sig.cam.off) { emit("camera_off", "alert"); sig.cam.off = true; }   // fire once, not every beat
    } else {
      if (sig.cam.off) { sig.cam.off = false; $("monTag").textContent = "🟢 Camera active · nothing is uploaded"; }
      pushStatus(state.lastStatus, true);   // refresh last_seen
    }
    cacheToken();   // keep the unload-beacon token fresh across a long exam
  }, CFG.HEARTBEAT_MS);
  const track = state.stream.getVideoTracks()[0];
  if (track) track.addEventListener("ended", () => { $("monTag").textContent = "🔴 Camera stopped"; if (!sig.cam.off) { emit("camera_off", "alert"); sig.cam.off = true; } });
  state.closeTimer = setInterval(checkClosed, 12000);   // stop monitoring once the teacher ends the exam
}

async function checkClosed() {
  try {
    const { data } = await sb.from("exams").select("status").eq("id", examId).maybeSingle();
    if (data && data.status === "closed") endExam();
  } catch (e) {}
}

function endExam() {
  if (state.mode === "ended") return;
  state.mode = "ended"; state.running = false;
  clearInterval(state.hbTimer); clearInterval(state.closeTimer);
  try { state.stream && state.stream.getTracks().forEach(t => t.stop()); } catch (e) {}
  show("s-ended");
}

async function begin() {
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }, audio: false });
  } catch { return fail("Vigil needs your camera to monitor this exam. Please allow camera access and reload."); }
  // flag obvious virtual / fake cameras (OBS etc.) feeding a looped "looking at screen" video
  try {
    const lbl = ((state.stream.getVideoTracks()[0] || {}).label || "").toLowerCase();
    if (/obs|virtual|manycam|snap camera|droidcam|epoccam|xsplit|fake/.test(lbl)) state.suspiciousCam = true;
  } catch (e) {}
  const video = $("calibVid"); video.srcObject = state.stream; state.video = video;
  await video.play().catch(() => {});
  await new Promise((r) => (video.readyState >= 2 ? r() : video.addEventListener("loadeddata", r, { once: true })));
  try {
    const fileset = await FilesetResolver.forVisionTasks("/vendor/mediapipe/wasm");
    state.landmarker = await FaceLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: "/vendor/mediapipe/face_landmarker.task" },
      runningMode: "VIDEO", numFaces: 2, outputFacialTransformationMatrixes: true,
    });
  } catch (e) { return fail("Could not load the monitoring model. Check your connection and reload."); }
  state.mode = "calib"; state.calibSamples = []; state.calibGX = []; state.calibGY = []; state.calibOpen = []; state.calibRetries = 0; state.calibStart = performance.now(); state.running = true;
  requestAnimationFrame(loop);
}
function fail(msg) { state.running = false; $("errMsg").textContent = msg; show("s-error"); }

// ── Boot: confirm the student joined this exam, then start ────────────────────
(async () => {
  const { data:{ user: u } } = await sb.auth.getUser();
  if (!u || !examId) { location.replace("/exam/"); return; }
  user = u;
  const { data: exam } = await sb.from("exams").select("title,status,owner").eq("id", examId).maybeSingle();
  if (exam) state.title = exam.title;
  // Only the exam's OWNER (a teacher previewing) may use debug + saved overrides.
  // For everyone else the baked-in defaults are enforced — a student can't loosen them.
  const isOwner = !!exam && exam.owner === u.id;
  if (isOwner && pendingCfg && typeof pendingCfg === "object") Object.assign(CFG, pendingCfg);
  debugOn = isOwner && DEBUG_REQUESTED;
  const { data: p } = await sb.from("participants").select("id,name").eq("exam_id", examId).eq("user_id", u.id).maybeSingle();
  if (!p) { location.replace("/exam/"); return; }
  part = p; $("yourName") && ($("yourName").textContent = p.name);
  try { localStorage.setItem("vg_role", "student"); } catch (e) {}   // in the room = acting as a student
  const al = $("activityLink"); if (al) al.href = "/exam/report.html?e=" + examId + "&as=student";
  const ea = $("endedActivity"); if (ea) ea.href = "/exam/report.html?e=" + examId + "&as=student";
  // if the teacher already closed the exam before this student opened the room
  const already = exam && exam.status === "closed";
  if (already) { show("s-ended"); return; }
  if (debugOn) wireTune();
  setupIntegrity();
  begin();
})();
