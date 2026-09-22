import threading
from pathlib import Path

import pytest

from laya_voice_browser import service
from laya_voice_browser.browser import BrowserSessionLost, ReconnectingBrowser, StalePage
from laya_voice_browser.cli import SERVICE_COMMANDS
from laya_voice_browser.types import Snapshot


def test_launch_agent_restarts_after_crashes_but_not_after_quit(monkeypatch):
    monkeypatch.setenv("LAYA_MODEL", "local/checkpoint")
    agent = service.launch_agent("/venv/bin/python", app=Path("/x/Laya.app/Contents/MacOS/Laya"))
    # launchd runs the Laya app (so macOS names it "Laya"), which runs Python as a child.
    assert agent["ProgramArguments"] == ["/x/Laya.app/Contents/MacOS/Laya", "--service"]
    assert agent["EnvironmentVariables"]["LAYA_PYTHON"] == "/venv/bin/python"
    assert agent["AssociatedBundleIdentifiers"] == ["dev.aryan.laya"]
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
