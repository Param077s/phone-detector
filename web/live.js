// NOTE: wrapped in an IIFE because this file now runs more than once per
// tab. The teacher walks between the console, this wall and the report, and each
// arrival re-executes it. Two classic scripts share one global scope, so the
// declarations below would collide on the second run and the page would
// arrive blank. See /app/softnav.js.
(function () {
  // Standalone fallback: these pages still work opened directly, with or
  // without the router (see /app/softnav.js).
  var page = window.vigilPage || {
    every: function (ms, fn) { return setInterval(fn, ms); },
    listen: function (t, e, f, o) { t.addEventListener(e, f, o); },
    onLeave: function () {}
  };

// Vigil · Live exam room — the teacher's wall of student tiles. It polls the
// server's computed live status every couple of seconds; the tiles stay green
// until a *confirmed* pattern turns one amber/red, and a student who goes dark
// stays on screen as a red "offline" tile (that absence is itself the signal).

const $ = (id) => document.getElementById(id);
const CODE = (location.hash.replace(/^#/, "").split("&")[0] || "").toUpperCase();
const POLL_MS = 2000;

const FLAG_LABEL = {
  head_down: "Looking down",
  face_absent: "Face not visible",
  second_face: "Second face in frame",
  camera_off: "Camera off",
  disconnected: "Disconnected",
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function statusText(s) {
  if (s.presence === "offline") return "Offline";
  if (s.presence === "camera_off") return "Camera off";
  if (s.level === "ok") return "Looking at screen";
  const lbl = FLAG_LABEL[s.last_flag] || "Flagged";
  return s.flag_age != null ? `${lbl} · ${Math.round(s.flag_age)}s ago` : lbl;
}

function render(data) {
  $("title").textContent = data.title || "Live exam";
  $("code").textContent = data.code || CODE;
  $("repLink").href = `/app/report.html#${data.code || CODE}`;

  const c = data.counts || { total: 0, flagged: 0, offline: 0 };
  $("counts").innerHTML =
    `<span class="pill"><b>${c.total}</b> student${c.total === 1 ? "" : "s"}</span>` +
    `<span class="pill flagged"><b>${c.flagged}</b> flagged</span>` +
    `<span class="pill offline"><b>${c.offline}</b> offline</span>`;

  const out = $("out");
  if (!data.students.length) {
    out.innerHTML = `<div class="empty"><div class="big">Waiting for students to join…</div>
      <div>Share code <b>${esc(data.code || CODE)}</b>. Tiles appear here as students start their exam.</div></div>`;
    return;
  }

  out.innerHTML = `<div class="grid">` + data.students.map((s) => `
    <div class="tile ${s.level}">
      <div class="top"><span class="dot"></span><span class="name">${esc(s.student)}</span></div>
      <div class="status">${esc(statusText(s))}</div>
      <div class="meta"><span>${s.online ? "🟢 live" : "⚫ gone"}</span><span>${s.flags} flag${s.flags === 1 ? "" : "s"}</span></div>
    </div>`).join("") + `</div>`;
}

async function poll() {
  try {
    const r = await fetch(`/api/exam/${encodeURIComponent(CODE)}/live`, { headers: { Accept: "application/json" } });
    if (r.status === 401) { location.href = "/login"; return; }
    if (r.status === 404) { $("out").innerHTML = `<div class="err">No exam found with code ${esc(CODE)}.</div>`; return; }
    if (!r.ok) throw new Error();
    render(await r.json());
  } catch {
    /* transient — keep the last good view, try again next tick */
  }
}

// Opening the live room enrolls this teacher for the exam's push alerts, so
// they're notified on their phone even after they step away from the desk.
async function watchExam() {
  try {
    const r = await fetch(`/api/exam/${encodeURIComponent(CODE)}/watch`, { method: "POST" });
    if (r.ok) { const a = $("alerts"); if (a) a.style.display = ""; }
  } catch { /* alerts are best-effort */ }
}

if (!/^[A-Z0-9]{4,6}$/.test(CODE)) {
  $("out").innerHTML = `<div class="err">Open this from the Exams list so it has an exam code.</div>`;
} else {
  watchExam();
  poll();
  page.every(POLL_MS, poll);
}

})();
