"""Exercise the installed stdin protocol with the real goal controller, no mic/browser/model."""
import io
import json

import pytest
from test_goals import BLANK, Browser, Engine

from laya_voice_browser import backend, goal_controller, goal_engine, speech


def test_development_helper_uses_the_native_goal_mode_default(monkeypatch, tmp_path):
    binary = speech.app_binary(tmp_path)
    binary.parent.mkdir(parents=True)
    binary.touch()
    commands = []

    def launch(command, **kwargs):
        commands.append(command)
        # Simulate LaunchServices' two output files, not a real app or microphone.
        from pathlib import Path
        from types import SimpleNamespace

        Path(command[command.index("--stderr") + 1]).write_text("laya-speech: ready pid=123\n")
        return SimpleNamespace(poll=lambda: 0)

    def gone(*args):
        raise ProcessLookupError()

    monkeypatch.setattr(speech.subprocess, "Popen", launch)
    monkeypatch.setattr(speech.os, "kill", gone)
    with pytest.raises(RuntimeError):
        list(speech.native_events(tmp_path, goal_loop=True))
    assert commands[0][-1] == str(speech.app_bundle(tmp_path))
    assert "--legacy" not in commands[0]


def test_pause_cannot_reopen_the_notch_with_a_listening_status():
    statuses = []
    controller = goal_controller.GoalController(
        Browser(), Engine(), status=lambda state, **kw: statuses.append(state), announce=lambda _: None)
    try:
        controller.pause()
        assert statuses == []
        controller.resume()
        controller.cancel()
        assert statuses == ["listening"]
    finally:
        controller.close()


def test_native_voice_session_stays_on_until_off_and_ignores_late_finals(monkeypatch):
    class WarmEngine(Engine):
        def warm(self):
            pass

    class VoiceBrowser(Browser):
        def follow_settings(self):
            pass

        def close(self):
            pass

    browser = VoiceBrowser([BLANK])
    controllers = []

    class CapturedController(goal_controller.GoalController):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            controllers.append(self)

        def prepare_browser(self):
            pass

    def transcript(text, uid):
        return dict(text=text, final=True, utterance_id=uid, at=0)

    events = [
        transcript("go back", "before-on"),  # startup is paused
        {"event": "voice_on"},
        transcript("go back", "one"),
        transcript("go forward", "two"),  # no second voice_on required
        {"event": "voice_off"},
        transcript("go back", "late-final"),
        {"event": "voice_on"},
        transcript("go back", "three"),
    ]

    def stream():
        for event in events:
            yield json.dumps(event)
            controllers[0].wait_idle()  # deterministic protocol check, not an ASR timing test

    monkeypatch.setattr(goal_engine, "GoalEngine", lambda _: WarmEngine())
    monkeypatch.setattr(goal_controller, "GoalController", CapturedController)
    monkeypatch.setattr(backend, "SettingsBrowser", lambda: browser)
    monkeypatch.setattr(backend, "_trim_log", lambda: None)
    monkeypatch.setattr(backend.signal, "signal", lambda *args: None)
    monkeypatch.setattr(backend.sys, "stdin", stream())
    monkeypatch.setattr(backend.sys, "stdout", io.StringIO())
    monkeypatch.setattr(backend.sys, "stderr", io.StringIO())
    assert backend.run(goal_loop=True) == 0
    assert browser.executed == [{"type": "back"}, {"type": "forward"}, {"type": "back"}]
    assert controllers[0]._closed
