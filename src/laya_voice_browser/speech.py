from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from .types import TranscriptEvent


class HelperQuit(RuntimeError):
    """The user chose Quit in the Laya menu-bar item."""


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def app_bundle(root: Path | None = None) -> Path:
    return (root or project_root()) / ".build" / "LayaBrowse.app"


def app_binary(root: Path | None = None) -> Path:
    return app_bundle(root) / "Contents" / "MacOS" / "LayaBrowse"


def build_native_helper(root: Path | None = None) -> Path:
    root = root or project_root()
    script = root / "native" / "build.sh"
    subprocess.run([str(script)], check=True, cwd=root)
    binary = app_binary(root)
    if not binary.is_file():
        raise RuntimeError("Native speech helper build did not produce an executable")
    return binary


def native_events(
    root: Path | None = None,
    *,
    status_port: int | None = None,
    on_signal: Callable[[str], None] | None = None,
) -> Iterator[TranscriptEvent]:
    """Transcripts from the LayaBrowse app; `on_signal` receives events such as "voice_on"."""
    root = root or project_root()
    app = app_bundle(root)
    if not app_binary(root).is_file():
        build_native_helper(root)
    temporary = Path(tempfile.mkdtemp(prefix="laya-speech-"))
    stdout_path = temporary / "stdout.jsonl"
    stderr_path = temporary / "stderr.log"
    stdout_path.touch()
    stderr_path.touch()
    command = [
        "open",
        "-n",
        "-g",
        "-o",
        str(stdout_path),
        "--stderr",
        str(stderr_path),
    ]
    for name in ("LAYA_SPEECH_LOCALE", "LAYA_HOTKEY_INTERVAL_MS", "LAYA_SILENCE_MS"):
        if name in os.environ:
            command.extend(["--env", f"{name}={os.environ[name]}"])
    if status_port:
        command.extend(["--env", f"LAYA_STATUS_PORT={status_port}"])
    command.extend(["--env", f"LAYA_PARENT_PID={os.getpid()}"])
    command.append(str(app))
    process = subprocess.Popen(
        command,
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    helper_pid: int | None = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and helper_pid is None:
            details = stderr_path.read_text(encoding="utf-8")
            match = re.search(r"ready pid=(\d+)", details)
            if match:
                helper_pid = int(match.group(1))
                break
            time.sleep(0.05)
        if helper_pid is None:
            details = stderr_path.read_text(encoding="utf-8").strip()
            raise RuntimeError(details or "LayaBrowse did not report ready within 5 seconds")
        with stdout_path.open("r", encoding="utf-8") as output:
            while True:
                line = output.readline()
                if line:
                    raw = json.loads(line)
                    if "event" in raw:
                        if on_signal:
                            on_signal(str(raw["event"]))
                        continue
                    yield TranscriptEvent(
                        text=str(raw["text"]),
                        final=bool(raw.get("final")),
                        utterance_id=str(raw.get("utterance_id", "native")),
                        at=float(raw.get("at", time.time())),
                    )
                    continue
                try:
                    os.kill(helper_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.04)
        details = stderr_path.read_text(encoding="utf-8").strip()
        if "quit requested" in details:
            raise HelperQuit("Quit from the menu bar")
        raise RuntimeError(details or "LayaBrowse exited unexpectedly")
    finally:
        if helper_pid:
            try:
                os.kill(helper_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.terminate()
        shutil.rmtree(temporary, ignore_errors=True)


def replay_events(phrases: list[str], *, word_delay: float = 0.2) -> Iterator[TranscriptEvent]:
    for phrase_index, phrase in enumerate(phrases):
        words = phrase.split()
        utterance_id = f"replay-{phrase_index}"
        built: list[str] = []
        for index, word in enumerate(words):
            built.append(word)
            yield TranscriptEvent(
                text=" ".join(built),
                final=index == len(words) - 1,
                utterance_id=utterance_id,
                at=time.time(),
            )
            time.sleep(word_delay)
