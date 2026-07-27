/* Vigil service worker — enables "Add to Home Screen" (installable PWA) and
   makes detection notifications tappable. No offline caching: Vigil always
   needs its live server, so we never serve stale pages. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

// Server-sent push — THIS is what fires when the app is fully closed or the
// phone is locked. The server signs it with VAPID; the browser's push service
// wakes the worker and we show the notification.
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) {}
  const title = d.title || "Phone detected";
  const opts = {
    body: d.body || "",
    icon: "/app/icon-192.png",
    badge: "/app/icon-192.png",
    // Exam pushes set their own tag (per student) so each updates in place;
    // detection alerts fall back to a per-id tag.
    tag: d.tag || ("vigil-" + (d.id || "push")),
    renotify: true,
    vibrate: [140, 70, 140],
    data: { id: d.id, camera: d.camera, url: d.url },
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});

// Tap a notification → go where it points (exam pushes carry a live-room URL),
// focusing an already-open Vigil window when there is one.
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/app/";
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of wins) {
      if ("focus" in c) {
        try { if ("navigate" in c) await c.navigate(url); } catch (_) {}
        return c.focus();
      }
    }
    if (self.clients.openWindow) return self.clients.openWindow(url);
  })());
});
