// Vigil Exams · student monitor — MediaPipe runs entirely on this device.
// Video/frames NEVER leave the laptop; only tiny events + presence go to Supabase.
import { sb } from "/exam/sb.js";
import { FaceLandmarker, FilesetResolver } from "/vendor/mediapipe/vision_bundle.mjs";

const CFG = {
  DETECT_MS: 90, CALIB_MS: 4500,
  HEAD_ENTER: 0.14, HEAD_EXIT: 0.08, HEAD_HOLD_MS: 8000,
  ABSENT_HOLD_MS: 5000, SECOND_HOLD_MS: 1500, SECOND_COOLDOWN_MS: 15000,
  HEARTBEAT_MS: 6000, STATUS_MIN_MS: 1500,
};
const NOSE_TIP = 1, EYE_L = 33, EYE_R = 263;
const DEBUG = /(?:^|[?#&])debug/.test(location.search + location.hash);
const $ = (id) => document.getElementById(id);
const show = (id) => ["s-calib","s-monitor","s-error"].forEach(s => $(s).classList.toggle("hidden", s !== id));

const examId = new URLSearchParams(location.search).get("e");
let user = null, part = null;   // part = { id, name }
const state = {
  stream: null, landmarker: null, video: null, mode: null, running: false,
  lastDetect: 0, lastTs: 0, baseline: null, calibSamples: [], calibStart: 0,
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
  if (!faces) return { faces: 0, noseGap: null };
  const lm = res.faceLandmarks[0], L = lm[EYE_L], R = lm[EYE_R], N = lm[NOSE_TIP];
  const iod = Math.hypot(L.x - R.x, L.y - R.y) || 1e-6;
  const noseGap = (N.y - (L.y + R.y) / 2) / iod;
  return { faces, noseGap };
}
const median = (a) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };

const sig = { head: { since: null, fired: false }, absent: { since: null, fired: false }, second: { since: null, lastFired: 0 } };

function doMonitor(mx, now) {
  if (mx.faces >= 1 && state.baseline != null && mx.noseGap != null) {
    const drop = state.baseline - mx.noseGap;
    if (drop > CFG.HEAD_ENTER) {
      if (!sig.head.since) sig.head.since = now;
      if (now - sig.head.since > CFG.HEAD_HOLD_MS && !sig.head.fired) { emit("head_down", "warn"); sig.head.fired = true; }
    } else if (drop < CFG.HEAD_EXIT) { sig.head.since = null; sig.head.fired = false; }
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
  else if (sig.head.fired) { cls = "warn"; label = "Head down"; }
  $("rState").className = "v " + cls; $("rState").textContent = label;
  $("mDot").className = "dot " + cls;
  const secs = Math.floor((now - state.startedAt) / 1000);
  $("mSub").textContent = `Monitored · ${String(Math.floor(secs/60)).padStart(2,"0")}:${String(secs%60).padStart(2,"0")}`;
  pushStatus(cls, false);   // keep the teacher's tile in sync (throttled)
  if (DEBUG) { const d = $("debug"); d.classList.remove("hidden");
    d.textContent = `faces=${mx.faces} gap=${mx.noseGap?.toFixed(3) ?? "—"} base=${state.baseline?.toFixed(3) ?? "—"} head=${sig.head.fired?"DOWN":"ok"}`; }
}

function doCalib(mx, now) {
  if (mx.faces >= 1 && mx.noseGap != null) state.calibSamples.push(mx.noseGap);
  $("calibBar").style.width = Math.min(100, ((now - state.calibStart) / CFG.CALIB_MS) * 100) + "%";
  if (now - state.calibStart >= CFG.CALIB_MS) {
    if (state.calibSamples.length < 5) { $("calibMsg").textContent = "Make sure your face is centred and well lit…"; state.calibStart = now; state.calibSamples = []; return; }
    state.baseline = median(state.calibSamples);
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
  state.mode = "calib"; state.calibSamples = []; state.calibStart = performance.now(); state.running = true;
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
  begin();
})();
