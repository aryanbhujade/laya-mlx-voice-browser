from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Protocol

from .types import Snapshot


class StalePage(RuntimeError):
    """The page changed after the decision; the action was not executed."""


class BrowserSessionLost(RuntimeError):
    """The controlled browser session is gone (window closed, browser quit or driver crashed)."""


class Browser(Protocol):
    """What the controller needs from any backend: SafariDriver today, an extension or CDP later."""

    def snapshot(self) -> Snapshot: ...

    def execute(self, action: dict[str, Any], expected_fingerprint: str | None = None) -> dict[str, Any]: ...

    def show_candidates(self, candidates: list[tuple[int, str]]) -> None:
        """Label numbered candidate elements on the page; backends without an overlay may no-op."""

    def clear_candidates(self) -> None: ...

    def close(self) -> None: ...


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

    @property
    def open(self) -> bool:
        return self._browser is not None

    def ensure(self) -> Browser:
        with self._lock:
            if self._browser is None:
                self._announce("opening the browser")
                self._browser = self._factory()
            return self._browser

    def _drop(self) -> None:
        with self._lock:
            browser, self._browser = self._browser, None
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass

    def snapshot(self) -> Snapshot:
        try:
            return self.ensure().snapshot()
        except BrowserSessionLost:
            # The window was closed since the last command: reopen and observe the new one.
            self._drop()
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
