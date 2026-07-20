"""
Vigil — Windows-native application layer (Fluent chrome, Mica, taskbar
identity, theme-synced titlebar). Imported by desktop.py on Windows only —
the peer of mac_native.py, same contract:

  * every step degrades silently — a failure never breaks the launch;
  * the page is told translucency is live ONLY when it actually is
    (has-vibrancy class), so the UI can never render transparent over
    a solid window.

Windows conventions are respected, not imitated from macOS: the REAL frame
stays (Snap Layouts, snap groups, minimize/maximize/restore, multi-monitor,
DPI-per-monitor all come from it) — we only merge the titlebar with the app
(immersive dark/light caption) and put a Mica backdrop behind the window.
"""
import os
import sys

assert os.name == "nt"

VIBRANT = False           # True once Mica + transparent WebView2 are both live
_dispatch = None

APP_ID = "Vigil.Vigil.Desktop"       # AppUserModelID: taskbar identity/grouping

# DWM window attributes (documented; unsupported ids fail harmlessly on Win10)
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36
_DWMWA_SYSTEMBACKDROP_TYPE = 38      # Win11 22H2+: 2 = Mica, 3 = Acrylic

# App surface colors as COLORREF (0x00BBGGRR)
_DARK_BG, _DARK_TX = 0x00100D0B, 0x00EFEBE8      # #0B0D10 / #E8EBEF
_LIGHT_BG, _LIGHT_TX = 0x00F9F7F6, 0x001D1814    # #F6F7F9 / #14181D


def _forms():
    try:
        import webview.platforms.winforms as wf
        return list(wf.BrowserView.instances.values())
    except Exception:
        return []


def _dwm_set(hwnd, attr, value):
    try:
        import webview.platforms.winforms as wf
        wf.DwmSetWindowAttribute(hwnd, attr, value)
    except Exception:
        pass                          # older Windows: attribute not supported


def set_taskbar_identity():
    """Explicit AppUserModelID so the taskbar shows Vigil's own icon and
    groups its windows correctly (instead of inheriting python.exe's)."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def apply_caption_theme(dark=True):
    """Merge the native titlebar with the app: immersive dark mode + caption
    painted the app's own surface color. Called again live whenever the user
    (or Windows auto theme) flips Vigil between dark and light."""
    bg, tx = (_DARK_BG, _DARK_TX) if dark else (_LIGHT_BG, _LIGHT_TX)
    for form in _forms():
        try:
            hwnd = form.Handle.ToInt32()
        except Exception:
            continue
        _dwm_set(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, 1 if dark else 0)
        _dwm_set(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
        _dwm_set(hwnd, _DWMWA_CAPTION_COLOR, bg)
        _dwm_set(hwnd, _DWMWA_TEXT_COLOR, tx)
        _dwm_set(hwnd, _DWMWA_BORDER_COLOR, bg)


def _pin_caption_theme():
    """pywebview re-themes the caption whenever the SYSTEM theme changes;
    keep it pinned to the APP's current look instead."""
    try:
        import webview.platforms.winforms as wf
        wf.BrowserView.BrowserForm.update_title_bar_theme = lambda self: None
    except Exception:
        pass


def enable_mica():
    """Win11 Mica behind the window. Visible through the page only where the
    page itself is transparent (the .has-vibrancy sidebar) — desktop.py
    creates the window with transparent=True on Windows, which makes
    pywebview set the WebView2 DefaultBackgroundColor to transparent.
    Returns True only when every piece is in place."""
    if os.environ.get("VIGIL_NO_MICA") == "1":
        return False
    ok = False
    for form in _forms():
        try:
            hwnd = form.Handle.ToInt32()
            # Backdrop only helps if the browser really is transparent —
            # pywebview only does that for EdgeChromium with transparent=True.
            browser = getattr(form, "browser", None)
            if browser is None or not getattr(form, "pywebview_window", None):
                pass
            _dwm_set(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, 2)     # Mica
            ok = True
        except Exception:
            continue
    return ok


def install(window, dispatch, transparent):
    """Run once the GUI loop is up. `transparent` = the window was created
    with a transparent WebView2 (the prerequisite for Mica showing through)."""
    global _dispatch, VIBRANT
    _dispatch = dispatch
    set_taskbar_identity()
    _pin_caption_theme()
    apply_caption_theme(dark=True)                 # app default; JS re-syncs
    try:
        VIBRANT = bool(transparent) and enable_mica()
    except Exception:
        VIBRANT = False
    try:
        print("[win_native] caption=ok mica=%s" % ("ok" if VIBRANT else "off"),
              file=sys.stderr)
    except Exception:
        pass
