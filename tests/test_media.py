from laya_voice_browser.policy import early_intent, evaluate
from laya_voice_browser.spans import deterministic_intent, media_command
from laya_voice_browser.types import ModelDecision, Snapshot


def test_media_phrases():
    assert media_command("mute the video") == {"command": "mute"}
    assert media_command("can you pause") == {"command": "pause"}
    assert media_command("skip ahead 30 seconds") == {"command": "forward", "amount": 30}
    assert media_command("rewind one minute") == {"command": "back", "amount": 60}
    assert media_command("play at 1.5 times") == {"command": "rate", "amount": 1.5}
    assert media_command("scroll to the next video") == {"command": "next"}
    assert media_command("skip the ad") == {"command": "skip_ad"}
    assert media_command("go back") is None
    assert media_command("play the next level of the game please") is None


def test_media_beats_history_and_navigation_rules():
    assert deterministic_intent("go back 10 seconds") == "media"
    assert deterministic_intent("go back") == "go_back"
    assert deterministic_intent("mute") == "media"


def test_instant_media_runs_mid_speech_but_amounts_wait():
    assert early_intent("pause", False)
    assert not early_intent("skip ahead", False)


def test_media_action_needs_no_confirmation():
    from test_policy import base_answers

    state = {"transcript": "mute"}
    decision = ModelDecision(base_answers("go_back"), {"text": [], "url": []}, 0.0, "t", state)
    page = Snapshot("https://youtube.com/watch", "YT", "", (), "f")
    result = evaluate(decision, page, final=True, silent_seconds=0)
    assert result.verdict == "act" and result.action == {"type": "media", "command": "mute"}
