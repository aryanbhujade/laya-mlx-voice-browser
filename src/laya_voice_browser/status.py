"""Tell the notch island what the controller is doing, over localhost UDP. Fire and forget."""

from __future__ import annotations

import json
import socket
import sys
import threading
from typing import Any, TextIO
from urllib.parse import parse_qs, urlparse

_SEARCH_KEYS = {"q", "query", "search", "search_query"}


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def action_kind(action: dict[str, Any]) -> str:
    """Island icon for an action: navigations that carry a query are shown as searches."""
    kind = str(action.get("type", ""))
    if kind == "navigate":
        query = parse_qs(urlparse(str(action.get("url", ""))).query)
        if _SEARCH_KEYS & set(query):
            return "search"
    return kind


class StatusChannel:
    def __init__(self, port: int) -> None:
        self.port = port
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def __call__(
        self,
        state: str,
        *,
        kind: str | None = None,
        label: str | None = None,
        ttl: float | None = None,
    ) -> None:
        message = {"state": state, "kind": kind, "label": label, "ttl": ttl}
        payload = json.dumps({key: value for key, value in message.items() if value is not None})
        try:
            self._socket.sendto(payload.encode(), ("127.0.0.1", self.port))
        except OSError:
            pass

    def endpoint(self, hint: str) -> None:
        try:
            self._socket.sendto(json.dumps({"endpoint": hint}).encode(), ("127.0.0.1", self.port))
        except OSError:
            pass

    def close(self) -> None:
        self._socket.close()


class PipeStatus:
    """Status lines on stdout for the LayaBrowse app, when it runs this backend as its child process."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout
        self._lock = threading.Lock()

    def __call__(
        self,
        state: str,
        *,
        kind: str | None = None,
        label: str | None = None,
        ttl: float | None = None,
    ) -> None:
        message = {"state": state, "kind": kind, "label": label, "ttl": ttl}
        self._write(json.dumps({key: value for key, value in message.items() if value is not None}))

    def endpoint(self, hint: str) -> None:
        """Tell the app whether the phrase so far sounds finished, so it can end it sooner or later."""
        self._write(json.dumps({"endpoint": hint}))

    def _write(self, line: str) -> None:
        with self._lock:
            try:
                self._stream.write(line + "\n")
                self._stream.flush()
            except (OSError, ValueError):
                pass
