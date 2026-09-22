from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .controller import StreamingController
from .laya import LayaEngine
from .safari import SafariBrowser
from .speech import native_events, replay_events
from .types import TranscriptEvent


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="laya-voice-browser",
        description="Control Safari from partial speech using local Laya-MLX decisions.",
    )
    result.add_argument("--url", default="https://example.com", help="Initial Safari URL")
    result.add_argument("--model", help="Local path or Hugging Face Laya-MLX checkpoint")
    result.add_argument("--trace", type=Path, help="Append inspectable JSONL decisions and outcomes")
    result.add_argument("--keep-open", action="store_true", help="Leave the controlled Safari session open")
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--command", help="Run one final typed command instead of listening")
    modes.add_argument("--replay", help="Replay one command word by word")
    result.add_argument("--word-delay", type=float, default=0.24, help="Replay delay between words")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    print("Warming Laya-MLX locally…", flush=True)
    engine = LayaEngine(args.model)
    try:
        engine.warm()
    except Exception as exc:
        print(f"Could not load Laya-MLX: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"Loaded {engine.model_name}. Starting Safari…", flush=True)
    try:
        browser = SafariBrowser(args.url)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    controller = StreamingController(browser, engine, trace_path=args.trace)
    try:
        if args.command:
            controller.submit(TranscriptEvent(args.command, True, "typed", time.time()))
            controller.wait_idle()
            return 3 if controller.session_lost else 0
        if args.replay:
            for event in replay_events([args.replay], word_delay=args.word_delay):
                controller.submit(event)
            controller.wait_idle()
            return 3 if controller.session_lost else 0

        print("Ready. Double-tap left Control to speak; press Control-C to stop.", flush=True)
        for event in native_events():
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
        if not args.keep_open and not controller.session_lost:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
