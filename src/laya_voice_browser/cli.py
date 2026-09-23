from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import browsers, config
from .controller import StreamingController
from .laya import LayaEngine
from .speech import native_events, replay_events
from .status import StatusChannel, free_udp_port
from .types import TranscriptEvent


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="layabrowse",
        description=(
            "LayaBrowse: browse by voice with local Laya-MLX decisions. "
            "Background service: install | uninstall | status | logs | daemon."
        ),
    )
    result.add_argument("--url", help="Open this page first")
    result.add_argument("--browser", help="safari, chrome, edge, … (default: the Browser setting)")
    result.add_argument("--model", help="Local path or Hugging Face Laya-MLX checkpoint")
    result.add_argument("--goal-loop", action="store_true", help="Experimental model-led browsing goals")
    result.add_argument("--trace", type=Path, help="Append inspectable JSONL decisions and outcomes")
    result.add_argument("--keep-open", action="store_true", help="Leave the browser window open afterwards")
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--command", help="Run one final typed command instead of listening")
    modes.add_argument("--replay", help="Replay one command word by word")
    result.add_argument("--word-delay", type=float, default=0.24, help="Replay delay between words")
    return result


SERVICE_COMMANDS = {"backend", "daemon", "install", "uninstall", "status", "logs"}


def service_main(command: str, rest: list[str]) -> int:
    from . import daemon, service

    options = argparse.ArgumentParser(prog=f"layabrowse {command}")
    if command == "backend":
        from . import backend

        options.add_argument("--model")
        options.add_argument("--trace", type=Path)
        options.add_argument("--goal-loop", action="store_true")
        args = options.parse_args(rest)
        return backend.run(args.model, args.trace, goal_loop=args.goal_loop)
    if command == "daemon":
        options.add_argument("--model")
        options.add_argument("--trace", type=Path)
        options.add_argument("--goal-loop", action="store_true")
        args = options.parse_args(rest)
        return daemon.run(args.model, args.trace, goal_loop=args.goal_loop)
    if command == "install":
        options.add_argument("--skip-model", action="store_true", help="Do not download the model now")
        args = options.parse_args(rest)
        return service.install(prepare_model=not args.skip_model)
    if command == "logs":
        options.add_argument("-n", type=int, default=40, help="Number of lines")
        return service.logs(options.parse_args(rest).n)
    options.parse_args(rest)
    return service.uninstall() if command == "uninstall" else service.status()


def _result_code(controller, goal_loop: bool) -> int:
    if controller.session_lost:
        return 3
    if goal_loop and (not controller.goal or controller.goal.status != "model_done"):
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in SERVICE_COMMANDS:
        return service_main(argv[0], argv[1:])
    args = parser().parse_args(argv)
    print("Warming Laya-MLX locally…", flush=True)
    if args.goal_loop:
        from .goal_controller import GoalController
        from .goal_engine import GoalEngine

    engine = GoalEngine(args.model) if args.goal_loop else LayaEngine(args.model)
    try:
        engine.warm()
    except Exception as exc:
        print(f"Could not load Laya-MLX: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    key = browsers.resolve(args.browser or config.load().browser)
    print(f"Loaded {engine.model_name}. Opening {key}…", flush=True)
    try:
        browser = browsers.open_browser(key)
        if args.url:
            browser.execute({"type": "navigate", "url": args.url})
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    status = StatusChannel(free_udp_port())
    controller_type = GoalController if args.goal_loop else StreamingController
    controller = controller_type(browser, engine, trace_path=args.trace, status=status)
    try:
        if args.command:
            controller.submit(TranscriptEvent(args.command, True, "typed", time.time()))
            controller.wait_idle(timeout=60)
            return _result_code(controller, args.goal_loop)
        if args.replay:
            for event in replay_events([args.replay], word_delay=args.word_delay):
                controller.submit(event)
            controller.wait_idle(timeout=60)
            return _result_code(controller, args.goal_loop)

        print("Ready. Double-tap left Control to speak; press Control-C to stop.", flush=True)
        def on_signal(name):
            if args.goal_loop and name in {"voice_on", "voice_off"}:
                controller.resume() if name == "voice_on" else controller.pause()

        for event in native_events(status_port=status.port, on_signal=on_signal):
            controller.submit(event)
            if controller.session_lost:
                return 3
        controller.wait_idle()
        print("The native speech helper exited unexpectedly.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        controller.close()
        status.close()
        if not args.keep_open and not controller.session_lost:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
