// Vigil Exams · student monitor — MediaPipe runs entirely on this device.
// Video/frames NEVER leave the laptop; only tiny events + presence go to Supabase.
import { sb } from "/exam/sb.js";
import { FaceLandmarker, FilesetResolver } from "/vendor/mediapipe/vision_bundle.mjs";

const CFG = {
  DETECT_MS: 90, CALIB_MS: 4500,
  // Head/eyes DOWN (fires on head tilt OR eyes cast down)
  HEAD_ENTER: 0.14, HEAD_EXIT: 0.08, HEAD_HOLD_MS: 3500,
  EYEDOWN_ENTER: 0.20,
  // Eyes looking AWAY (far left / right)
  GAZE_ENTER: 0.15, GAZE_EXIT: 0.09, GAZE_HOLD_MS: 1400,
  // Presence
  ABSENT_HOLD_MS: 5000, SECOND_HOLD_MS: 1500, SECOND_COOLDOWN_MS: 15000,
  HEARTBEAT_MS: 6000, STATUS_MIN_MS: 1500,
};
// live-tunable overrides saved from the ?debug tuning panel
try { Object.assign(CFG, JSON.parse(localStorage.getItem("vg_cfg") || "{}")); } catch (e) {}
let lastMx = { faces: 0, noseGap: null, gazeX: null, gazeY: null };
// canonical face-mesh indices
const NOSE_TIP = 1, EYE_L = 33, EYE_R = 263;
// eye corners for gaze (right eye = 33 outer / 133 inner; left eye = 362 inner / 263 outer)
const RE_OUT = 33, RE_IN = 133, LE_IN = 362, LE_OUT = 263;
// eyelid top/bottom for vertical gaze
const RE_TOP = 159, RE_BOT = 145, LE_TOP = 386, LE_BOT = 374;
// iris centres (present only on the 478-landmark model)
const IRIS_R = 468, IRIS_L = 473;
const DEBUG = /(?:^|[?#&])debug/.test(location.search + location.hash);
const $ = (id) => document.getElementById(id);
const show = (id) => ["s-calib","s-monitor","s-error"].forEach(s => $(s).classList.toggle("hidden", s !== id));

const examId = new URLSearchParams(location.search).get("e");
let user = null, part = null;   // part = { id, name }
const state = {
  stream: null, landmarker: null, video: null, mode: null, running: false,
  lastDetect: 0, lastTs: 0, baseline: null, baseGazeX: null, baseGazeY: null,
  calibSamples: [], calibGX: [], calibGY: [], calibStart: 0,
  startedAt: 0, title: "Exam", lastStatus: "ok", lastStatusAt: 0,
};

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
  if (!faces) return { faces: 0, noseGap: null, gazeX: null, gazeY: null };
  const lm = res.faceLandmarks[0], L = lm[EYE_L], R = lm[EYE_R], N = lm[NOSE_TIP];
  const iod = Math.hypot(L.x - R.x, L.y - R.y) || 1e-6;
  const noseGap = (N.y - (L.y + R.y) / 2) / iod;
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
  return { faces, noseGap, gazeX, gazeY };
}
const median = (a) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };

const sig = {
  head: { since: null, fired: false },
  absent: { since: null, fired: false },
  second: { since: null, lastFired: 0 },
  away: { since: null, fired: false },
};

function doMonitor(mx, now) {
  const haveFace = mx.faces >= 1 && state.baseline != null;
  // DOWN — head tilted down (nose vs eye-line) OR eyes cast down (iris low in the lids)
  if (haveFace && mx.noseGap != null) {
    const drop = state.baseline - mx.noseGap;
    const eyeDown = (state.baseGazeY != null && mx.gazeY != null) ? (mx.gazeY - state.baseGazeY) : 0;
    const down = drop > CFG.HEAD_ENTER || eyeDown > CFG.EYEDOWN_ENTER;
    const up = drop < CFG.HEAD_EXIT && eyeDown < CFG.EYEDOWN_ENTER * 0.6;
    if (down) {
      if (!sig.head.since) sig.head.since = now;
      if (now - sig.head.since > CFG.HEAD_HOLD_MS && !sig.head.fired) { emit("head_down", "warn"); sig.head.fired = true; }
    } else if (up) { sig.head.since = null; sig.head.fired = false; }
  }
  // LOOK AWAY — eyes turned far left or right of where they calibrated
  if (haveFace && mx.gazeX != null && state.baseGazeX != null) {
    const off = Math.abs(mx.gazeX - state.baseGazeX);
    if (off > CFG.GAZE_ENTER) {
      if (!sig.away.since) sig.away.since = now;
      if (now - sig.away.since > CFG.GAZE_HOLD_MS && !sig.away.fired) { emit("look_away", "warn"); sig.away.fired = true; }
    } else if (off < CFG.GAZE_EXIT) { sig.away.since = null; sig.away.fired = false; }
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
  if (DEBUG) updateReadout();
}

// ── Live tuning (open the room with &debug) ──────────────────────────────────
function updateReadout() {
  const d = $("tRead"); if (!d) return;
  const drop = (state.baseline != null && lastMx.noseGap != null) ? (state.baseline - lastMx.noseGap) : null;
  const gx = (state.baseGazeX != null && lastMx.gazeX != null) ? (lastMx.gazeX - state.baseGazeX) : null;
  const gy = (state.baseGazeY != null && lastMx.gazeY != null) ? (lastMx.gazeY - state.baseGazeY) : null;
  const iris = lastMx.gazeX != null;
  d.textContent =
    `faces ${lastMx.faces}   noseGap ${lastMx.noseGap?.toFixed(3) ?? "—"}   base ${state.baseline?.toFixed(3) ?? "—"}\n` +
    `down   ${drop != null ? drop.toFixed(3) : "—"} / ${CFG.HEAD_ENTER.toFixed(2)}   ${sig.head.fired ? "● DOWN" : "ok"}\n` +
    (iris
      ? `look   ${gx != null ? gx.toFixed(3) : "—"} / ${CFG.GAZE_ENTER.toFixed(2)}   ${sig.away.fired ? "● AWAY" : "ok"}\n` +
        `eyeDn  ${gy != null ? gy.toFixed(3) : "—"} / ${CFG.EYEDOWN_ENTER.toFixed(2)}`
      : `look   (no iris landmarks from model)`);
}
function saveCfg() {
  localStorage.setItem("vg_cfg", JSON.stringify({
    HEAD_ENTER: CFG.HEAD_ENTER, HEAD_HOLD_MS: CFG.HEAD_HOLD_MS, EYEDOWN_ENTER: CFG.EYEDOWN_ENTER,
    GAZE_ENTER: CFG.GAZE_ENTER, GAZE_HOLD_MS: CFG.GAZE_HOLD_MS,
    ABSENT_HOLD_MS: CFG.ABSENT_HOLD_MS, SECOND_HOLD_MS: CFG.SECOND_HOLD_MS,
  }));
}
const TUNE_KEYS = ["HEAD_ENTER","HEAD_HOLD_MS","EYEDOWN_ENTER","GAZE_ENTER","GAZE_HOLD_MS","ABSENT_HOLD_MS","SECOND_HOLD_MS"];
function wireTune() {
  const t = $("tune"); if (!t) return;
  t.classList.remove("hidden");
  const bind = (sId, vId, key, mul, unit) => {
    const s = $(sId), v = $(vId); if (!s) return;
    s.value = CFG[key] / mul; v.textContent = (CFG[key] / mul) + unit;
    s.oninput = () => { CFG[key] = parseFloat(s.value) * mul; v.textContent = s.value + unit; saveCfg(); };
  };
  bind("sHeadEnter", "vHeadEnter", "HEAD_ENTER", 1, "");
  bind("sHeadHold", "vHeadHold", "HEAD_HOLD_MS", 1000, "s");
  bind("sEyeDown", "vEyeDown", "EYEDOWN_ENTER", 1, "");
  bind("sGaze", "vGaze", "GAZE_ENTER", 1, "");
  bind("sGazeHold", "vGazeHold", "GAZE_HOLD_MS", 1000, "s");
  bind("sAbsentHold", "vAbsentHold", "ABSENT_HOLD_MS", 1000, "s");
  bind("sSecondHold", "vSecondHold", "SECOND_HOLD_MS", 1000, "s");
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
  }
  $("calibBar").style.width = Math.min(100, ((now - state.calibStart) / CFG.CALIB_MS) * 100) + "%";
  if (now - state.calibStart >= CFG.CALIB_MS) {
    if (state.calibSamples.length < 5) { $("calibMsg").textContent = "Make sure your face is centred and well lit…"; state.calibStart = now; state.calibSamples = []; state.calibGX = []; state.calibGY = []; return; }
    state.baseline = median(state.calibSamples);
    state.baseGazeX = median(state.calibGX);
    state.baseGazeY = median(state.calibGY);
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

function startMonitoring(now) {
  state.mode = "monitor"; state.startedAt = now;
  $("monVid").srcObject = state.stream; $("monVid").play().catch(() => {});
  $("mTitle").textContent = state.title;
  show("s-monitor");
  pushStatus("ok", true);
  setInterval(() => {
    const track = state.stream && state.stream.getVideoTracks()[0];
    const camOn = track && track.readyState === "live" && track.enabled;
    if (!camOn) { $("monTag").textContent = "🔴 Camera is off"; emit("camera_off", "alert"); }
    else pushStatus(state.lastStatus, true);   // refresh last_seen
  }, CFG.HEARTBEAT_MS);
  const track = state.stream.getVideoTracks()[0];
  if (track) track.addEventListener("ended", () => { $("monTag").textContent = "🔴 Camera stopped"; emit("camera_off", "alert"); });
}

async function begin() {
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }, audio: false });
  } catch { return fail("Vigil needs your camera to monitor this exam. Please allow camera access and reload."); }
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
  state.mode = "calib"; state.calibSamples = []; state.calibGX = []; state.calibGY = []; state.calibStart = performance.now(); state.running = true;
  requestAnimationFrame(loop);
}
function fail(msg) { state.running = false; $("errMsg").textContent = msg; show("s-error"); }

// ── Boot: confirm the student joined this exam, then start ────────────────────
(async () => {
  const { data:{ user: u } } = await sb.auth.getUser();
  if (!u || !examId) { location.replace("/exam/"); return; }
  user = u;
  const { data: exam } = await sb.from("exams").select("title,status").eq("id", examId).maybeSingle();
  if (exam) state.title = exam.title;
  const { data: p } = await sb.from("participants").select("id,name").eq("exam_id", examId).eq("user_id", u.id).maybeSingle();
  if (!p) { location.replace("/exam/"); return; }
  part = p; $("yourName") && ($("yourName").textContent = p.name);
  const al = $("activityLink"); if (al) al.href = "/exam/report.html?e=" + examId;
  if (DEBUG) wireTune();
  begin();
})();
