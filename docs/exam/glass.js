// The glass bar's edge, for every page that has one.
//
// The bottom hairline appears only once something has scrolled under the bar —
// a line beneath a bar at rest is a border drawn for no reason.
//
// This is a scroll listener rather than an IntersectionObserver. The observer is
// the tidier instrument and was the first choice, but nothing available could
// confirm it ever fired, and this could be proven. It early-returns on every
// frame that does not cross the threshold, so the work per scroll frame is a
// comparison.
(() => {
  const bar = document.querySelector(".glassbar");
  if (!bar) return;
  let on = null;
  const sync = () => {
    const want = scrollY > 4;
    if (want === on) return;
    on = want;
    bar.classList.toggle("lifted", want);
  };
  addEventListener("scroll", sync, { passive: true });
  addEventListener("resize", sync, { passive: true });
  sync();
})();
