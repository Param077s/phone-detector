/* ============================================================================
   Vigil Exams — soft navigation
   ============================================================================

   WHY THIS FILE EXISTS

   The exam app was seven separate HTML documents, and every link between them
   was a document navigation. That is what put the spinner in the browser tab,
   and the spinner was telling the truth: each click threw the whole tab away
   and started again. The cost of one click on "Live room" was

     · the JS heap discarded — including the Supabase client
     · `@supabase/supabase-js` re-imported from esm.sh, a THIRD-PARTY origin,
       so a DNS + TLS + fetch round trip before any of our code could run
     · `sb.auth.getUser()` — another round trip, before the first useful pixel
     · the realtime socket torn down and re-handshaked
     · the stylesheet re-parsed and the page rebuilt from an empty DOM

   None of that work is about the page you asked for. It is the price of
   destroying a document, and it is paid on every click.

   So the document stops being destroyed. Links are intercepted, the next page
   is fetched as HTML, and only what actually differs is patched into the DOM
   that is already on screen. The tab never navigates, so the browser never
   shows a loading indicator, and — the part that actually makes it fast — the
   module registry survives. `/exam/sb.js` is imported once for the lifetime of
   the tab. The Supabase client, its auth session and its realtime socket are
   the SAME objects on page seven as on page one. The second navigation costs a
   fetch of a few KB of HTML that was, in most cases, already prefetched while
   the pointer was travelling toward the link.

   WHAT IS DELIBERATELY NOT HERE

   room.html is not managed. A student in an exam room has a camera stream, a
   MediaPipe worker and a heartbeat running; that page is entered once and left
   once, and giving it a soft-navigation escape hatch would be a way to leave an
   exam by accident. It gets a real document load, on purpose, both ways.

   FALLBACK

   Every managed page is still a complete, working document on its own. If this
   module fails to load, or a fetch fails mid-navigation, the links are ordinary
   links and the app degrades to exactly what it was before. Nothing here is
   load-bearing for correctness — only for speed.
   ========================================================================= */

import { sb } from "/exam/sb.js";

/* The pages this router owns. Anything else — room.html, the marketing site,
   /logout — is left to the browser. Matching on the pathname only; the query
   string is what distinguishes one exam from another and must not affect
   whether we handle the click. */
const MANAGED = /^\/exam\/(?:index\.html|console\.html|live\.html|report\.html|findings\.html|history\.html)?$/;

const HTML_TTL = 20_000;   // a prefetched page is worth reusing for this long
const NAV_MS   = 170;      // the transition, when the platform can't do better

const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");

/* ── page lifecycle ─────────────────────────────────────────────────────────
   A page's script now runs more than once per tab, so anything it starts has
   to be something it can stop. These are the four things the pages actually
   start — intervals, listeners, realtime channels and in-flight requests — and
   each one here registers its own teardown at the moment it is created, so a
   page cannot forget to clean up something it never had to remember.

   Without this, leaving the console would leave its 5-second poll and its
   realtime subscription running against a DOM that is no longer on screen, and
   an hour of navigating would end with a dozen of them. */
let hooks = [];
let ctl = new AbortController();

export function onLeave(fn) { hooks.push(fn); }

/** setInterval, stopped automatically when this page is navigated away from. */
export function every(ms, fn) {
  const id = setInterval(fn, ms);
  onLeave(() => clearInterval(id));
  return id;
}

/** addEventListener, removed automatically when this page is navigated away from. */
export function listen(target, type, fn, opts) {
  target.addEventListener(type, fn, opts);
  onLeave(() => target.removeEventListener(type, fn, opts));
  return fn;
}

/** A Supabase realtime channel, unsubscribed automatically on leaving. */
export function channel(name) {
  const ch = sb.channel(name);
  onLeave(() => { try { sb.removeChannel(ch); } catch (_) {} });
  return ch;
}

/** Aborts when this page is navigated away from. Pass to fetch, or to
    supabase-js via `.abortSignal(pageSignal())`, so a slow query for a page
    nobody is looking at stops instead of landing in a dead callback. */
export const pageSignal = () => ctl.signal;

function teardown() {
  ctl.abort();
  ctl = new AbortController();
  const list = hooks;
  hooks = [];
  for (const fn of list) { try { fn(); } catch (_) {} }
}

/* ── data cache ─────────────────────────────────────────────────────────────
   Navigating back to the console should not re-ask the server everything it
   asked ninety seconds ago before it can draw. Values are held briefly and
   handed out while a refresh happens underneath, so a return visit paints from
   memory on the first frame and corrects itself a moment later if it needs to.

   Held as PROMISES, not values: two callers a millisecond apart share one
   request rather than racing two. */
const store = new Map();

export function cached(key, make, ttl = 12_000) {
  const hit = store.get(key);
  if (hit && performance.now() - hit.at < ttl) return hit.p;
  const p = Promise.resolve().then(make);
  store.set(key, { at: performance.now(), p });
  p.catch(() => { if (store.get(key)?.p === p) store.delete(key); });
  return p;
}

/** Drop cached data whose key starts with `prefix` — call after a write, so
    the next read is the truth rather than what was true before the write. */
export function invalidate(prefix = "") {
  for (const k of [...store.keys()]) if (k.startsWith(prefix)) store.delete(k);
}

/* Pages register a warmer so that hovering a link can start fetching the DATA
   that link will need, not just its HTML. The console uses this: pointing at
   "Live room" begins reading that exam's row before the click lands. */
let warmers = [];
export function onPrefetch(fn) {
  warmers.push(fn);
  onLeave(() => { warmers = warmers.filter(w => w !== fn); });
}

/* ── document prefetch ──────────────────────────────────────────────────────
   The HTML is a few KB and is usually still in the HTTP cache, but "usually"
   is not a guarantee and a cold fetch is the one thing between a click and a
   paint. So we start it on the intent signals that precede the click: the
   pointer arriving over a link, a touch starting on one, or a link taking
   keyboard focus. On a mouse that buys 80–250ms; on a keyboard, more. */
const docs = new Map();

function fetchDoc(url) {
  const hit = docs.get(url);
  if (hit && performance.now() - hit.at < HTML_TTL) return hit.p;
  const p = fetch(url, { credentials: "same-origin" })
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
    .then(html => new DOMParser().parseFromString(html, "text/html"));
  docs.set(url, { at: performance.now(), p });
  p.catch(() => { if (docs.get(url)?.p === p) docs.delete(url); });
  return p;
}

export function prefetch(href) {
  const u = managed(href);
  if (!u || u.href === location.href) return;
  fetchDoc(u.href).catch(() => {});
  for (const w of warmers) { try { w(u); } catch (_) {} }
}

function managed(href) {
  let u;
  try { u = new URL(href, location.href); } catch (_) { return null; }
  if (u.origin !== location.origin) return null;
  if (!MANAGED.test(u.pathname)) return null;
  return u;
}

/* ── morph ──────────────────────────────────────────────────────────────────
   Used on the glass bar and nothing else (see the swap below for why).

   The bar is on every teacher page and is nearly identical across them, so
   rebuilding it would mean a new element, a lost scroll state, a re-run of
   backdrop-filter over the whole strip, and a flash on the frame where the old
   one is gone and the new one has not painted. Instead the live bar is walked
   against the incoming one and only real differences are applied — the "·
   Console" label becomes "· Your exams", a button appears or goes, and the bar
   itself, the brand mark and its SVG survive from the first page to the last.

   Reused elements have their inline handlers cleared first. A page assigns its
   own on every run, so this costs nothing — and without it the console's
   sign-out button would arrive on the history page still wired to the
   console's copy of the closure it captured.

   Keyed by `id` where there is one, so controls that move along the bar are
   moved rather than rewritten. */
const REUSABLE_PROPS = ["onclick", "onkeydown", "oninput", "onchange", "onsubmit", "onmousedown"];
const keyOf = n => (n.nodeType === 1 && (n.id || n.getAttribute("data-k"))) || null;
const alike = (a, b) => a.nodeType === b.nodeType && a.nodeName === b.nodeName;

function morph(from, to) {
  syncAttrs(from, to);
  morphChildren(from, to);
}

function morphChildren(parent, next) {
  const wanted = [...next.childNodes];
  const keyed = new Map();
  for (let n = parent.firstChild; n; n = n.nextSibling) {
    const k = keyOf(n);
    if (k) keyed.set(k, n);
  }

  let cursor = parent.firstChild;
  for (const want of wanted) {
    const k = keyOf(want);

    // a node we already have, identified by id — move it here and patch it
    if (k && keyed.has(k)) {
      const found = keyed.get(k);
      keyed.delete(k);
      if (found !== cursor) parent.insertBefore(found, cursor);
      else cursor = cursor.nextSibling;
      if (alike(found, want)) { patch(found, want); continue; }
      found.replaceWith(want);                       // same id, different element
      continue;
    }

    // otherwise reuse whatever is in this position, if it is the same kind of
    // thing and is not spoken for by an id of its own
    if (cursor && alike(cursor, want) && !keyOf(cursor)) {
      const here = cursor;
      cursor = cursor.nextSibling;
      patch(here, want);
      continue;
    }

    parent.insertBefore(want, cursor);
  }

  while (cursor) { const dead = cursor; cursor = cursor.nextSibling; dead.remove(); }
  for (const orphan of keyed.values()) orphan.remove();
}

function patch(node, want) {
  if (node.nodeType !== 1) {
    if (node.nodeValue !== want.nodeValue) node.nodeValue = want.nodeValue;
    return;
  }
  // an opt-out, for anything whose identity matters more than its markup
  if (node.hasAttribute("data-static")) return;
  for (const p of REUSABLE_PROPS) if (node[p]) node[p] = null;
  syncAttrs(node, want);
  // the browser keeps live value/checked off the attributes, so they have to be
  // said explicitly or a reused input arrives on the next page still filled in
  if (node.tagName === "INPUT" || node.tagName === "TEXTAREA" || node.tagName === "SELECT") {
    const v = want.getAttribute("value");
    if (node.value !== (v ?? "")) node.value = v ?? "";
    if (node.type === "checkbox" || node.type === "radio") node.checked = want.hasAttribute("checked");
  }
  morphChildren(node, want);
}

function syncAttrs(el, want) {
  for (const a of want.attributes) if (el.getAttribute(a.name) !== a.value) el.setAttribute(a.name, a.value);
  for (const a of [...el.attributes]) if (!want.hasAttribute(a.name)) el.removeAttribute(a.name);
}

/* ── per-page <style> ───────────────────────────────────────────────────────
   Each page carries its own block of CSS, and they genuinely conflict: `.bar`,
   `.row` and `.empty` mean different things on the console and in the report.
   So exactly one may be live at a time.

   They are not removed, though. A <style> that has been parsed once is disabled
   with `media="not all"` and re-enabled on the way back, which is a flag flip
   rather than a re-parse — so the second visit to a page costs nothing at all
   for its stylesheet. */
const styles = new Map();

/* `adopt` is for the page the tab actually loaded: its <style> is ALREADY in
   the head, and copying it in would leave the document carrying the same rules
   twice — harmless to look at, which is exactly what makes it the kind of thing
   that survives. Every later page arrives as a parsed document whose nodes
   belong to another document, so those really do have to be copied. */
function useStyles(key, incoming, adopt) {
  for (const [k, els] of styles) if (k !== key) els.forEach(el => el.media = "not all");
  if (styles.has(key)) { styles.get(key).forEach(el => el.removeAttribute("media")); return; }
  if (adopt) { styles.set(key, incoming); return; }
  const added = incoming.map(src => {
    const el = document.createElement("style");
    el.textContent = src.textContent;
    document.head.appendChild(el);
    return el;
  });
  styles.set(key, added);
}

/* ── scripts ────────────────────────────────────────────────────────────────
   A <script> that is moved does not run again — the browser marks it as
   already-executed — so each page's module is re-created from its source and
   appended. That re-execution is the whole point: it is what gives the new page
   its behaviour. What it does NOT do is re-download anything, because every
   `import` in it resolves out of the module registry that this tab has been
   accumulating since the first load.

   External scripts are run once per tab and skipped afterwards. A page that
   pulls in a shared script is asking for that script's effects to exist, not
   for them to happen again — re-running one on every page change is how a tab
   ends up with six copies of the same scroll listener. */
const ranSrc = new Set();

function runScripts(list) {
  for (const old of list) {
    const src = old.getAttribute("src");
    if (src) {
      if (ranSrc.has(src)) continue;
      ranSrc.add(src);
    }
    const s = document.createElement("script");
    for (const a of old.attributes) s.setAttribute(a.name, a.value);
    if (!src) s.textContent = old.textContent;
    document.body.appendChild(s);
  }
}

/* ── the glass bar's hairline ───────────────────────────────────────────────
   The bottom hairline appears only once something has scrolled under the bar —
   a line beneath a bar at rest is a border drawn for no reason.

   This used to be glass.js, a per-page script that found the bar on load and
   listened for scroll. That does not survive a router: the bar now outlives the
   page it arrived with, and re-running the script per page would stack a
   listener per navigation. One listener lives here instead, re-pointed at
   whichever bar is current after each swap.

   Still a scroll listener rather than an IntersectionObserver, for the reason
   it always was: the observer is the tidier instrument but nothing available
   could confirm it ever fired, and this could be proven. It early-returns on
   every frame that does not cross the threshold. */
let bar = null;
function syncGlass() {
  if (!bar) return;
  const want = scrollY > 4;
  if (bar.classList.contains("lifted") !== want) bar.classList.toggle("lifted", want);
}
function findBar() { bar = document.querySelector(".glassbar"); syncGlass(); }

/* ── the navigation itself ─────────────────────────────────────────────────*/
let generation = 0;

/** Go to a page, without the browser going anywhere. */
export function go(href) { return visit(href, { mode: "push" }); }

/** Replace the current entry — for redirects, which should not be somewhere
    the back button can return you to. */
export function replace(href) { return visit(href, { mode: "replace" }); }

async function visit(href, { mode = "push", y = 0 } = {}) {
  const u = managed(href);
  if (!u) { location.href = href; return; }             // not ours to handle

  const gen = ++generation;
  const root = document.documentElement;
  root.classList.add("is-navigating");

  let doc;
  try {
    doc = await fetchDoc(u.href);
  } catch (_) {
    location.href = u.href;                             // never strand anyone
    return;
  }
  if (gen !== generation) return;                       // a later click won

  const apply = () => {
    // The URL has to be right BEFORE the page's script runs: every one of these
    // pages reads its subject out of `?e=…` on the first line of its module.
    if (mode === "push") {
      history.replaceState({ vg: 1, y: scrollY }, "");   // remember where we were
      history.pushState({ vg: 1, y: 0 }, "", u.href);
    } else if (mode === "replace") {
      history.replaceState({ vg: 1, y: 0 }, "", u.href);
    }

    teardown();

    const next = document.importNode(doc.body, true);    // never mutate the cache
    const scripts = [...next.querySelectorAll("script")];
    scripts.forEach(s => s.remove());

    useStyles(u.pathname, [...doc.head.querySelectorAll("style")]);

    /* The bar is the one thing meant to survive a page change, and it has to do
       so BY CONSTRUCTION. Morphing the whole body looked like it did that, and
       between the console, the report and the history it even worked — those
       three nest their bar the same way, so the walk lined up. It did not
       survive console → live, where the bar is a direct child of <body>: the
       walk matched the console's .wrap against the live room's .bar and quietly
       repurposed the old bar element into the room's .inner. Nobody would ever
       have SEEN that — every attribute is fixed up on the way through, inside a
       view transition — which is exactly what made it worth removing. An
       element silently re-cast in an unrelated role keeps every listener
       anything ever attached to it.

       So: move the live bar to where the incoming page puts its own, patch its
       contents to match, and let the rest of the body be genuinely new. The bar
       keeps its identity, its scroll state and its listeners; nothing else can
       accidentally keep anything. */
    const incomingBar = next.querySelector(".glassbar");
    const currentBar = document.querySelector(".glassbar");
    if (incomingBar && currentBar) {
      incomingBar.replaceWith(currentBar);
      morph(currentBar, incomingBar);
    }
    syncAttrs(document.body, next);
    document.body.replaceChildren(...next.childNodes);
    document.title = doc.title;

    scrollTo({ top: y, behavior: "instant" });
    findBar();
    runScripts(scripts);
  };

  // The platform's own crossfade where it exists: it snapshots the old frame,
  // so there is no moment with nothing on screen and no reflow to watch.
  if (!reduceMotion.matches && document.startViewTransition) {
    const t = document.startViewTransition(apply);
    try { await t.finished; } catch (_) {}
  } else {
    apply();
    if (!reduceMotion.matches) {
      const el = document.body;
      el.classList.add("nav-enter");
      setTimeout(() => el.classList.remove("nav-enter"), NAV_MS);
    }
  }
  if (gen === generation) root.classList.remove("is-navigating");
}

/* ── wiring, installed once per tab ────────────────────────────────────────*/
if (!window.__vgNav) {
  window.__vgNav = true;

  history.scrollRestoration = "manual";
  if (!history.state || !history.state.vg) history.replaceState({ vg: 1, y: 0 }, "");

  const plainClick = e =>
    e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && !e.defaultPrevented;

  /* On `document`, not `window`. Both are in the bubble path, but listeners on
     the same target fire in registration order, and this module is imported on
     the first line of every page's script — so this runs before any handler a
     page registers on `document`. Pages here do delegate clicks on the document
     and do call stopPropagation on some of them; none of those targets is
     inside a link today, and this makes sure it stays a non-issue rather than a
     bug waiting for someone to put a link inside a chip.

     It does not stop propagation itself: a page's own click handling should
     still see the click it would have seen. */
  document.addEventListener("click", (e) => {
    if (!plainClick(e)) return;
    const a = e.target.closest("a[href]");
    if (!a || a.target || a.hasAttribute("download") || a.hasAttribute("data-hard")) return;
    const raw = a.getAttribute("href");
    /* A hash link is a place on this page, not a page. `href="#"` in particular
       is what a link looks like before its script has filled the destination
       in — and resolving it against the current URL produces "…?e=abc#", which
       is not byte-equal to the current URL and would therefore be treated as a
       navigation TO THE PAGE YOU ARE ALREADY ON. Pressing such a link re-ran
       the page and pushed a history entry, so it read as being sent backwards.
       Links like that are the browser's business. */
    if (!raw || raw.charAt(0) === "#") return;
    const u = managed(raw);
    if (!u) return;
    e.preventDefault();
    if (u.href === location.href) return;
    go(u.href);
  });

  // intent, in the order it arrives: focus and touch are commitments, a pointer
  // arriving over a link is a good guess. All three are cheap to be wrong about.
  let hoverAt = 0;
  const guess = (e) => {
    const a = e.target.closest?.("a[href]");
    if (!a || a.target || a.hasAttribute("data-hard")) return;
    const now = performance.now();
    if (now - hoverAt < 60) return;                     // sweeping across a toolbar
    hoverAt = now;
    prefetch(a.getAttribute("href"));
  };
  addEventListener("pointerenter", guess, { capture: true, passive: true });
  addEventListener("touchstart", guess, { capture: true, passive: true });
  addEventListener("focusin", guess, { passive: true });

  addEventListener("popstate", (e) => {
    // Back out of the app entirely (or into room.html) is a real navigation and
    // the browser has already done it; only handle entries we put there.
    if (!managed(location.href)) { location.reload(); return; }
    visit(location.href, { mode: "none", y: (e.state && e.state.y) || 0 });
  });

  addEventListener("scroll", syncGlass, { passive: true });
  addEventListener("resize", syncGlass, { passive: true });
  findBar();

  // Whatever a page is showing on the way out is still the truth on the way
  // back, so hand the router the initial page's stylesheet under the same key
  // it will be asked for later.
  useStyles(location.pathname, [...document.head.querySelectorAll("style")], true);

  // Everything on screen that we could be asked for next, once the browser is
  // otherwise idle. There are only ever a handful of these.
  const idle = window.requestIdleCallback || (fn => setTimeout(fn, 400));
  idle(() => {
    const seen = new Set();
    for (const a of document.querySelectorAll("a[href]")) {
      const u = managed(a.getAttribute("href"));
      if (!u || seen.has(u.href) || u.href === location.href) continue;
      seen.add(u.href);
      if (seen.size > 6) break;
      prefetch(u.href);
    }
  });
}
