// Vigil · Exam report — reads the durable event log for one session and lays
// it out as a per-student timeline. This is the calm, after-the-fact review a
// human invigilator uses; the live tiles are a separate screen.

const $ = (id) => document.getElementById(id);
let current = null;   // the last loaded report, for CSV export

// How each raw event type reads to a human, and how severe it is.
const KIND = {
  joined:       { label: "Joined the exam",        sev: "info"  },
  calibrated:   { label: "Calibration complete",   sev: "info"  },
  head_down:    { label: "Looked down",            sev: "warn"  },
  face_absent:  { label: "Face not visible",       sev: "warn"  },
  second_face:  { label: "Second face in frame",   sev: "alert" },
  camera_off:   { label: "Camera turned off",      sev: "alert" },
  disconnected: { label: "Monitor disconnected",   sev: "alert" },
};

function hms(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function dur(v) {
  if (v == null) return "";
  const s = Math.round(v);
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}

function render(data) {
  current = data;
  $("title").textContent = data.title || "Exam report";
  $("sub").textContent = `Code ${data.code} · ${data.status} · ${data.events.length} events`;
  // Nice filename when the browser saves this page as PDF.
  document.title = `Vigil report · ${data.title || "Exam"} (${data.code})`;
  $("gen").textContent = `Generated ${new Date().toLocaleString()} · Vigil`;
  $("gen").classList.remove("hidden");
  $("csvBtn").classList.remove("hidden");
  $("pdfBtn").classList.remove("hidden");

  const out = $("out");
  out.innerHTML = "";

  if (!data.events.length) {
    out.innerHTML = `<div class="empty">No activity recorded yet for this exam.</div>`;
    return;
  }

  // Group events by student, preserving chronological order.
  const byStudent = new Map();
  for (const e of data.events) {
    if (!byStudent.has(e.student)) byStudent.set(e.student, []);
    byStudent.get(e.student).push(e);
  }

  for (const [student, events] of byStudent) {
    const counts = { head_down: 0, face_absent: 0, second_face: 0, offline: 0 };
    for (const e of events) {
      if (e.type in counts) counts[e.type]++;
      if (e.type === "camera_off" || e.type === "disconnected") counts.offline++;
    }
    const flags = counts.head_down + counts.face_absent + counts.second_face + counts.offline;

    const chips = [];
    if (counts.head_down)   chips.push(`<span class="chip warn"><b>${counts.head_down}</b> head down</span>`);
    if (counts.face_absent) chips.push(`<span class="chip warn"><b>${counts.face_absent}</b> face absent</span>`);
    if (counts.second_face) chips.push(`<span class="chip alert"><b>${counts.second_face}</b> second face</span>`);
    if (counts.offline)     chips.push(`<span class="chip alert"><b>${counts.offline}</b> went offline</span>`);
    if (!flags)             chips.push(`<span class="chip ok">No flags</span>`);

    const timeline = events.map((e) => {
      const k = KIND[e.type] || { label: e.type, sev: "info" };
      const extra = e.value != null && (e.type === "head_down" || e.type === "face_absent")
        ? ` <small>for ${dur(e.value)}</small>` : "";
      return `<div class="ev ${k.sev}"><span class="time">${hms(e.created_at)}</span>` +
             `<span class="what">${k.label}${extra}</span></div>`;
    }).join("");

    const card = document.createElement("div");
    card.className = "student";
    card.innerHTML =
      `<h2>${escapeHtml(student)} <span class="pill">${flags} flag${flags === 1 ? "" : "s"}</span></h2>` +
      `<div class="chips">${chips.join("")}</div>` +
      `<div class="tl">${timeline}</div>`;
    out.appendChild(card);
  }
  requestAnimationFrame(updateBeams);
}

// Timeline beams fill as the report scrolls (Aceternity-style).
function updateBeams() {
  const vh = window.innerHeight;
  document.querySelectorAll(".tl").forEach((tl) => {
    const r = tl.getBoundingClientRect();
    const p = (vh * 0.82 - r.top) / (r.height || 1);
    tl.style.setProperty("--fill", Math.max(0, Math.min(1, p)).toFixed(3));
  });
}
addEventListener("scroll", () => requestAnimationFrame(updateBeams), { passive: true });
addEventListener("resize", () => requestAnimationFrame(updateBeams));

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function load(code) {
  $("err").textContent = "";
  $("out").innerHTML = "";
  try {
    const r = await fetch(`/api/exam/${encodeURIComponent(code)}/events`);
    if (r.status === 404) throw new Error("No exam found with that code.");
    if (r.status === 401) throw new Error("Please sign in to Vigil first.");
    if (!r.ok) throw new Error("Could not load the report.");
    render(await r.json());
  } catch (e) {
    $("err").textContent = e.message || "Something went wrong.";
  }
}

$("loadBtn").addEventListener("click", () => {
  const code = $("code").value.trim().toUpperCase();
  if (code.length >= 4) load(code);
});
$("code").addEventListener("keydown", (e) => { if (e.key === "Enter") $("loadBtn").click(); });

// ── Export ───────────────────────────────────────────────────────────────────
function toCSV(data) {
  const esc = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
  const rows = [["Student", "Event", "Severity", "Duration (s)", "Time"]];
  for (const e of data.events) {
    const k = KIND[e.type] || { label: e.type, sev: "info" };
    rows.push([e.student, k.label, e.severity || k.sev,
               e.value != null ? Math.round(e.value) : "", e.created_at]);
  }
  return rows.map((r) => r.map(esc).join(",")).join("\r\n");
}

function download(name, text, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("csvBtn").addEventListener("click", () => {
  if (!current) return;
  const date = new Date().toISOString().slice(0, 10);
  download(`vigil-report-${current.code}-${date}.csv`, toCSV(current), "text/csv;charset=utf-8");
});
$("pdfBtn").addEventListener("click", () => window.print());   // browser "Save as PDF"

// Deep link: /app/report.html#ABC123 loads that exam straight away.
(() => {
  const h = location.hash.replace(/^#/, "").toUpperCase();
  if (/^[A-Z0-9]{4,6}$/.test(h)) { $("code").value = h; load(h); }
})();
