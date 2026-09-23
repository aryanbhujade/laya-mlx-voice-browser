"""Run the service in a terminal (development): this process starts the LayaBrowse app as a helper.

The installed service is the other way round: the LayaBrowse app starts `layabrowse backend`.
"""

from __future__ import annotations

import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from .backend import SettingsBrowser
from .controller import StreamingController
from .laya import LayaEngine
from .speech import HelperQuit, native_events
from .status import StatusChannel, free_udp_port

HELPER_RETRY_MAX_SECONDS = 60.0
HEALTHY_RUN_SECONDS = 30.0


def log(message: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def _terminate(*_: object) -> None:
    # launchd stops the service with SIGTERM; unwind normally so the helper is shut down too.
    raise SystemExit(0)


def run(model: str | None = None, trace: Path | None = None, *, goal_loop: bool = False) -> int:
    signal.signal(signal.SIGTERM, _terminate)
    log("starting LayaBrowse")
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
    status = StatusChannel(free_udp_port())
    browser = SettingsBrowser()
    controller_type = GoalController if goal_loop else StreamingController
    controller = controller_type(browser, engine, trace_path=trace, status=status, announce=log)

    def on_signal(name: str) -> None:
        if name == "voice_on":
            if goal_loop:
                controller.resume()
            browser.follow_settings()
            controller.prepare_browser()
        elif name == "voice_off" and goal_loop:
            controller.pause()
        elif name == "config_changed":
            browser.follow_settings()

    failures = 0
    try:
        while True:
            started = time.monotonic()
            try:
                log("speech helper starting; double-tap left Control to talk")
                for event in native_events(status_port=status.port, on_signal=on_signal):
                    controller.submit(event)
            except HelperQuit:
                log("quit from the menu bar")
                return 0
            except RuntimeError as exc:
                log(f"speech helper stopped: {exc}")
            # Back off while the helper keeps failing (e.g. a permission not granted yet).
            failures = 1 if time.monotonic() - started > HEALTHY_RUN_SECONDS else failures + 1
            delay = min(HELPER_RETRY_MAX_SECONDS, 2.0**failures)
            log(f"restarting the speech helper in {delay:.0f}s")
            time.sleep(delay)
    except KeyboardInterrupt:
        return 0
    finally:
        controller.close()
        status.close()
        browser.close()
        log("stopped")


if __name__ == "__main__":
    sys.exit(run())
