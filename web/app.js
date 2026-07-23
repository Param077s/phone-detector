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
  phone:    'M7 2h10a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM11 18h2',
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
  sidebar:  'M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM9.5 4v16',
};
const icon = (name, cls = "") =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"${cls?` class="${cls}"`:""}>${
    P[name].split("M").filter(Boolean).map(d => `<path d="M${d}"/>`).join("")
  }</svg>`;

const LOGO = `<svg viewBox="0 0 24 24" fill="none"><rect width="24" height="24" rx="7" fill="var(--surface-3)"/><path d="M6 10V7.5A1.5 1.5 0 0 1 7.5 6H10M14 6h2.5A1.5 1.5 0 0 1 18 7.5V10M18 14v2.5a1.5 1.5 0 0 1-1.5 1.5H14M10 18H7.5A1.5 1.5 0 0 1 6 16.5V14" stroke="var(--text-3)" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="12" r="2.6" fill="var(--accent)"/></svg>`;

/* Empty-state illustrations — small drawn scenes, never a bare rectangle. */
const ILLO = {
  cameras: `<svg class="empty__art" viewBox="0 0 132 96" fill="none">
    <defs><radialGradient id="ilc-g" cx="50%" cy="40%" r="60%">
      <stop offset="0%" stop-color="var(--accent)" stop-opacity=".16"/>
      <stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/></radialGradient></defs>
    <ellipse cx="66" cy="50" rx="62" ry="40" fill="url(#ilc-g)"/>
    <rect x="34" y="28" width="52" height="36" rx="9" fill="var(--surface-2)" stroke="var(--border-strong)"/>
    <circle cx="60" cy="46" r="11" fill="var(--surface-inset)" stroke="var(--border-strong)"/>
    <circle cx="60" cy="46" r="4.5" fill="var(--accent)"/>
    <circle cx="78" cy="37" r="2.2" fill="var(--danger)" opacity=".8"/>
    <path d="M92 40c6 2 6 10 0 12M99 36c10 4 10 16 0 20" stroke="var(--accent)" stroke-opacity=".5" stroke-width="2" stroke-linecap="round"/>
    <rect x="46" y="68" width="28" height="4" rx="2" fill="var(--surface-3)"/>
  </svg>`,
  clear: `<svg class="empty__art" viewBox="0 0 132 96" fill="none">
    <defs><radialGradient id="ilk-g" cx="50%" cy="40%" r="60%">
      <stop offset="0%" stop-color="var(--accent)" stop-opacity=".14"/>
      <stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/></radialGradient></defs>
    <ellipse cx="66" cy="50" rx="62" ry="40" fill="url(#ilk-g)"/>
    <path d="M66 22l26 10v16c0 15-11 24-26 28-15-4-26-13-26-28V32l26-10z" fill="var(--surface-2)" stroke="var(--border-strong)"/>
    <path d="M55 48l8 8 15-16" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`,
  search: `<svg class="empty__art" viewBox="0 0 132 96" fill="none">
    <defs><radialGradient id="ils-g" cx="50%" cy="40%" r="60%">
      <stop offset="0%" stop-color="var(--info)" stop-opacity=".12"/>
      <stop offset="100%" stop-color="var(--info)" stop-opacity="0"/></radialGradient></defs>
    <ellipse cx="66" cy="50" rx="62" ry="40" fill="url(#ils-g)"/>
    <rect x="30" y="30" width="30" height="20" rx="5" fill="var(--surface-2)" stroke="var(--border-strong)"/>
    <rect x="66" y="30" width="30" height="20" rx="5" fill="var(--surface-2)" stroke="var(--border-strong)" opacity=".55"/>
    <rect x="48" y="56" width="30" height="20" rx="5" fill="var(--surface-2)" stroke="var(--border-strong)" opacity=".35"/>
    <circle cx="88" cy="60" r="12" fill="var(--surface)" stroke="var(--text-3)" stroke-width="2.4"/>
    <path d="M97 69l8 8" stroke="var(--text-3)" stroke-width="2.4" stroke-linecap="round"/>
  </svg>`,
};

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

/* Human-readable camera source type. */
function sourceLabel(s) {
  s = String(s || "").trim();
  if (s === "0" || s === "") return "Built-in webcam";
  if (s === "browser") return "Phone / browser camera";
  if (/^rtsp/i.test(s)) return "CCTV (RTSP)";
  if (/^https?:/i.test(s)) return "IP camera";
  return "Custom source";
}

/* Detection schedule helpers. A camera's schedule is {start,end,days} (days is
   0=Mon..6=Sun, empty = every day) or absent (always on). */
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function schedule(c) {
  const s = c && c.schedule;
  if (!s || !s.start || !s.end) return null;
  return { start: s.start, end: s.end, days: Array.isArray(s.days) ? s.days : [] };
}
/* Short chip text, e.g. "10:00–13:00" or "10:00–13:00 · Mon–Fri". */
function scheduleLabel(c, withDays = true) {
  const s = schedule(c);
  if (!s) return "";
  let span = `${s.start}–${s.end}`;
  if (!withDays || !s.days.length || s.days.length === 7) return span;
  const d = [...s.days].sort((a, b) => a - b);
  const contiguous = d.every((v, i) => i === 0 || v === d[i - 1] + 1);
  const days = contiguous && d.length > 2 ? `${WEEKDAYS[d[0]]}–${WEEKDAYS[d[d.length - 1]]}`
                                          : d.map(i => WEEKDAYS[i]).join(", ");
  return `${span} · ${days}`;
}

/* Loading skeletons — shown immediately, replaced when data arrives. */
const skel = {
  tiles: (n = 6) => Array.from({ length: n }, () => `<div class="cam skeleton" style="aspect-ratio:16/9;border:none"></div>`).join(""),
  evCards: (n = 8) => `<div class="ev-grid">${Array.from({ length: n }, () => `<div class="ev-card" style="pointer-events:none"><div class="ev-card__thumb skeleton"></div><div class="ev-card__meta"><div class="skeleton" style="height:14px;width:60%;border-radius:6px"></div><div class="skeleton" style="height:11px;width:40%;margin-top:8px;border-radius:6px"></div></div></div>`).join("")}</div>`,
  rows: (n = 6) => Array.from({ length: n }, () => `<tr><td colspan="5" style="padding:10px var(--s4)"><div class="skeleton" style="height:34px;border-radius:8px"></div></td></tr>`).join(""),
};

/* -------------------------------------------------------------------------
   3. Toasts / confirm / menu
   ------------------------------------------------------------------------- */
function toast(title, { msg = "", kind = "info", timeout = 3600, onClick = null } = {}) {
  const iconName = kind === "ok" ? "check" : kind === "danger" ? "alert" : "info";
  const color = kind === "ok" ? "var(--ok)" : kind === "danger" ? "var(--danger)" : "var(--info)";
  const el = h(`<div class="toast"${onClick ? ' style="cursor:pointer"' : ""}><span class="toast__icon" style="color:${color}">${icon(iconName)}</span>
    <div class="toast__body"><div class="toast__title">${esc(title)}</div>${msg ? `<div class="toast__msg">${esc(msg)}</div>` : ""}</div></div>`);
  $("#toasts").appendChild(el);
  const kill = () => { el.classList.add("is-leaving"); setTimeout(() => el.remove(), 200); };
  el.addEventListener("click", () => { if (onClick) onClick(); kill(); });
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

/* Keep Tab focus inside an overlay; returns a detach fn. */
const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
function trapFocus(container) {
  const onKey = (e) => {
    if (e.key !== "Tab") return;
    const items = [...container.querySelectorAll(FOCUSABLE)].filter(el => el.offsetParent !== null && !el.disabled);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  container.addEventListener("keydown", onKey);
  return () => container.removeEventListener("keydown", onKey);
}

function openModal(node) {
  const prevFocus = document.activeElement;
  const scrim = h(`<div class="scrim"></div>`);
  scrim.appendChild(node);
  const untrap = trapFocus(scrim);
  const close = () => { untrap(); scrim.remove(); document.removeEventListener("keydown", onKey); if (prevFocus && prevFocus.focus) try { prevFocus.focus(); } catch {} };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  scrim.addEventListener("click", (e) => { if (e.target === scrim) close(); });
  document.addEventListener("keydown", onKey);
  $("#overlays").appendChild(scrim);
  // focus the first sensible control
  setTimeout(() => { const f = scrim.querySelector("input, textarea, button.btn--primary, [data-save], button"); if (f) try { f.focus(); } catch {} }, 0);
  return close;
}

function contextMenu(x, y, items) {
  $$(".menu").forEach(m => m.remove());
  items.forEach((it, i) => it._i = i);
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
  $$("[data-i]", menu).forEach(n => { const it = items[+n.dataset.i]; if (it && it.onClick) n.onclick = () => { close(); it.onClick(); }; });
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
  updateCheck:  () => MOCK
    ? Promise.resolve({ current: "1.2.0", latest: "1.3.0", url: "https://github.com/Param077s/vigil/releases/latest", update_available: true, can_self_update: true })
    : api._get("/api/update-check"),
  lanInfo:      () => MOCK
    ? Promise.resolve({ ip: "192.168.1.42", port: 8000, url: "http://192.168.1.42:8000/app/", qr: "", on_lan: true })
    : api._get("/api/lan-info"),
  updateState:  () => api._get("/api/update/state"),
  updateStart:  () => fetch("/api/update/start", { method: "POST" }).then(r => r.json()),
  updateApply:  (relaunch) => fetch("/api/update/apply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ relaunch }) }).then(r => r.json()),

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
  me: { username: "diljot", role: "admin", version: "1.1.1" },
  stats: { cameras: 6, alerts_today: 4, pending: 2 },
  cameras: [
    { id: "a1", label: "Main Entrance", location: "Building A · Lobby", source: "rtsp://…", enabled: true },
    { id: "a2", label: "Exam Hall 1", location: "Building A · Floor 2", source: "rtsp://…", enabled: true, schedule: { start: "10:00", end: "13:00", days: [0,1,2,3,4] } },
    { id: "a3", label: "Exam Hall 2", location: "Building A · Floor 2", source: "rtsp://…", enabled: true, schedule: { start: "14:00", end: "16:30", days: [] } },
    { id: "a4", label: "Corridor West", location: "Building B", source: "0", enabled: true },
    { id: "a5", label: "Library", location: "Building C · Ground", source: "rtsp://…", enabled: false },
    { id: "a6", label: "Parking Deck", location: "Exterior", source: "rtsp://…", enabled: true },
  ],
  status: { a1: "online", a2: "online", a3: "scheduled", a4: "offline", a5: "paused", a6: "online" },
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
  settings: { WATCH_TARGET: "phone", MODEL_NAME: "yolo11m.pt", CONFIDENCE: 0.5, REQUIRED_HITS: 3, ALERT_COOLDOWN: 3, IMG_SIZE: 960, VLM_ENABLED: true, VLM_MODEL: "moondream", VLM_VERIFY: true },
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
  theme: localStorage.getItem("vigil.theme") || "dark",   // "auto" | "dark" | "light"
  navW: Math.min(320, Math.max(200, +localStorage.getItem("vigil.navW") || 248)),
  // Collapsed = icon rail (a dock, not a disappearance). Old "hidden" pref
  // from earlier builds migrates to the rail.
  navRail: (localStorage.getItem("vigil.navRail") ?? localStorage.getItem("vigil.navHidden")) === "1",
  evFilter: { status: "all", camera: "all", date: "", range: "all", bookmarked: false },
  seenAlerts: new Set(),          // alert ids we've already notified about
  alertsSeeded: false,            // don't toast the backlog on first load
  notifications: [],              // recent detections for the bell
  snoozeUntil: 0,                 // epoch ms; suppress toasts until then
  bookmarks: new Set(JSON.parse(localStorage.getItem("vigil.bookmarks") || "[]")),
};
function saveBookmarks() { localStorage.setItem("vigil.bookmarks", JSON.stringify([...state.bookmarks])); }
function toggleBookmark(id) { if (state.bookmarks.has(id)) state.bookmarks.delete(id); else state.bookmarks.add(id); saveBookmarks(); }
function openExternal(url) {
  const papi = window.pywebview && window.pywebview.api;   // desktop: real browser
  if (papi && typeof papi.open_external === "function") papi.open_external(url);
  else window.open(url, "_blank", "noopener");
}

/* -------------------------------------------------------------------------
   Recovery states — every failure gets a calm explanation + a next step.
   ------------------------------------------------------------------------- */
const RECOVER = {
  network:   { tone: "alert", icon: "wifioff", title: "Can't reach Vigil's engine",
    text: "The app lost its connection to the detection service. This usually clears in a moment." },
  offline:   { tone: "warn", icon: "camoff", title: "All cameras are offline",
    text: "Vigil can't reach any camera feed right now. Check the cameras are powered on and on the same network." },
  model:     { tone: "warn", icon: "cpu", title: "AI model not ready",
    text: "The detection model is missing or still preparing. Vigil keeps retrying automatically — this can take a minute on first run." },
  storage:   { tone: "alert", icon: "db", title: "Storage is full",
    text: "There's no room left to save new evidence. Free up disk space, or clear events you've already dismissed." },
  permission:{ tone: "warn", icon: "lock", title: "Camera access is blocked",
    text: "Your system is blocking camera access. Grant it in System Settings → Privacy & Security → Camera, then reopen Vigil." },
  corrupted: { tone: "alert", icon: "alert", title: "This file can't be opened",
    text: "The snapshot is unreadable — it may be corrupted or was removed from disk." },
};
/* Build a recovery panel. actions: [{label, primary?, onClick}] */
function recoverNode(kind, actions = []) {
  const r = RECOVER[kind] || RECOVER.network;
  const el = h(`<div class="empty empty--${r.tone}" role="alert" style="grid-column:1/-1">
    <div class="empty__icon">${icon(r.icon)}</div>
    <div class="empty__title">${esc(r.title)}</div>
    <div class="empty__text">${esc(r.text)}</div>
    ${actions.length ? `<div class="empty__actions">${actions.map((a, i) =>
      `<button class="btn ${a.primary ? "btn--primary" : ""}" data-a="${i}">${a.icon ? icon(a.icon) : ""}${esc(a.label)}</button>`).join("")}</div>` : ""}
  </div>`);
  actions.forEach((a, i) => { const b = $(`[data-a="${i}"]`, el); if (b && a.onClick) b.onclick = a.onClick; });
  return el;
}
function alertEpoch(a) {           // best-effort timestamp from date + "HH:MM:SS"
  const t = Date.parse(`${a.date}T${(a.time || "00:00:00")}`);
  return isNaN(t) ? 0 : t;
}
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
        ${isAdmin() ? `<button class="btn" id="selectCams">${icon("check")} Select</button>
        <button class="btn" id="pauseAll">${icon("pause")} Pause all</button>
        <button class="btn btn--primary" id="addCam">${icon("plus")} Add camera</button>` : ""}
      </div>
      <div class="live">
        <div class="ribbon" id="stats"></div>
        <div class="grid-cams" id="camGrid" data-density="${state.density}">${skel.tiles(6)}</div>
      </div>
      <div class="selbar hidden" id="selBar">
        <span class="selbar__count" id="selCount">0 selected</span>
        <div class="spacer"></div>
        <button class="btn btn--sm" id="selAll">Select all</button>
        <button class="btn btn--sm" id="selPause">${icon("pause")} Pause</button>
        <button class="btn btn--sm" id="selClearSched">${icon("clock")} Clear hours</button>
        <button class="btn btn--sm btn--primary" id="selSetSched">${icon("clock")} Set detection hours</button>
        <button class="btn btn--sm btn--ghost" id="selDone">Done</button>
      </div>`;

    $("#density", root).onclick = (e) => { const b = e.target.closest("[data-d]"); if (!b) return;
      state.density = b.dataset.d; localStorage.setItem("vigil.density", state.density);
      $$("#density button").forEach(x => x.classList.toggle("is-active", x === b));
      $("#camGrid").dataset.density = state.density; };
    $("#camSearch", root).oninput = debounce((e) => Live.filter(e.target.value), 120);
    if (isAdmin()) {
      $("#addCam", root).onclick = () => CameraForm.open();
      $("#pauseAll", root).onclick = () => Live.togglePauseAll($("#pauseAll", root));
      $("#selectCams", root).onclick = () => Live.selecting ? Live.exitSelect() : Live.enterSelect();
      $("#selDone", root).onclick = () => Live.exitSelect();
      $("#selAll", root).onclick = () => Live.selectAll();
      $("#selPause", root).onclick = () => Live.bulkPause();
      $("#selSetSched", root).onclick = () => Live.bulkSchedule();
      $("#selClearSched", root).onclick = () => Live.bulkClearSchedule();
    }
    Live.sel = new Set();           // ids selected while in select mode
    Live.selecting = false;

    await Live.refresh(true);
    Live.pollTimer = setInterval(() => Live.refresh(false), 3000);
  },

  destroy() { clearInterval(Live.pollTimer); Live.feeds.forEach(stop => stop()); Live.feeds.clear();
    Live.selecting = false; Live.sel && Live.sel.clear(); document.body.classList.remove("is-selecting"); },

  async refresh(first) {
    let cams, status;
    // Stats + detections come from the app-wide Notify poller, so Live only
    // needs the fast-changing camera list and per-camera status here.
    try { [cams, status] = await Promise.all([api.cameras(), api.cameraStatus()]); Live._netFail = 0; }
    catch {
      Live._netFail = (Live._netFail || 0) + 1;
      // Only take over the grid if we have nothing good to show — a transient
      // blip while cameras are already on screen shouldn't wipe the wall.
      if ((first || !state.cameras.length) && $("#camGrid")) {
        const g = $("#camGrid"); g.innerHTML = "";
        g.appendChild(recoverNode("network", [{ label: "Retry", primary: true, icon: "wifi", onClick: () => Live.refresh(true) }]));
      }
      return;
    }
    state.cameras = cams; state.status = status;
    Live.renderStats();
    if (first) Live.buildGrid();
    Live.syncGrid();
  },

  renderStats() {
    const online = state.cameras.filter(c => state.status[c.id] === "online").length;
    const total = state.cameras.length;
    const s = state.stats;
    // Keep the pause-all button honest: it toggles, so its label must too.
    const pa = $("#pauseAll");
    if (pa) {
      const anyOn = state.cameras.some(c => c.enabled !== false);
      pa.innerHTML = `${icon(anyOn ? "pause" : "play")} ${anyOn ? "Pause all" : "Resume all"}`;
    }
    // One quiet status line — the cameras are the page, numbers just support.
    $("#stats").innerHTML = `
      <span class="ribbon__item"><span class="dot ${online ? "dot--live" : total ? "dot--danger" : ""}"></span>
        <span id="onlineCount"><strong>${online}</strong>&nbsp;of ${total} live</span></span>
      <span class="ribbon__sep"></span>
      <span class="ribbon__item">${icon("alert")} <strong>${s.alerts_today ?? 0}</strong>&nbsp;detections today</span>
      <span class="ribbon__sep"></span>
      <span class="ribbon__item ${s.pending ? "is-attention" : ""}">${icon("clock")} <strong>${s.pending ?? 0}</strong>&nbsp;awaiting review</span>
      <span class="ribbon__sep"></span>
      <span class="ribbon__item">${icon("shield")} AI watching</span>`;
  },

  buildGrid() {
    const grid = $("#camGrid");
    Live.feeds.forEach(stop => stop()); Live.feeds.clear();
    if (!state.cameras.length) { grid.innerHTML = ""; grid.appendChild(Live.empty()); return; }
    grid.innerHTML = "";
    state.cameras.forEach((c, i) => grid.appendChild(Live.tile(c, i)));
    if (isAdmin()) Live.enableDrag(grid);
    Live.syncBadges();
  },

  enableDrag(grid) {
    grid.ondragover = (e) => {
      if (!Live._drag) return;
      e.preventDefault();
      const after = Live.afterEl(grid, e.clientX, e.clientY);
      if (after == null) grid.appendChild(Live._drag);
      else if (after !== Live._drag) grid.insertBefore(Live._drag, after);
    };
  },
  afterEl(grid, x, y) {
    const els = $$(".cam:not(.dragging)", grid).filter(el => !el.classList.contains("hidden"));
    let best = null, bestD = Infinity;
    for (const el of els) {
      const b = el.getBoundingClientRect();
      const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
      const after = cy > y + 1 || (Math.abs(cy - y) < b.height / 2 && cx > x);
      if (!after) continue;
      const d = Math.hypot(cx - x, cy - y);
      if (d < bestD) { bestD = d; best = el; }
    }
    return best;
  },
  persistOrder() {
    const grid = $("#camGrid"); if (!grid) return;
    const order = $$(".cam", grid).map(t => t.dataset.id);
    state.cameras.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    api.reorder(order).catch(() => {});
  },

  syncBadges() {
    const grid = $("#camGrid"); if (!grid) return;
    const now = Date.now(), recent = {};
    state.recentAlerts.forEach(a => {
      if (a.status === "dismissed") return;
      if (now - alertEpoch(a) > 20000) return;         // only the last ~20s counts as "live"
      if (!recent[a.camera] || alertEpoch(a) > alertEpoch(recent[a.camera])) recent[a.camera] = a;
    });
    state.cameras.forEach(c => {
      const el = $(`.cam[data-id="${c.id}"]`, grid); if (!el) return;
      const a = recent[c.label];                        // alerts are keyed by camera label
      let det = $(".cam__det", el);
      if (a && !el.classList.contains("is-offline")) {
        el.classList.add("is-alerting");
        if (!det) el.appendChild(h(`<div class="cam__det">${icon("alert")} Phone ${Math.round((a.confidence || 0) * 100)}%</div>`));
      } else {
        el.classList.remove("is-alerting");
        if (det) det.remove();
      }
    });
  },

  empty() {
    const admin = isAdmin();
    const e = h(`<div class="empty" style="grid-column:1/-1">
      ${ILLO.cameras}
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
      <div class="cam__check" aria-hidden="true">${icon("check")}</div>
      <div class="cam__top">
        <span class="cam__status"><span class="dot"></span><span class="cam__status-t"></span></span>
        <span class="cam__sched hidden" title="Only detects during set hours">${icon("clock")}<span class="cam__sched-t"></span></span>
        <span class="cam__ai">${icon("shield")} AI</span>
      </div>
      <div class="cam__actions"></div>
      <div class="cam__bottom">
        <div style="min-width:0"><div class="cam__name">${esc(c.label)}</div>${c.location ? `<div class="cam__loc">${esc(c.location)}</div>` : ""}</div>
      </div></div>`);

    // actions
    const actions = $(".cam__actions", el);
    const btn = (ic, title, fn) => { const b = h(`<button class="cam__btn" title="${title}" aria-label="${title} — ${esc(c.label)}">${icon(ic)}</button>`); b.onclick = (e) => { e.stopPropagation(); fn(); }; return b; };
    actions.appendChild(btn("maximize", "Fullscreen", () => Focus.open(c)));
    if (isAdmin()) {
      actions.appendChild(btn("edit", "Edit", () => CameraForm.open(c)));
      actions.appendChild(btn("more", "More", (ev) => Live.tileMenu(c, el)));
    }
    el.tabIndex = 0; el.setAttribute("role", "button"); el.setAttribute("aria-label", `${c.label} — open fullscreen`);
    // In select mode a click toggles this camera; otherwise it opens fullscreen.
    el.onclick = () => Live.selecting ? Live.toggleSelect(c.id) : Focus.open(c);
    el.onkeydown = (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === el) { e.preventDefault(); Live.selecting ? Live.toggleSelect(c.id) : Focus.open(c); } };
    el.oncontextmenu = (e) => { e.preventDefault(); Live.tileMenu(c, el, e.clientX, e.clientY); };
    el.classList.toggle("is-selected", Live.sel && Live.sel.has(c.id));

    if (isAdmin()) {
      el.draggable = true;
      el.addEventListener("dragstart", (e) => { Live._drag = el; el.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", c.id); } catch {} });
      el.addEventListener("dragend", () => { el.classList.remove("dragging"); Live._drag = null; Live.persistOrder(); });
    }

    Live.applyStatus(el, c, st);
    return el;
  },

  tileMenu(c, el, x, y) {
    const r = el.getBoundingClientRect();
    const st = state.status[c.id] || (c.enabled === false ? "paused" : "offline");
    const sch = schedule(c);
    const items = [
      { label: `${sourceLabel(c.source)} · ${st.charAt(0).toUpperCase() + st.slice(1)}`, header: true },
      { label: "Open fullscreen", icon: "maximize", onClick: () => Focus.open(c) },
    ];
    if (sch) items.push({ label: `Detects ${scheduleLabel(c)}`, icon: "clock", onClick: () => CameraForm.open(c) });
    if (isAdmin()) {
      const paused = c.enabled === false;
      items.push(
        { label: "Edit camera", icon: "edit", onClick: () => CameraForm.open(c) },
        { label: paused ? "Resume" : "Pause", icon: paused ? "play" : "pause", onClick: () => Live.toggleCam(c) },
        { label: "Select cameras…", icon: "check", onClick: () => Live.enterSelect(c.id) },
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
    dot.className = "dot " + (st === "online" ? "dot--live"
      : (st === "paused" || st === "scheduled") ? "dot--warn" : "dot--danger");
    t.textContent = st === "online" ? "Live" : st === "paused" ? "Paused"
      : st === "scheduled" ? "Scheduled" : "Offline";
    if (st === "online") {
      off.classList.add("hidden"); feed.classList.remove("hidden");
      if (!Live.feeds.has(c.id)) Live.feeds.set(c.id, startFeed(feed, c.id));
    } else {
      if (Live.feeds.has(c.id)) { Live.feeds.get(c.id)(); Live.feeds.delete(c.id); }
      feed.classList.add("hidden"); off.classList.remove("hidden");
      $("span", off).textContent = st === "paused" ? "Paused"
        : st === "scheduled" ? `Detects ${scheduleLabel(c)}` : "Camera offline";
    }
    // A quiet clock chip on any camera that only detects during set hours.
    const chip = $(".cam__sched", el);
    const sch = schedule(c);
    if (chip) {
      chip.classList.toggle("hidden", !sch);
      if (sch) $(".cam__sched-t", chip).textContent = scheduleLabel(c, false);
    }
  },

  syncGrid() {
    const grid = $("#camGrid"); if (!grid) return;
    const ids = state.cameras.map(c => c.id);
    const present = $$(".cam", grid).map(t => t.dataset.id);
    if (ids.length !== present.length || ids.some((id, i) => id !== present[i])) return Live.buildGrid();
    state.cameras.forEach(c => {
      const el = $(`.cam[data-id="${c.id}"]`, grid); if (!el) return;
      const st = state.status[c.id] || (c.enabled === false ? "paused" : "offline");
      Live.applyStatus(el, c, st);
      $(".cam__name", el).textContent = c.label;
    });
    Live.syncBadges();
    // (online count in the ribbon is repainted by renderStats each refresh)
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

  /* ---- Bulk selection (admin) — pick cameras, then set their hours at once ---- */
  enterSelect(seedId) {
    if (!isAdmin()) return;
    Live.selecting = true;
    Live.sel = Live.sel || new Set();
    if (seedId) Live.sel.add(seedId);
    document.body.classList.add("is-selecting");
    $("#camGrid")?.classList.add("is-selecting");
    $("#selBar")?.classList.remove("hidden");
    const b = $("#selectCams"); if (b) b.innerHTML = `${icon("x")} Cancel`;
    Live.syncSel();
  },
  exitSelect() {
    Live.selecting = false;
    Live.sel && Live.sel.clear();
    document.body.classList.remove("is-selecting");
    $("#camGrid")?.classList.remove("is-selecting");
    $("#selBar")?.classList.add("hidden");
    const b = $("#selectCams"); if (b) b.innerHTML = `${icon("check")} Select`;
    $$(".cam.is-selected").forEach(el => el.classList.remove("is-selected"));
  },
  toggleSelect(id) {
    if (!Live.selecting) Live.enterSelect();
    if (Live.sel.has(id)) Live.sel.delete(id); else Live.sel.add(id);
    Live.syncSel();
  },
  selectAll() {
    const all = state.cameras.every(c => Live.sel.has(c.id));
    Live.sel = new Set(all ? [] : state.cameras.map(c => c.id));   // toggle all/none
    Live.syncSel();
  },
  syncSel() {
    $$(".cam").forEach(el => el.classList.toggle("is-selected", Live.sel.has(el.dataset.id)));
    const n = Live.sel.size;
    const cnt = $("#selCount"); if (cnt) cnt.textContent = `${n} selected`;
    const allBtn = $("#selAll"); if (allBtn) allBtn.textContent = (n && n === state.cameras.length) ? "Select none" : "Select all";
    ["#selSetSched", "#selClearSched", "#selPause"].forEach(sel => { const b = $(sel); if (b) b.disabled = n === 0; });
    // Smart Pause/Resume: if any selected camera is on, the action pauses them all.
    const pause = $("#selPause");
    if (pause) {
      const anyOn = Live.selectedCams().some(c => c.enabled !== false);
      pause.innerHTML = anyOn ? `${icon("pause")} Pause` : `${icon("play")} Resume`;
    }
  },
  selectedCams() { return state.cameras.filter(c => Live.sel.has(c.id)); },
  bulkSchedule() {
    const cams = Live.selectedCams();
    if (!cams.length) { toast("Select at least one camera", { kind: "info" }); return; }
    BulkSchedule.open(cams);
  },
  async bulkPause() {
    const cams = Live.selectedCams();
    if (!cams.length) { toast("Select at least one camera", { kind: "info" }); return; }
    const anyOn = cams.some(c => c.enabled !== false);      // on -> pause all; all paused -> resume
    const targets = cams.filter(c => (c.enabled !== false) === anyOn);   // only those that actually change
    try {
      await Promise.all(targets.map(c => api.editCamera(c.id, { enabled: !anyOn })));
      toast(`${targets.length} camera${targets.length > 1 ? "s" : ""} ${anyOn ? "paused" : "resumed"}`, { kind: "ok" });
      Live.exitSelect(); Live.refresh(true);
    } catch { toast("Could not update every camera", { kind: "danger" }); }
  },
  async bulkClearSchedule() {
    const cams = Live.selectedCams().filter(c => schedule(c));
    if (!cams.length) { toast("None of the selected cameras have set hours", { kind: "info" }); return; }
    if (!await confirmDialog({ title: "Clear detection hours?", body: `${cams.length} camera${cams.length > 1 ? "s" : ""} will go back to always detecting.`, confirmText: "Clear hours" })) return;
    try {
      await Promise.all(cams.map(c => api.editCamera(c.id, { schedule: null })));
      toast(`Detection hours cleared on ${cams.length} camera${cams.length > 1 ? "s" : ""}`, { kind: "ok" });
      Live.exitSelect(); Live.refresh(true);
    } catch { toast("Could not update every camera", { kind: "danger" }); }
  },
};

/* Snapshot polling — chained on load so a slow frame never piles up.
   Mirrors the backend's proven snapshot approach (no MJPEG freeze). */
function startFeed(img, id) {
  if (MOCK) { img.src = mockFrame(id); return () => {}; }
  // The installed system (desktop app, or a browser on the Vigil machine itself)
  // watches its own cameras over localhost — stream MJPEG so it plays at the
  // camera's FULL native frame rate, with no snapshot-polling cap. Remote/phone
  // keeps chained snapshots: bandwidth-friendly and immune to MJPEG stalls.
  const onDevice = (state.me && state.me.desktop)
    || ["localhost", "127.0.0.1", "::1"].includes(location.hostname);
  if (onDevice) {
    img.src = `/stream/${id}`;                 // continuous, full-fps
    return () => { try { img.src = ""; } catch (_) {} };
  }
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

/* Scroll-to-zoom + drag-to-pan on an image inside a stage. Returns detach(). */
function attachZoom(stage, img) {
  let scale = 1, ox = 0, oy = 0, drag = false, sx = 0, sy = 0;
  const apply = () => { img.style.transform = `translate(${ox}px,${oy}px) scale(${scale})`; img.style.cursor = scale > 1 ? "grab" : ""; };
  const onWheel = (e) => { e.preventDefault(); scale = Math.min(6, Math.max(1, scale + (e.deltaY < 0 ? 0.25 : -0.25))); if (scale === 1) { ox = oy = 0; } apply(); };
  const onDown = (e) => { if (scale === 1) return; drag = true; sx = e.clientX - ox; sy = e.clientY - oy; img.style.cursor = "grabbing"; e.preventDefault(); };
  const onMove = (e) => { if (!drag) return; ox = e.clientX - sx; oy = e.clientY - sy; apply(); };
  const onUp = () => { drag = false; apply(); };
  stage.addEventListener("wheel", onWheel, { passive: false });
  img.addEventListener("mousedown", onDown);
  addEventListener("mousemove", onMove); addEventListener("mouseup", onUp);
  return () => { stage.removeEventListener("wheel", onWheel); img.removeEventListener("mousedown", onDown); removeEventListener("mousemove", onMove); removeEventListener("mouseup", onUp); };
}

/* A static image lightbox (evidence snapshots) with zoom/pan. */
function lightbox(src) {
  const node = h(`<div class="focus"><div class="focus__bar">
    <button class="btn btn--icon" data-close title="Close (Esc)">${icon("minimize")}</button>
    <div class="spacer"></div><span class="muted" style="font-size:var(--fs-sm)">Scroll to zoom · drag to pan</span></div>
    <div class="focus__stage"><img class="focus__img" src="${src}" alt=""></div></div>`);
  $("#overlays").appendChild(node);
  const detach = attachZoom($(".focus__stage", node), $(".focus__img", node));
  const close = () => { detach(); node.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  $("[data-close]", node).onclick = close;
  document.addEventListener("keydown", onKey);
}

/* Fullscreen focus */
const Focus = {
  stop: null, detach: null,
  open(c) {
    const st = state.status[c.id] || "offline";
    const node = h(`<div class="focus">
      <div class="focus__bar">
        <button class="btn btn--icon" data-close title="Close (Esc)">${icon("minimize")}</button>
        <div><div class="strong">${esc(c.label)}</div><div class="muted" style="font-size:var(--fs-sm)">${c.location ? esc(c.location) + " · " : ""}${sourceLabel(c.source)}</div></div>
        <span class="badge ${st==="online"?"badge--ok":st==="paused"?"badge--warn":"badge--danger"}"><span class="dot ${st==="online"?"dot--live":""}"></span>${st==="online"?"Live":st==="paused"?"Paused":"Offline"}</span>
        <div class="spacer"></div>
        <span class="muted" style="font-size:var(--fs-sm)">Scroll to zoom</span>
        <span class="cam__ai" style="position:static">${icon("shield")} AI detection on</span>
      </div>
      <div class="focus__stage"><img class="focus__img" alt="${esc(c.label)}"></div></div>`);
    $("#overlays").appendChild(node);
    const img = $(".focus__img", node);
    if (st === "online") { Focus.stop = startFeed(img, c.id); Focus.detach = attachZoom($(".focus__stage", node), img); }
    else img.replaceWith(h(`<div class="empty"><div class="empty__icon">${icon("camoff")}</div><div class="empty__title">${st==="paused"?"Camera paused":"Camera offline"}</div></div>`));
    const close = () => { if (Focus.stop) Focus.stop(); if (Focus.detach) Focus.detach(); Focus.stop = Focus.detach = null; node.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    $("[data-close]", node).onclick = close;
    document.addEventListener("keydown", onKey);
  },
};

/* Shared "detection hours" editor — a toggle that reveals From/To + weekday
   chips. Used by both the single-camera form and the bulk-schedule modal so
   the two never drift apart. */
const Sched = {
  fields(sch, { label = "Only detect during set hours", hint = "Outside these hours the camera idles — no detection, no recording." } = {}) {
    const dayBtns = WEEKDAYS.map((d, i) =>
      `<button type="button" class="daychip${sch && sch.days.includes(i) ? " is-active" : ""}" data-day="${i}">${d}</button>`).join("");
    return `<div class="field sched-row">
        <div class="sched-row__text"><div class="label" style="margin:0">${label}</div>
          <span class="hint" style="margin:0">${hint}</span></div>
        <label class="toggle"><input type="checkbox" data-sched-on ${sch ? "checked" : ""}><span class="toggle__track"></span></label>
      </div>
      <div class="sched-body${sch ? "" : " hidden"}" data-sched-body>
        <div class="sched-times">
          <div class="field"><label class="label">From</label><input type="time" class="input" data-sched-start value="${sch ? sch.start : "10:00"}"></div>
          <div class="field"><label class="label">To</label><input type="time" class="input" data-sched-end value="${sch ? sch.end : "13:00"}"></div>
        </div>
        <div class="field"><label class="label">Days <span class="muted">(none selected = every day)</span></label>
          <div class="daychips" data-days>${dayBtns}</div></div>
      </div>`;
  },
  wire(node) {
    const body = $("[data-sched-body]", node);
    $("[data-sched-on]", node).onchange = (e) => body.classList.toggle("hidden", !e.target.checked);
    $("[data-days]", node).onclick = (e) => { const b = e.target.closest("[data-day]"); if (b) b.classList.toggle("is-active"); };
  },
  /* Returns { schedule: {...}|null } on success, or { error: "…" } to show. */
  read(node) {
    if (!$("[data-sched-on]", node).checked) return { schedule: null };   // null = always on
    const start = $("[data-sched-start]", node).value, end = $("[data-sched-end]", node).value;
    if (!start || !end) return { error: "Set both a start and end time" };
    if (start === end) return { error: "Start and end can't be the same time" };
    const days = $$("[data-day].is-active", node).map(b => +b.dataset.day);
    return { schedule: { start, end, days } };
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
        ${Sched.fields(schedule(cam))}
      </div>
      <div class="modal__foot"><button class="btn" data-x>Cancel</button><button class="btn btn--primary" data-save>${editing ? "Save changes" : "Add camera"}</button></div></div>`);
    const close = openModal(node);
    $$("[data-x]", node).forEach(b => b.onclick = close);
    $("[data-f='label']", node).focus();
    Sched.wire(node);

    $("[data-save]", node).onclick = async () => {
      const body = {}; $$("[data-f]", node).forEach(i => body[i.dataset.f] = i.value.trim());
      if (!body.label) { toast("Name is required", { kind: "danger" }); return; }
      if (!body.source) body.source = "0";
      const sch = Sched.read(node);
      if (sch.error) { toast(sch.error, { kind: "danger" }); return; }
      body.schedule = sch.schedule;
      try {
        if (editing) { await api.editCamera(cam.id, body); toast("Camera updated", { kind: "ok" }); }
        else { await api.addCamera(body); toast("Camera added", { kind: "ok" }); }
        close(); Live.refresh(true);
      } catch { toast("Could not save camera", { kind: "danger" }); }
    };
  },
};

/* Bulk detection-hours editor — applies one schedule (or clears it) to every
   selected camera at once. Same "selected cameras + time range" job, done to a
   batch. */
const BulkSchedule = {
  open(cams) {
    if (!cams.length) return;
    // Seed from a shared schedule if every camera already has the same one.
    const first = schedule(cams[0]);
    const allSame = first && cams.every(c => JSON.stringify(schedule(c)) === JSON.stringify(first));
    const node = h(`<div class="modal" role="dialog" aria-modal="true">
      <div class="modal__head"><div class="modal__title">Detection hours</div><div class="spacer"></div><button class="btn btn--icon btn--ghost" data-x>${icon("x")}</button></div>
      <div class="modal__body">
        <p class="muted" style="margin:0 0 var(--s2)">Applies to <b>${cams.length} camera${cams.length > 1 ? "s" : ""}</b>: ${esc(cams.map(c => c.label).join(", "))}</p>
        ${Sched.fields(allSame ? first : null, { label: "Only detect during set hours", hint: "Turn off to have these cameras always detect." })}
      </div>
      <div class="modal__foot"><button class="btn" data-x>Cancel</button><button class="btn btn--primary" data-save>Apply to ${cams.length}</button></div></div>`);
    const close = openModal(node);
    $$("[data-x]", node).forEach(b => b.onclick = close);
    Sched.wire(node);

    $("[data-save]", node).onclick = async () => {
      const sch = Sched.read(node);
      if (sch.error) { toast(sch.error, { kind: "danger" }); return; }
      const saveBtn = $("[data-save]", node); saveBtn.disabled = true;
      try {
        await Promise.all(cams.map(c => api.editCamera(c.id, { schedule: sch.schedule })));
        toast(sch.schedule ? `Detection hours set on ${cams.length} camera${cams.length > 1 ? "s" : ""}`
                           : `Detection hours cleared on ${cams.length} camera${cams.length > 1 ? "s" : ""}`, { kind: "ok" });
        close(); Live.exitSelect(); Live.refresh(true);
      } catch { saveBtn.disabled = false; toast("Could not update every camera", { kind: "danger" }); }
    };
  },
};

/* =========================================================================
   6b. WATCH ON YOUR PHONE  (LAN share — QR + link a teacher scans to open the
   live wall on their phone; same Wi-Fi, still login-gated)
   ========================================================================= */
const PhoneAccess = {
  // Shared body for both the modal and the Settings section.
  _fill(box, d) {
    if (!d || !d.on_lan) {
      box.innerHTML = `<div class="phone-share phone-share--warn">${icon("wifioff")}
        <div><div class="strong">This Mac isn't on a network yet</div>
        <div class="muted">Connect it to Wi‑Fi, then reopen this. Teachers must be on the same Wi‑Fi to watch.</div></div></div>`;
      return;
    }
    box.innerHTML = `<div class="phone-share">
        <div class="phone-share__qr">${d.qr
          ? `<img src="${d.qr}" alt="Scan to open Vigil on your phone" width="220" height="220">`
          : `<div class="phone-share__noqr">${icon("phone")}</div>`}</div>
        <ol class="phone-share__steps">
          <li>Join the phone to the <b>same Wi‑Fi</b> as this Mac.</li>
          <li><b>Scan the code</b> with the phone camera (or open the link).</li>
          <li>Log in with the account you gave the teacher to watch the live wall.</li>
        </ol>
        <div class="phone-share__url"><span class="mono" title="${esc(d.url)}">${esc(d.url)}</span>
          <button class="btn btn--sm" id="phoneCopy">${icon("share")} Copy link</button></div>
        ${d.ipv6_only
          ? `<p class="hint">This Wi‑Fi is IPv6‑only, so the link uses a numeric IPv6 address — it opens on <b>Android and iPhone</b>.${d.alt ? ` On iPhone you can also use <span class="mono">${esc(d.alt)}</span>.` : ""} If it still won't open, your hotspot is blocking device‑to‑device — use a normal Wi‑Fi router instead.</p>`
          : `<p class="hint">Anyone on this Wi‑Fi with a login can watch, and gets alerts while Vigil is open. Some campus networks block device‑to‑device — if the link won't open, join the same Wi‑Fi network.</p>`}
      </div>`;
    const copy = $("#phoneCopy", box);
    if (copy) copy.onclick = () => {
      (navigator.clipboard?.writeText(d.url) || Promise.resolve()).then(
        () => toast("Link copied", { kind: "ok" }), () => toast(d.url, { kind: "info" }));
    };
  },
  async open() {
    const node = h(`<div class="modal modal--phone" role="dialog" aria-modal="true">
      <div class="modal__head"><div class="modal__title">${icon("phone")} Watch on your phone</div><div class="spacer"></div><button class="btn btn--icon btn--ghost" data-x>${icon("x")}</button></div>
      <div class="modal__body" id="phoneBody"><div class="phone-share__loading">${icon("phone")}<span>Finding this Mac on the network…</span></div></div></div>`);
    const close = openModal(node);
    $$("[data-x]", node).forEach(b => b.onclick = close);
    let d; try { d = await api.lanInfo(); } catch { d = null; }
    PhoneAccess._fill($("#phoneBody", node), d);
  },
  // Render into a Settings-section container (no modal chrome).
  async renderInline(box) {
    if (!box) return;
    let d; try { d = await api.lanInfo(); } catch { d = null; }
    PhoneAccess._fill(box, d);
  },
};

/* =========================================================================
   7. EVIDENCE
   ========================================================================= */
const Evidence = {
  all: [], pendingOpen: null, selected: new Set(), _lastSel: null,
  async render(root) {
    root.className = "content content--flush";
    root.innerHTML = `<div class="evidence">
      <aside class="evidence__side" id="evSide"></aside>
      <div class="evidence__main"><div class="toolbar">
        <div class="search" style="max-width:260px"><span>${icon("search")}</span><input id="evSearch" placeholder="Search evidence…"></div>
        <div class="segmented" id="evRange">${[["all","All"],["today","Today"],["7d","7 days"],["30d","30 days"]].map(([r,l]) => `<button data-r="${r}" class="${state.evFilter.range===r && !state.evFilter.date?"is-active":""}">${l}</button>`).join("")}</div>
        <div class="spacer"></div>
        <input type="date" class="input" id="evDate" style="width:150px" value="${state.evFilter.date}" aria-label="Filter by date">
        <button class="btn" id="evExport">${icon("download")} Export</button>
      </div><div id="evBody">${skel.evCards(8)}</div></div></div>`;
    $("#evSearch", root).oninput = debounce(() => Evidence.paint(), 120);
    $("#evRange", root).onclick = (e) => { const b = e.target.closest("[data-r]"); if (!b) return; state.evFilter.range = b.dataset.r; state.evFilter.date = ""; const d = $("#evDate"); if (d) d.value = ""; $$("#evRange button").forEach(x => x.classList.toggle("is-active", x === b)); Evidence.paint(); };
    $("#evDate", root).onchange = (e) => { state.evFilter.date = e.target.value; if (e.target.value) $$("#evRange button").forEach(x => x.classList.remove("is-active")); else { state.evFilter.range = "all"; const a = $$("#evRange button")[0]; if (a) a.classList.add("is-active"); } Evidence.paint(); };
    $("#evExport", root).onclick = () => Evidence.export();
    await Evidence.load();
  },
  destroy() {},

  async load() {
    Evidence.selected.clear(); Evidence._lastSel = null;
    // Fetch all recent once; date range/day is filtered client-side (see filtered()).
    try { Evidence.all = await api.evidence("?status=all"); }
    catch {
      const body = $("#evBody");
      if (body) { body.innerHTML = ""; body.appendChild(recoverNode("network", [{ label: "Retry", primary: true, icon: "wifi", onClick: () => Evidence.load() }])); }
      return;
    }
    Evidence.renderSide(); Evidence.paint();
    if (Evidence.pendingOpen != null) { const id = Evidence.pendingOpen; Evidence.pendingOpen = null; Evidence.detail(id); }
    if (Evidence.pendingExport) { Evidence.pendingExport = false; Evidence.export(); }
  },

  filtered() {
    const f = state.evFilter, q = ($("#evSearch")?.value || "").toLowerCase();
    const inRange = (a) => {
      if (f.date) return a.date === f.date;                 // a specific day was picked
      if (f.range === "all") return true;
      const days = f.range === "today" ? 0 : f.range === "7d" ? 6 : 29;
      const cutoff = new Date(); cutoff.setHours(0, 0, 0, 0); cutoff.setDate(cutoff.getDate() - days);
      const ad = new Date(a.date + "T00:00:00");
      return !isNaN(ad) && ad >= cutoff;
    };
    return Evidence.all.filter(a =>
      (f.status === "all" || a.status === f.status) &&
      (f.camera === "all" || a.camera === f.camera) &&
      (!f.bookmarked || state.bookmarks.has(a.id)) &&
      inRange(a) &&
      (!q || (a.camera + " " + a.thing + " " + (a.description || "")).toLowerCase().includes(q)));
  },

  renderSide() {
    const counts = { all: Evidence.all.length, pending: 0, confirmed: 0, dismissed: 0 };
    Evidence.all.forEach(a => counts[a.status] !== undefined && counts[a.status]++);
    const cams = [...new Set(Evidence.all.map(a => a.camera))];
    const f = state.evFilter;
    const bmCount = Evidence.all.filter(a => state.bookmarks.has(a.id)).length;
    $("#evSide").innerHTML = `
      <div class="filtergroup"><div class="filtergroup__label">Status</div>
        ${[["all","All events"],["pending","Pending review"],["confirmed","Confirmed"],["dismissed","Dismissed"]].map(([k,l]) =>
          `<div class="filter-item ${f.status===k && !f.bookmarked?"is-active":""}" data-status="${k}"><span class="dot ${k==="pending"?"dot--warn":k==="confirmed"?"dot--ok":k==="dismissed"?"":""}"></span>${l}<span class="count">${counts[k]??""}</span></div>`).join("")}
        <div class="filter-item ${f.bookmarked?"is-active":""}" data-bm>${icon("star")} Bookmarked<span class="count">${bmCount||""}</span></div>
      </div>
      <div class="filtergroup"><div class="filtergroup__label">Camera</div>
        <div class="filter-item ${f.camera==="all"?"is-active":""}" data-cam="all">All cameras<span class="count">${Evidence.all.length}</span></div>
        ${cams.map(c => `<div class="filter-item ${f.camera===c?"is-active":""}" data-cam="${esc(c)}">${esc(c)}<span class="count">${Evidence.all.filter(a=>a.camera===c).length}</span></div>`).join("")}
      </div>`;
    $$("[data-status]").forEach(n => n.onclick = () => { state.evFilter.status = n.dataset.status; state.evFilter.bookmarked = false; Evidence.renderSide(); Evidence.paint(); });
    $("[data-bm]").onclick = () => { state.evFilter.bookmarked = !state.evFilter.bookmarked;
      if (state.evFilter.bookmarked) state.evFilter.status = "all";   // show ALL bookmarks, not just the last status filter
      Evidence.renderSide(); Evidence.paint(); };
    $$("[data-cam]").forEach(n => n.onclick = () => { state.evFilter.camera = n.dataset.cam; Evidence.renderSide(); Evidence.paint(); });
  },

  paint() {
    const rows = Evidence.filtered();
    const body = $("#evBody");
    if (!rows.length) { body.innerHTML = ""; body.appendChild(Evidence.empty()); return; }
    body.classList.toggle("has-sel", Evidence.selected.size > 0);
    body.innerHTML = `<div class="ev-grid">${rows.map((a, i) => Evidence.card(a, i)).join("")}</div>`;
    $$(".ev-card", body).forEach(c => {
      c.onclick = (e) => { if (e.target.closest(".ev-card__check")) return; Evidence.detail(+c.dataset.id); };
      c.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); Evidence.detail(+c.dataset.id); }
        else if (e.key === "x" || e.key === "X") { e.preventDefault(); Evidence.toggleSelect(+c.dataset.id, e.shiftKey); }
      };
    });
    $$("[data-check]", body).forEach(cb => cb.onclick = (e) => { e.stopPropagation(); Evidence.toggleSelect(+cb.dataset.check, e.shiftKey); });
    if (Evidence.selected.size) Evidence.renderBulk(body);
  },

  card(a, i) {
    const badge = a.status === "pending" ? `<span class="badge badge--warn">Pending</span>`
      : a.status === "confirmed" ? `<span class="badge badge--danger">Confirmed</span>`
      : `<span class="badge">Dismissed</span>`;
    const img = MOCK ? mockFrame("e" + a.id) : (a.image || `/evidence/image/${a.id}`);
    const sel = Evidence.selected.has(a.id);
    const star = state.bookmarks.has(a.id) ? `<span style="margin-left:auto;color:var(--warn)">${icon("star")}</span>` : "";
    return `<div class="ev-card ${sel ? "is-selected" : ""}" data-id="${a.id}" tabindex="0" role="button" aria-label="Evidence ${a.id} — ${esc(a.camera)}, ${a.status}" style="animation-delay:${Math.min(i*24,300)}ms">
      <div class="ev-card__thumb"><img loading="lazy" src="${img}" alt=""><div class="ev-card__badge">${badge}</div>
        <label class="ev-card__check"><input type="checkbox" data-check="${a.id}" ${sel ? "checked" : ""} aria-label="Select event"></label></div>
      <div class="ev-card__meta">
        <div class="ev-card__title">${esc(a.thing || "Phone")} <span class="muted" style="font-weight:400">· ${Math.round((a.confidence||0)*100)}%</span>${star}</div>
        <div class="ev-card__sub">${icon("live")} ${esc(a.camera)}</div>
        <div class="ev-card__sub">${icon("clock")} ${relDate(a.date)} · ${fmtTime(a.time)}</div>
      </div></div>`;
  },

  toggleSelect(id, shift) {
    const rows = Evidence.filtered().map(a => a.id);
    if (shift && Evidence._lastSel != null) {
      const a = rows.indexOf(Evidence._lastSel), b = rows.indexOf(id);
      if (a > -1 && b > -1) { const lo = Math.min(a, b), hi = Math.max(a, b); for (let k = lo; k <= hi; k++) Evidence.selected.add(rows[k]); }
    } else if (Evidence.selected.has(id)) { Evidence.selected.delete(id); }
    else { Evidence.selected.add(id); }
    Evidence._lastSel = id;
    Evidence.paint();
  },

  renderBulk(body) {
    const n = Evidence.selected.size;
    const total = Evidence.filtered().length;
    const bar = h(`<div class="bulkbar">
      <span class="strong">${n} selected</span>
      ${n < total ? `<button class="btn btn--ghost btn--sm" data-bulk="all">Select all ${total}</button>` : ""}
      <div class="spacer"></div>
      <button class="btn btn--danger btn--sm" data-bulk="confirm">${icon("alert")} Confirm</button>
      <button class="btn btn--sm" data-bulk="dismiss">${icon("x")} Dismiss</button>
      <button class="btn btn--sm" data-bulk="export">${icon("download")} Export</button>
      <button class="btn btn--ghost btn--sm" data-bulk="clear">Clear</button></div>`);
    body.appendChild(bar);
    const allBtn = $("[data-bulk=all]", bar); if (allBtn) allBtn.onclick = () => { Evidence.filtered().forEach(a => Evidence.selected.add(a.id)); Evidence.paint(); };
    $("[data-bulk=confirm]", bar).onclick = () => Evidence.bulkReview("confirm");
    $("[data-bulk=dismiss]", bar).onclick = () => Evidence.bulkReview("dismiss");
    $("[data-bulk=export]", bar).onclick = () => { Evidence.exportRows(Evidence.all.filter(a => Evidence.selected.has(a.id))); };
    $("[data-bulk=clear]", bar).onclick = () => { Evidence.selected.clear(); Evidence.paint(); };
  },

  async bulkReview(action) {
    const ids = [...Evidence.selected].filter(id => { const a = Evidence.all.find(x => x.id === id); return a && a.status === "pending"; });
    if (!ids.length) { toast("No pending events selected", { kind: "info" }); return; }
    const verb = action === "confirm" ? "Confirm" : "Dismiss";
    const plural = ids.length > 1 ? "s" : "";
    if (!await confirmDialog({ title: `${verb} ${ids.length} event${plural}?`,
        body: `${ids.length} pending event${plural} will be marked as ${action === "confirm" ? "confirmed incidents" : "dismissed"}. Each keeps an audit record of who decided.`,
        confirmText: verb, danger: action === "confirm" })) return;
    await Promise.all(ids.map(id => api.reviewAlert(id, action)));
    toast(`${ids.length} event${ids.length > 1 ? "s" : ""} ${action === "confirm" ? "confirmed" : "dismissed"}`, { kind: "ok" });
    Evidence.selected.clear(); Notify.poll(); Evidence.load();
  },

  empty() {
    const f = state.evFilter;
    const filtered = f.status !== "all" || f.camera !== "all" || state.evFilter.date;
    return h(`<div class="empty">
      ${filtered ? ILLO.search : ILLO.clear}
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
        <button class="btn btn--icon btn--ghost" data-star title="Bookmark">${icon("star")}</button></div>
      <div class="drawer__body">
        <img class="drawer__img" src="${img}" alt="" data-zoom style="cursor:zoom-in">
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
        <button class="btn btn--icon" data-dl title="Download snapshot">${icon("download")}</button>
      </div></div>`);
    const close = openModal(node);
    $$("[data-x]", node).forEach(b => b.onclick = close);
    const starBtn = $("[data-star]", node);
    const paintStar = () => starBtn.style.color = state.bookmarks.has(id) ? "var(--warn)" : "";
    paintStar();
    starBtn.onclick = () => { toggleBookmark(id); paintStar(); toast(state.bookmarks.has(id) ? "Bookmarked" : "Bookmark removed", { kind: "ok" }); };
    $("[data-zoom]", node).onclick = () => lightbox(img);
    $("[data-dl]", node).onclick = () => {
      const link = document.createElement("a");
      link.href = img; link.download = `vigil-evidence-${a.id}.jpg`;
      document.body.appendChild(link); link.click(); link.remove();
    };
    const di = $("[data-zoom]", node);
    di.onerror = () => { const rec = recoverNode("corrupted"); rec.style.gridColumn = ""; di.replaceWith(rec); };
    if (di.complete && di.naturalWidth === 0) di.onerror();   // already failed before handler attached
    if (canReview) {
      $("[data-confirm]", node).onclick = async () => { await api.reviewAlert(id, "confirm"); toast("Marked as confirmed incident", { kind: "ok" }); close(); Notify.poll(); Evidence.load(); };
      $("[data-dismiss]", node).onclick = async () => { await api.reviewAlert(id, "dismiss"); toast("Dismissed", { kind: "ok" }); close(); Notify.poll(); Evidence.load(); };
    }
  },

  export() { Evidence.exportRows(Evidence.filtered()); },

  exportRows(rows) {
    if (!rows.length) { toast("Nothing to export", { msg: "No events selected or matching filters.", kind: "info" }); return; }
    const cols = ["id", "date", "time", "camera", "thing", "confidence", "status", "reviewed_by", "reviewed_at"];
    const csv = [cols.join(",")].concat(rows.map(a => cols.map(k => `"${String(a[k] ?? "").replace(/"/g, '""')}"`).join(","))).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = `vigil-evidence-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    toast("Evidence exported", { msg: `${rows.length} events → CSV`, kind: "ok" });
  },
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
      <div class="page-head">
        <div><h1>Users</h1><div class="muted">People who can access Vigil and review evidence.</div></div>
        <div class="spacer"></div>
        <div class="search" style="max-width:260px"><span>${icon("search")}</span><input id="uSearch" placeholder="Search people…"></div>
        <button class="btn btn--primary" id="addUser">${icon("plus")} Add user</button>
      </div>
      <div class="card"><table class="table"><thead><tr>
        <th class="sortable" data-k="username">Name</th><th>Role</th><th>Sign-in</th><th class="sortable" data-k="last_login">Last active</th><th></th>
      </tr></thead><tbody id="uBody">${skel.rows(5)}</tbody></table></div></div>`;
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
        { label: "Reset password", icon: "lock", onClick: () => Users.resetPassword(u) },
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
  resetPassword(u) {
    if (u.auth === "google") { toast("This person signs in with Google — there is no password to reset.", { kind: "info" }); return; }
    const node = h(`<div class="modal"><div class="modal__head"><div class="modal__title">Reset password</div><div class="spacer"></div><button class="btn btn--icon btn--ghost" data-x>${icon("x")}</button></div>
      <div class="modal__body">
        <p class="muted" style="margin:0 0 var(--s4)">Set a new password for <b>${esc(u.username)}</b>. They'll use it the next time they sign in.</p>
        <div class="field"><label class="label">New password</label><input class="input" type="password" data-f="password" placeholder="At least 6 characters"></div>
      </div><div class="modal__foot"><button class="btn" data-x>Cancel</button><button class="btn btn--primary" data-save>Set password</button></div></div>`);
    const close = openModal(node); $$("[data-x]", node).forEach(b => b.onclick = close);
    const pw = $("[data-f=password]", node); pw.focus();
    $("[data-save]", node).onclick = async () => {
      if (pw.value.length < 6) { toast("Password must be at least 6 characters", { kind: "danger" }); return; }
      const f = new FormData(); f.append("username", u.username); f.append("password", pw.value);
      try {
        const r = await fetch("/users/reset_password", { method: "POST", body: f });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.error || "failed");
        toast("Password updated", { kind: "ok" }); close();
      } catch (e) { toast(e.message === "failed" ? "Could not reset password" : e.message, { kind: "danger" }); }
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
    ["cameras", "Cameras", "live"], ["phone", "Watch on your phone", "phone"],
    ["storage", "Storage", "db"],
    ["privacy", "Privacy", "lock"], ["updates", "Updates", "download"],
    ["account", "Account", "users"],
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
      ${Settings.row("Appearance", "Auto follows your system's light/dark setting live. Dark is easiest on the eyes for long shifts.", `<div class="segmented" id="themePick">
        <button data-t="auto" class="${state.theme==="auto"?"is-active":""}">Auto</button><button data-t="dark" class="${state.theme==="dark"?"is-active":""}">Dark</button><button data-t="light" class="${state.theme==="light"?"is-active":""}">Light</button></div>`)}
      ${Settings.row("Default grid density", "How many cameras fill the Live Footage wall by default.", sel("_density", [["comfortable","Large"],["cozy","Medium"],["compact","Small"],["dense","Wall"]], state.density))}</div>`;
    else if (Settings.section === "ai") html = `<div class="settings__group"><h2>AI Models</h2><p>The detection engine. Defaults are tuned — change only if you know the trade-offs.</p>
      ${Settings.row("Detection model", "Larger models are more accurate but need more power.", sel("MODEL_NAME", [["yolo11n.pt","Fast (nano)"],["yolo11m.pt","Balanced (medium)"],["yolo11x.pt","Accurate (xlarge)"]], d.MODEL_NAME))}
      ${Settings.row("Confidence threshold", "How sure the AI must be. 0.5 is a good balance.", num("CONFIDENCE", d.CONFIDENCE, "0.05"))}
      ${Settings.row("Image size", "Higher catches smaller/farther phones, slightly slower.", num("IMG_SIZE", d.IMG_SIZE, "32"))}
      ${Settings.row("AI second look", "A vision model re-checks each detection to filter false alarms.", tog("VLM_ENABLED", d.VLM_ENABLED))}</div>`;
    else if (Settings.section === "notifications") html = `<div class="settings__group"><h2>Notifications</h2><p>Alerts show inside Vigil the instant a phone is detected — the bell, a banner and a sound while the app is open. On the same‑Wi‑Fi link a teacher just keeps Vigil open to get them.</p>
      ${Settings.row("Notify me on this device", "Also show a system pop‑up + buzz when a phone is spotted. Works on this computer and on phones opened over a secure (https) link.", `<button class="btn" id="notifToggle">…</button>`)}
      ${Settings.row("Test notification", "Send a sample alert to this device now to check it shows.", `<button class="btn btn--sm" id="notifTest">Send test</button>`)}</div>`;
    else if (Settings.section === "cameras") html = `<div class="settings__group"><h2>Cameras</h2><p>Defaults applied to camera feeds.</p>
      ${Settings.row("Manage cameras", "Add, edit, and arrange cameras from Live Footage.", `<a class="btn" href="#/live">Go to Live Footage</a>`)}</div>`;
    else if (Settings.section === "phone") html = `<div class="settings__group"><h2>Watch on your phone</h2><p>Teachers on the <b>same Wi‑Fi</b> scan this code (or open the link) to watch the live wall on their phone. Create a login for them in <b>Users</b>, send it over WhatsApp, and they just sign in — no setup on their end.</p>
      <div id="phoneInline"><div class="phone-share__loading">${icon("phone")}<span>Finding this Mac on the network…</span></div></div></div>`;
    else if (Settings.section === "storage") html = `<div class="settings__group"><h2>Storage</h2><p>Where evidence lives on this machine.</p>
      ${Settings.row("Evidence location", "Snapshots and the database are stored locally on this device.", `<span class="badge">Local disk</span>`)}
      ${Settings.row("Clear dismissed evidence", "Permanently delete events you've dismissed.", `<button class="btn btn--danger" id="clearDismissed">Clear…</button>`)}</div>`;
    else if (Settings.section === "privacy") html = `<div class="settings__group"><h2>Privacy</h2><p>Vigil runs entirely on this device.</p>
      ${Settings.row("On-device processing", "Video never leaves this machine. No cloud, no third parties.", `<span class="badge badge--ok">${icon("check")} On-device</span>`)}
      ${Settings.row("Audit trail", "Every confirm/dismiss records who decided and when.", `<span class="badge badge--ok">Enabled</span>`)}</div>`;
    else if (Settings.section === "updates") html = `<div class="settings__group"><h2>Updates</h2><p>Keep Vigil up to date.</p>
      ${Settings.row("Current version", "The version of Vigil running on this device.", `<span class="badge">v${esc(state.me.version||"—")}</span>`)}
      ${Settings.row("Check for updates", "See if a newer version is available to download.", `<button class="btn" id="checkUpdate">${icon("download")} Check now</button>`)}
      <div id="updateResult"></div></div>`;
    else if (Settings.section === "account") html = `<div class="settings__group"><h2>Account</h2><p>Your Vigil sign-in.</p>
      ${Settings.row("Signed in as", "", `<span class="strong">${esc(state.me.username)}</span>`)}
      ${Settings.row("Sign out", "End this session on this device.", `<a class="btn" href="/logout">${icon("logout")} Sign out</a>`)}</div>`;

    body.innerHTML = html + (["general","ai","notifications"].includes(Settings.section)
      ? `<div class="row" style="justify-content:flex-end;gap:var(--s2)"><button class="btn btn--primary" id="setSave">Save changes</button></div>` : "");

    // wire live controls
    const tp = $("#themePick"); if (tp) tp.onclick = (e) => { const b = e.target.closest("[data-t]"); if (!b) return; setTheme(b.dataset.t); $$("#themePick button").forEach(x => x.classList.toggle("is-active", x === b)); };
    const dp = $("[data-k='_density']"); if (dp) dp.onchange = () => { state.density = dp.value; localStorage.setItem("vigil.density", state.density); toast("Default density updated", { kind: "ok" }); };
    const save = $("#setSave"); if (save) save.onclick = () => Settings.save();
    const cu = $("#checkUpdate"); if (cu) cu.onclick = () => Settings.checkUpdate(cu);
    if (Settings.section === "phone") PhoneAccess.renderInline($("#phoneInline"));

    // Notifications section: device toggle + test
    const nt = $("#notifToggle");
    if (nt) {
      const ntOn = () => MOCK ? localStorage.getItem(PhoneNotify.KEY) === "1" : PhoneNotify.on();
      const paintNt = () => { const on = ntOn(); nt.textContent = on ? "On — turn off" : (MOCK || PhoneNotify.supported() ? "Turn on" : "Not supported here"); nt.classList.toggle("btn--primary", !on); };
      paintNt();
      nt.onclick = async () => {
        if (ntOn()) { PhoneNotify.disable(); toast("Device notifications off", { kind: "ok" }); }
        else { if (MOCK) { toast("Notifications on (demo)", { kind: "ok" }); localStorage.setItem(PhoneNotify.KEY, "1"); } else await PhoneNotify.enable(); }
        paintNt();
      };
    }
    // Send a REAL server push to every subscribed device — the honest way to
    // confirm the closed-app path (lock the phone, then tap Send).
    const ntTest = $("#notifTest");
    if (ntTest) ntTest.onclick = async () => {
      const old = ntTest.textContent; ntTest.disabled = true; ntTest.textContent = "Sending…";
      try {
        if (MOCK) { PhoneNotify.fire({ _test: true }); toast("Test sent (demo)", { kind: "ok" }); }
        else {
          const r = await fetch("/api/push/test", { method: "POST" });
          const d2 = await r.json().catch(() => ({}));
          if (d2 && d2.ok && d2.count) toast(`Test push sent to ${d2.count} device${d2.count === 1 ? "" : "s"}`, { msg: "Lock your phone — it should still arrive.", kind: "ok" });
          else if (d2 && d2.ok) toast("No devices subscribed yet", { msg: 'Tap "Turn on" above on the phone first.', kind: "info" });
          else toast("Couldn't send test", { msg: "Push may be unavailable on this server.", kind: "info" });
        }
      } catch { toast("Couldn't send test", { kind: "info" }); }
      ntTest.disabled = false; ntTest.textContent = old;
    };
    const cd = $("#clearDismissed"); if (cd) cd.onclick = async () => {
      if (!await confirmDialog({ title: "Clear dismissed evidence?",
          body: "All dismissed events and their snapshots will be permanently deleted. Confirmed evidence is kept.",
          confirmText: "Clear dismissed", danger: true })) return;
      try {
        const r = await fetch("/evidence/clear_dismissed", { method: "POST" });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error);
        toast("Dismissed evidence cleared", { msg: `${d.deleted} event${d.deleted === 1 ? "" : "s"} removed`, kind: "ok" });
      } catch { toast("Could not clear evidence", { kind: "danger" }); }
    };
  },

  async checkUpdate(btn) {
    const box = $("#updateResult");
    btn.disabled = true; btn.innerHTML = "Checking…";
    box.innerHTML = "";
    try {
      let d;
      if (MOCK) { await new Promise(r => setTimeout(r, 500)); d = { current: "1.1.1", latest: "1.2.0", update_available: true, can_self_update: true, url: "https://github.com/Param077s/vigil/releases/latest" }; }
      else { const r = await fetch("/api/update-check"); d = await r.json(); if (!r.ok) throw new Error(d.error || "failed"); }
      if (d.update_available) {
        box.innerHTML = `<div class="card" style="margin-top:var(--s4)"><div class="card__body" id="updBody"></div></div>`;
        const render = (s) => {
          const body = $("#updBody"); if (!body) return;
          if (s.state === "downloading") {
            body.innerHTML = `<div><div class="strong">Downloading v${esc(d.latest)}…</div>
              <div class="progress"><div class="progress__bar" style="width:${Math.round((s.progress || 0) * 100)}%"></div></div>
              <div class="muted" style="font-size:var(--fs-sm)">Keep using Vigil — it installs when you restart.</div></div>`;
          } else if (s.state === "ready") {
            body.innerHTML = `<div class="row" style="justify-content:space-between;gap:var(--s4)">
              <div><div class="strong" style="color:var(--ok)">${icon("check")} Update ready — v${esc(d.latest)}</div>
                <div class="muted" style="font-size:var(--fs-sm)">Restart Vigil to finish. It reopens updated.</div></div>
              <button class="btn btn--primary" id="updRestart">Restart now</button></div>`;
            $("#updRestart").onclick = () => UpdateFlow.restart();
          } else if (s.state === "error") {
            body.innerHTML = `<div class="row" style="justify-content:space-between;gap:var(--s4)">
              <div style="color:var(--danger)">${icon("alert")} <span>${esc(s.error || "Update failed.")}</span></div>
              <button class="btn btn--sm" id="updRetry">Retry</button></div>`;
            $("#updRetry").onclick = () => UpdateFlow.download(d);
          } else {
            body.innerHTML = `<div class="row" style="justify-content:space-between;gap:var(--s4)">
              <div><div class="strong">Update available — v${esc(d.latest)}</div><div class="muted" style="font-size:var(--fs-sm)">You're on v${esc(d.current)}. ${d.can_self_update ? "Downloads in the background." : "Opens the download page."}</div></div>
              <button class="btn btn--primary" id="dlUpdate">${icon("download")} ${d.can_self_update ? "Download" : "Get update"}</button></div>`;
            $("#dlUpdate").onclick = () => UpdateFlow.download(d);
          }
        };
        UpdateFlow.info = d;
        Settings._updUnsub && Settings._updUnsub();
        Settings._updUnsub = UpdateFlow.subscribe(render);
      } else {
        box.innerHTML = `<div class="row" style="margin-top:var(--s4);color:var(--ok)">${icon("check")} <span>You're on the latest version (v${esc(d.current)}).</span></div>`;
      }
    } catch (e) {
      box.innerHTML = `<div class="row" style="margin-top:var(--s4);color:var(--danger)">${icon("alert")} <span>${esc(e.message || "Couldn't check for updates.")}</span></div>`;
    }
    btn.disabled = false; btn.innerHTML = `${icon("download")} Check now`;
  },
  async save() {
    // The backend's form fields are lowercase (alert_cooldown, model_name, …)
    // and booleans are presence-only — an unchecked box must send NOTHING.
    // Sending the UPPERCASE keys we read from /api/settings made FastAPI fall
    // back to each parameter's default, silently resetting settings on every save.
    const form = new FormData();
    const put = (k, v) => {
      const key = k.toLowerCase();
      if (typeof v === "boolean") { if (v) form.set(key, "on"); else form.delete(key); return; }
      form.set(key, v);
    };
    Object.entries(Settings.data).forEach(([k, v]) => put(k, v));   // don't blank unshown fields
    $$("[data-k]").forEach(el => { const k = el.dataset.k; if (k.startsWith("_")) return;
      put(k, el.type === "checkbox" ? el.checked : el.value); });
    try {
      await api.saveSettings(form);
      try { Settings.data = await api.settings(); } catch {}
      toast("Settings saved", { kind: "ok" });
    }
    catch { toast("Could not save settings", { kind: "danger" }); }
  },
};

function noAccess() {
  return `<div class="empty"><div class="empty__icon">${icon("lock")}</div><div class="empty__title">Admins only</div>
    <div class="empty__text">This section is limited to administrators. Ask an admin if you need access.</div></div>`;
}

/* =========================================================================
   9b. NOTIFICATIONS  (app-wide detection awareness — bell, toasts, nav badge)
   ========================================================================= */
const Notify = {
  timer: null,
  async start() { await Notify.poll(); Notify.timer = setInterval(Notify.poll, 3000); },
  async poll() {
    let alerts, stats;
    try { [alerts, stats] = await Promise.all([api.evidence("?status=all"), api.stats()]); }
    catch { return; }
    state.recentAlerts = alerts.slice(0, 60);
    state.stats = stats;
    const fresh = [];
    alerts.forEach(a => {
      if (!state.seenAlerts.has(a.id)) {
        state.seenAlerts.add(a.id);
        if (state.alertsSeeded && a.status === "pending") fresh.push(a);
      }
    });
    state.alertsSeeded = true;
    state.notifications = alerts.filter(a => a.status === "pending").slice(0, 30);
    Notify.paintBell();
    if (state.route === "live") Live.syncBadges();
    // Awareness, not interruption: a brief toast per fresh detection, unless snoozed.
    if (Date.now() > state.snoozeUntil) {
      fresh.slice(0, 3).forEach(a => toast(`Phone detected · ${a.camera}`, {
        msg: `${Math.round((a.confidence || 0) * 100)}% confidence · click to review`,
        kind: "danger", timeout: 6500,
        onClick: () => { Evidence.pendingOpen = a.id; go("evidence"); },
      }));
      fresh.forEach(a => PhoneNotify.fire(a));    // system notification + vibrate on the phone
    }
  },
  paintBell() {
    const count = state.notifications.length;
    const b = $("#bellCount");
    if (b) { b.textContent = count > 99 ? "99+" : count; b.classList.toggle("hidden", count === 0); }
    const nb = $("#navBadge");
    if (nb) { nb.textContent = state.stats.pending || ""; nb.classList.toggle("hidden", !state.stats.pending); }
  },
  openPanel(anchor) {
    $$(".menu").forEach(m => m.remove());
    const r = anchor.getBoundingClientRect();
    const groups = {};
    state.notifications.forEach(a => (groups[a.camera] = groups[a.camera] || []).push(a));
    const snoozed = Date.now() < state.snoozeUntil;
    const panel = h(`<div class="menu notif">
      <div class="notif__head"><span class="strong">Notifications</span>
        <button class="btn btn--ghost btn--sm" data-snooze>${snoozed ? "Snoozed" : "Snooze 15m"}</button></div>
      ${state.notifications.length ? Object.entries(groups).map(([cam, list]) => `
        <div class="menu__label">${esc(cam)} · ${list.length}</div>
        ${list.slice(0, 4).map(a => `<div class="notif__item" data-id="${a.id}">
          <img class="notif__thumb" src="${MOCK ? mockFrame("e" + a.id) : (a.image || `/evidence/image/${a.id}`)}" alt="">
          <div style="min-width:0"><div class="truncate">Phone · ${Math.round((a.confidence || 0) * 100)}%</div>
          <div class="muted" style="font-size:var(--fs-xs)">${relDate(a.date)} · ${esc(a.time)}</div></div></div>`).join("")}`).join("")
        : `<div class="empty" style="padding:var(--s8) var(--s4)"><div class="empty__icon">${icon("check")}</div><div class="empty__title" style="font-size:var(--fs-md)">All clear</div><div class="empty__text" style="font-size:var(--fs-sm)">No detections waiting for review.</div></div>`}</div>`);
    document.body.appendChild(panel);
    panel.style.left = Math.min(r.left - 120, innerWidth - 336) + "px";
    panel.style.top = (r.bottom + 6) + "px";
    const close = () => { panel.remove(); document.removeEventListener("click", onDoc); };
    const onDoc = (e) => { if (!panel.contains(e.target) && e.target !== anchor && !anchor.contains(e.target)) close(); };
    setTimeout(() => document.addEventListener("click", onDoc), 0);
    addEventListener("hashchange", close, { once: true });
    $("[data-snooze]", panel).onclick = (e) => { e.stopPropagation(); state.snoozeUntil = Date.now() + 15 * 60 * 1000; toast("Notifications snoozed for 15 minutes", { kind: "ok" }); close(); };
    $$("[data-id]", panel).forEach(n => n.onclick = () => { close(); Evidence.pendingOpen = +n.dataset.id; go("evidence"); });
  },
};

/* =========================================================================
   9a2. PHONE NOTIFICATIONS  ("Allow notifications" — a system notification +
   vibrate on each new detection, on the device the teacher is using. Works on
   Android and on iPhone once Vigil is Added to Home Screen over the secure
   (https) link. Registers a service worker so it's an installable app.
   ========================================================================= */
const PhoneNotify = {
  reg: null, KEY: "vigil.notify",
  async init() {
    if (MOCK) return;
    if ("serviceWorker" in navigator) {
      try { PhoneNotify.reg = await navigator.serviceWorker.register("/app/sw.js", { scope: "/app/" }); } catch {}
    }
    // Already opted in? Make sure the server still has this phone's push
    // subscription (survives server restarts / re-installs).
    if (PhoneNotify.on()) PhoneNotify.subscribePush();
  },
  supported() { return "Notification" in window; },
  on() { return localStorage.getItem(PhoneNotify.KEY) === "1" && PhoneNotify.supported() && Notification.permission === "granted"; },
  async enable() {
    if (!PhoneNotify.supported()) { toast("This device can't show notifications", { msg: "On iPhone, tap Share → Add to Home Screen first.", kind: "info" }); return false; }
    let p = Notification.permission;
    if (p !== "granted") { try { p = await Notification.requestPermission(); } catch { p = "denied"; } }
    if (p !== "granted") { localStorage.setItem(PhoneNotify.KEY, "0"); toast("Notifications are blocked", { msg: "Allow them for this site in your browser settings.", kind: "info" }); return false; }
    localStorage.setItem(PhoneNotify.KEY, "1");
    await PhoneNotify.subscribePush();                 // real push (fires when app is CLOSED)
    PhoneNotify.fire({ _test: true });                 // confirm it works right away
    return true;
  },
  disable() { localStorage.setItem(PhoneNotify.KEY, "0"); PhoneNotify.unsubscribePush(); },

  // Convert the server's base64url VAPID public key to the byte array the
  // Push API wants for applicationServerKey.
  _urlB64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const arr = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
    return arr;
  },
  // Subscribe this phone to server-sent push and register it with Vigil. Safe
  // to call repeatedly — reuses an existing subscription. Fails quietly; the
  // in-app local notification still works even if push can't be set up.
  async subscribePush() {
    try {
      if (!PhoneNotify.reg || !("PushManager" in window)) return;
      const r = await fetch("/api/push/vapid").then(x => x.json()).catch(() => null);
      if (!r || !r.enabled || !r.key) return;
      let sub = await PhoneNotify.reg.pushManager.getSubscription();
      if (!sub) {
        sub = await PhoneNotify.reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: PhoneNotify._urlB64ToUint8Array(r.key),
        });
      }
      await fetch("/api/push/subscribe", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sub),
      });
    } catch (e) { /* push is best-effort; local notifications remain */ }
  },
  async unsubscribePush() {
    try {
      if (!PhoneNotify.reg || !("PushManager" in window)) return;
      const sub = await PhoneNotify.reg.pushManager.getSubscription();
      if (!sub) return;
      await fetch("/api/push/unsubscribe", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: sub.endpoint }),
      }).catch(() => {});
      await sub.unsubscribe().catch(() => {});
    } catch {}
  },
  fire(a) {
    if (!PhoneNotify.on()) return;
    const test = a && a._test;
    const title = test ? "Vigil notifications are on" : `Phone detected · ${a.camera}`;
    const body = test ? "You'll be alerted here the moment a phone is spotted."
                      : `${Math.round((a.confidence || 0) * 100)}% confidence · tap to review`;
    const opts = { body, icon: "/app/icon-192.png", badge: "/app/icon-192.png",
                   tag: "vigil-" + ((a && a.id) || "test"), renotify: true,
                   vibrate: [140, 70, 140], data: { id: a && a.id } };
    try {
      if (PhoneNotify.reg && PhoneNotify.reg.showNotification) PhoneNotify.reg.showNotification(title, opts);
      else new Notification(title, opts);
    } catch {}
    try { navigator.vibrate && navigator.vibrate([140, 70, 140]); } catch {}
  },
};

/* =========================================================================
   9b. UPDATE FLOW  (Claude-Code style background self-update)
   When the packaged app CAN self-update, "Download" fetches the new build in
   the background while you keep working; when it's ready it says "Restart to
   update", and the swap happens on the next quit. When it CAN'T (dev, plain
   web, or an old build), it falls back to opening the release page. Both the
   Settings panel and the sidebar chip drive and observe this one controller.
   ========================================================================= */
const UpdateFlow = {
  info: null, last: { state: "idle", progress: 0 }, _poll: null, _subs: new Set(),
  canSelf() { return !!(UpdateFlow.info && UpdateFlow.info.can_self_update); },
  subscribe(fn) { UpdateFlow._subs.add(fn); try { fn(UpdateFlow.last); } catch {} return () => UpdateFlow._subs.delete(fn); },
  _emit(s) { UpdateFlow.last = s; UpdateFlow._subs.forEach(fn => { try { fn(s); } catch {} }); },

  /* User asked to get the update. Background-downloads if we can self-update;
     otherwise opens the release page in the browser. */
  download(info) {
    UpdateFlow.info = info || UpdateFlow.info;
    if (!UpdateFlow.info) return;
    if (!UpdateFlow.canSelf()) { openExternal(UpdateFlow.info.url); return; }
    if (UpdateFlow.last.state === "downloading" || UpdateFlow.last.state === "ready") return;
    if (MOCK) return UpdateFlow._mock();
    api.updateStart().then(s => { UpdateFlow._emit(s); UpdateFlow._startPoll(); }).catch(() => {});
  },
  _startPoll() {
    if (UpdateFlow._poll) return;
    UpdateFlow._poll = setInterval(async () => {
      let s; try { s = await api.updateState(); } catch { return; }
      UpdateFlow._emit(s);
      if (s.state === "ready" || s.state === "error") { clearInterval(UpdateFlow._poll); UpdateFlow._poll = null; }
    }, 1000);
  },
  restart() {
    if (MOCK) { toast("Restarting to finish update…", { kind: "ok" }); return; }
    api.updateApply(true).catch(() => {});
    toast("Restarting to finish update…", { msg: "Vigil will reopen updated.", kind: "ok" });
  },
  _mock() {          // browser (?mock=1) simulation of a background download
    let p = 0; UpdateFlow._emit({ state: "downloading", progress: 0 });
    const t = setInterval(() => {
      p += 0.17;
      if (p >= 1) { clearInterval(t); UpdateFlow._emit({ state: "ready", progress: 1, version: (UpdateFlow.info || {}).latest }); }
      else UpdateFlow._emit({ state: "downloading", progress: p });
    }, 450);
  },
};

/* =========================================================================
   9c. UPDATES  (automatic — publish a release and every running app learns)
   The app quietly asks its own server (which asks GitHub, cached 1h) shortly
   after launch and every few hours. A new version paints a sidebar chip and
   shows one toast; "skip this version" is remembered until the next one.
   ========================================================================= */
const Updates = {
  info: null, timer: null,
  start() {
    setTimeout(() => Updates.check(), 15000);              // never slow launch
    Updates.timer = setInterval(() => Updates.check(), 6 * 3600 * 1000);
  },
  async check() {
    let d;
    try { d = await api.updateCheck(); } catch { return; } // offline → silent
    if (!d || !d.update_available) return;
    if (localStorage.getItem("vigil.skipVer") === d.latest) return;
    const fresh = !Updates.info || Updates.info.latest !== d.latest;
    Updates.info = d;
    UpdateFlow.info = d;
    Updates.paint();
    if (fresh && sessionStorage.getItem("vigil.updateToast") !== d.latest) {
      sessionStorage.setItem("vigil.updateToast", d.latest);
      toast(`Vigil ${d.latest} is available`, {
        msg: d.can_self_update ? "Click to download it in the background" : "Click to download the update",
        kind: "info", timeout: 9000,
        onClick: () => Updates.act(),
      });
    }
  },
  // Chip / toast click: download if idle, restart if a build is staged.
  act() {
    const s = UpdateFlow.last;
    if (s.state === "ready") UpdateFlow.restart();
    else if (s.state !== "downloading") UpdateFlow.download(Updates.info);
  },
  paint() {
    const chip = $("#updateChip");
    if (!chip || !Updates.info) return;
    chip.classList.remove("hidden");
    if (!Updates._sub) Updates._sub = UpdateFlow.subscribe(() => Updates._paintChip());
    Updates._paintChip();
  },
  _paintChip() {
    const chip = $("#updateChip"); if (!chip || !Updates.info) return;
    const label = $("#updateChipLabel", chip); if (!label) return;
    const s = UpdateFlow.last;
    if (s.state === "downloading") label.textContent = `Downloading ${Math.round((s.progress || 0) * 100)}%`;
    else if (s.state === "ready") label.textContent = "Restart to update";
    else label.textContent = `Update ${Updates.info.latest}`;
  },
  skip() {
    if (Updates.info) localStorage.setItem("vigil.skipVer", Updates.info.latest);
    const chip = $("#updateChip"); if (chip) chip.classList.add("hidden");
    toast("Okay — skipping this version", { msg: "You'll be told about the next one.", kind: "info" });
  },
};

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
  const nav = (id, ic, label, badge) => `<div class="nav__item ${state.route===id?"is-active":""}" data-route="${id}" role="link" tabindex="0" title="${label}" ${state.route===id?'aria-current="page"':""}>${icon(ic)}<span>${label}</span>${badge?`<span class="nav__badge" id="navBadge">${badge}</span>`:""}</div>`;
  $("#app").innerHTML = `
    <a href="#view" class="skip-link" id="skipLink">Skip to content</a>
    <aside class="nav" role="navigation" aria-label="Primary">
      <div class="nav__resize" id="navResize" title="Drag to resize · double-click to reset"></div>
      <div class="nav__brand">${LOGO}<span class="nav__brand-name">Vigil</span></div>
      <div class="nav__section">Monitor</div>
      ${nav("live","live","Live Footage")}
      ${nav("evidence","evidence","Evidence", state.stats.pending || "")}
      <div class="nav__section">Manage</div>
      ${nav("users","users","Users")}
      ${nav("settings","settings","Settings")}
      <div class="nav__spacer"></div>
      <div class="nav__update hidden" id="updateChip" role="button" tabindex="0" title="A new version of Vigil is ready — click to download">
        ${icon("download")}<span id="updateChipLabel">Update</span>
        <button class="nav__update-x" id="updateSkip" title="Skip this version" aria-label="Skip this version">${icon("x")}</button>
      </div>
      <div class="nav__user" id="navUser">
        <span class="avatar">${initials(state.me.username)}</span>
        <div class="nav__user-meta"><div class="nav__user-name">${esc(state.me.username||"—")}</div><div class="nav__user-role">${state.me.role==="admin"?"Administrator":"Invigilator"}</div></div>
      </div>
    </aside>
    <header class="topbar">
      <button class="btn btn--icon btn--ghost btn--sm" id="navToggle" title="Toggle sidebar (⌥⌘S)" aria-label="Toggle sidebar">${icon("sidebar")}</button>
      <div><div class="topbar__title" id="tbTitle"></div></div>
      <div class="topbar__spacer"></div>
      <button class="topbar__search" id="cmdkBtn" title="Search Vigil" aria-label="Open command palette">${icon("search")}<span>Search Vigil…</span><span class="kbd">${/mac/i.test(navigator.platform) ? "⌘K" : "Ctrl K"}</span></button>
      ${isAdmin() ? `<button class="btn btn--icon btn--ghost btn--sm" id="phoneBtn" title="Watch on your phone" aria-label="Watch on your phone">${icon("phone")}</button>` : ""}
      <button class="btn btn--icon btn--ghost btn--sm bell" id="bellBtn" title="Notifications" aria-label="Notifications">${icon("bell")}<span class="bell__count hidden" id="bellCount">0</span></button>
      <button class="btn btn--icon btn--ghost btn--sm" id="themeBtn" title="Toggle theme" aria-label="Toggle light or dark theme">${icon(document.documentElement.dataset.theme==="dark"?"sun":"moon")}</button>
      <span class="topbar__clock tnum" id="clock"></span>
    </header>
    <main class="content" id="view" tabindex="-1"></main>
    <div class="nav-scrim" id="navScrim"></div>`;
  $("#skipLink").onclick = (e) => { e.preventDefault(); const v = $("#view"); if (v) { v.focus(); v.scrollIntoView(); } };
  // On phones a nav tap navigates AND closes the drawer.
  $$("[data-route]").forEach(n => { const goRoute = () => { go(n.dataset.route); closeNav(); }; n.onclick = goRoute; n.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goRoute(); } }; });
  $("#navScrim").onclick = closeNav;
  $("#navUser").onclick = (e) => { const r = e.currentTarget.getBoundingClientRect();
    contextMenu(r.left, r.top - 8, [
      { label: state.me.username, header: true },
      { label: "Settings", icon: "settings", onClick: () => go("settings") },
      { sep: true },
      { label: "Sign out", icon: "logout", onClick: () => location.href = "/logout" },
    ]); };
  $("#themeBtn").onclick = () => {
    const cur = document.documentElement.dataset.theme;      // resolved (auto → actual)
    setTheme(cur === "dark" ? "light" : "dark");
    $("#themeBtn").innerHTML = icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon");
  };
  $("#bellBtn").onclick = (e) => { e.stopPropagation(); Notify.openPanel($("#bellBtn")); };
  { const pb = $("#phoneBtn"); if (pb) pb.onclick = () => PhoneAccess.open(); }
  $("#cmdkBtn").onclick = () => Palette.open();
  $("#navToggle").onclick = toggleSidebar;
  navResizer($("#navResize"));
  applyNav();
  const chip = $("#updateChip");
  chip.onclick = () => { if (Updates.info) Updates.act(); };
  chip.onkeydown = (e) => { if (e.key === "Enter" && Updates.info) Updates.act(); };
  $("#updateSkip").onclick = (e) => { e.stopPropagation(); Updates.skip(); };
  Updates.paint();                 // repaint if a check already found one
  Notify.paintBell();
  // macOS desktop uses the native inset titlebar (real traffic lights drawn by
  // the OS over our content) — nothing to render here; .is-inset only pads the
  // brand so it clears the window buttons.
  startClock();
}

function go(route) { location.hash = "#/" + route; }

async function mount() {
  const route = (location.hash.replace(/^#\/?/, "") || "live").split("?")[0];
  state.route = ROUTES[route] ? route : "live";
  localStorage.setItem("vigil.route", state.route);   // reopen where you left off
  // tear down anything transient left over from the previous view
  $$(".menu").forEach(m => m.remove());
  $("#overlays").innerHTML = "";
  if (current && current.destroy) current.destroy();
  // update nav active + title without full reflow of feeds
  $$("[data-route]").forEach(n => { const on = n.dataset.route === state.route; n.classList.toggle("is-active", on); on ? n.setAttribute("aria-current", "page") : n.removeAttribute("aria-current"); });
  const r = ROUTES[state.route];
  $("#tbTitle") && ($("#tbTitle").textContent = r.title);
  const view = $("#view");
  view.innerHTML = "";
  current = r.view;
  await r.view.render(view);
}

/* "auto" follows the OS live (macOS appearance changes apply instantly). */
const sysDark = matchMedia("(prefers-color-scheme: dark)");
function setTheme(t) {
  state.theme = t; localStorage.setItem("vigil.theme", t);
  const resolved = t === "auto" ? (sysDark.matches ? "dark" : "light") : t;
  document.documentElement.dataset.theme = resolved;
  // Windows desktop: repaint the native titlebar to match (win_native.py).
  const papi = window.pywebview && window.pywebview.api;
  if (papi && papi.set_caption && document.documentElement.classList.contains("is-win"))
    try { papi.set_caption(resolved === "dark"); } catch {}
}
sysDark.addEventListener("change", () => { if (state.theme === "auto") setTheme("auto"); });
addEventListener("pywebviewready", () => setTheme(state.theme));

/* ---- Desktop sidebar: persisted width, drag-resize, rail collapse ---- */
function applyNav() {
  const root = document.documentElement;
  root.style.setProperty("--nav-w", state.navW + "px");
  root.classList.toggle("is-navrail", state.navRail);
  const tb = $("#navToggle");
  if (tb) tb.setAttribute("aria-label", state.navRail ? "Expand sidebar" : "Collapse sidebar");
}
const isMobile = () => window.matchMedia("(max-width: 720px)").matches;
function closeNav() { document.documentElement.classList.remove("is-navopen"); }
function toggleSidebar() {
  if (isMobile()) {                       // phones: the toggle opens/closes the drawer
    document.documentElement.classList.toggle("is-navopen");
    return;
  }
  state.navRail = !state.navRail;         // desktop: collapse to an icon rail
  localStorage.setItem("vigil.navRail", state.navRail ? "1" : "0");
  applyNav();
}
function navResizer(handle) {
  let startX = 0, startW = 0;
  handle.onmousedown = (e) => {
    e.preventDefault(); startX = e.clientX; startW = state.navW;
    document.body.style.cursor = "col-resize";
    document.documentElement.classList.add("is-navdrag");   // suspend width transition
    const move = (ev) => {
      state.navW = Math.min(320, Math.max(184, startW + ev.clientX - startX));
      document.documentElement.style.setProperty("--nav-w", state.navW + "px");
    };
    const up = () => {
      removeEventListener("mousemove", move); removeEventListener("mouseup", up);
      document.body.style.cursor = "";
      document.documentElement.classList.remove("is-navdrag");
      localStorage.setItem("vigil.navW", state.navW);
    };
    addEventListener("mousemove", move); addEventListener("mouseup", up);
  };
  handle.ondblclick = () => { state.navW = 232; localStorage.setItem("vigil.navW", 232); applyNav(); };
}

function focusSearch() {
  const s = $("#camSearch, #evSearch, #uSearch");
  if (s) s.focus(); else Palette.open();
}
function refreshView() { mount(); }

function startClock() {
  const tick = () => { const c = $("#clock"); if (c) c.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); };
  tick(); clearInterval(window.__clk); window.__clk = setInterval(tick, 1000);
}

/* Command palette (⌘K / Ctrl-K) — quick nav + actions, Raycast-style. */
const Palette = {
  open() {
    if ($(".cmdk")) return;
    const cmds = Palette.commands();
    const scrim = h(`<div class="scrim cmdk-scrim"><div class="cmdk" role="dialog" aria-modal="true" aria-label="Command palette">
      <div class="cmdk__head">${icon("search")}<input class="cmdk__input" placeholder="Search commands…" aria-label="Search commands" autocomplete="off"></div>
      <div class="cmdk__list" id="cmdkList" role="listbox"></div></div></div>`);
    $("#overlays").appendChild(scrim);
    const input = $(".cmdk__input", scrim), list = $("#cmdkList", scrim);
    let active = 0, filtered = cmds;
    const paintActive = () => $$(".cmdk__item", list).forEach(n => n.classList.toggle("is-active", +n.dataset.i === active));
    const scrollActive = () => { const n = $(".cmdk__item.is-active", list); if (n) n.scrollIntoView({ block: "nearest" }); };
    const render = () => {
      list.innerHTML = filtered.length
        ? filtered.map((c, i) => `<div class="cmdk__item ${i === active ? "is-active" : ""}" data-i="${i}" role="option">${icon(c.icon)}<span>${esc(c.label)}</span>${c.hint ? `<span class="cmdk__hint kbd">${esc(c.hint)}</span>` : ""}</div>`).join("")
        : `<div class="cmdk__empty">No matching commands</div>`;
      $$(".cmdk__item", list).forEach(n => { n.onmousemove = () => { active = +n.dataset.i; paintActive(); }; n.onclick = () => run(+n.dataset.i); });
    };
    const run = (i) => { const c = filtered[i]; if (!c) return; close(); c.run(); };
    const filter = () => { const q = input.value.toLowerCase().trim(); filtered = q ? cmds.filter(c => (c.label + " " + (c.keywords || "")).toLowerCase().includes(q)) : cmds; active = 0; render(); };
    const untrap = trapFocus(scrim);
    const close = () => { untrap(); scrim.remove(); document.removeEventListener("keydown", onKey, true); };
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, filtered.length - 1); paintActive(); scrollActive(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); paintActive(); scrollActive(); }
      else if (e.key === "Enter") { e.preventDefault(); run(active); }
    };
    scrim.addEventListener("click", (e) => { if (e.target === scrim) close(); });
    input.oninput = filter;
    document.addEventListener("keydown", onKey, true);
    render(); input.focus();
  },
  commands() {
    const admin = isAdmin(), out = [];
    out.push({ label: "Go to Live Footage", icon: "live", hint: "1", run: () => go("live") });
    out.push({ label: "Go to Evidence", icon: "evidence", hint: "2", run: () => go("evidence") });
    if (admin) out.push({ label: "Go to Users", icon: "users", hint: "3", run: () => go("users") });
    out.push({ label: "Go to Settings", icon: "settings", hint: "4", run: () => go("settings") });
    if (admin) out.push(
      { label: "Add camera", icon: "plus", keywords: "new camera", run: () => { go("live"); setTimeout(() => CameraForm.open(), 60); } },
      { label: "Watch on your phone", icon: "phone", keywords: "mobile qr teacher share lan wifi", run: () => PhoneAccess.open() },
      { label: "Pause all cameras", icon: "pause", keywords: "stop", run: () => api.pauseAll().then(() => { toast("All cameras paused", { kind: "ok" }); if (state.route === "live") Live.refresh(true); }) },
      { label: "Resume all cameras", icon: "play", keywords: "start", run: () => api.resumeAll().then(() => { toast("All cameras resumed", { kind: "ok" }); if (state.route === "live") Live.refresh(true); }) },
    );
    out.push(
      { label: `Switch to ${state.theme === "dark" ? "light" : "dark"} theme`, icon: state.theme === "dark" ? "sun" : "moon", keywords: "theme appearance dark light", run: () => { setTheme(state.theme === "dark" ? "light" : "dark"); const tb = $("#themeBtn"); if (tb) tb.innerHTML = icon(state.theme === "dark" ? "sun" : "moon"); } },
      { label: "Check for updates", icon: "download", keywords: "version upgrade", run: () => { Settings.section = "updates"; go("settings"); } },
      { label: "Sign out", icon: "logout", keywords: "logout exit", run: () => location.href = "/logout" },
    );
    return out;
  },
};

/* Keyboard-shortcuts help overlay (press ?). */
const ShortcutsHelp = {
  open() {
    if ($(".sc-help")) return;
    const mac = /mac/i.test(navigator.platform);
    const mod = mac ? "⌘" : "Ctrl", alt = mac ? "⌥" : "Alt";
    const groups = [
      ["Navigation", [[[mod, "1"], "Live Footage"], [[mod, "2"], "Evidence"], [[mod, "3"], "Users"], [[mod, "4"], "Settings"], [[mod, "K"], "Command palette"], [[mod, "F"], "Find"], [["/"], "Focus search"]]],
      ["Actions", [[[mod, "N"], "Add camera"], [["⇧", mod, "E"], "Export evidence"], [[mod, "R"], "Refresh view"], [[alt, mod, "S"], "Toggle sidebar"], [[mod, ","], "Settings"]]],
      ["General", [[["Esc"], "Close / dismiss"], [["?"], "This help"]]],
    ];
    const node = h(`<div class="modal sc-help" role="dialog" aria-modal="true">
      <div class="modal__head"><div class="modal__title">Keyboard shortcuts</div><div class="spacer"></div><button class="btn btn--icon btn--ghost" data-x aria-label="Close">${icon("x")}</button></div>
      <div class="modal__body">${groups.map(([g, items]) => `
        <div><div class="stat__label" style="margin-bottom:6px">${g}</div>
        ${items.map(([keys, label]) => `<div class="row" style="justify-content:space-between;padding:5px 0"><span>${esc(label)}</span><span class="row" style="gap:4px">${keys.map(k => `<span class="kbd" style="margin:0">${esc(k)}</span>`).join("")}</span></div>`).join("")}</div>`).join("")}
      </div></div>`);
    const close = openModal(node);
    $("[data-x]", node).onclick = close;
  },
};

/* -------------------------------------------------------------------------
   Native menu bridge — the macOS menu bar (mac_native.py) calls
   window.vigilMenu('<cmd>'); browser keyboard shortcuts route here too, so
   menus, keys and buttons all share one set of actions.
   ------------------------------------------------------------------------- */
window.vigilMenu = (cmd) => {
  if (cmd.startsWith("goto:")) return go(cmd.slice(5));
  switch (cmd) {
    case "settings":       return go("settings");
    case "new-camera":
      if (!isAdmin()) return;
      if (state.route !== "live") go("live");
      return void setTimeout(() => CameraForm.open(), state.route === "live" ? 0 : 80);
    case "export":
      if (state.route === "evidence") return Evidence.export();
      Evidence.pendingExport = true; return go("evidence");
    case "search":         return focusSearch();
    case "refresh":        return refreshView();
    case "toggle-sidebar": return toggleSidebar();
    case "shortcuts":      return ShortcutsHelp.open();
    case "palette":        return Palette.open();
  }
};

/* Global keyboard shortcuts */
function shortcuts(e) {
  const mod = e.metaKey || e.ctrlKey;
  if ((e.key === "k" || e.key === "K") && mod) { e.preventDefault(); Palette.open(); return; }
  // Desktop-grade ⌘ shortcuts. In the packaged Mac app most of these arrive
  // via the native menu bar instead; this path covers the browser (and any
  // key the menu doesn't own).
  if (mod && e.altKey && e.code === "KeyS") { e.preventDefault(); toggleSidebar(); return; }
  if (mod && !e.altKey) {
    const nav = { "1": "live", "2": "evidence", "3": "users", "4": "settings", ",": "settings" };
    if (nav[e.key] && !e.shiftKey) { e.preventDefault(); go(nav[e.key]); return; }
    if ((e.key === "f" || e.key === "F") && !e.shiftKey) { e.preventDefault(); focusSearch(); return; }
    if ((e.key === "r" || e.key === "R") && !e.shiftKey) { e.preventDefault(); refreshView(); return; }
    if ((e.key === "n" || e.key === "N") && !e.shiftKey) { e.preventDefault(); window.vigilMenu("new-camera"); return; }
    if ((e.key === "e" || e.key === "E") && e.shiftKey) { e.preventDefault(); window.vigilMenu("export"); return; }
    // Windows desktop: Ctrl+W closes the window (the browser owns it otherwise).
    if ((e.key === "w" || e.key === "W") && !e.shiftKey &&
        document.documentElement.classList.contains("is-win")) {
      const papi = window.pywebview && window.pywebview.api;
      if (papi && papi.close) { e.preventDefault(); papi.close(); }
      return;
    }
    return;
  }
  if (e.target.matches("input, textarea, select")) { if (e.key === "Escape") e.target.blur(); return; }
  if (e.key === "?") { e.preventDefault(); ShortcutsHelp.open(); return; }
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
  if (state.me.desktop) {
    document.documentElement.classList.add("is-desktop");
    if (/mac/i.test(navigator.platform) || /mac/i.test(navigator.userAgent))
      document.documentElement.classList.add("is-inset");
    else if (/win/i.test(navigator.platform) || /Windows/i.test(navigator.userAgent)) {
      document.documentElement.classList.add("is-win");
      setTheme(state.theme);          // re-resolve so the caption syncs too
    }
  }
  // Phones get a purpose-built teacher experience, not the admin dashboard.
  if (TeacherMobile.enabled()) { await TeacherMobile.start(); return; }
  try { state.stats = await api.stats(); } catch {}
  // Open on the page you last used (only when no explicit route was asked for).
  if (!location.hash) {
    const last = localStorage.getItem("vigil.route");
    if (last && ROUTES[last]) history.replaceState(null, "", "#/" + last);
  }
  shell();
  addEventListener("hashchange", mount);
  document.addEventListener("keydown", shortcuts);
  await mount();
  Notify.start();               // app-wide detection awareness (bell + toasts)
  PhoneNotify.init();           // register the service worker (installable + notifications)
  Updates.start();              // automatic update notice (chip + one toast)
}
/* =========================================================================
   TEACHER MOBILE  — a purpose-built phone experience for invigilators.
   Minimal, glanceable, fluent: Home (status + rooms) · Alerts · Settings, and
   a full-screen live view on tap. Reuses the whole api/stream layer; adds no
   server routes. Takes over #app on phones (see boot). Styled by teacher.css.
   ========================================================================= */
const TeacherMobile = {
  enabled: () => !state.me.desktop && isMobile(),
  tab: "home",
  cameras: [], status: {}, alerts: [],
  _feeds: [], _poll: null, _sig: "",

  async start() {
    document.documentElement.classList.add("is-teacher");
    $("#app").innerHTML = `<div class="tm" id="tm"></div>`;
    await this.load();
    this.render();
    try { PhoneNotify.init(); } catch {}
    // Auto-refresh on its own: pull fresh cameras/alerts/status every 6s and
    // re-render if anything changed (live camera tiles refresh continuously).
    this._poll = setInterval(() => this.load().then(() => this.softUpdate()), 6000);
  },

  async load() {
    try {
      const [cams, st, ev] = await Promise.all([api.cameras(), api.cameraStatus(), api.evidence("")]);
      this.cameras = (cams || []).filter(c => c.enabled !== false);
      this.status = st || {};
      this.alerts = (ev || []).slice(0, 40);
    } catch (_) {}
  },

  // ---- derived ----
  pending() { return this.alerts.filter(a => a.status === "pending"); },
  camId(label) { const c = this.cameras.find(x => x.label === label); return c ? c.id : ""; },
  imgFor(a) { return MOCK ? mockFrame("e" + a.id) : (a.image || `/evidence/image/${a.id}`); },
  sig() { return JSON.stringify([this.tab, this.cameras.map(c => c.id),
            Object.values(this.status), this.pending().map(a => a.id)]); },

  // ---- render ----
  render() {
    const el = $("#tm"); if (!el) return;
    el.innerHTML = this.screen() + this.tabbar();
    this._sig = this.sig();
    this.wire();
    this.mountFeeds();
  },
  softUpdate() {                 // called on poll — don't yank the rug mid live-view
    if ($("#overlays").children.length) return;
    if (this.sig() === this._sig) return;   // nothing meaningful changed; keep feeds running
    this.render();
  },
  go(tab) { this.tab = tab; this.render(); },

  screen() {
    if (this.tab === "alerts")   return this.alertsScreen();
    if (this.tab === "settings") return this.settingsScreen();
    return this.home();
  },

  home() {
    const hr = new Date().getHours();
    const greet = hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
    const p = this.pending(), a = p[0];
    const status = a
      ? `<button class="tm-status tm-status--alert" data-live="${esc(this.camId(a.camera))}" data-alert="${a.id}">
           <div class="tm-status__ic">${icon("alert")}</div>
           <div class="tm-status__txt"><b>Phone detected</b><span>${esc(a.camera)} · ${esc(a.time || "")}${p.length > 1 ? ` · +${p.length - 1} more` : ""}</span></div>
           <div class="tm-status__go">${icon("chevron")}</div>
         </button>`
      : `<div class="tm-status tm-status--ok">
           <div class="tm-status__ic">${icon("check")}</div>
           <div class="tm-status__txt"><b>All clear</b><span>${this.cameras.length} ${this.cameras.length === 1 ? "room" : "rooms"} watched</span></div>
         </div>`;
    const rooms = this.cameras.length
      ? this.cameras.map((c, i) => this.roomCard(c, i)).join("")
      : `<div class="tm-empty">No rooms assigned yet.<br>Ask your admin to add you to a camera.</div>`;
    return `<div class="tm-screen">
      <div class="tm-head"><div class="tm-hello">${greet}</div><div class="tm-name">${esc(state.me.username || "there")}</div></div>
      ${status}
      <div class="tm-section">Your rooms</div>
      <div class="tm-rooms">${rooms}</div>
    </div>`;
  },
  roomCard(c, i) {
    const st = this.status[c.id] || "online";
    const active = this.pending().some(a => a.camera === c.label);
    const dot = st === "online" ? "ok" : st === "offline" ? "off" : "idle";
    const label = st === "online" ? "Live" : st === "offline" ? "Offline" : st === "scheduled" ? "Scheduled" : "Paused";
    return `<button class="tm-room ${active ? "tm-room--alert" : ""}" data-live="${c.id}" style="animation-delay:${i * 40}ms">
      <div class="tm-room__thumb"><img data-feed="${c.id}" alt="">${active ? `<div class="tm-room__flag">${icon("alert")}</div>` : ""}</div>
      <div class="tm-room__meta"><div class="tm-room__name">${esc(c.label)}</div>
        <div class="tm-room__sub"><span class="tm-dot tm-dot--${dot}"></span>${label}</div></div>
    </button>`;
  },

  alertsScreen() {
    const rows = this.alerts.length
      ? this.alerts.map((a, i) => this.alertRow(a, i)).join("")
      : `<div class="tm-empty">No detections yet.</div>`;
    return `<div class="tm-screen">
      <div class="tm-head"><div class="tm-name">Alerts</div></div>
      <div class="tm-alerts">${rows}</div></div>`;
  },
  alertRow(a, i) {
    const pct = Math.round((a.confidence || 0) * 100);
    const kind = a.status === "pending" ? "warn" : a.status === "confirmed" ? "alert" : "dim";
    const label = a.status === "pending" ? "New" : a.status === "confirmed" ? "Confirmed" : "Dismissed";
    return `<button class="tm-alert" data-live="${esc(this.camId(a.camera))}" data-alert="${a.id}" style="animation-delay:${i * 30}ms">
      <div class="tm-alert__thumb"><img src="${this.imgFor(a)}" alt=""></div>
      <div class="tm-alert__body">
        <div class="tm-alert__title">${esc(a.thing || "Phone")} · ${pct}%</div>
        <div class="tm-alert__sub">${esc(a.camera)} · ${esc(a.time || "")}</div>
      </div>
      <span class="tm-pill tm-pill--${kind}">${label}</span>
    </button>`;
  },

  settingsScreen() {
    const notifOn = (() => { try { return PhoneNotify.on(); } catch { return false; } })();
    const dark = state.theme !== "light";
    return `<div class="tm-screen">
      <div class="tm-head"><div class="tm-name">Settings</div></div>
      <div class="tm-profile"><div class="tm-avatar">${initials(state.me.username || "?")}</div>
        <div><div class="tm-profile__name">${esc(state.me.username || "—")}</div><div class="tm-profile__role">Invigilator</div></div></div>
      <div class="tm-list">
        <div class="tm-row"><div class="tm-row__l">${icon("bell")} Notifications</div>
          <button class="tm-toggle ${notifOn ? "is-on" : ""}" id="tmNotif"></button></div>
        <div class="tm-row"><div class="tm-row__l">${icon("moon")} Dark mode</div>
          <button class="tm-toggle ${dark ? "is-on" : ""}" id="tmDark"></button></div>
        <div class="tm-row"><div class="tm-row__l">${icon("info")} Version</div>
          <span class="tm-row__r">v${esc(state.me.version || "—")}</span></div>
      </div>
      <a class="tm-signout" href="/logout">${icon("logout")} Sign out</a>
    </div>`;
  },

  tabbar() {
    const t = (id, ic, label) => `<button class="tm-tab ${this.tab === id ? "is-active" : ""}" data-tab="${id}">${icon(ic)}<span>${label}</span></button>`;
    return `<nav class="tm-tabbar">${t("home", "grid", "Home")}${t("alerts", "bell", "Alerts")}${t("settings", "settings", "Settings")}</nav>`;
  },

  // ---- feeds ----
  mountFeeds() {
    this.stopFeeds();
    $$("[data-feed]", $("#tm")).forEach(img => this._feeds.push(startFeed(img, img.dataset.feed)));
  },
  stopFeeds() { this._feeds.forEach(fn => { try { fn(); } catch (_) {} }); this._feeds = []; },

  // ---- interactions ----
  wire() {
    const el = $("#tm");
    $$("[data-tab]", el).forEach(b => b.onclick = () => this.go(b.dataset.tab));
    $$("[data-live]", el).forEach(b => b.onclick = () => this.openLive(b.dataset.live, b.dataset.alert));
    const nt = $("#tmNotif", el);
    if (nt) nt.onclick = async () => {
      if (MOCK) { nt.classList.toggle("is-on"); toast("Notifications " + (nt.classList.contains("is-on") ? "on" : "off") + " (demo)", { kind: "ok" }); return; }
      try {
        if (PhoneNotify.on()) { PhoneNotify.disable(); nt.classList.remove("is-on"); toast("Notifications off", { kind: "ok" }); }
        else { const ok = await PhoneNotify.enable(); nt.classList.toggle("is-on", !!ok); }
      } catch { toast("Notifications aren't available here", { kind: "info" }); }
    };
    const dk = $("#tmDark", el);
    if (dk) dk.onclick = () => { const dark = !dk.classList.contains("is-on"); dk.classList.toggle("is-on", dark); setTheme(dark ? "dark" : "light"); };
  },

  openLive(id, alertId) {
    if (!id) { toast("That camera isn't available", { kind: "info" }); return; }
    const c = this.cameras.find(x => x.id === id) || { label: "Camera" };
    const a = alertId ? this.alerts.find(x => String(x.id) === String(alertId))
                      : this.pending().find(x => x.camera === c.label);
    const node = h(`<div class="tm-live">
      <div class="tm-live__bar"><button class="tm-back" data-back>${icon("chevron")}Back</button>
        <div class="tm-live__title">${esc(c.label)}</div><div style="width:78px"></div></div>
      <div class="tm-live__stage"><img id="tmLiveImg" alt=""></div>
      ${a ? `<div class="tm-live__incident">
        <div class="tm-inc__row"><span class="tm-inc__badge">${icon("alert")} ${esc(a.thing || "Phone")} ${Math.round((a.confidence || 0) * 100)}%</span>
          <span class="tm-inc__time">${esc(a.time || "")}</span></div>
        ${a.description ? `<div class="tm-inc__desc">${esc(a.description)}</div>` : ""}
        ${a.status === "pending" ? `<div class="tm-inc__actions">
          <button class="tm-btn tm-btn--ghost" data-review="dismiss">Dismiss</button>
          <button class="tm-btn" data-review="confirm">Confirm</button></div>` : ""}
      </div>` : ""}</div>`);
    $("#overlays").appendChild(node);
    const img = $("#tmLiveImg", node);
    const stop = startFeed(img, id);
    const close = () => { stop(); node.remove(); };
    $("[data-back]", node).onclick = close;
    $$("[data-review]", node).forEach(btn => btn.onclick = async () => {
      const action = btn.dataset.review;
      if (!MOCK) { try { await api.reviewAlert(a.id, action); } catch (_) {} }
      if (a) a.status = action === "confirm" ? "confirmed" : "dismissed";
      toast(action === "confirm" ? "Marked as confirmed" : "Dismissed", { kind: "ok" });
      close(); this.render();
    });
  },
};

// Dev hook — only exposed in mock mode (?mock=1), never in the real app.
if (MOCK) window.__vigil = { recoverNode, RECOVER, Live, Evidence, Settings, Notify, Updates, PhoneAccess, PhoneNotify, TeacherMobile, Palette, ShortcutsHelp, toast, go, state };
boot();
})();
