/* ==========================================================================
   VIGIL — application shell
   Vanilla JS. No build step, no framework, no external requests (works offline).
   Talks to the EXISTING backend JSON APIs — no AI/detection code is touched.
   Routes (hash): #/live  #/evidence  #/users  #/settings
   ========================================================================== */
(() => {
"use strict";

/* -------------------------------------------------------------------------
   0. Mock mode — ONLY when ?mock=1. Lets the UI render with sample data for
   design review without the backend. Production never sets this flag.
   ------------------------------------------------------------------------- */
const MOCK = new URLSearchParams(location.search).has("mock");

/* -------------------------------------------------------------------------
   1. Icons  (Lucide-style, single stroke, 24px viewBox)
   ------------------------------------------------------------------------- */
const P = {
  live:     'M15 10l4.55-2.28A1 1 0 0 1 21 8.62v6.76a1 1 0 0 1-1.45.9L15 14M4 6h9a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z',
  evidence: 'M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM3 7h18M7 3v18M17 3v18M3 12h18M3 17h18',
  users:    'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  settings: 'M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z',
  plus:     'M12 5v14M5 12h14',
  search:   'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35',
  more:     'M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM19 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM5 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
  maximize: 'M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M16 21h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3',
  minimize: 'M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M16 21v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3',
  pause:    'M6 4h4v16H6zM14 4h4v16h-4z',
  play:     'M6 3l14 9-14 9V3z',
  edit:     'M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z',
  trash:    'M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6',
  x:        'M18 6 6 18M6 6l12 12',
  check:    'M20 6 9 17l-5-5',
  alert:    'M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01',
  camoff:   'M2 2l20 20M7 7H4a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h11M15 9.34V7a2 2 0 0 0-2-2H9.66M23 7l-5 3.5v3',
  shield:   'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
  chevron:  'M9 18l6-6-6-6',
  chevdown: 'M6 9l6 6 6-6',
  star:     'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z',
  download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
  share:    'M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8M16 6l-4-4-4 4M12 2v13',
  clock:    'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2',
  filter:   'M22 3H2l8 9.46V19l4 2v-8.54L22 3z',
  logout:   'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
  cpu:      'M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2M6 6h12v12H6zM9 9h6v6H9z',
  wifi:     'M5 13a10 10 0 0 1 14 0M8.5 16.5a5 5 0 0 1 7 0M2 8.82a15 15 0 0 1 20 0M12 20h.01',
  wifioff:  'M2 2l20 20M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 5.24-2.76M19 13a10 10 0 0 0-1.4-1.14M12 20h.01',
  sun:      'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon:     'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z',
  grid:     'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z',
  bell:     'M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0',
  hd:       'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z',
  db:       'M12 8c4.42 0 8-1.34 8-3s-3.58-3-8-3-8 1.34-8 3 3.58 3 8 3zM4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3',
  zap:      'M13 2 3 14h9l-1 8 10-12h-9l1-8z',
  info:     'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01',
  lock:     'M5 11h14a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2zM7 11V7a5 5 0 0 1 10 0v4',
};
const icon = (name, cls = "") =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"${cls?` class="${cls}"`:""}>${
    P[name].split("M").filter(Boolean).map(d => `<path d="M${d}"/>`).join("")
  }</svg>`;

const LOGO = `<svg viewBox="0 0 24 24" fill="none"><rect width="24" height="24" rx="7" fill="var(--surface-3)"/><path d="M6 10V7.5A1.5 1.5 0 0 1 7.5 6H10M14 6h2.5A1.5 1.5 0 0 1 18 7.5V10M18 14v2.5a1.5 1.5 0 0 1-1.5 1.5H14M10 18H7.5A1.5 1.5 0 0 1 6 16.5V14" stroke="var(--text-3)" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="12" r="2.6" fill="var(--accent)"/></svg>`;

/* -------------------------------------------------------------------------
   2. Small DOM + utility helpers
   ------------------------------------------------------------------------- */
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const h = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
const debounce = (fn, ms = 200) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

function fmtTime(t) { return t || "—"; }
function relDate(d) {
  if (!d) return "";
  const today = new Date().toISOString().slice(0, 10);
  const y = new Date(Date.now() - 864e5).toISOString().slice(0, 10);
  if (d === today) return "Today";
  if (d === y) return "Yesterday";
  return d;
}
function initials(name) {
  const s = (name || "?").replace(/@.*/, "");
  return s.slice(0, 2).toUpperCase();
}

/* -------------------------------------------------------------------------
   3. Toasts / confirm / menu
   ------------------------------------------------------------------------- */
function toast(title, { msg = "", kind = "info", timeout = 3600 } = {}) {
  const iconName = kind === "ok" ? "check" : kind === "danger" ? "alert" : "info";
  const color = kind === "ok" ? "var(--ok)" : kind === "danger" ? "var(--danger)" : "var(--info)";
  const el = h(`<div class="toast"><span class="toast__icon" style="color:${color}">${icon(iconName)}</span>
    <div class="toast__body"><div class="toast__title">${esc(title)}</div>${msg ? `<div class="toast__msg">${esc(msg)}</div>` : ""}</div></div>`);
  $("#toasts").appendChild(el);
  const kill = () => { el.classList.add("is-leaving"); setTimeout(() => el.remove(), 200); };
  el.addEventListener("click", kill);
  if (timeout) setTimeout(kill, timeout);
}

function confirmDialog({ title, body, confirmText = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    const scrim = h(`<div class="scrim"><div class="modal" role="dialog" aria-modal="true">
      <div class="modal__head"><div class="modal__title">${esc(title)}</div></div>
      <div class="modal__body"><p class="muted" style="margin:0">${esc(body)}</p></div>
      <div class="modal__foot"><button class="btn" data-x>Cancel</button>
      <button class="btn ${danger ? "btn--danger" : "btn--primary"}" data-ok>${esc(confirmText)}</button></div></div></div>`);
    const close = (v) => { scrim.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
    const onKey = (e) => { if (e.key === "Escape") close(false); if (e.key === "Enter") close(true); };
    scrim.addEventListener("click", (e) => { if (e.target === scrim) close(false); });
    $("[data-x]", scrim).onclick = () => close(false);
    $("[data-ok]", scrim).onclick = () => close(true);
    document.addEventListener("keydown", onKey);
    $("#overlays").appendChild(scrim);
    $("[data-ok]", scrim).focus();
  });
}

function openModal(node) {
  const scrim = h(`<div class="scrim"></div>`);
  scrim.appendChild(node);
  const close = () => { scrim.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  scrim.addEventListener("click", (e) => { if (e.target === scrim) close(); });
  document.addEventListener("keydown", onKey);
  $("#overlays").appendChild(scrim);
  return close;
}

function contextMenu(x, y, items) {
  $$(".menu").forEach(m => m.remove());
  const menu = h(`<div class="menu" role="menu">${items.map(it =>
    it.sep ? `<div class="menu__sep"></div>` :
    it.label && it.header ? `<div class="menu__label">${esc(it.label)}</div>` :
    `<div class="menu__item ${it.danger ? "menu__item--danger" : ""}" data-i="${it._i}">${it.icon ? icon(it.icon) : ""}<span>${esc(it.label)}</span>${it.kbd ? `<span class="kbd">${it.kbd}</span>` : ""}</div>`
  ).join("")}</div>`);
  document.body.appendChild(menu);
  const r = menu.getBoundingClientRect();
  menu.style.left = Math.min(x, innerWidth - r.width - 8) + "px";
  menu.style.top = Math.min(y, innerHeight - r.height - 8) + "px";
  const close = () => { menu.remove(); document.removeEventListener("click", close); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  items.forEach((it, i) => { if (it.onClick) { const n = $(`[data-i="${i}"]`, menu); if (n) n.onclick = () => { close(); it.onClick(); }; } });
  items.forEach((it, i) => it._i = i);
  $$("[data-i]", menu).forEach(n => { const it = items[+n.dataset.i]; if (it.onClick) n.onclick = () => { close(); it.onClick(); }; });
  setTimeout(() => document.addEventListener("click", close), 0);
  document.addEventListener("keydown", onKey);
  addEventListener("hashchange", close, { once: true });
}

/* -------------------------------------------------------------------------
   4. API layer  (existing backend endpoints; mock fallback for design review)
   ------------------------------------------------------------------------- */
const api = {
  async _get(url) {
    const r = await fetch(url, { headers: { "Accept": "application/json" } });
    if (r.status === 401) { location.href = "/login"; throw new Error("unauthorized"); }
    if (!r.ok) throw new Error(r.status + " " + url);
    return r.json();
  },
  me:           () => MOCK ? Promise.resolve(MOCKDATA.me)         : api._get("/api/me"),
  stats:        () => MOCK ? Promise.resolve(MOCKDATA.stats)      : api._get("/stats"),
  cameras:      () => MOCK ? Promise.resolve(MOCKDATA.cameras)    : api._get("/cameras"),
  cameraStatus: () => MOCK ? Promise.resolve(MOCKDATA.status)     : api._get("/camera_status"),
  evidence:  (q = "") => MOCK ? Promise.resolve(MOCKDATA.evidence): api._get("/evidence/list" + q),
  users:        () => MOCK ? Promise.resolve(MOCKDATA.users)      : api._get("/api/users"),
  settings:     () => MOCK ? Promise.resolve(MOCKDATA.settings)   : api._get("/api/settings"),

  addCamera: (b) => fetch("/cameras", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }).then(r => r.json()),
  editCamera: (id, b) => fetch("/cameras/" + id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }).then(r => r.json()),
  delCamera: (id) => fetch("/cameras/" + id, { method: "DELETE" }),
  reorder: (order) => fetch("/cameras/reorder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ order }) }),
  pauseAll: () => fetch("/cameras/pause_all", { method: "POST" }),
  resumeAll: () => fetch("/cameras/resume_all", { method: "POST" }),
  reviewAlert: (id, action) => fetch(`/alerts/${id}/${action}`, { method: "POST" }).then(r => r.json()),
  saveSettings: (form) => fetch("/settings", { method: "POST", body: form }),
  addUser: (form) => fetch("/users", { method: "POST", body: form }),
  delUser: (username) => { const f = new FormData(); f.append("username", username); return fetch("/users/delete", { method: "POST", body: f }); },
};

const MOCKDATA = {
  me: { username: "diljot", role: "admin" },
  stats: { cameras: 6, alerts_today: 4, pending: 2 },
  cameras: [
    { id: "a1", label: "Main Entrance", location: "Building A · Lobby", source: "rtsp://…", enabled: true },
    { id: "a2", label: "Exam Hall 1", location: "Building A · Floor 2", source: "rtsp://…", enabled: true },
    { id: "a3", label: "Exam Hall 2", location: "Building A · Floor 2", source: "rtsp://…", enabled: true },
    { id: "a4", label: "Corridor West", location: "Building B", source: "0", enabled: true },
    { id: "a5", label: "Library", location: "Building C · Ground", source: "rtsp://…", enabled: false },
    { id: "a6", label: "Parking Deck", location: "Exterior", source: "rtsp://…", enabled: true },
  ],
  status: { a1: "online", a2: "online", a3: "online", a4: "offline", a5: "paused", a6: "online" },
  evidence: [
    { id: 21, time: "14:32:08", date: new Date().toISOString().slice(0,10), confidence: 0.91, camera: "Exam Hall 1", status: "pending", thing: "Phone", image: "", description: "A person holding a phone near desk, screen visible.", reviewed_by: "", reviewed_at: "" },
    { id: 20, time: "14:18:44", date: new Date().toISOString().slice(0,10), confidence: 0.78, camera: "Exam Hall 2", status: "pending", thing: "Phone", image: "", description: "", reviewed_by: "", reviewed_at: "" },
    { id: 19, time: "13:55:12", date: new Date().toISOString().slice(0,10), confidence: 0.88, camera: "Main Entrance", status: "confirmed", thing: "Phone", image: "", description: "Phone raised to ear.", reviewed_by: "diljot", reviewed_at: "13:56" },
    { id: 18, time: "11:02:31", date: new Date().toISOString().slice(0,10), confidence: 0.64, camera: "Corridor West", status: "dismissed", thing: "Phone", image: "", description: "False positive — dark rectangle.", reviewed_by: "param", reviewed_at: "11:03" },
  ],
  users: [
    { username: "diljot", email: "diljot@vigil.app", role: "admin", auth: "google", created_at: "2026-05-01", last_login: "Today, 14:20" },
    { username: "param", email: "", role: "admin", auth: "password", created_at: "2026-05-01", last_login: "Today, 09:12" },
    { username: "invigilator1", email: "", role: "invigilator", auth: "password", created_at: "2026-06-10", last_login: "Yesterday" },
  ],
  settings: { WATCH_TARGET: "phone", MODEL_NAME: "yolo11m.pt", CONFIDENCE: 0.5, REQUIRED_HITS: 3, ALERT_COOLDOWN: 3, IMG_SIZE: 960, VLM_ENABLED: true, VLM_MODEL: "moondream", VLM_VERIFY: true, TELEGRAM_TOKEN: "", TELEGRAM_CHAT_IDS: "" },
};

/* -------------------------------------------------------------------------
   5. App state
   ------------------------------------------------------------------------- */
const state = {
  me: { username: "", role: "invigilator" },
  route: "live",
  cameras: [], status: {}, stats: { cameras: 0, alerts_today: 0, pending: 0 },
  recentAlerts: [], selected: new Set(),
  density: localStorage.getItem("vigil.density") || "cozy",
  theme: localStorage.getItem("vigil.theme") || "dark",
  evFilter: { status: "all", camera: "all", date: "" },
};
const isAdmin = () => state.me.role === "admin";

/* =========================================================================
   6. LIVE FOOTAGE
   ========================================================================= */
const Live = {
  feeds: new Map(),          // camId -> stop()
  pollTimer: null,

  async render(root) {
    root.className = "content content--flush";
    root.innerHTML = `
      <div class="toolbar">
        <div class="segmented" id="density">
          ${[["comfortable","Large"],["cozy","Medium"],["compact","Small"],["dense","Wall"]].map(([k,l]) =>
            `<button data-d="${k}" class="${state.density===k?"is-active":""}">${l}</button>`).join("")}
        </div>
        <div class="search" style="max-width:280px"><span>${icon("search")}</span>
          <input id="camSearch" placeholder="Search cameras…" autocomplete="off"></div>
        <div class="spacer"></div>
        <span id="onlineCount" class="muted"></span>
        ${isAdmin() ? `<button class="btn" id="pauseAll">${icon("pause")} Pause all</button>
        <button class="btn btn--primary" id="addCam">${icon("plus")} Add camera</button>` : ""}
      </div>
      <div class="live">
        <div class="live__stats" id="stats"></div>
        <div class="grid-cams" id="camGrid" data-density="${state.density}"></div>
      </div>`;

    $("#density", root).onclick = (e) => { const b = e.target.closest("[data-d]"); if (!b) return;
      state.density = b.dataset.d; localStorage.setItem("vigil.density", state.density);
      $$("#density button").forEach(x => x.classList.toggle("is-active", x === b));
      $("#camGrid").dataset.density = state.density; };
    $("#camSearch", root).oninput = debounce((e) => Live.filter(e.target.value), 120);
    if (isAdmin()) {
      $("#addCam", root).onclick = () => CameraForm.open();
      $("#pauseAll", root).onclick = () => Live.togglePauseAll($("#pauseAll", root));
    }

    await Live.refresh(true);
    Live.pollTimer = setInterval(() => Live.refresh(false), 3000);
  },

  destroy() { clearInterval(Live.pollTimer); Live.feeds.forEach(stop => stop()); Live.feeds.clear(); },

  async refresh(first) {
    let cams, status, stats, alerts;
    try { [cams, status, stats, alerts] = await Promise.all([api.cameras(), api.cameraStatus(), api.stats(), api.evidence("?status=all")]); }
    catch { return; }
    state.cameras = cams; state.status = status; state.stats = stats; state.recentAlerts = alerts.slice(0, 40);
    Live.renderStats();
    if (first) Live.buildGrid();
    Live.syncGrid();
  },

  renderStats() {
    const online = state.cameras.filter(c => state.status[c.id] === "online").length;
    const s = state.stats;
    $("#onlineCount").textContent = `${online}/${state.cameras.length} online`;
    $("#stats").innerHTML = [
      ["Cameras online", `${online}<small> / ${state.cameras.length}</small>`, "live"],
      ["Detections today", s.alerts_today, "alert"],
      ["Pending review", s.pending, "clock"],
      ["AI engine", `Active`, "cpu"],
    ].map(([label, val, ic]) => `<div class="stat"><div class="stat__label">${icon(ic)} ${label}</div><div class="stat__value">${val}</div></div>`).join("");
  },

  buildGrid() {
    const grid = $("#camGrid");
    Live.feeds.forEach(stop => stop()); Live.feeds.clear();
    if (!state.cameras.length) { grid.innerHTML = ""; grid.appendChild(Live.empty()); return; }
    grid.innerHTML = "";
    state.cameras.forEach((c, i) => grid.appendChild(Live.tile(c, i)));
  },

  empty() {
    const admin = isAdmin();
    const e = h(`<div class="empty" style="grid-column:1/-1">
      <div class="empty__icon">${icon("live")}</div>
      <div class="empty__title">No cameras yet</div>
      <div class="empty__text">Live Footage shows every camera Vigil is watching, with AI detection running on each feed. ${admin ? "Add your first camera to start monitoring." : "Ask an admin to add cameras."}</div>
      ${admin ? `<button class="btn btn--primary" style="margin-top:8px">${icon("plus")} Add camera</button>` : ""}</div>`);
    if (admin) $("button", e).onclick = () => CameraForm.open();
    return e;
  },

  tile(c, i) {
    const st = state.status[c.id] || (c.enabled === false ? "paused" : "offline");
    const el = h(`<div class="cam" data-id="${c.id}" style="animation-delay:${Math.min(i*30,300)}ms">
      <img class="cam__feed" alt="${esc(c.label)}">
      <div class="cam__offline hidden">${icon("camoff")}<span></span></div>
      <div class="cam__top">
        <span class="cam__status"><span class="dot"></span><span class="cam__status-t"></span></span>
        <span class="cam__ai">${icon("shield")} AI</span>
      </div>
      <div class="cam__actions"></div>
      <div class="cam__bottom">
        <div style="min-width:0"><div class="cam__name">${esc(c.label)}</div>${c.location ? `<div class="cam__loc">${esc(c.location)}</div>` : ""}</div>
      </div></div>`);

    // actions
    const actions = $(".cam__actions", el);
    const btn = (ic, title, fn) => { const b = h(`<button class="cam__btn" title="${title}">${icon(ic)}</button>`); b.onclick = (e) => { e.stopPropagation(); fn(); }; return b; };
    actions.appendChild(btn("maximize", "Fullscreen", () => Focus.open(c)));
    if (isAdmin()) {
      actions.appendChild(btn("edit", "Edit", () => CameraForm.open(c)));
      actions.appendChild(btn("more", "More", (ev) => Live.tileMenu(c, el)));
    }
    el.onclick = () => Focus.open(c);
    el.oncontextmenu = (e) => { e.preventDefault(); Live.tileMenu(c, el, e.clientX, e.clientY); };

    Live.applyStatus(el, c, st);
    return el;
  },

  tileMenu(c, el, x, y) {
    const r = el.getBoundingClientRect();
    const items = [
      { label: "Open fullscreen", icon: "maximize", onClick: () => Focus.open(c) },
    ];
    if (isAdmin()) {
      const paused = c.enabled === false;
      items.push(
        { label: "Edit camera", icon: "edit", onClick: () => CameraForm.open(c) },
        { label: paused ? "Resume" : "Pause", icon: paused ? "play" : "pause", onClick: () => Live.toggleCam(c) },
        { sep: true },
        { label: "Remove camera", icon: "trash", danger: true, onClick: () => Live.removeCam(c) },
      );
    }
    contextMenu(x ?? r.right - 180, y ?? r.top + 40, items);
  },

  applyStatus(el, c, st) {
    const dot = $(".cam__status .dot", el), t = $(".cam__status-t", el);
    const off = $(".cam__offline", el), feed = $(".cam__feed", el);
    el.classList.toggle("is-offline", st === "offline");
    dot.className = "dot " + (st === "online" ? "dot--live" : st === "paused" ? "dot--warn" : "dot--danger");
    t.textContent = st === "online" ? "Live" : st === "paused" ? "Paused" : "Offline";
    if (st === "online") {
      off.classList.add("hidden"); feed.classList.remove("hidden");
      if (!Live.feeds.has(c.id)) Live.feeds.set(c.id, startFeed(feed, c.id));
    } else {
      if (Live.feeds.has(c.id)) { Live.feeds.get(c.id)(); Live.feeds.delete(c.id); }
      feed.classList.add("hidden"); off.classList.remove("hidden");
      $("span", off).textContent = st === "paused" ? "Paused" : "Camera offline";
    }
  },

  syncGrid() {
    const grid = $("#camGrid"); if (!grid) return;
    const ids = state.cameras.map(c => c.id);
    const present = $$(".cam", grid).map(t => t.dataset.id);
    if (ids.length !== present.length || ids.some((id, i) => id !== present[i])) return Live.buildGrid();
    // detection badges: any alert in the last 10s for a camera
    const now = Date.now();
    const recentByCam = {};
    state.recentAlerts.forEach(a => { recentByCam[a.camera] = recentByCam[a.camera] || a; });
    state.cameras.forEach(c => {
      const el = $(`.cam[data-id="${c.id}"]`, grid); if (!el) return;
      const st = state.status[c.id] || (c.enabled === false ? "paused" : "offline");
      Live.applyStatus(el, c, st);
      $(".cam__name", el).textContent = c.label;
    });
    $("#onlineCount").textContent = `${state.cameras.filter(c => state.status[c.id]==="online").length}/${state.cameras.length} online`;
  },

  filter(q) {
    q = q.toLowerCase().trim();
    $$(".cam").forEach(el => {
      const c = state.cameras.find(x => x.id === el.dataset.id) || {};
      const hit = !q || (c.label + " " + (c.location || "")).toLowerCase().includes(q);
      el.classList.toggle("hidden", !hit);
    });
  },

  async toggleCam(c) { await api.editCamera(c.id, { enabled: c.enabled === false }); toast(c.enabled === false ? "Camera resumed" : "Camera paused", { kind: "ok" }); Live.refresh(true); },
  async removeCam(c) {
    if (!await confirmDialog({ title: "Remove camera?", body: `“${c.label}” will be removed from monitoring. Recorded evidence is kept.`, confirmText: "Remove camera", danger: true })) return;
    await api.delCamera(c.id); toast("Camera removed", { kind: "ok" }); Live.refresh(true);
  },
  async togglePauseAll(btn) {
    const anyOn = state.cameras.some(c => c.enabled !== false);
    if (anyOn) { await api.pauseAll(); toast("All cameras paused", { kind: "ok" }); }
    else { await api.resumeAll(); toast("All cameras resumed", { kind: "ok" }); }
    Live.refresh(true);
  },
};

/* Snapshot polling — chained on load so a slow frame never piles up.
   Mirrors the backend's proven snapshot approach (no MJPEG freeze). */
function startFeed(img, id) {
  if (MOCK) { img.src = mockFrame(id); return () => {}; }
  let stopped = false;
  const gap = () => document.hidden ? 1000 : ({ comfortable: 90, cozy: 120, compact: 160, dense: 220 }[state.density] || 130);
  const tick = () => { if (!stopped) img.src = `/snapshot/${id}?t=${Date.now()}`; };
  img.onload = () => { if (!stopped) setTimeout(tick, gap()); };
  img.onerror = () => { if (!stopped) setTimeout(tick, 1500); };
  tick();
  return () => { stopped = true; img.onload = img.onerror = null; };
}
function mockFrame(id) {
  const hue = [200, 160, 220, 20, 280, 340][id.charCodeAt(1) % 6] || 200;
  return `data:image/svg+xml;utf8,` + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="hsl(${hue},18%,14%)"/><circle cx="160" cy="80" r="34" fill="hsl(${hue},20%,20%)"/><rect x="70" y="128" width="180" height="10" rx="5" fill="hsl(${hue},18%,22%)"/></svg>`);
}

/* Fullscreen focus */
const Focus = {
  stop: null,
  open(c) {
    const st = state.status[c.id] || "offline";
    const node = h(`<div class="focus">
      <div class="focus__bar">
        <button class="btn btn--icon" data-close title="Close (Esc)">${icon("minimize")}</button>
        <div><div class="strong">${esc(c.label)}</div>${c.location ? `<div class="muted" style="font-size:var(--fs-sm)">${esc(c.location)}</div>` : ""}</div>
        <span class="badge ${st==="online"?"badge--ok":st==="paused"?"badge--warn":"badge--danger"}"><span class="dot ${st==="online"?"dot--live":""}"></span>${st==="online"?"Live":st==="paused"?"Paused":"Offline"}</span>
        <div class="spacer"></div>
        <span class="cam__ai" style="position:static">${icon("shield")} AI detection on</span>
      </div>
      <div class="focus__stage"><img class="focus__img" alt="${esc(c.label)}"></div></div>`);
    $("#overlays").appendChild(node);
    const img = $(".focus__img", node);
    if (st === "online") Focus.stop = startFeed(img, c.id);
    else img.replaceWith(h(`<div class="empty"><div class="empty__icon">${icon("camoff")}</div><div class="empty__title">${st==="paused"?"Camera paused":"Camera offline"}</div></div>`));
    const close = () => { if (Focus.stop) Focus.stop(); Focus.stop = null; node.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    $("[data-close]", node).onclick = close;
    document.addEventListener("keydown", onKey);
  },
};

/* Add / edit camera */
const CameraForm = {
  open(cam = null) {
    const editing = !!cam;
    const node = h(`<div class="modal" role="dialog" aria-modal="true">
      <div class="modal__head"><div class="modal__title">${editing ? "Edit camera" : "Add camera"}</div><div class="spacer"></div><button class="btn btn--icon btn--ghost" data-x>${icon("x")}</button></div>
      <div class="modal__body">
        <div class="field"><label class="label">Name</label><input class="input" data-f="label" placeholder="e.g. Main Entrance" value="${esc(cam?.label || "")}"></div>
        <div class="field"><label class="label">Location <span class="muted">(optional)</span></label><input class="input" data-f="location" placeholder="e.g. Building A · Lobby" value="${esc(cam?.location || "")}"></div>
        <div class="field"><label class="label">Source</label><input class="input mono" data-f="source" placeholder="rtsp://… , http://…/video , or 0 for this Mac" value="${esc(cam?.source || "")}">
          <span class="hint">RTSP for CCTV, an IP-camera URL, or <b>0</b> for the built-in webcam.</span></div>
      </div>
      <div class="modal__foot"><button class="btn" data-x>Cancel</button><button class="btn btn--primary" data-save>${editing ? "Save changes" : "Add camera"}</button></div></div>`);
    const close = openModal(node);
    $$("[data-x]", node).forEach(b => b.onclick = close);
    $("[data-f='label']", node).focus();
    $("[data-save]", node).onclick = async () => {
      const body = {}; $$("[data-f]", node).forEach(i => body[i.dataset.f] = i.value.trim());
      if (!body.label) { toast("Name is required", { kind: "danger" }); return; }
      if (!body.source) body.source = "0";
      try {
        if (editing) { await api.editCamera(cam.id, body); toast("Camera updated", { kind: "ok" }); }
        else { await api.addCamera(body); toast("Camera added", { kind: "ok" }); }
        close(); Live.refresh(true);
      } catch { toast("Could not save camera", { kind: "danger" }); }
    };
  },
};

/* =========================================================================
   7. EVIDENCE
   ========================================================================= */
const Evidence = {
  all: [],
  async render(root) {
    root.className = "content content--flush";
    root.innerHTML = `<div class="evidence">
      <aside class="evidence__side" id="evSide"></aside>
      <div class="evidence__main"><div class="toolbar">
        <div class="search" style="max-width:320px"><span>${icon("search")}</span><input id="evSearch" placeholder="Search evidence…"></div>
        <div class="spacer"></div>
        <input type="date" class="input" id="evDate" style="width:150px">
        <button class="btn" id="evExport">${icon("download")} Export</button>
      </div><div id="evBody"></div></div></div>`;
    $("#evSearch", root).oninput = debounce(() => Evidence.paint(), 120);
    $("#evDate", root).onchange = (e) => { state.evFilter.date = e.target.value; Evidence.load(); };
    $("#evExport", root).onclick = () => Evidence.export();
    await Evidence.load();
  },
  destroy() {},

  async load() {
    const q = "?status=all" + (state.evFilter.date ? "&date=" + state.evFilter.date : "");
    try { Evidence.all = await api.evidence(q); } catch { Evidence.all = []; }
    Evidence.renderSide(); Evidence.paint();
  },

  renderSide() {
    const counts = { all: Evidence.all.length, pending: 0, confirmed: 0, dismissed: 0 };
    Evidence.all.forEach(a => counts[a.status] !== undefined && counts[a.status]++);
    const cams = [...new Set(Evidence.all.map(a => a.camera))];
    const f = state.evFilter;
    $("#evSide").innerHTML = `
      <div class="filtergroup"><div class="filtergroup__label">Status</div>
        ${[["all","All events"],["pending","Pending review"],["confirmed","Confirmed"],["dismissed","Dismissed"]].map(([k,l]) =>
          `<div class="filter-item ${f.status===k?"is-active":""}" data-status="${k}"><span class="dot ${k==="pending"?"dot--warn":k==="confirmed"?"dot--ok":k==="dismissed"?"":""}"></span>${l}<span class="count">${counts[k]??""}</span></div>`).join("")}
      </div>
      <div class="filtergroup"><div class="filtergroup__label">Camera</div>
        <div class="filter-item ${f.camera==="all"?"is-active":""}" data-cam="all">All cameras<span class="count">${Evidence.all.length}</span></div>
        ${cams.map(c => `<div class="filter-item ${f.camera===c?"is-active":""}" data-cam="${esc(c)}">${esc(c)}<span class="count">${Evidence.all.filter(a=>a.camera===c).length}</span></div>`).join("")}
      </div>`;
    $$("[data-status]").forEach(n => n.onclick = () => { state.evFilter.status = n.dataset.status; Evidence.renderSide(); Evidence.paint(); });
    $$("[data-cam]").forEach(n => n.onclick = () => { state.evFilter.camera = n.dataset.cam; Evidence.renderSide(); Evidence.paint(); });
  },

  paint() {
    const f = state.evFilter, q = ($("#evSearch")?.value || "").toLowerCase();
    let rows = Evidence.all.filter(a =>
      (f.status === "all" || a.status === f.status) &&
      (f.camera === "all" || a.camera === f.camera) &&
      (!q || (a.camera + " " + a.thing + " " + (a.description||"")).toLowerCase().includes(q)));
    const body = $("#evBody");
    if (!rows.length) { body.innerHTML = ""; body.appendChild(Evidence.empty()); return; }
    body.innerHTML = `<div class="ev-grid">${rows.map((a, i) => Evidence.card(a, i)).join("")}</div>`;
    $$(".ev-card", body).forEach(c => c.onclick = () => Evidence.detail(+c.dataset.id));
  },

  card(a, i) {
    const badge = a.status === "pending" ? `<span class="badge badge--warn">Pending</span>`
      : a.status === "confirmed" ? `<span class="badge badge--danger">Confirmed</span>`
      : `<span class="badge">Dismissed</span>`;
    const img = MOCK ? mockFrame("e" + a.id) : (a.image || `/evidence/image/${a.id}`);
    return `<div class="ev-card" data-id="${a.id}" style="animation-delay:${Math.min(i*24,300)}ms">
      <div class="ev-card__thumb"><img loading="lazy" src="${img}" alt=""><div class="ev-card__badge">${badge}</div></div>
      <div class="ev-card__meta">
        <div class="ev-card__title">${esc(a.thing || "Phone")} <span class="muted" style="font-weight:400">· ${Math.round((a.confidence||0)*100)}%</span></div>
        <div class="ev-card__sub">${icon("live")} ${esc(a.camera)}</div>
        <div class="ev-card__sub">${icon("clock")} ${relDate(a.date)} · ${fmtTime(a.time)}</div>
      </div></div>`;
  },

  empty() {
    const f = state.evFilter;
    const filtered = f.status !== "all" || f.camera !== "all" || state.evFilter.date;
    return h(`<div class="empty">
      <div class="empty__icon">${icon("evidence")}</div>
      <div class="empty__title">${filtered ? "No matching evidence" : "No evidence yet"}</div>
      <div class="empty__text">${filtered
        ? "No events match these filters. Try widening the status, camera, or date filters."
        : "Every time the AI detects a phone, a snapshot is saved here with the time, camera, and confidence — ready to review, confirm, or dismiss."}</div>
      ${filtered ? `<button class="btn" style="margin-top:8px" onclick="location.reload()">Clear filters</button>` : ""}</div>`);
  },

  detail(id) {
    const a = Evidence.all.find(x => x.id === id); if (!a) return;
    const img = MOCK ? mockFrame("e" + a.id) : (a.image || `/evidence/image/${a.id}`);
    const canReview = a.status === "pending";
    const node = h(`<div class="drawer" role="dialog" aria-modal="true">
      <div class="drawer__head"><button class="btn btn--icon btn--ghost" data-x>${icon("x")}</button>
        <div class="strong">Evidence #${a.id}</div><div class="spacer"></div>
        <button class="btn btn--icon btn--ghost" title="Bookmark">${icon("star")}</button></div>
      <div class="drawer__body">
        <img class="drawer__img" src="${img}" alt="">
        <div><span class="badge ${a.status==="pending"?"badge--warn":a.status==="confirmed"?"badge--danger":""}">${a.status[0].toUpperCase()+a.status.slice(1)}</span></div>
        <dl class="kv">
          <dt>Detected</dt><dd>${esc(a.thing || "Phone")}</dd>
          <dt>Confidence</dt><dd>${Math.round((a.confidence||0)*100)}%</dd>
          <dt>Camera</dt><dd>${esc(a.camera)}</dd>
          <dt>Time</dt><dd>${relDate(a.date)} · ${fmtTime(a.time)}</dd>
          ${a.reviewed_by ? `<dt>Reviewed by</dt><dd>${esc(a.reviewed_by)}${a.reviewed_at?` · ${esc(a.reviewed_at)}`:""}</dd>` : ""}
        </dl>
        ${a.description ? `<div class="card"><div class="card__body"><div class="stat__label" style="margin-bottom:6px">${icon("cpu")} AI second look</div>${esc(a.description)}</div></div>` : ""}
      </div>
      <div class="drawer__foot">
        ${canReview ? `<button class="btn btn--danger" data-confirm style="flex:1">${icon("alert")} Confirm incident</button>
        <button class="btn" data-dismiss style="flex:1">${icon("x")} Dismiss</button>` :
        `<button class="btn" data-x style="flex:1">Close</button>`}
        <button class="btn btn--icon" title="Download">${icon("download")}</button>
      </div></div>`);
    const close = openModal(node);
    $$("[data-x]", node).forEach(b => b.onclick = close);
    if (canReview) {
      $("[data-confirm]", node).onclick = async () => { await api.reviewAlert(id, "confirm"); toast("Marked as confirmed incident", { kind: "ok" }); close(); Evidence.load(); };
      $("[data-dismiss]", node).onclick = async () => { await api.reviewAlert(id, "dismiss"); toast("Dismissed", { kind: "ok" }); close(); Evidence.load(); };
    }
  },

  export() { toast("Export ready", { msg: "Evidence list prepared for export.", kind: "ok" }); },
};

/* =========================================================================
   8. USERS
   ========================================================================= */
const Users = {
  list: [], sort: { key: "username", dir: 1 },
  async render(root) {
    root.className = "content";
    if (!isAdmin()) { root.innerHTML = `<div class="content__inner">${noAccess()}</div>`; return; }
    root.innerHTML = `<div class="users-wrap">
      <div class="row" style="margin-bottom:var(--s5)">
        <div><h1 style="font-size:var(--fs-xl);font-weight:600">Users</h1><div class="muted">People who can access Vigil and review evidence.</div></div>
        <div class="spacer"></div>
        <div class="search" style="max-width:260px"><span>${icon("search")}</span><input id="uSearch" placeholder="Search people…"></div>
        <button class="btn btn--primary" id="addUser">${icon("plus")} Add user</button>
      </div>
      <div class="card"><table class="table"><thead><tr>
        <th class="sortable" data-k="username">Name</th><th>Role</th><th>Sign-in</th><th class="sortable" data-k="last_login">Last active</th><th></th>
      </tr></thead><tbody id="uBody"></tbody></table></div></div>`;
    $("#addUser").onclick = () => Users.form();
    $("#uSearch").oninput = debounce(() => Users.paint(), 120);
    $$("[data-k]").forEach(th => th.onclick = () => { const k = th.dataset.k; state && (Users.sort = { key: k, dir: Users.sort.key === k ? -Users.sort.dir : 1 }); Users.paint(); });
    try { Users.list = await api.users(); } catch { Users.list = []; }
    Users.paint();
  },
  destroy() {},
  paint() {
    const q = ($("#uSearch")?.value || "").toLowerCase();
    let rows = Users.list.filter(u => !q || (u.username + " " + (u.email||"")).toLowerCase().includes(q));
    const { key, dir } = Users.sort;
    rows.sort((a, b) => String(a[key]||"").localeCompare(String(b[key]||"")) * dir);
    const body = $("#uBody");
    if (!rows.length) { body.innerHTML = `<tr><td colspan="5">${Users.empty()}</td></tr>`; return; }
    body.innerHTML = rows.map(u => `<tr>
      <td><div class="user-cell"><span class="avatar">${initials(u.username)}</span><div><div class="user-name">${esc(u.username.replace(/@.*/,""))}</div>${u.email?`<div class="user-email">${esc(u.email)}</div>`:""}</div></div></td>
      <td><span class="badge ${u.role==="admin"?"badge--accent":""}">${u.role==="admin"?"Admin":"Invigilator"}</span></td>
      <td class="muted">${u.auth==="google"?"Google":"Password"}</td>
      <td class="muted">${esc(u.last_login||"—")}</td>
      <td style="text-align:right"><button class="btn btn--icon btn--ghost btn--sm" data-more="${esc(u.username)}">${icon("more")}</button></td>
    </tr>`).join("");
    $$("[data-more]").forEach(b => b.onclick = (e) => { const u = Users.list.find(x => x.username === b.dataset.more); const r = b.getBoundingClientRect();
      contextMenu(r.right - 180, r.bottom + 4, [
        { label: "Reset password", icon: "lock", onClick: () => toast("Send a reset from Settings → Account") },
        { sep: true },
        { label: "Remove user", icon: "trash", danger: true, onClick: () => Users.remove(u) },
      ]); });
  },
  empty() { return `<div class="empty" style="padding:var(--s10)"><div class="empty__icon">${icon("users")}</div><div class="empty__title">No people found</div></div>`; },
  form() {
    const node = h(`<div class="modal"><div class="modal__head"><div class="modal__title">Add user</div><div class="spacer"></div><button class="btn btn--icon btn--ghost" data-x>${icon("x")}</button></div>
      <div class="modal__body">
        <div class="field"><label class="label">Username or Google email</label><input class="input" data-f="username" placeholder="name or name@gmail.com"></div>
        <div class="field"><label class="label">Password <span class="muted">(leave blank for Google sign-in)</span></label><input class="input" type="password" data-f="password"></div>
        <div class="field"><label class="label">Role</label><select class="select" data-f="role"><option value="invigilator">Invigilator — review only</option><option value="admin">Admin — full access</option></select></div>
      </div><div class="modal__foot"><button class="btn" data-x>Cancel</button><button class="btn btn--primary" data-save>Add user</button></div></div>`);
    const close = openModal(node); $$("[data-x]", node).forEach(b => b.onclick = close);
    $("[data-save]", node).onclick = async () => {
      const f = new FormData(); $$("[data-f]", node).forEach(i => f.append(i.dataset.f, i.value));
      if (!f.get("username").trim()) { toast("Username is required", { kind: "danger" }); return; }
      try { await api.addUser(f); toast("User added", { kind: "ok" }); close(); Users.render($("#view")); } catch { toast("Could not add user", { kind: "danger" }); }
    };
  },
  async remove(u) {
    if (u.username === state.me.username) { toast("You can't remove yourself", { kind: "danger" }); return; }
    if (!await confirmDialog({ title: "Remove user?", body: `${u.username} will lose access to Vigil.`, confirmText: "Remove user", danger: true })) return;
    await api.delUser(u.username); toast("User removed", { kind: "ok" }); Users.render($("#view"));
  },
};

/* =========================================================================
   9. SETTINGS
   ========================================================================= */
const Settings = {
  data: {}, section: "general",
  groups: [
    ["general", "General", "info"], ["appearance", "Appearance", "sun"],
    ["ai", "AI Models", "cpu"], ["notifications", "Notifications", "bell"],
    ["cameras", "Cameras", "live"], ["storage", "Storage", "db"],
    ["privacy", "Privacy", "lock"], ["account", "Account", "users"],
  ],
  async render(root) {
    root.className = "content content--flush";
    if (!isAdmin()) { root.innerHTML = `<div class="content__inner">${noAccess()}</div>`; return; }
    try { Settings.data = await api.settings(); } catch { Settings.data = {}; }
    root.innerHTML = `<div class="settings">
      <nav class="settings__nav" id="setNav">${Settings.groups.map(([k,l,ic]) =>
        `<div class="nav__item ${Settings.section===k?"is-active":""}" data-s="${k}">${icon(ic)} ${l}</div>`).join("")}</nav>
      <div class="settings__main"><div class="settings__inner" id="setBody"></div></div></div>`;
    $$("[data-s]").forEach(n => n.onclick = () => { Settings.section = n.dataset.s; $$("[data-s]").forEach(x => x.classList.toggle("is-active", x === n)); Settings.paint(); });
    Settings.paint();
  },
  destroy() {},
  row(name, desc, control) {
    return `<div class="setting"><div class="setting__info"><div class="setting__name">${name}</div><div class="setting__desc">${desc}</div></div><div class="setting__control">${control}</div></div>`;
  },
  paint() {
    const d = Settings.data, body = $("#setBody");
    const sel = (id, opts, val) => `<select class="select" data-k="${id}">${opts.map(o => `<option value="${o[0]}" ${String(val)===String(o[0])?"selected":""}>${o[1]}</option>`).join("")}</select>`;
    const num = (id, val, step="1") => `<input class="input" type="number" step="${step}" data-k="${id}" value="${val??""}">`;
    const tog = (id, on) => `<label class="toggle"><input type="checkbox" data-k="${id}" ${on?"checked":""}><span class="toggle__track"></span></label>`;
    let html = "";
    if (Settings.section === "general") html = `<div class="settings__group"><h2>General</h2><p>Core monitoring behaviour.</p>
      ${Settings.row("What to watch for", "The object the AI flags across every camera.", sel("WATCH_TARGET", [["phone","Phone"],["person","Person"],["laptop","Laptop"]], d.WATCH_TARGET))}
      ${Settings.row("Alert cooldown", "Seconds to wait before the same camera can alert again.", num("ALERT_COOLDOWN", d.ALERT_COOLDOWN))}
      ${Settings.row("Confirmations before alert", "Consecutive detections required — higher means fewer false alarms.", num("REQUIRED_HITS", d.REQUIRED_HITS))}</div>`;
    else if (Settings.section === "appearance") html = `<div class="settings__group"><h2>Appearance</h2><p>How Vigil looks on this device.</p>
      ${Settings.row("Theme", "Dark is easiest on the eyes for long monitoring shifts.", `<div class="segmented" id="themePick">
        <button data-t="dark" class="${state.theme==="dark"?"is-active":""}">Dark</button><button data-t="light" class="${state.theme==="light"?"is-active":""}">Light</button></div>`)}
      ${Settings.row("Default grid density", "How many cameras fill the Live Footage wall by default.", sel("_density", [["comfortable","Large"],["cozy","Medium"],["compact","Small"],["dense","Wall"]], state.density))}</div>`;
    else if (Settings.section === "ai") html = `<div class="settings__group"><h2>AI Models</h2><p>The detection engine. Defaults are tuned — change only if you know the trade-offs.</p>
      ${Settings.row("Detection model", "Larger models are more accurate but need more power.", sel("MODEL_NAME", [["yolo11n.pt","Fast (nano)"],["yolo11m.pt","Balanced (medium)"],["yolo11x.pt","Accurate (xlarge)"]], d.MODEL_NAME))}
      ${Settings.row("Confidence threshold", "How sure the AI must be. 0.5 is a good balance.", num("CONFIDENCE", d.CONFIDENCE, "0.05"))}
      ${Settings.row("Image size", "Higher catches smaller/farther phones, slightly slower.", num("IMG_SIZE", d.IMG_SIZE, "32"))}
      ${Settings.row("AI second look", "A vision model re-checks each detection to filter false alarms.", tog("VLM_ENABLED", d.VLM_ENABLED))}</div>`;
    else if (Settings.section === "notifications") html = `<div class="settings__group"><h2>Notifications</h2><p>Where alerts are sent, beyond the dashboard.</p>
      ${Settings.row("Telegram bot token", "Optional — send alerts to a Telegram chat.", `<input class="input mono" data-k="TELEGRAM_TOKEN" value="${esc(d.TELEGRAM_TOKEN||"")}" placeholder="Not set">`)}
      ${Settings.row("Telegram chat IDs", "Comma-separated chat IDs to notify.", `<input class="input mono" data-k="TELEGRAM_CHAT_IDS" value="${esc(d.TELEGRAM_CHAT_IDS||"")}" placeholder="Not set">`)}</div>`;
    else if (Settings.section === "cameras") html = `<div class="settings__group"><h2>Cameras</h2><p>Defaults applied to camera feeds.</p>
      ${Settings.row("Manage cameras", "Add, edit, and arrange cameras from Live Footage.", `<a class="btn" href="#/live">Go to Live Footage</a>`)}</div>`;
    else if (Settings.section === "storage") html = `<div class="settings__group"><h2>Storage</h2><p>Where evidence lives on this machine.</p>
      ${Settings.row("Evidence location", "Snapshots and the database are stored locally on this device.", `<span class="badge">Local disk</span>`)}
      ${Settings.row("Clear dismissed evidence", "Permanently delete events you've dismissed.", `<button class="btn btn--danger">Clear…</button>`)}</div>`;
    else if (Settings.section === "privacy") html = `<div class="settings__group"><h2>Privacy</h2><p>Vigil runs entirely on this device.</p>
      ${Settings.row("On-device processing", "Video never leaves this machine. No cloud, no third parties.", `<span class="badge badge--ok">${icon("check")} On-device</span>`)}
      ${Settings.row("Audit trail", "Every confirm/dismiss records who decided and when.", `<span class="badge badge--ok">Enabled</span>`)}</div>`;
    else if (Settings.section === "account") html = `<div class="settings__group"><h2>Account</h2><p>Your Vigil sign-in.</p>
      ${Settings.row("Signed in as", "", `<span class="strong">${esc(state.me.username)}</span>`)}
      ${Settings.row("Sign out", "End this session on this device.", `<a class="btn" href="/logout">${icon("logout")} Sign out</a>`)}</div>`;

    body.innerHTML = html + (["general","ai","notifications"].includes(Settings.section)
      ? `<div class="row" style="justify-content:flex-end;gap:var(--s2)"><button class="btn btn--primary" id="setSave">Save changes</button></div>` : "");

    // wire live controls
    const tp = $("#themePick"); if (tp) tp.onclick = (e) => { const b = e.target.closest("[data-t]"); if (!b) return; setTheme(b.dataset.t); $$("#themePick button").forEach(x => x.classList.toggle("is-active", x === b)); };
    const dp = $("[data-k='_density']"); if (dp) dp.onchange = () => { state.density = dp.value; localStorage.setItem("vigil.density", state.density); toast("Default density updated", { kind: "ok" }); };
    const save = $("#setSave"); if (save) save.onclick = () => Settings.save();
  },
  async save() {
    const form = new FormData();
    // start from current so we don't blank other fields the backend expects
    Object.entries(Settings.data).forEach(([k, v]) => form.append(k, typeof v === "boolean" ? (v ? "on" : "") : v));
    $$("[data-k]").forEach(el => { const k = el.dataset.k; if (k.startsWith("_")) return;
      let v = el.type === "checkbox" ? (el.checked ? "on" : "") : el.value;
      form.set(k, v); });
    try { await api.saveSettings(form); toast("Settings saved", { kind: "ok" }); }
    catch { toast("Could not save settings", { kind: "danger" }); }
  },
};

function noAccess() {
  return `<div class="empty"><div class="empty__icon">${icon("lock")}</div><div class="empty__title">Admins only</div>
    <div class="empty__text">This section is limited to administrators. Ask an admin if you need access.</div></div>`;
}

/* =========================================================================
   10. SHELL + ROUTER
   ========================================================================= */
const ROUTES = {
  live:     { title: "Live Footage", sub: "Real-time monitoring", view: Live, section: "monitor" },
  evidence: { title: "Evidence",     sub: "Detected events",       view: Evidence, section: "monitor" },
  users:    { title: "Users",        sub: "Access & roles",        view: Users, section: "manage" },
  settings: { title: "Settings",     sub: "Configuration",         view: Settings, section: "manage" },
};
let current = null;

function shell() {
  const nav = (id, ic, label, badge) => `<div class="nav__item ${state.route===id?"is-active":""}" data-route="${id}">${icon(ic)}<span>${label}</span>${badge?`<span class="nav__badge" id="navBadge">${badge}</span>`:""}</div>`;
  $("#app").innerHTML = `
    <aside class="nav">
      <div class="nav__brand">${LOGO}<span class="nav__brand-name">Vigil</span></div>
      <div class="nav__section">Monitor</div>
      ${nav("live","live","Live Footage")}
      ${nav("evidence","evidence","Evidence", state.stats.pending || "")}
      <div class="nav__section">Manage</div>
      ${nav("users","users","Users")}
      ${nav("settings","settings","Settings")}
      <div class="nav__spacer"></div>
      <div class="nav__user" id="navUser">
        <span class="avatar">${initials(state.me.username)}</span>
        <div class="nav__user-meta"><div class="nav__user-name">${esc(state.me.username||"—")}</div><div class="nav__user-role">${state.me.role==="admin"?"Administrator":"Invigilator"}</div></div>
      </div>
    </aside>
    <header class="topbar">
      <div><div class="topbar__title" id="tbTitle"></div></div>
      <div class="topbar__spacer"></div>
      <button class="btn btn--icon btn--ghost btn--sm" id="themeBtn" title="Toggle theme">${icon(state.theme==="dark"?"sun":"moon")}</button>
      <span class="topbar__clock tnum" id="clock"></span>
    </header>
    <main class="content" id="view"></main>`;
  $$("[data-route]").forEach(n => n.onclick = () => go(n.dataset.route));
  $("#navUser").onclick = (e) => { const r = e.currentTarget.getBoundingClientRect();
    contextMenu(r.left, r.top - 8, [
      { label: state.me.username, header: true },
      { label: "Settings", icon: "settings", onClick: () => go("settings") },
      { sep: true },
      { label: "Sign out", icon: "logout", onClick: () => location.href = "/logout" },
    ]); };
  $("#themeBtn").onclick = () => { setTheme(state.theme === "dark" ? "light" : "dark"); $("#themeBtn").innerHTML = icon(state.theme==="dark"?"sun":"moon"); };
  startClock();
}

function go(route) { location.hash = "#/" + route; }

async function mount() {
  const route = (location.hash.replace(/^#\/?/, "") || "live").split("?")[0];
  state.route = ROUTES[route] ? route : "live";
  // tear down anything transient left over from the previous view
  $$(".menu").forEach(m => m.remove());
  $("#overlays").innerHTML = "";
  if (current && current.destroy) current.destroy();
  // update nav active + title without full reflow of feeds
  $$("[data-route]").forEach(n => n.classList.toggle("is-active", n.dataset.route === state.route));
  const r = ROUTES[state.route];
  $("#tbTitle") && ($("#tbTitle").textContent = r.title);
  const view = $("#view");
  view.innerHTML = "";
  current = r.view;
  await r.view.render(view);
}

function setTheme(t) { state.theme = t; document.documentElement.dataset.theme = t; localStorage.setItem("vigil.theme", t); }

function startClock() {
  const tick = () => { const c = $("#clock"); if (c) c.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); };
  tick(); clearInterval(window.__clk); window.__clk = setInterval(tick, 1000);
}

/* Global keyboard shortcuts */
function shortcuts(e) {
  if (e.target.matches("input, textarea, select")) { if (e.key === "Escape") e.target.blur(); return; }
  const map = { "1": "live", "2": "evidence", "3": "users", "4": "settings" };
  if (map[e.key]) { go(map[e.key]); return; }
  if (e.key === "/" ) { const s = $("#camSearch, #evSearch, #uSearch"); if (s) { e.preventDefault(); s.focus(); } }
  if ((e.key === "n" || e.key === "N") && state.route === "live" && isAdmin()) CameraForm.open();
}

/* =========================================================================
   11. BOOT
   ========================================================================= */
async function boot() {
  setTheme(state.theme);
  try { state.me = await api.me(); } catch { /* redirected to /login by api._get */ return; }
  try { state.stats = await api.stats(); } catch {}
  shell();
  addEventListener("hashchange", mount);
  document.addEventListener("keydown", shortcuts);
  await mount();
}
boot();
})();
