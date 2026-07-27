// Vigil · Exam mode — student monitor (runs entirely on the student's laptop).
//
// The vision model and the camera frames NEVER leave this device. All that
// crosses the network is a stream of tiny JSON events over one WebSocket:
// heartbeats, and confirmed activity patterns (head-down, face-absent, etc.).
//
// Detection philosophy: the model only gives us geometry (where the face is
// pointing). A per-student calibration + duration timers + hysteresis turn that
// geometry into *confirmed patterns*, never single twitches. That's what keeps
// a nervous student green and only flags sustained behaviour.

import { FaceLandmarker, FilesetResolver } from "/app/vendor/mediapipe/vision_bundle.mjs";

// ── Tunables (Slice 1 defaults — watch the ?debug readout and adjust) ────────
const CFG = {
  DETECT_MS:      90,      // run the model ~11×/sec (plenty; saves CPU)
  CALIB_MS:       4500,    // learn this student's neutral pose
  HEAD_ENTER:     0.14,    // nose-gap DROP (in eye-width units) to start "down"
  HEAD_EXIT:      0.08,    // must recover past this to clear it (hysteresis)
  HEAD_HOLD_MS:   8000,    // sustained this long before it's an EVENT
  ABSENT_HOLD_MS: 5000,    // no face for this long → face_absent
  SECOND_HOLD_MS: 1500,    // a 2nd face for this long → second_face
  SECOND_COOLDOWN_MS: 15000,
  HEARTBEAT_MS:   4000,
};

// FaceMesh landmark indices we rely on (stable points).
const NOSE_TIP = 1, EYE_L = 33, EYE_R = 263;

const $ = (id) => document.getElementById(id);
const show = (id) => {
  ["s-join","s-consent","s-calib","s-monitor","s-error"].forEach(s =>
    $(s).classList.toggle("hidden", s !== id));
};

const DEBUG = /(?:^|[?#&])debug/.test(location.search + location.hash);
let identity = null;   // the student's name when they're already signed in

// ── App state ────────────────────────────────────────────────────────────────
const state = {
  code: "", name: "", title: "Exam",
  stream: null, landmarker: null, video: null,
  ws: null, wsWant: false, reconnectT: null,
  mode: null, running: false,
  lastDetect: 0, lastTs: 0,
  baseline: null,
  calibSamples: [], calibStart: 0,
  startedAt: 0,
};

// ── WebSocket to the server (events only, never video) ───────────────────────
function wsUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/exam/${encodeURIComponent(state.code)}/${encodeURIComponent(state.name)}`;
}
function connect() {
  state.wsWant = true;
  try { state.ws = new WebSocket(wsUrl()); } catch { scheduleReconnect(); return; }
  state.ws.onopen  = () => setConn(true);
  state.ws.onclose = () => { setConn(false); if (state.wsWant) scheduleReconnect(); };
  state.ws.onerror = () => {};
}
function scheduleReconnect() {
  clearTimeout(state.reconnectT);
  state.reconnectT = setTimeout(() => { if (state.wsWant) connect(); }, 2000);
}
function send(obj) {
  const ws = state.ws;
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}
function disconnect() {
  state.wsWant = false;
  clearTimeout(state.reconnectT);
  try { state.ws && state.ws.close(); } catch {}
}

// ── Geometry: model output → the numbers our rules care about ────────────────
function metrics(res) {
  const faces = res.faceLandmarks ? res.faceLandmarks.length : 0;
  if (!faces) return { faces: 0, noseGap: null, pitch: null };
  const lm = res.faceLandmarks[0];
  const L = lm[EYE_L], R = lm[EYE_R], N = lm[NOSE_TIP];
  const iod = Math.hypot(L.x - R.x, L.y - R.y) || 1e-6;   // eye width ~ pose-invariant
  const eyeMidY = (L.y + R.y) / 2;
  // noseGap shrinks when the head tilts DOWN (nose rides up toward the eye line)
  // and grows when it tilts up. Normalised by eye width so distance doesn't matter.
  const noseGap = (N.y - eyeMidY) / iod;
  // Matrix pitch — for the debug readout only. Column-major 4x4 from MediaPipe.
  let pitch = null;
  const m = res.facialTransformationMatrixes && res.facialTransformationMatrixes[0]
            && res.facialTransformationMatrixes[0].data;
  if (m) pitch = Math.atan2(m[6], m[10]) * 180 / Math.PI;
  return { faces, noseGap, pitch };
}

const median = (a) => {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y);
  return s[Math.floor(s.length / 2)];
};

// ── Per-signal trackers (each fires once per sustained episode) ──────────────
const sig = {
  head:   { since: null, fired: false },
  absent: { since: null, fired: false },
  second: { since: null, lastFired: 0 },
};

function doMonitor(mx, now) {
  // 1) HEAD DOWN — hysteresis + hold, all relative to THIS student's baseline
  if (mx.faces >= 1 && state.baseline != null && mx.noseGap != null) {
    const drop = state.baseline - mx.noseGap;          // >0 means head is lower than neutral
    if (drop > CFG.HEAD_ENTER) {
      if (!sig.head.since) sig.head.since = now;
      if (now - sig.head.since > CFG.HEAD_HOLD_MS && !sig.head.fired) {
        send({ type: "head_down", value: (now - sig.head.since) / 1000 });
        sig.head.fired = true;
      }
    } else if (drop < CFG.HEAD_EXIT) {
      sig.head.since = null; sig.head.fired = false;
    }
  }

  // 2) FACE ABSENT — nobody in frame for a stretch (walked away / ducked down)
  if (mx.faces === 0) {
    if (!sig.absent.since) sig.absent.since = now;
    if (now - sig.absent.since > CFG.ABSENT_HOLD_MS && !sig.absent.fired) {
      send({ type: "face_absent", value: (now - sig.absent.since) / 1000 });
      sig.absent.fired = true;
    }
  } else {
    sig.absent.since = null; sig.absent.fired = false;
  }

  // 3) SECOND FACE — someone else in frame (with a cooldown so it can re-fire)
  if (mx.faces >= 2) {
    if (!sig.second.since) sig.second.since = now;
    if (now - sig.second.since > CFG.SECOND_HOLD_MS &&
        now - sig.second.lastFired > CFG.SECOND_COOLDOWN_MS) {
      send({ type: "second_face", value: mx.faces });
      sig.second.lastFired = now;
    }
  } else {
    sig.second.since = null;
  }

  paintStatus(mx, now);
}

// ── Live status shown to the student (calm, non-accusatory) ──────────────────
function paintStatus(mx, now) {
  let cls = "ok", label = "Looking at screen", dot = "";
  if (mx.faces === 0)              { cls = "warn";  label = "Face not visible"; }
  else if (mx.faces >= 2)          { cls = "alert"; label = "More than one face"; }
  else if (sig.head.fired)         { cls = "warn";  label = "Head down"; }

  $("rState").className = "v " + cls;
  $("rState").textContent = label;
  $("mDot").className = "dot" + (cls === "ok" ? "" : " " + cls);

  const secs = Math.floor((now - state.startedAt) / 1000);
  const mm = String(Math.floor(secs / 60)).padStart(2, "0");
  const ss = String(secs % 60).padStart(2, "0");
  $("mSub").textContent = `Monitored · ${mm}:${ss}`;
}

function setConn(ok) {
  const el = $("rConn"); if (!el) return;
  el.className = "v " + (ok ? "ok" : "alert");
  el.textContent = ok ? "Connected" : "Reconnecting…";
}

function renderDebug(mx) {
  if (!DEBUG) return;
  const d = $("debug"); d.classList.remove("hidden");
  const drop = (state.baseline != null && mx.noseGap != null)
    ? (state.baseline - mx.noseGap).toFixed(3) : "—";
  d.textContent =
    `faces=${mx.faces}  noseGap=${mx.noseGap != null ? mx.noseGap.toFixed(3) : "—"}  ` +
    `base=${state.baseline != null ? state.baseline.toFixed(3) : "—"}  drop=${drop}\n` +
    `pitch=${mx.pitch != null ? mx.pitch.toFixed(1) + "°" : "—"}  ` +
    `head=${sig.head.fired ? "DOWN" : "ok"}  ws=${state.ws ? state.ws.readyState : "—"}`;
}

// ── Calibration: collect neutral-pose samples, then start monitoring ─────────
function doCalib(mx, now) {
  if (mx.faces >= 1 && mx.noseGap != null) state.calibSamples.push(mx.noseGap);
  const pct = Math.min(100, ((now - state.calibStart) / CFG.CALIB_MS) * 100);
  $("calibBar").style.width = pct + "%";
  if (now - state.calibStart >= CFG.CALIB_MS) {
    if (state.calibSamples.length < 5) {         // face barely seen — give more time
      $("calibMsg").textContent = "Make sure your face is centred and well lit…";
      state.calibStart = now; state.calibSamples = [];
      return;
    }
    state.baseline = median(state.calibSamples);
    send({ type: "calibrated" });
    startMonitoring(now);
  }
}

// ── The single detection loop (calibrate → monitor) ──────────────────────────
function loop() {
  if (!state.running) return;
  requestAnimationFrame(loop);
  const now = performance.now();
  if (now - state.lastDetect < CFG.DETECT_MS) return;
  state.lastDetect = now;
  let ts = now; if (ts <= state.lastTs) ts = state.lastTs + 1; state.lastTs = ts;

  let res;
  try { res = state.landmarker.detectForVideo(state.video, ts); }
  catch { return; }
  const mx = metrics(res);

  if (state.mode === "calib")  doCalib(mx, now);
  else if (state.mode === "monitor") doMonitor(mx, now);
  renderDebug(mx);
}

function startMonitoring(now) {
  state.mode = "monitor";
  state.startedAt = now;
  $("monVid").srcObject = state.stream;
  $("monVid").play().catch(() => {});
  $("mTitle").textContent = state.title;
  show("s-monitor");

  // Heartbeat — proof the monitor is alive. Its ABSENCE is a flag server-side.
  setInterval(() => {
    const track = state.stream && state.stream.getVideoTracks()[0];
    const camOn = track && track.readyState === "live" && track.enabled;
    if (!camOn) { $("monTag").textContent = "🔴 Camera is off"; }
    send({ type: "heartbeat", camera: camOn ? "on" : "off" });
  }, CFG.HEARTBEAT_MS);

  // If the OS/browser kills the camera, say so loudly.
  const track = state.stream.getVideoTracks()[0];
  if (track) track.addEventListener("ended", () => {
    $("monTag").textContent = "🔴 Camera stopped";
    send({ type: "heartbeat", camera: "off" });
  });
}

// ── Boot: camera → model → calibrate ─────────────────────────────────────────
async function begin() {
  show("s-calib");
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      audio: false,
    });
  } catch {
    return fail("Vigil needs your camera to monitor this exam. Please allow camera access and try again.");
  }

  const video = $("calibVid");
  video.srcObject = state.stream;
  state.video = video;
  await video.play().catch(() => {});
  await new Promise((r) => (video.readyState >= 2 ? r() : video.addEventListener("loadeddata", r, { once: true })));

  try {
    const fileset = await FilesetResolver.forVisionTasks("/app/vendor/mediapipe/wasm");
    state.landmarker = await FaceLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: "/app/vendor/mediapipe/face_landmarker.task" },
      runningMode: "VIDEO",
      numFaces: 2,
      outputFacialTransformationMatrixes: true,
    });
  } catch (e) {
    return fail("Could not load the monitoring model. Check your connection and try again.");
  }

  connect();                       // open the event socket
  state.mode = "calib";
  state.calibSamples = [];
  state.calibStart = performance.now();
  state.running = true;
  requestAnimationFrame(loop);
}

function fail(msg) {
  state.running = false;
  disconnect();
  $("errMsg").textContent = msg;
  show("s-error");
}

// ── Screen wiring ────────────────────────────────────────────────────────────
$("joinBtn").addEventListener("click", async () => {
  const code = $("code").value.trim().toUpperCase();
  const name = identity || $("name").value.trim();
  $("joinErr").textContent = "";
  if (code.length < 4)  return ($("joinErr").textContent = "Enter the exam code.");
  if (!identity && name.length < 2)  return ($("joinErr").textContent = "Enter your name.");
  $("joinBtn").disabled = true;
  try {
    const r = await fetch(`/api/exam/${encodeURIComponent(code)}`);
    if (r.status === 404) throw new Error("No exam found with that code.");
    if (r.status === 401) throw new Error("Please sign in to Vigil first, then reopen this link.");
    if (!r.ok) throw new Error("Could not reach the server.");
    const info = await r.json();
    if (info.status !== "open") throw new Error("This exam is not open for joining.");
    state.code = info.code; state.name = name; state.title = info.title || "Exam";
    $("consentTitle").textContent = state.title;
    show("s-consent");
  } catch (e) {
    $("joinErr").textContent = e.message || "Something went wrong.";
  } finally {
    $("joinBtn").disabled = false;
  }
});

$("backBtn").addEventListener("click", () => show("s-join"));
$("consentBtn").addEventListener("click", begin);
$("retryBtn").addEventListener("click", () => location.reload());

// ── Boot: prefill code, detect an existing sign-in, offer Google ─────────────
const currentCode = () => ($("code").value || "").trim().toUpperCase();

async function boot() {
  const h = location.hash.replace(/^#/, "").split("&")[0].toUpperCase();
  if (/^[A-Z0-9]{4,6}$/.test(h)) $("code").value = h;
  show("s-join");

  // Already signed in (e.g. just came back from Google)? Use that identity and
  // drop the name field — the student doesn't type who they are.
  try {
    const r = await fetch("/api/me", { headers: { Accept: "application/json" } });
    if (r.ok) {
      const me = await r.json();
      if (me && me.username) {
        identity = String(me.username).replace(/@.*/, "");
        $("nameWrap").classList.add("hidden");
        $("signedIn").classList.remove("hidden");
        $("signedIn").querySelector(".who").textContent = "Signed in as " + identity;
      }
    }
  } catch {}

  // Offer Google sign-in for students only when the server has it configured.
  if (!identity) {
    try {
      const cfg = await (await fetch("/api/exam/config")).json();
      if (cfg && cfg.google && cfg.client_id) wireGoogle(cfg.client_id);
    } catch {}
  }
}

// Google self-onboarding: the exam CODE is the invite. The student enters the
// code, signs in with Google, the server creates their student account, and we
// reload — now signed in, with the code remembered in the hash.
function wireGoogle(clientId) {
  window.onExamGoogle = async (resp) => {
    const code = currentCode();
    $("joinErr").textContent = "";
    if (code.length < 4) { $("joinErr").textContent = "Enter your exam code first, then sign in."; return; }
    try {
      const r = await fetch("/auth/google", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: resp.credential, exam_code: code }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || "Google sign-in failed.");
      location.hash = "#" + code;   // survive the reload
      location.reload();            // return signed in; identity is picked up
    } catch (e) { $("joinErr").textContent = e.message; }
  };
  const s = document.createElement("script");
  s.src = "https://accounts.google.com/gsi/client";
  s.async = true;
  s.onload = () => {
    if (!window.google || !google.accounts) return;
    google.accounts.id.initialize({ client_id: clientId, callback: window.onExamGoogle });
    google.accounts.id.renderButton($("gbtn"), { theme: "filled_black", size: "large", text: "signin_with", width: 300 });
    $("googleWrap").classList.remove("hidden");
  };
  document.head.appendChild(s);
}

// Cursor-follow glare across the card — a calm premium touch, no distracting motion.
{
  const card = document.querySelector(".card");
  if (card) card.addEventListener("pointermove", (e) => {
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", (e.clientX - r.left) + "px");
    card.style.setProperty("--my", (e.clientY - r.top) + "px");
  });
}

boot();
