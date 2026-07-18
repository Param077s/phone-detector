# Changelog

All notable changes to Vigil. Dates are the release date.

## 1.1.4
- **Accurate app version** — the built app now reports its real version in
  Finder / Get Info (previous builds always said 1.0.0). The bundle version is
  read from the app itself at build time, so "Check for updates" and the
  installed app can never disagree.

## 1.1.3
- **Error-recovery states** — calm, actionable panels for offline / no-engine /
  storage-full / model-not-ready / camera-permission-blocked / corrupted-file.
- **Command palette** (⌘K / Ctrl-K) for quick navigation and actions, with a
  discoverability chip in the top bar.
- **Keyboard-shortcuts overlay** (press `?`) and a keyboard-navigable sidebar,
  skip-to-content link, and focus trapping in dialogs.
- **Evidence** — multi-select with bulk confirm / dismiss / export (and a
  confirmation step), a date-range filter (All / Today / 7 days / 30 days), and
  clickable detection toasts that jump straight to the event.
- **Cameras** — source-type + status details in fullscreen and the right-click
  menu; tiles are keyboard-openable.
- **Loading skeletons** across the main screens.

## 1.1.2
- **Check for updates** — Settings → Updates shows your current version and checks
  GitHub for a newer release, with a one-click link to the download.
- **Branded installer** — the macOS `.dmg` is now a proper drag-to-Applications
  window (dark, on-brand, with the drag arrow).

## 1.1.1
- **Native frameless window on macOS** — the sidebar runs flush to the top with
  custom traffic-light controls (Linear/Arc-style). Windows keeps its standard
  native frame.
- **Material & motion polish** — tactile "lit-from-above" surfaces on cards and
  dialogs, spring feedback on presses.
- **Security hardening** — strict response headers (Content-Security-Policy,
  clickjacking protection, MIME-sniff protection), per-IP login rate-limiting,
  and stronger Google Sign-In token verification (issuer + audience + email).
- **Desktop login simplified** — password sign-in in the app; Google Sign-In
  stays on the web/localhost version (it can't work inside an embedded webview).
- **Fix** — no more crash dialog when quitting while a detection is running.

## 1.1.0
- **Premium desktop redesign** — a native desktop app that opens in its own
  window: no Terminal, no browser, no visible localhost.
- Redesigned **Live Footage, Evidence, Users, Settings** on a new design system,
  with app-wide notifications, drag-to-reorder cameras, evidence zoom / bookmark
  / CSV export, and a first-run setup screen.
