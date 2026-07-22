/* Vigil service worker — enables "Add to Home Screen" (installable PWA) and
   makes detection notifications tappable. No offline caching: Vigil always
   needs its live server, so we never serve stale pages. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

// Tap a "phone detected" notification → focus the open app, or open it.
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of wins) { if ("focus" in c) return c.focus(); }
    if (self.clients.openWindow) return self.clients.openWindow("/app/");
  })());
});
