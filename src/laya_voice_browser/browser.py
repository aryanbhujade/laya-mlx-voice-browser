from __future__ import annotations

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
