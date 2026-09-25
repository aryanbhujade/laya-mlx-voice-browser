"""Install the background service as a per-user LaunchAgent so it starts at login."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

LABEL = "dev.aryan.layabrowse"
# Earlier names of this service, removed on install so two copies never run.
LEGACY_LABELS = ("dev.aryan.laya-voice-browser",)
APP_BUNDLE_ID = "dev.aryan.layabrowse"
PASSED_ENVIRONMENT = (
    "LAYA_MODEL",
    "LAYA_DTYPE",
    "LAYA_BATCH_SIZE",
    "LAYA_COMPILE",
    "LAYA_SPEECH_LOCALE",
    "LAYA_HOTKEY_INTERVAL_MS",
    "LAYA_SILENCE_MS",
    "HF_HOME",
)


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "laya-voice-browser" / "service.log"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def launch_agent(python: str | None = None, app: Path | None = None, *, goal_loop: bool = True) -> dict:
    """launchd runs the signed LayaBrowse app, which runs Python as its child.

    Pointing launchd at the app (not at python) is what makes macOS show "LayaBrowse" in the background
    activity notice, Login Items and every permission prompt instead of "Python Software Foundation".
    """
    from .speech import app_binary

    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONUNBUFFERED": "1",
        "LAYA_PYTHON": python or sys.executable,
    }
    environment.update({name: os.environ[name] for name in PASSED_ENVIRONMENT if name in os.environ})
    log = str(log_path())
    return {
        "Label": LABEL,
        "ProgramArguments": [str(app or app_binary()), "--service"] + ([] if goal_loop else ["--legacy"]),
        "AssociatedBundleIdentifiers": [APP_BUNDLE_ID],
        "EnvironmentVariables": environment,
        "RunAtLoad": True,
        # Restart after crashes, but not after "Quit LayaBrowse" from the menu bar (a clean exit).
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 20,
        "ProcessType": "Interactive",
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _loaded(label: str) -> bool:
    return _launchctl("print", f"{_domain()}/{label}").returncode == 0


def _stop_loaded(timeout: float = 10.0) -> None:
    """Unload this service (and older names of it) and wait until launchd has really let go:
    `bootout` returns before the old process has exited."""
    for label in (LABEL, *LEGACY_LABELS):
        _launchctl("bootout", f"{_domain()}/{label}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(_loaded(label) for label in (LABEL, *LEGACY_LABELS)):
        time.sleep(0.1)
    for label in LEGACY_LABELS:
        (plist_path().parent / f"{label}.plist").unlink(missing_ok=True)


def install(*, prepare_model: bool = True, goal_loop: bool = True) -> int:
    from .speech import build_native_helper

    print("Building LayaBrowse…", flush=True)
    build_native_helper()
    if prepare_model:
        from .goal_engine import GoalEngine
        from .laya import LayaEngine

        engine = GoalEngine() if goal_loop else LayaEngine()
        print(f"Downloading and checking {engine.model_name}…", flush=True)
        engine.warm()
    log_path().parent.mkdir(parents=True, exist_ok=True)
    plist_path().parent.mkdir(parents=True, exist_ok=True)
    with plist_path().open("wb") as handle:
        plistlib.dump(launch_agent(goal_loop=goal_loop), handle)
    _stop_loaded()
    result = _launchctl("bootstrap", _domain(), str(plist_path()))
    for _ in range(10):
        # launchd can still be unloading the previous copy ("Bootstrap failed: 5"); give it a moment.
        if result.returncode == 0:
            break
        time.sleep(0.5)
        result = _launchctl("bootstrap", _domain(), str(plist_path()))
    if result.returncode != 0:
        print(f"launchctl could not start the service: {result.stderr.strip()}", file=sys.stderr)
        return 2
    print(
        "Installed. LayaBrowse now runs in the background and starts at login.\n"
        f"Engine: {'Laya goal loop' if goal_loop else 'legacy rules-first'}\n"
        "macOS will ask to allow LayaBrowse to use the microphone and speech recognition.\n"
        "Then double-tap left Control anywhere to talk (change the shortcut in the menu-bar icon).\n"
        f"Logs: {log_path()}",
        flush=True,
    )
    return 0


def uninstall() -> int:
    _stop_loaded()
    plist_path().unlink(missing_ok=True)
    print("Removed the background service. Your model cache and logs were left in place.")
    return 0


def status() -> int:
    if not plist_path().exists():
        print("Not installed. Run: layabrowse install")
        return 1
    result = _launchctl("print", f"{_domain()}/{LABEL}")
    running = "state = running" in result.stdout
    pid = next((line.split("=")[1].strip() for line in result.stdout.splitlines() if "pid =" in line), None)
    state = f"yes (pid {pid})" if running and pid else "no"
    try:
        with plist_path().open("rb") as handle:
            goal_loop = "--legacy" not in plistlib.load(handle).get("ProgramArguments", [])
        mode = "Laya goal loop" if goal_loop else "legacy rules-first"
    except (OSError, ValueError, plistlib.InvalidFileException):
        mode = "unknown (cannot read LaunchAgent)"
    print(f"Installed: yes\nRunning: {state}\nConfigured engine: {mode}\nLogs: {log_path()}")
    return 0 if running else 3


def logs(lines: int = 40) -> int:
    path = log_path()
    if not path.exists():
        print(f"No log yet at {path}")
        return 1
    print("\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]))
    return 0
