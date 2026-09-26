from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from .types import Snapshot

NEW_TAB_URL = "https://www.google.com/"
_RELEASE_WAIT_SECONDS = 5.0


def pick_tab(ids: list[str], current: str, action: dict[str, Any]) -> str:
    """The tab an action refers to: an explicit id, a direction relative to the current tab, or the
    current tab itself."""
    if action.get("tab_id") in ids:
        return action["tab_id"]
    here = ids.index(current) if current in ids else 0
    direction = action.get("direction")
    if direction == "first":
        return ids[0]
    if direction == "last":
        return ids[-1]
    if direction in {"next", "previous"}:
        return ids[(here + (1 if direction == "next" else -1)) % len(ids)]
    return current


class StalePage(RuntimeError):
    """The page changed after the decision; the action was not executed."""


class Unavailable(RuntimeError):
    """The page has nothing to carry out this command (no video to mute, no Reply button…)."""


NoMedia = Unavailable


class BrowserSessionLost(RuntimeError):
    """The controlled browser session is gone (window closed, browser quit or driver crashed)."""


class BrowserBusy(Unavailable):
    """The existing browser session is still busy or being released; do not replace it."""


class Browser(Protocol):
    """What the controller needs from any backend: SafariDriver today, an extension or CDP later."""

    def snapshot(self) -> Snapshot: ...

    def execute(self, action: dict[str, Any], expected_fingerprint: str | None = None) -> dict[str, Any]: ...

    def show_candidates(self, candidates: list[tuple[int, str]]) -> None:
        """Label numbered candidate elements on the page; backends without an overlay may no-op."""

    def clear_candidates(self) -> None: ...

    def close(self) -> None: ...


def _close_quietly(browser: Browser) -> None:
    try:
        browser.close()
    except Exception:
        pass


class ReconnectingBrowser:
    """Open the browser on first use and reopen it after the window or session is lost.

    The background service starts with no browser at all; the first command (or turning voice
    control on) opens one, and closing the window just means the next command opens a fresh one.
    """

    def __init__(self, factory: Callable[[], Browser], *, announce: Callable[[str], None] = print) -> None:
        self._factory = factory
        self._announce = announce
        self._browser: Browser | None = None
        self._lock = threading.RLock()
        self._closing: threading.Event | None = None
        self._retry_after = 0.0

    @property
    def open(self) -> bool:
        return self._browser is not None

    def ensure(self) -> Browser:
        with self._lock:
            if self._browser is None:
                if self._closing is not None and not self._closing.is_set():
                    raise BrowserBusy("Safari is still releasing its automation session; try shortly")
                if time.monotonic() < self._retry_after:
                    raise BrowserBusy("Safari's automation session is still paired; try shortly")
                self._announce("opening the browser")
                try:
                    self._browser = self._factory()
                except RuntimeError as exc:
                    if "already paired with another WebDriver session" not in str(exc):
                        raise
                    self._retry_after = time.monotonic() + 5.0
                    raise BrowserBusy("Safari's automation session is still paired; try shortly") from exc
                self._retry_after = 0.0
            return self._browser

    def ensure_alive(self) -> Browser:
        """Like `ensure`, but first replace a session that stopped answering (e.g. "Stop Session")."""
        with self._lock:
            health = getattr(self._browser, "health", None)
            alive = getattr(self._browser, "alive", None)
            state = (health() if health else "alive" if alive is None or alive() else "gone")
            if self._browser is not None and state == "busy":
                raise BrowserBusy("Safari is still loading; try shortly")
            if self._browser is not None and state == "gone":
                self._announce("the browser session stopped; opening a new one")
                self._drop(wait=True)
            return self.ensure()

    def _drop(self, *, wait: bool = False) -> None:
        with self._lock:
            browser, self._browser = self._browser, None
            if browser is not None:
                finished = threading.Event()
                self._closing = finished

                def release() -> None:
                    try:
                        _close_quietly(browser)
                    finally:
                        finished.set()

                threading.Thread(target=release, daemon=True).start()
            else:
                finished = self._closing
        if wait and finished is not None and not finished.wait(_RELEASE_WAIT_SECONDS):
            raise BrowserBusy("Safari is still releasing its automation session; try shortly")

    def snapshot(self) -> Snapshot:
        try:
            return self.ensure().snapshot()
        except BrowserSessionLost:
            # The window was closed since the last command: reopen and observe the new one.
            self._drop(wait=True)
            return self.ensure().snapshot()

    def execute(self, action: dict[str, Any], expected_fingerprint: str | None = None) -> dict[str, Any]:
        try:
            return self.ensure().execute(action, expected_fingerprint)
        except BrowserSessionLost as exc:
            # The decision was made on a page that no longer exists; never replay it elsewhere.
            self._drop()
            raise StalePage("the browser window closed before the action ran; say it again") from exc

    def show_candidates(self, candidates: list[tuple[int, str]]) -> None:
        if self._browser is not None:
            self._browser.show_candidates(candidates)

    def clear_candidates(self) -> None:
        if self._browser is not None:
            try:
                self._browser.clear_candidates()
            except BrowserSessionLost:
                self._drop()

    def close(self) -> None:
        self._drop()
