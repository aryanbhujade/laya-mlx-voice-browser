import threading
from pathlib import Path

import pytest

from laya_voice_browser import service
from laya_voice_browser.browser import BrowserSessionLost, ReconnectingBrowser, StalePage
from laya_voice_browser.cli import SERVICE_COMMANDS
from laya_voice_browser.types import Snapshot


def test_launch_agent_restarts_after_crashes_but_not_after_quit(monkeypatch):
    monkeypatch.setenv("LAYA_MODEL", "local/checkpoint")
    agent = service.launch_agent("/venv/bin/python", app=Path("/x/LayaBrowse.app/Contents/MacOS/LayaBrowse"))
    # launchd runs the app (so macOS names it "LayaBrowse"), which runs Python as a child.
    assert agent["ProgramArguments"] == ["/x/LayaBrowse.app/Contents/MacOS/LayaBrowse", "--service"]
    assert agent["EnvironmentVariables"]["LAYA_PYTHON"] == "/venv/bin/python"
    assert agent["AssociatedBundleIdentifiers"] == ["dev.aryan.layabrowse"]
    assert agent["RunAtLoad"] is True
    assert agent["KeepAlive"] == {"SuccessfulExit": False}
    assert agent["EnvironmentVariables"]["LAYA_MODEL"] == "local/checkpoint"
    assert agent["StandardOutPath"].endswith("laya-voice-browser/service.log")


def test_service_commands_are_routed_before_foreground_flags():
    assert {"install", "uninstall", "status", "logs", "daemon"} <= SERVICE_COMMANDS


class FlakyBrowser:
    def __init__(self, name, lose_on_snapshot=False, lose_on_execute=False):
        self.name = name
        self.lose_on_snapshot = lose_on_snapshot
        self.lose_on_execute = lose_on_execute
        self.closed = False

    def snapshot(self):
        if self.lose_on_snapshot:
            raise BrowserSessionLost("closed")
        return Snapshot(f"https://{self.name}", self.name, "", (), self.name)

    def execute(self, action, expected_fingerprint=None):
        if self.lose_on_execute:
            raise BrowserSessionLost("closed")
        return {"after_url": f"https://{self.name}"}

    def close(self):
        self.closed = True


def test_browser_opens_lazily_and_reopens_after_the_window_closes():
    made = []

    def factory():
        browser = FlakyBrowser(f"b{len(made)}", lose_on_snapshot=not made)
        made.append(browser)
        return browser

    browser = ReconnectingBrowser(factory, announce=lambda _: None)
    assert not browser.open and made == []
    assert browser.snapshot().title == "b1"
    assert made[0].closed and len(made) == 2


def test_lost_session_during_action_is_never_replayed_on_a_new_window():
    made = []

    def factory():
        browser = FlakyBrowser(f"b{len(made)}", lose_on_execute=not made)
        made.append(browser)
        return browser

    browser = ReconnectingBrowser(factory, announce=lambda _: None)
    with pytest.raises(StalePage):
        browser.execute({"type": "back"}, "b0")
    assert len(made) == 1 and not browser.open
    assert browser.execute({"type": "back"})["after_url"] == "https://b1"


def test_prepare_browser_opens_it_once_in_the_background():
    from laya_voice_browser.controller import StreamingController

    opened = threading.Event()

    def factory():
        opened.set()
        return FlakyBrowser("warm")

    browser = ReconnectingBrowser(factory, announce=lambda _: None)
    controller = StreamingController(browser, engine=None, announce=lambda _: None)
    controller.prepare_browser()
    controller.wait_idle()
    controller.prepare_browser()
    controller.wait_idle()
    controller.close()
    assert opened.is_set() and browser.open


def test_double_tap_replaces_a_stopped_session():
    """Safari's "Stop Session" leaves a session object that no longer answers."""
    made = []

    class Stoppable(FlakyBrowser):
        def __init__(self, name):
            super().__init__(name)
            self.stopped = False

        def alive(self):
            return not self.stopped

    def factory():
        made.append(Stoppable(f"b{len(made)}"))
        return made[-1]

    browser = ReconnectingBrowser(factory, announce=lambda _: None)
    browser.ensure_alive()
    made[0].stopped = True  # the user pressed "Stop Session"
    browser.ensure_alive()
    assert len(made) == 2 and browser.snapshot().title == "b1"


def test_install_waits_for_launchd_to_let_go_of_the_old_service(monkeypatch, tmp_path):
    calls = []
    loaded = {"dev.aryan.laya-voice-browser": 3, service.LABEL: 0}
    attempts = {"bootstrap": 0}

    class Result:
        def __init__(self, code, stderr=""):
            self.returncode, self.stderr, self.stdout = code, stderr, ""

    def fake_launchctl(*args):
        calls.append(args)
        if args[0] == "print":
            label = args[1].split("/")[-1]
            loaded[label] = max(0, loaded.get(label, 0) - 1)
            return Result(0 if loaded[label] else 113)
        if args[0] == "bootstrap":
            attempts["bootstrap"] += 1
            busy = attempts["bootstrap"] == 1
            return Result(5, "Bootstrap failed: 5: Input/output error") if busy else Result(0)
        return Result(0)

    monkeypatch.setattr(service, "_launchctl", fake_launchctl)
    monkeypatch.setattr(service, "plist_path", lambda: tmp_path / "LaunchAgents" / f"{service.LABEL}.plist")
    monkeypatch.setattr(service, "log_path", lambda: tmp_path / "Logs" / "service.log")
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    import laya_voice_browser.speech as speech

    monkeypatch.setattr(speech, "build_native_helper", lambda root=None: None)
    assert service.install(prepare_model=False) == 0
    assert ("bootout", f"gui/{service.os.getuid()}/dev.aryan.laya-voice-browser") in calls
    assert attempts["bootstrap"] == 2  # the transient error 5 was retried
