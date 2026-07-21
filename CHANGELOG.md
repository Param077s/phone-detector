# Changelog

All notable changes to Vigil. Dates are the release date.

## 1.2.0
- **Detection schedules** — a camera can be set to only run detection during
  set hours (e.g. Exam Hall 1, 10:00–13:00, weekdays) instead of always-on.
  Set it per camera in the camera form, or select several cameras on the Live
  wall and apply one schedule — or pause/resume — to all of them at once.
  Outside its hours a camera idles: no detection, no recording. Overnight
  windows (e.g. 22:00–06:00) are supported. Cameras with no schedule are
  unchanged (always on).
- **Automatic update notice** — Vigil now checks for a newer version shortly
  after launch and every few hours, showing a quiet sidebar chip and one
  toast when an update is ready (in addition to the manual check in Settings).
- **Complete redesign** — Vigil no longer looks like a dashboard. The
  cameras are the page: a deep stage with luminous feed panels, one quiet
  status line instead of stat cards, a glass command bar, and a sidebar
  dock that collapses to an icon rail. New motion throughout (staggered
  entrances, gliding panels, spring presses) and drawn illustrations for
  every empty state. Same features, same workflow.
- **A real Mac app** — native menu bar (File/Edit/View/Window/Help) with
  full keyboard shortcuts (⌘1–4, ⌘F, ⌘N, ⇧⌘E, ⌘,, ⌥⌘S), native About
  panel, translucent sidebar over the real macOS material, and ⌘W now
  hides the window while detection keeps running (click the Dock icon to
  bring it back). The window remembers its size and position.
- **A real Windows app** — Mica backdrop behind the sidebar, titlebar
  color that follows the app's light/dark theme live, taskbar identity,
  window size/position memory, Ctrl+W to close, and a proper installer
  (Start Menu entry, uninstall listing, optional desktop shortcut).
- **Preferences that stick** — theme, sidebar width and state, and your
  last-opened page now survive relaunches (two launch-time bugs fixed:
  a rotating localhost port and private browsing mode were silently
  wiping saved settings and sign-ins every start).
- **Auto appearance** — a new Auto theme follows your system's light/dark
  setting live, on both platforms.

## 1.1.6
- **Native Windows titlebar** — the titlebar now merges with the app on
  Windows: always-dark caption painted the app's own color (no more white
  strip on light-mode PCs), Mica backdrop on Windows 11, and the real
  minimize/maximize/close buttons with snap layouts kept intact.

## 1.1.5
- **No more crash on quit** — quitting with ⌘Q ended with a crash report every
  time; the app now exits cleanly however you close it.
- **Real macOS window chrome** — genuine native traffic-light buttons (with
  hover glyphs and system behavior) replacing the web-drawn ones, content
  running edge-to-edge under a hidden titlebar, and dragging only on the top
  strip like every other Mac app.
- **Context menus fixed** — Remove / Edit / Pause camera and the Users row
  menus did nothing when clicked; they all work now.
- **Settings actually save** — "Save changes" was silently resetting settings
  to defaults; values now persist (and are re-read after saving).
- **Evidence** — the detail drawer's Download button now saves the snapshot,
  and the Bookmarked filter no longer hides results behind a stale status
  filter.
- **Storage** — "Clear dismissed evidence" is now a real action: confirmation,
  then permanent deletion of dismissed events and their snapshots.
- **Users** — "Reset password" opens a proper set-password flow.
- **Pause all** button now flips to "Resume all" so its state is always clear.
- **Updates land instantly** — the app no longer runs stale cached UI code
  after an update.

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
