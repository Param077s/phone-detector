/* ============================================================================
   Vigil · soft navigation for the light teacher door
   ============================================================================

   The pages this covers — /console, /app/live.html, /app/report.html — used to
   be reachable only by opening a new tab. Same tab now, which means they have
   to behave like one application rather than three documents, and that is what
   this file is for: the link is intercepted, the next page is fetched, and its
   HTML is swapped into the document that is already open. The tab never
   navigates, so the browser never shows a loading indicator.

   WHY IT IS NOT THE ROUTER IN /exam/nav.js

   That one morphs the DOM and keeps a shared shell alive, because those pages
   ARE a shared shell with different content inside it. These three are not:
   the console, the live wall and the report have separate layouts, separate
   stylesheets and separate scripts. There is nothing to preserve between them,
   so this replaces the body outright — which is simpler, and for pages this
   size, indistinguishable.

   THE TWO THINGS THAT MAKE IT NON-TRIVIAL

   1. `live.js` and `report.js` are classic scripts that declare `const $` at
      the top level. Two classic scripts share one global scope, so running the
      report's after the live room's would throw "Identifier '$' has already
      been declared" and the page would arrive blank. Both are wrapped in an
      IIFE now; this file is why.

   2. The live room and the report load `exam.css`; the console does not. Adding
      a stylesheet during the swap means the new body can paint before its CSS
      arrives — a flash of unstyled content, which is exactly the thing we are
      removing. So a missing sheet is warmed with `rel=preload` BEFORE the swap
      starts, and the real <link> then resolves out of the cache. Preload
      fetches without applying, so warming it cannot restyle the page you are
      still looking at.

   Anything not listed in MANAGED — /logout, /login, /app/exam.html, the
   marketing site — is left to the browser. Those are auth and role boundaries
   and they should get a real document.
   ========================================================================= */
(function () {
  if (window.vigilGo) return;              // already installed in this document

  var MANAGED = /^\/(?:console|app\/(?:live|report)\.html)$/;
  var CACHE_MS = 15000;

  /* ── page lifecycle ──────────────────────────────────────────────────────
     A page's script now runs more than once per tab, so whatever it starts it
     has to be able to stop. These register the teardown at the moment the
     thing is created, so a page cannot forget to clean up something it never
     had to remember. Without it, walking console → live → console → live would
     leave two pollers running against a wall nobody is looking at. */
  var stops = [];
  window.vigilPage = {
    onLeave: function (fn) { stops.push(fn); },
    every: function (ms, fn) {
      var id = setInterval(fn, ms);
      stops.push(function () { clearInterval(id); });
      return id;
    },
    listen: function (target, type, fn, opts) {
      target.addEventListener(type, fn, opts);
      stops.push(function () { target.removeEventListener(type, fn, opts); });
      return fn;
    }
  };
  function teardown() {
    var list = stops; stops = [];
    for (var i = 0; i < list.length; i++) { try { list[i](); } catch (e) {} }
  }

  function managed(href) {
    var u;
    try { u = new URL(href, location.href); } catch (e) { return null; }
    if (u.origin !== location.origin) return null;
    if (!MANAGED.test(u.pathname)) return null;
    return u;
  }

  /* ── fetching ahead ──────────────────────────────────────────────────────
     Started when the pointer arrives over a link, which on a mouse buys most of
     the trip to the click. Holding the text rather than a parsed document: the
     parse is sub-millisecond and a stored Document would keep a whole detached
     tree alive for something that may never be opened. */
  var docs = {};
  function fetchDoc(url) {
    var hit = docs[url];
    if (hit && Date.now() - hit.at < CACHE_MS) return hit.p;
    var p = fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text().then(function (html) { return { html: html, landed: new URL(r.url, location.href) }; });
    });
    docs[url] = { at: Date.now(), p: p };
    p.catch(function () { delete docs[url]; });
    return p;
  }
  function prefetch(href) {
    var u = managed(href);
    if (!u || u.href === location.href) return;
    fetchDoc(u.href).catch(function () {});
  }

  /* Fetch a stylesheet we are about to need without applying it to the page we
     are still showing. `as=style` warms the HTTP cache only. */
  function warmCss(hrefs) {
    return Promise.all(hrefs.map(function (href) {
      return new Promise(function (done) {
        var l = document.createElement("link");
        l.rel = "preload"; l.as = "style"; l.href = href;
        l.onload = l.onerror = function () { done(); };
        document.head.appendChild(l);
        setTimeout(done, 1200);         // never hold a navigation for a slow sheet
      });
    }));
  }

  function sheetHrefs(root) {
    return [].map.call(root.querySelectorAll('link[rel="stylesheet"]'), function (l) {
      return new URL(l.getAttribute("href"), location.href).href;
    });
  }

  function go(href, opts) {
    opts = opts || {};
    var want = managed(href);
    if (!want) { location.href = href; return Promise.resolve(); }
    return fetchDoc(want.href).then(function (got) {
      // The server gets to disagree about where we belong — an expired session,
      // a student account. Anywhere but where we asked for is a real document.
      if (got.landed.pathname !== want.pathname) { location.replace(got.landed.href); return; }

      var doc = new DOMParser().parseFromString(got.html, "text/html");
      var have = sheetHrefs(document.head);
      var need = sheetHrefs(doc.head).filter(function (h) { return have.indexOf(h) < 0; });

      return warmCss(need).then(function () { swap(doc, want, opts); });
    }).catch(function () {
      location.href = want.href;          // never strand anyone mid-navigation
    });
  }

  function swap(doc, want, opts) {
    var apply = function () {
      // The URL has to be right before the scripts run: both live.js and
      // report.js read their exam code out of location.hash on their first line.
      if (opts.replace) history.replaceState({ vg: 1, y: 0 }, "", want.href);
      else {
        history.replaceState({ vg: 1, y: window.scrollY }, "");
        history.pushState({ vg: 1, y: 0 }, "", want.href);
      }

      teardown();
      document.title = doc.title;

      var themeIn = doc.head.querySelector('meta[name="theme-color"]');
      var themeNow = document.head.querySelector('meta[name="theme-color"]');
      if (themeIn && themeNow) themeNow.content = themeIn.getAttribute("content");

      // stylesheets: drop what this page brought, keep what both want, add the
      // rest (already warmed above, so this resolves from cache)
      var wantSheets = sheetHrefs(doc.head);
      [].forEach.call(document.head.querySelectorAll('link[rel="stylesheet"]'), function (l) {
        if (wantSheets.indexOf(new URL(l.getAttribute("href"), location.href).href) < 0) l.remove();
      });
      var still = sheetHrefs(document.head);
      wantSheets.forEach(function (href) {
        if (still.indexOf(href) >= 0) return;
        var l = document.createElement("link");
        l.rel = "stylesheet"; l.href = href;
        document.head.appendChild(l);
      });

      // inline CSS is per-page by definition; [data-keep] opts out
      [].forEach.call(document.head.querySelectorAll("style:not([data-keep])"), function (s) { s.remove(); });
      [].forEach.call(doc.head.querySelectorAll("style"), function (s) {
        document.head.appendChild(document.importNode(s, true));
      });

      var next = document.importNode(doc.body, true);
      var scripts = [].slice.call(next.querySelectorAll("script"));
      scripts.forEach(function (s) { s.remove(); });
      [].slice.call(document.body.attributes).forEach(function (a) { document.body.removeAttribute(a.name); });
      [].slice.call(next.attributes).forEach(function (a) { document.body.setAttribute(a.name, a.value); });
      document.body.replaceChildren.apply(document.body, [].slice.call(next.childNodes));
      window.scrollTo(0, opts.y || 0);

      // A <script> that is merely moved never runs again — the browser marks it
      // executed — so each one is rebuilt. [data-persist] is how this file
      // exempts itself: it is already running, and re-running it would be a
      // request for nothing.
      scripts.forEach(function (old) {
        if (old.hasAttribute("data-persist")) return;
        var s = document.createElement("script");
        [].slice.call(old.attributes).forEach(function (a) { s.setAttribute(a.name, a.value); });
        if (!old.src) s.textContent = old.textContent;
        document.body.appendChild(s);
      });
    };

    if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches)
      document.startViewTransition(apply);
    else apply();
  }

  /* ── the transition ─────────────────────────────────────────────────────
     Injected here rather than written into each page, because the rules have to
     still be live WHILE the swap plays — and a swap is precisely the moment
     each page's own <style> is being taken out. [data-keep] is what the swap
     leaves alone.

     A short crossfade with a 6px rise. The outgoing frame is a snapshot the
     browser holds until the incoming one is opaque, so there is never a frame
     with nothing on it. */
  var vt = document.createElement("style");
  vt.setAttribute("data-keep", "");
  vt.textContent =
    "@media(prefers-reduced-motion:no-preference){" +
      "::view-transition-old(root),::view-transition-new(root){" +
        "animation-duration:.18s;animation-timing-function:cubic-bezier(.2,.7,.2,1)}" +
      "::view-transition-new(root){animation-name:vgSoftIn}" +
      "@keyframes vgSoftIn{from{opacity:0;transform:translateY(6px)}}" +
    "}";
  document.head.appendChild(vt);

  /* ── wiring ─────────────────────────────────────────────────────────────*/
  history.scrollRestoration = "manual";
  if (!history.state || !history.state.vg) history.replaceState({ vg: 1, y: 0 }, "");

  // On `document` rather than `window`: same bubble path, but listeners on one
  // target fire in registration order and this file loads before every page
  // script, so a page that stops propagation on its own delegated clicks cannot
  // accidentally swallow a link.
  document.addEventListener("click", function (e) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.defaultPrevented) return;
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a || a.target || a.hasAttribute("download") || a.hasAttribute("data-hard")) return;
    var u = managed(a.getAttribute("href"));
    if (!u) return;
    e.preventDefault();
    if (u.href === location.href) return;
    go(u.href);
  });

  var lastHover = 0;
  function guess(e) {
    var a = e.target && e.target.closest && e.target.closest("a[href]");
    if (!a || a.target || a.hasAttribute("data-hard")) return;
    var now = Date.now();
    if (now - lastHover < 60) return;          // sweeping across a toolbar
    lastHover = now;
    prefetch(a.getAttribute("href"));
  }
  addEventListener("pointerenter", guess, { capture: true, passive: true });
  addEventListener("touchstart", guess, { capture: true, passive: true });
  addEventListener("focusin", guess, { passive: true });

  addEventListener("popstate", function (e) {
    if (!managed(location.href)) { location.reload(); return; }
    go(location.href, { replace: true, y: (e.state && e.state.y) || 0 });
  });

  window.vigilGo = go;
  window.vigilPrefetch = prefetch;
})();
