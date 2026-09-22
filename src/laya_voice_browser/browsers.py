"""Pick and open the browser backend from settings; "auto" follows the macOS default browser."""

from __future__ import annotations

import plistlib
from pathlib import Path

from .browser import Browser
from .chromium import CHROMIUM_APPS, ChromiumApp, app_path

SAFARI = "safari"
_LAUNCH_SERVICES = (
    Path.home()
    / "Library"
    / "Preferences"
    / "com.apple.LaunchServices"
    / "com.apple.launchservices.secure.plist"
)


def default_browser_bundle_id(preferences: Path | None = None) -> str:
    """The bundle id handling https links; Safari when the user never chose another browser."""
    preferences = preferences or _LAUNCH_SERVICES
    try:
        handlers = plistlib.loads(preferences.read_bytes()).get("LSHandlers", [])
    except (OSError, ValueError, plistlib.InvalidFileException):
        return "com.apple.safari"
    for scheme in ("https", "http"):
        for handler in handlers:
            if handler.get("LSHandlerURLScheme") == scheme and handler.get("LSHandlerRoleAll"):
                return str(handler["LSHandlerRoleAll"]).casefold()
    return "com.apple.safari"


def resolve(choice: str, default_bundle_id: str | None = None) -> str:
    """Backend key for a setting: "safari" or a Chromium key such as "chrome"."""
    choice = (choice or "auto").casefold()
    if choice == SAFARI or any(app.key == choice for app in CHROMIUM_APPS):
        return choice
    bundle = (default_bundle_id or default_browser_bundle_id()).casefold()
    for app in CHROMIUM_APPS:
        if app.bundle_id.casefold() == bundle and app_path(app):
            return app.key
    return SAFARI  # the default browser is Safari, or one Laya cannot drive yet


WEB_SEARCH_ENGINES = ("google", "duckduckgo", "bing", "brave")


def web_search_engine(setting: str, backend: str) -> str:
    """The engine for a plain "search for …". Automatic: Google in the Chromium window (which can be
    signed in, and where a Google check can be solved by hand), DuckDuckGo in Safari's automation
    window, which starts signed out every time and cannot show a solvable check."""
    if setting in WEB_SEARCH_ENGINES:
        return setting
    return "duckduckgo" if backend == SAFARI else "google"


def open_browser(key: str) -> Browser:
    if key == SAFARI:
        from .safari import SafariBrowser

        return SafariBrowser("about:blank")
    from .chromium import ChromiumBrowser

    app: ChromiumApp = next(app for app in CHROMIUM_APPS if app.key == key)
    return ChromiumBrowser(app)
