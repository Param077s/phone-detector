"""
Vigil — macOS-native application layer (menu bar, window memory, About panel,
Dock behavior, vibrancy). Imported by desktop.py on darwin only.

Everything here degrades silently: if any AppKit call fails (OS change,
pywebview internals moved), the app keeps running with the plain window —
never a crash, never a broken launch.

The menu bar is the real contract of a Mac app: every command here dispatches
into the web UI through window.vigilMenu('<cmd>') (defined in web/app.js), so
menus, keyboard shortcuts, and on-screen controls all drive the same actions.
"""
import os
import sys
import webbrowser

assert sys.platform == "darwin"

import AppKit
import objc

# Retained ObjC objects (targets/menus are weakly referenced by AppKit; if
# Python garbage-collects them, menu items silently stop firing).
_KEEP = []
_dispatch = None          # set by install(): fn(cmd:str) -> None
_window = None            # the pywebview Window (not NSWindow)
VIBRANT = False           # True once the vibrancy underlay is actually live

FRAME_NAME = "VigilMainWindow"
HELP_URL = "https://github.com/Param077s/phone-detector#readme"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _nswindows():
    try:
        from webview.platforms.cocoa import BrowserView
        return [(i, i.window) for i in BrowserView.instances.values()]
    except Exception:
        return []


def _app_version():
    """VIGIL_VERSION from the (lazily imported) server module."""
    m = sys.modules.get("app")
    return getattr(m, "VIGIL_VERSION", "") or ""


class _MenuTarget(AppKit.NSObject):
    """One shared target for every custom menu item; the command string rides
    on the item's representedObject."""

    def invoke_(self, sender):
        cmd = str(sender.representedObject() or "")
        if not cmd:
            return
        if cmd == "about":
            _show_about()
        elif cmd == "help":
            webbrowser.open(HELP_URL)
        elif cmd == "close-window":
            _hide_main_window()
        elif _dispatch:
            _dispatch(cmd)


def _show_about():
    opts = {
        "ApplicationName": "Vigil",
        "ApplicationVersion": _app_version(),
        "Version": "",
        "Credits": AppKit.NSAttributedString.alloc().initWithString_attributes_(
            "On-device AI camera monitoring.\nVideo never leaves this Mac.",
            {AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(11)}),
        "Copyright": "© 2026 Vigil",
    }
    AppKit.NSApp.activateIgnoringOtherApps_(True)
    AppKit.NSApp.orderFrontStandardAboutPanelWithOptions_(opts)


def _hide_main_window():
    """⌘W: hide, don't quit — the real Mac convention. The Dock icon (or
    Window ▸ Vigil) brings it back; detection keeps running meanwhile."""
    for _, w in _nswindows():
        w.orderOut_(None)


def _show_main_window():
    for _, w in _nswindows():
        w.makeKeyAndOrderFront_(None)
    AppKit.NSApp.activateIgnoringOtherApps_(True)


def _install_reopen_hook():
    """Dock-icon click after ⌘W re-opens the window (standard app behavior)."""
    try:
        from webview.platforms.cocoa import BrowserView

        def applicationShouldHandleReopen_hasVisibleWindows_(self, app, flag):
            if not flag:
                _show_main_window()
            return True

        BrowserView.AppDelegate.applicationShouldHandleReopen_hasVisibleWindows_ = \
            applicationShouldHandleReopen_hasVisibleWindows_
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Menu bar
# ---------------------------------------------------------------------------

_CMD = AppKit.NSEventModifierFlagCommand
_OPT = AppKit.NSEventModifierFlagOption
_CTL = AppKit.NSEventModifierFlagControl
_SFT = AppKit.NSEventModifierFlagShift


def _item(title, action=None, key="", mods=None, cmd=None, target=None):
    it = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        title, action, key)
    if mods is not None:
        it.setKeyEquivalentModifierMask_(mods)
    if cmd is not None:
        it.setRepresentedObject_(cmd)
    if target is not None:
        it.setTarget_(target)
    return it


def _menu(title, items):
    m = AppKit.NSMenu.alloc().initWithTitle_(title)
    for it in items:
        m.addItem_(it if it is not None else AppKit.NSMenuItem.separatorItem())
    return m


def _install_menubar():
    target = _MenuTarget.alloc().init()
    _KEEP.append(target)
    T = lambda title, cmd, key="", mods=None: _item(
        title, "invoke:", key, mods, cmd=cmd, target=target)

    # -- Vigil (application menu) --
    services = AppKit.NSMenu.alloc().initWithTitle_("Services")
    app_menu = _menu("Vigil", [
        T("About Vigil", "about"),
        None,
        T("Settings…", "settings", ","),
        None,
        _item("Services", None, ""),
        None,
        _item("Hide Vigil", "hide:", "h"),
        _item("Hide Others", "hideOtherApplications:", "h", _CMD | _OPT),
        _item("Show All", "unhideAllApplications:"),
        None,
        _item("Quit Vigil", "terminate:", "q"),
    ])
    app_menu.itemWithTitle_("Services").setSubmenu_(services)
    AppKit.NSApp.setServicesMenu_(services)

    file_menu = _menu("File", [
        T("New Camera…", "new-camera", "n"),
        None,
        T("Export Evidence…", "export", "e", _CMD | _SFT),
        None,
        T("Close Window", "close-window", "w"),
    ])

    edit_menu = _menu("Edit", [
        _item("Undo", "undo:", "z"),
        _item("Redo", "redo:", "z", _CMD | _SFT),
        None,
        _item("Cut", "cut:", "x"),
        _item("Copy", "copy:", "c"),
        _item("Paste", "paste:", "v"),
        _item("Select All", "selectAll:", "a"),
        None,
        T("Find", "search", "f"),
    ])

    view_menu = _menu("View", [
        T("Live Footage", "goto:live", "1"),
        T("Evidence", "goto:evidence", "2"),
        T("Users", "goto:users", "3"),
        T("Settings", "goto:settings", "4"),
        None,
        T("Toggle Sidebar", "toggle-sidebar", "s", _CMD | _OPT),
        T("Refresh", "refresh", "r"),
        None,
        _item("Enter Full Screen", "toggleFullScreen:", "f", _CMD | _CTL),
    ])

    window_menu = _menu("Window", [
        _item("Minimize", "performMiniaturize:", "m"),
        _item("Zoom", "performZoom:"),
        None,
        _item("Bring All to Front", "arrangeInFront:"),
    ])
    AppKit.NSApp.setWindowsMenu_(window_menu)

    help_menu = _menu("Help", [
        T("Keyboard Shortcuts", "shortcuts", "/"),
        None,
        T("Vigil Help", "help"),
    ])
    AppKit.NSApp.setHelpMenu_(help_menu)

    main = AppKit.NSMenu.alloc().initWithTitle_("MainMenu")
    for title, sub in (("Vigil", app_menu), ("File", file_menu),
                       ("Edit", edit_menu), ("View", view_menu),
                       ("Window", window_menu), ("Help", help_menu)):
        holder = _item(title, None, "")
        holder.setSubmenu_(sub)
        main.addItem_(holder)
    AppKit.NSApp.setMainMenu_(main)
    _KEEP.append(main)


# ---------------------------------------------------------------------------
# Window memory + vibrancy
# ---------------------------------------------------------------------------

def _remember_frame():
    """Restore last session's size/position, then keep saving it (native
    NSWindow frame autosave — survives relaunches, multiple displays)."""
    for _, w in _nswindows():
        try:
            w.setFrameUsingName_(FRAME_NAME)
            w.setFrameAutosaveName_(FRAME_NAME)
        except Exception:
            pass


def enable_vibrancy():
    """The real macOS sidebar material: an NSVisualEffectView filling the
    window BEHIND a transparent WKWebView. The page opts in per-region — the
    sidebar goes translucent (CSS, .has-vibrancy), content stays opaque.
    Returns True only if every step succeeded, so the page is never left
    transparent over a solid window."""
    ok = False
    for i, w in _nswindows():
        try:
            wk = getattr(i, "webview", None) or getattr(i, "webkit", None)
            content = w.contentView()
            if wk is None or content is None:
                continue
            effect = AppKit.NSVisualEffectView.alloc().initWithFrame_(content.bounds())
            effect.setMaterial_(AppKit.NSVisualEffectMaterialSidebar)
            effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
            effect.setState_(AppKit.NSVisualEffectStateFollowsWindowActiveState)
            effect.setAutoresizingMask_(
                AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
            content.addSubview_positioned_relativeTo_(
                effect, AppKit.NSWindowBelow, wk)
            # Undocumented-but-stable WKWebView switch every translucent Mac
            # app uses; without it the web view paints an opaque white/dark bg.
            wk.setValue_forKey_(objc.NO, "drawsBackground")
            try:
                wk.setUnderPageBackgroundColor_(AppKit.NSColor.clearColor())
            except Exception:
                pass
            _KEEP.append(effect)
            ok = True
        except Exception:
            continue
    return ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def install(window, dispatch):
    """Run on the AppKit main queue once the GUI loop is up.
    dispatch(cmd) forwards menu commands into the page."""
    global _dispatch, _window
    _dispatch = dispatch
    _window = window

    def apply():
        global VIBRANT
        menubar_ok = True
        try:
            _install_menubar()
        except Exception as e:
            menubar_ok = False
            _log_err = e
        _remember_frame()
        _install_reopen_hook()
        try:
            VIBRANT = enable_vibrancy()
        except Exception:
            VIBRANT = False
        # One status line so packaged-app logs show whether the native layer
        # really applied (every failure above is silent by design).
        try:
            print("[mac_native] menubar=%s vibrancy=%s" %
                  ("ok" if menubar_ok else "FAILED: %r" % _log_err,
                   "ok" if VIBRANT else "off"), file=sys.stderr)
        except Exception:
            pass

    AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(apply)
