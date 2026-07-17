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


PORT = _free_port()
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


def _boot(window):
    """Runs once the splash is on screen (pywebview calls this after the GUI
    loop starts). Loads the engine, starts the server, then opens the app."""
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
        _js(window, "vigilSetup.set(3, null, 'Optimizing performance…')")

        # Start the existing FastAPI app, bound to loopback only.
        _js(window, "vigilSetup.set(4, null, 'Finalizing setup…')")
        import uvicorn
        config = uvicorn.Config(vigil.app, host="127.0.0.1", port=PORT,
                                log_level="warning", access_log=False)
        server = uvicorn.Server(config)
        threading.Thread(target=server.run, daemon=True).start()

        if not _wait_port(PORT):
            raise RuntimeError("the local service did not start in time")

        _js(window, "vigilSetup.done()")
        time.sleep(0.4)
        # "localhost" (not 127.0.0.1) so Google Sign-In's trusted origin matches.
        window.load_url("http://localhost:%d/app/" % PORT)
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


def main():
    global _win
    # macOS: frameless + easy_drag = the flush-to-top, no-titlebar native look;
    # the UI draws its own traffic-light controls (wired to _WinControls), and
    # Cmd-Q / Cmd-W / Cmd-M still work as a fallback. Windows keeps its standard
    # (already native) frame — safer, and it still gets all the UI polish.
    frameless = sys.platform == "darwin"
    _win = webview.create_window(
        "Vigil",
        url="file://%s" % SPLASH,
        width=1180, height=760, min_size=(920, 600),
        background_color="#0B0D10",
        frameless=frameless,
        easy_drag=frameless,
        resizable=True,
        js_api=_WinControls(),
    )
    webview.start(_boot, _win)
    # Hard-exit once the window closes. Letting Python/C++ run normal exit
    # destructors tears down PyTorch's dispatcher while a detection thread may
    # still be mid-inference on the GPU (Metal/MPS) — that race segfaults on
    # quit (crash report: RegisterOperators dtor vs mps conv2d). SQLite commits
    # per-write, so skipping finalizers loses nothing.
    os._exit(0)


if __name__ == "__main__":
    main()
