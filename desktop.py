#!/usr/bin/env python3
"""
Vigil — native desktop shell.

Runs the existing Vigil server (app.py) inside THIS process and shows it in a
native window. No browser, no Terminal, no visible localhost — the redesigned
UI at /app is the whole interface.

This file adds nothing to detection/AI. It only:
  1. shows a native setup/onboarding splash (web/splash.html),
  2. imports app.py (which loads the YOLO engine) and starts the server on a
     private loopback port,
  3. swaps the window over to the live app once it's ready.

Run:  ./venv/bin/python desktop.py      (or double-click "Vigil Desktop.command")
"""
import os
import sys
import time
import socket
import threading

FROZEN = getattr(sys, "frozen", False)
# Resource dir holds bundled web/, splash and model. In a PyInstaller build
# that's the unpack dir (sys._MEIPASS); from source it's this folder.
RES = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
HERE = RES


def _user_data_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(base, "Vigil")


if FROZEN:
    # A packaged app can't write inside its own read-only bundle, so all
    # config/evidence goes to a per-user data folder; web/ and the model are
    # read from the bundle.
    DATA = _user_data_dir()
    os.makedirs(DATA, exist_ok=True)
    os.environ["VIGIL_DATA_DIR"] = DATA
    os.environ["VIGIL_WEB_DIR"] = os.path.join(RES, "web")
    # Tell the server which installed Vigil.app to self-update (background
    # download + swap-on-quit). sys.executable is …/Vigil.app/Contents/MacOS/Vigil.
    _exe = os.path.abspath(sys.executable)
    _i = _exe.find(".app" + os.sep + "Contents" + os.sep + "MacOS")
    if _i != -1:
        os.environ["VIGIL_APP_PATH"] = _exe[: _i + len(".app")]
    for _m in ("yolo11m.pt", "yolo11n.pt"):        # bundled default model, if present
        _p = os.path.join(RES, _m)
        if os.path.exists(_p):
            os.environ.setdefault("MODEL_NAME", _p)
            break
    os.chdir(DATA)
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Makes app.py treat the redesigned /app as home, so every login path
# (password, Google, first-run setup) lands inside the new UI.
os.environ["VIGIL_DESKTOP"] = "1"

try:
    import webview  # pywebview
except ImportError:
    sys.stderr.write(
        "\nVigil desktop needs pywebview.\n"
        "  ./venv/bin/pip install -r requirements-desktop.txt\n\n")
    sys.exit(1)


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _stable_port():
    """A per-user port that stays the SAME across launches. The web origin
    (localhost:PORT) scopes localStorage — with a random port every run, the
    UI's remembered theme/sidebar/last-page silently reset each launch."""
    cfg = os.path.join(os.getcwd(), ".vigil-port")
    try:
        port = int(open(cfg).read().strip())
        if 1024 < port < 65536:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:   # free → reuse it
                    return port
    except Exception:
        pass
    port = _free_port()
    try:
        open(cfg, "w").write(str(port))
    except Exception:
        pass
    return port


PORT = _stable_port()
SPLASH = os.path.join(HERE, "web", "splash.html")
_state = {"error": None}


def _js(window, code):
    """Push a progress update into the splash; ignore if it isn't ready yet."""
    try:
        window.evaluate_js(code)
    except Exception:
        pass


def _wait_port(port, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.25)
    return False


def _model_present():
    """The configured weight file — ultralytics downloads it during import if
    it's missing, which is the one step that may need the network."""
    try:
        import json
        name = "yolo11m.pt"
        cfg = os.path.join(HERE, "settings.json")
        if os.path.exists(cfg):
            name = json.load(open(cfg)).get("MODEL_NAME", name)
        name = os.environ.get("MODEL_NAME", name)
        return os.path.exists(os.path.join(HERE, name))
    except Exception:
        return True


def _native_titlebar():
    """The 'hidden titlebar' look real Mac apps use (Linear/Arc/Slack): REAL
    traffic lights with native hover glyphs and behavior, content running to
    the top edge, and dragging only on the titlebar strip. Replaces the old
    frameless window whose web-drawn buttons and drag-from-anywhere felt fake."""
    if sys.platform != "darwin":
        return
    try:
        import AppKit
        from webview.platforms.cocoa import BrowserView

        def apply():
            for i in BrowserView.instances.values():
                w = i.window
                w.setStyleMask_(w.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
                w.setTitlebarAppearsTransparent_(True)
                w.setTitleVisibility_(AppKit.NSWindowTitleHidden)
                # pywebview paints the titlebar container an opaque window
                # color at creation — that solid strip defeats the transparent
                # titlebar, so clear it.
                try:
                    w.contentView().superview().subviews().lastObject() \
                        .setBackgroundColor_(AppKit.NSColor.clearColor())
                except Exception:
                    pass
                # Make the (web) content view actually occupy the titlebar
                # area — adding the mask alone doesn't re-lay-out an existing
                # window's content.
                try:
                    cv = w.contentView()
                    cv.setFrame_(cv.superview().bounds())
                except Exception:
                    pass

        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(apply)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Window geometry memory (Windows). macOS uses NSWindow frame autosave in
# mac_native.py; here pywebview's own x/y/width/height do the same job.
# ---------------------------------------------------------------------------
_GEOM_FILE = "window.json"


def _load_geometry():
    """Last session's window bounds, sanity-checked. Off-screen placement is
    corrected after boot (once real screen info exists) — see _fix_offscreen."""
    if os.name != "nt":
        return {}
    try:
        import json
        g = json.load(open(_GEOM_FILE))
        w, h = int(g.get("w", 0)), int(g.get("h", 0))
        if not (300 <= w <= 20000 and 200 <= h <= 20000):
            return {}
        return {"x": int(g.get("x", 100)), "y": int(g.get("y", 100)),
                "width": w, "height": h, "maximized": bool(g.get("max"))}
    except Exception:
        return {}


def _save_geometry():
    if os.name != "nt" or _win is None:
        return
    try:
        import json
        maximized = False
        try:                                # winforms-only detail; best effort
            import webview.platforms.winforms as wf
            for f in wf.BrowserView.instances.values():
                maximized = "Maximized" in str(f.WindowState)
        except Exception:
            pass
        json.dump({"x": _win.x, "y": _win.y, "w": _win.width,
                   "h": _win.height, "max": maximized}, open(_GEOM_FILE, "w"))
    except Exception:
        pass


def _fix_offscreen():
    """A remembered position can point at a monitor that no longer exists —
    if no screen contains the window's top strip, pull it back on-screen."""
    try:
        import webview
        x, y, w = _win.x, _win.y, _win.width
        for s in webview.screens:
            sx, sy = getattr(s, "x", 0), getattr(s, "y", 0)
            if sx - w + 80 < x < sx + s.width - 80 and sy - 10 <= y < sy + s.height - 60:
                return
        _win.move(80, 80)
    except Exception:
        pass


def _dispatch_js(cmd):
    """Forward a native menu command into the page (web/app.js: vigilMenu)."""
    try:
        _win and _win.evaluate_js("window.vigilMenu && window.vigilMenu(%r)" % str(cmd))
    except Exception:
        pass


def _boot(window):
    """Runs once the splash is on screen (pywebview calls this after the GUI
    loop starts). Loads the engine, starts the server, then opens the app."""
    _native_titlebar()
    if sys.platform == "darwin":
        # Menu bar, window-frame memory, About panel, Dock reopen, vibrancy.
        try:
            import mac_native
            mac_native.install(window, _dispatch_js)
        except Exception:
            pass
    elif os.name == "nt":
        # Taskbar identity, Mica backdrop, theme-synced immersive titlebar.
        try:
            import win_native
            win_native.install(window, _dispatch_js, transparent=_TRANSPARENT)
        except Exception:
            pass
        _fix_offscreen()
    time.sleep(0.35)  # let the splash DOM settle before we script it
    try:
        _js(window, "vigilSetup.set(0, null, 'Preparing Vigil…')")

        if _model_present():
            _js(window, "vigilSetup.set(1, 100, 'AI models ready')")
        else:
            _js(window, "vigilSetup.set(1, null, 'Downloading AI models…')")

        # Importing app.py builds the YOLO model — the slow first-run step.
        _js(window, "vigilSetup.set(2, null, 'Verifying files…')")
        import app as vigil
        # "Restart now" (web/app.js) → quit so the update helper can swap + reopen.
        vigil._updater.on_restart = lambda: (_save_geometry(), os._exit(0))
        _js(window, "vigilSetup.set(3, null, 'Optimizing performance…')")

        # Bind all interfaces so a phone on the SAME Wi-Fi can open the live
        # wall ("Watch on your phone"). Every route is still login-gated and
        # LAN logins are rate-limited; the app window itself uses localhost.
        # macOS shows a one-time "accept incoming connections?" prompt — allow it.
        _js(window, "vigilSetup.set(4, null, 'Finalizing setup…')")
        os.environ["VIGIL_PORT"] = str(PORT)
        import uvicorn
        config = uvicorn.Config(vigil.app, host="0.0.0.0", port=PORT,
                                log_level="warning", access_log=False)
        server = uvicorn.Server(config)
        threading.Thread(target=server.run, daemon=True).start()

        if not _wait_port(PORT):
            raise RuntimeError("the local service did not start in time")

        _js(window, "vigilSetup.done()")
        time.sleep(0.4)
        # "localhost" (not 127.0.0.1) so Google Sign-In's trusted origin matches.
        window.load_url("http://localhost:%d/app/" % PORT)
        # Re-apply the inset titlebar: the first pass can run before the
        # webview becomes the window's content view (splash still loading),
        # in which case the freshly-installed content view sits below the
        # titlebar again. Idempotent, so applying twice is harmless.
        time.sleep(0.6)
        _native_titlebar()
    except Exception as e:
        _state["error"] = str(e)
        msg = str(e).replace("'", " ")[:140]
        _js(window, "vigilSetup.set(0, null, 'Could not start Vigil: %s')" % msg)


_win = None


class _WinControls:
    """Exposed to the page as window.pywebview.api.* so the frameless window's
    custom traffic-light controls can drive the real OS window."""
    def minimize(self):
        try:
            _win and _win.minimize()
        except Exception:
            pass

    def set_caption(self, dark):
        """Windows: keep the native titlebar's color in step with the app's
        light/dark theme (app.js calls this whenever the theme resolves)."""
        if os.name != "nt":
            return
        try:
            import win_native
            win_native.apply_caption_theme(bool(dark))
        except Exception:
            pass

    def close(self):
        try:
            _win and _win.destroy()
        except Exception:
            pass

    def zoom(self):
        try:
            _win and _win.toggle_fullscreen()
        except Exception:
            pass

    def open_external(self, url):
        """Open a link (e.g. the update download page) in the real browser."""
        import webbrowser
        try:
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                webbrowser.open(url)
        except Exception:
            pass


def _apply_pending_update():
    """If a background-downloaded update is staged, spawn the detached helper
    that waits for us to exit and swaps the bundle in place. Idempotent."""
    try:
        import app as vigil
        vigil._updater.apply(relaunch=False)
    except Exception:
        pass


def _install_quit_hook():
    """Make Cmd-Q (and Dock ▸ Quit) hard-exit like window-close does.

    Quitting goes -[NSApplication terminate:] -> C exit(), which never returns
    through webview.start(), so the os._exit() after it is skipped and C++
    static destructors (torch / MPSGraph) tear down while detection threads are
    still mid-inference — SIGABRT on every quit. Answering the terminate
    request with an immediate hard exit skips that doomed teardown; SQLite
    commits per-write, so nothing is lost."""
    if sys.platform != "darwin":
        return
    try:
        from webview.platforms.cocoa import BrowserView

        def applicationShouldTerminate_(self, app):
            _apply_pending_update()          # swap-on-quit if an update is staged
            os._exit(0)

        BrowserView.AppDelegate.applicationShouldTerminate_ = applicationShouldTerminate_
    except Exception:
        pass
    # Backstop if pywebview's internals ever change: exit() runs atexit
    # handlers newest-first before dylib destructors, so hard-exit there too.
    try:
        import ctypes
        global _ATEXIT_CB
        _ATEXIT_CB = ctypes.CFUNCTYPE(None)(lambda: os._exit(0))
        ctypes.CDLL(None).atexit(_ATEXIT_CB)
    except Exception:
        pass


# Windows: a transparent WebView2 is the prerequisite for the Mica backdrop
# showing through the sidebar (win_native.py). Page surfaces stay opaque via
# CSS until the shell confirms Mica is live, so this is safe on Win10 too.
_TRANSPARENT = os.name == "nt" and os.environ.get("VIGIL_NO_MICA") != "1"


def main():
    global _win
    if os.name == "nt":
        # Before any window exists, so the taskbar groups/icons correctly.
        try:
            import win_native
            win_native.set_taskbar_identity()
        except Exception:
            pass
    geom = _load_geometry()
    # Standard native window everywhere; on macOS _native_titlebar() then hides
    # the titlebar into the content (real traffic lights, titlebar-strip drag).
    _win = webview.create_window(
        "Vigil",
        url="file://%s" % SPLASH,
        width=geom.get("width", 1180), height=geom.get("height", 760),
        x=geom.get("x"), y=geom.get("y"),
        maximized=geom.get("maximized", False),
        min_size=(920, 600),
        background_color="#0B0D10",
        transparent=_TRANSPARENT,
        resizable=True,
        js_api=_WinControls(),
    )
    try:
        _win.events.closing += lambda *a: _save_geometry()
    except Exception:
        pass

    def _on_loaded(*_a):
        """Every page load: tell the UI when the native translucency layer is
        live (macOS vibrancy / Windows Mica) so it can make the sidebar
        translucent (web/vigil.css, .has-vibrancy)."""
        try:
            if sys.platform == "darwin":
                import mac_native as native
            elif os.name == "nt":
                import win_native as native
            else:
                return
            if native.VIBRANT:
                _win.evaluate_js(
                    "document.documentElement.classList.add('has-vibrancy')")
        except Exception:
            pass

    try:
        _win.events.loaded += _on_loaded
    except Exception:
        pass
    _install_quit_hook()
    # private_mode=False: pywebview's default private mode clears cookies and
    # localStorage on EVERY launch — that would sign the user out and forget
    # window/sidebar/theme preferences each time the app opens.
    webview.start(_boot, _win, private_mode=False)
    # Hard-exit once the window closes. Letting Python/C++ run normal exit
    # destructors tears down PyTorch's dispatcher while a detection thread may
    # still be mid-inference on the GPU (Metal/MPS) — that race segfaults on
    # quit (crash report: RegisterOperators dtor vs mps conv2d). SQLite commits
    # per-write, so skipping finalizers loses nothing.
    os._exit(0)


if __name__ == "__main__":
    main()
