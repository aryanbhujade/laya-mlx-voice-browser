"""The Python half of LayaBrowse: the menu-bar app starts this as a child process.

stdin:  JSON lines from the app: transcripts, and events such as {"event": "voice_on"}
stdout: JSON status lines for the notch island (nothing else may be printed there)
stderr: the log
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

from . import browsers, config
from .browser import ReconnectingBrowser
from .controller import StreamingController
from .laya import LayaEngine
from .status import PipeStatus
from .types import TranscriptEvent


def log(message: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}", file=sys.stderr, flush=True)


class SettingsBrowser(ReconnectingBrowser):
    """Opens whichever browser the settings choose, switching when the choice changes."""

    def __init__(self) -> None:
        self.key: str | None = None
        super().__init__(self._open, announce=log)

    def _open(self):
        self.key = browsers.resolve(config.load().browser)
        log(f"opening {self.key}")
        return browsers.open_browser(self.key)

    def follow_settings(self) -> None:
        wanted = browsers.resolve(config.load().browser)
        if self.open and wanted != self.key:
            log(f"browser setting changed to {wanted}")
            self.close()


LOG_LIMIT_BYTES = 4 * 1024 * 1024


def _trim_log() -> None:
    """Keep the service log small: past the limit, keep only its most recent quarter."""
    from .service import log_path

    path = log_path()
    try:
        if path.stat().st_size > LOG_LIMIT_BYTES:
            recent = path.read_bytes()[-LOG_LIMIT_BYTES // 4 :]
            path.write_bytes(recent[recent.find(b"\n") + 1 :])
    except OSError:
        pass


def _terminate(*_: object) -> None:
    raise SystemExit(0)


def run(model: str | None = None, trace: Path | None = None, *, goal_loop: bool = False) -> int:
    signal.signal(signal.SIGTERM, _terminate)
    # stdout carries only status lines for the app; anything a library prints goes to the log.
    status_stream = sys.stdout
    sys.stdout = sys.stderr
    _trim_log()
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    warnings.filterwarnings("ignore", message=".*temperatures outside.*")
    log("backend starting")
    if goal_loop:
        from .goal_controller import GoalController
        from .goal_engine import GoalEngine

    engine = GoalEngine(model) if goal_loop else LayaEngine(model)
    try:
        engine.warm()
    except Exception as exc:
        log(f"could not load Laya-MLX: {type(exc).__name__}: {exc}")
        return 2
    log(f"model ready: {engine.model_name}")
    browser = SettingsBrowser()
    status = PipeStatus(status_stream)
    controller_type = GoalController if goal_loop else StreamingController
    controller = controller_type(browser, engine, trace_path=trace, status=status, announce=log)
    try:
        for line in sys.stdin:
            try:
                raw = json.loads(line)
            except ValueError:
                continue
            event = raw.get("event")
            if event == "voice_on":
                if goal_loop:
                    controller.resume()
                browser.follow_settings()
                controller.prepare_browser()
            elif event == "voice_off" and goal_loop:
                controller.pause()
            elif event == "config_changed":
                browser.follow_settings()
            elif "text" in raw:
                controller.submit(
                    TranscriptEvent(
                        text=str(raw["text"]),
                        final=bool(raw.get("final")),
                        utterance_id=str(raw.get("utterance_id", "native")),
                        at=float(raw.get("at", time.time())),
                    )
                )
        log("the LayaBrowse app closed the connection")
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        controller.close()
        browser.close()
        log("backend stopped")
