"""
Vigil — background self-update (macOS).

Claude-Code-style: the app downloads the new release in the background while
you keep working; when it's ready it just says "restart to finish", and the
swap happens the next time Vigil quits — so the next launch is the new version.
Nothing to drag, no Finder.

Only active in the packaged macOS app (a writable Vigil.app). Everywhere else
(dev, the plain web UI, Windows) `supported()` is False and the UI falls back
to opening the release page.

Flow:
  start()  -> download the release's Vigil.dmg to <data>/updates, mount it,
              copy Vigil.app out to <data>/updates/staged, write ready.json.
  apply()  -> spawn a tiny detached helper that waits for THIS app to quit,
              swaps the staged app over the installed one (with rollback), and
              optionally relaunches. Also run automatically on quit.
"""

import os
import sys
import json
import time
import stat
import shutil
import threading
import subprocess
import urllib.request

_UPDATE_REPO = "Param077s/vigil"
_DMG_ASSET = "Vigil.dmg"


def _version_tuple(v):
    nums = []
    for part in str(v).split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if digits:
            nums.append(int(digits))
    return tuple(nums) or (0,)


def _app_path_from_executable():
    """In the packaged app, sys.executable is
    /Applications/Vigil.app/Contents/MacOS/Vigil — walk up to the .app."""
    exe = os.path.abspath(sys.executable or "")
    marker = ".app" + os.sep + "Contents" + os.sep + "MacOS"
    i = exe.find(marker)
    if i != -1:
        return exe[: i + len(".app")]
    return None


class Updater:
    def __init__(self):
        self._lock = threading.Lock()
        self.state = "idle"          # idle | downloading | ready | error
        self.progress = 0.0          # 0..1 while downloading
        self.version = None          # version being / that was staged
        self.error = None
        self.data_dir = None
        self.app_path = None         # the installed Vigil.app to replace
        self.current_version = None
        self.on_restart = None       # desktop.py sets this to close the window
        self._thread = None
        self._applied = False        # guard so we never spawn two swap helpers

    # ---- setup -----------------------------------------------------------
    def configure(self, data_dir, current_version, app_path=None):
        self.data_dir = data_dir
        self.current_version = current_version
        self.app_path = app_path or (_app_path_from_executable() if getattr(sys, "frozen", False) else None)
        # If a previous session already staged an update, surface it as ready —
        # unless we're now running that version (the swap already happened).
        try:
            m = self._read_manifest()
            if m and _version_tuple(m.get("version")) > _version_tuple(current_version) \
                    and os.path.isdir(self._staged_app()):
                self.state, self.version = "ready", m.get("version")
            elif m:
                self._clear_staged()      # stale (already applied or downgrade)
        except Exception:
            pass

    def supported(self):
        return bool(self.app_path) and sys.platform == "darwin" \
            and os.path.isdir(self.app_path) and os.access(self.app_path, os.W_OK)

    # ---- paths -----------------------------------------------------------
    def _updates_dir(self):
        d = os.path.join(self.data_dir or ".", "updates")
        os.makedirs(d, exist_ok=True)
        return d

    def _staged_app(self):
        return os.path.join(self._updates_dir(), "Vigil.app")

    def _manifest_path(self):
        return os.path.join(self._updates_dir(), "ready.json")

    def _read_manifest(self):
        try:
            with open(self._manifest_path()) as f:
                return json.load(f)
        except Exception:
            return None

    def _clear_staged(self):
        for p in (self._staged_app(), self._manifest_path()):
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                elif os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    # ---- public state ----------------------------------------------------
    def snapshot(self):
        with self._lock:
            return {"state": self.state, "progress": round(self.progress, 3),
                    "version": self.version, "error": self.error,
                    "supported": self.supported(), "current": self.current_version}

    # ---- download + stage ------------------------------------------------
    def start(self):
        """Begin (or resume being) a background download+stage. No-op if a
        download is already running or an update is already staged."""
        if not self.supported():
            return self.snapshot()
        with self._lock:
            if self.state in ("downloading", "ready"):
                return {"state": self.state, "progress": round(self.progress, 3),
                        "version": self.version, "error": self.error,
                        "supported": True, "current": self.current_version}
            self.state, self.progress, self.error = "downloading", 0.0, None
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self.snapshot()

    def _fail(self, msg):
        with self._lock:
            self.state, self.error = "error", msg

    def _run(self):
        try:
            asset_url, version, size = self._latest_dmg()
        except Exception:
            return self._fail("Couldn't reach the update server.")
        if not asset_url:
            return self._fail("No downloadable update was found.")
        if _version_tuple(version) <= _version_tuple(self.current_version):
            with self._lock:
                self.state, self.version = "idle", None
            return
        with self._lock:
            self.version = version

        self._clear_staged()
        dmg = os.path.join(self._updates_dir(), "Vigil-%s.dmg" % version)
        part = dmg + ".part"
        try:
            self._download(asset_url, part, size)
            os.replace(part, dmg)
        except Exception:
            try:
                os.remove(part)
            except Exception:
                pass
            return self._fail("The download didn't finish. It will retry next time.")

        try:
            self._extract_app(dmg, self._staged_app())
        except Exception:
            return self._fail("Couldn't unpack the update.")
        finally:
            try:
                os.remove(dmg)
            except Exception:
                pass

        try:
            with open(self._manifest_path(), "w") as f:
                json.dump({"version": version, "app": self._staged_app(),
                           "target": self.app_path}, f)
        except Exception:
            return self._fail("Couldn't finalize the update.")
        with self._lock:
            self.state, self.progress = "ready", 1.0

    def _latest_dmg(self):
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/releases/latest" % _UPDATE_REPO,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "Vigil"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        version = (data.get("tag_name") or "").lstrip("vV")
        for a in data.get("assets", []):
            if a.get("name") == _DMG_ASSET:
                return a.get("browser_download_url"), version, int(a.get("size") or 0)
        return None, version, 0

    def _download(self, url, dest, total):
        req = urllib.request.Request(url, headers={"User-Agent": "Vigil"})
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
            total = total or int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 20)          # 1 MiB
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    with self._lock:
                        self.progress = min(0.99, got / total)
        if total and got < total * 0.995:
            raise IOError("short read")

    def _extract_app(self, dmg, dest):
        """Mount the DMG read-only, copy Vigil.app out, unmount."""
        mnt = os.path.join(self._updates_dir(), "mnt-%d" % int(time.time()))
        os.makedirs(mnt, exist_ok=True)
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-quiet", "-readonly",
                        "-mountpoint", mnt, dmg], check=True)
        try:
            src = os.path.join(mnt, "Vigil.app")
            if not os.path.isdir(src):
                raise IOError("Vigil.app not in dmg")
            if os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)
            subprocess.run(["ditto", src, dest], check=True)
        finally:
            subprocess.run(["hdiutil", "detach", mnt, "-quiet", "-force"], check=False)
            shutil.rmtree(mnt, ignore_errors=True)

    # ---- apply -----------------------------------------------------------
    def apply(self, relaunch=False):
        """Swap in the staged update. Spawns a detached helper that waits for
        this process to exit first, so it can replace the running .app. Safe to
        call repeatedly; a no-op unless an update is staged."""
        if self.state != "ready" or not self.supported():
            return False
        with self._lock:
            if self._applied:                    # helper already spawned once
                if relaunch and callable(self.on_restart):
                    threading.Timer(0.4, self.on_restart).start()
                return True
            self._applied = True
        staged, target = self._staged_app(), self.app_path
        if not (os.path.isdir(staged) and target):
            return False
        helper = self._write_helper()
        try:
            subprocess.Popen(
                ["/bin/bash", helper, str(os.getpid()), staged, target,
                 "1" if relaunch else "0", self._manifest_path()],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return False
        if relaunch and callable(self.on_restart):
            # give the helper a beat to start waiting, then quit so it can swap
            threading.Timer(0.4, self.on_restart).start()
        return True

    def _write_helper(self):
        path = os.path.join(self._updates_dir(), "apply-update.sh")
        script = r'''#!/bin/bash
# Vigil update helper: wait for the app to quit, then swap the bundle in place.
PID="$1"; STAGED="$2"; TARGET="$3"; RELAUNCH="$4"; MANIFEST="$5"
for _ in $(seq 1 240); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
sleep 0.5
NEW="${TARGET}.new-$$"; OLD="${TARGET}.old-$$"
rm -rf "$NEW" "$OLD"
if /usr/bin/ditto "$STAGED" "$NEW"; then
  if /bin/mv "$TARGET" "$OLD"; then
    if /bin/mv "$NEW" "$TARGET"; then
      /bin/rm -rf "$OLD" "$STAGED" "$MANIFEST"
    else
      /bin/mv "$OLD" "$TARGET"          # rollback
      /bin/rm -rf "$NEW"
    fi
  else
    /bin/rm -rf "$NEW"
  fi
fi
if [ "$RELAUNCH" = "1" ]; then /usr/bin/open "$TARGET"; fi
'''
        with open(path, "w") as f:
            f.write(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return path
