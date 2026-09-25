"""Model-selected, observed YouTube media capabilities in the goal loop."""
from dataclasses import replace

import pytest
from test_goals import RecordingGoalEngine

from laya_voice_browser.goal_contracts import GoalContract, contract_options, verify
from laya_voice_browser.goals import Goal, action_space
from laya_voice_browser.types import Snapshot, Tab

URL = "https://www.youtube.com/shorts/5uT9mf_gpSQ"
SHORT = Snapshot(
    URL, "A Short - YouTube", "A Short", (), "short",
    tabs=(Tab("one", URL, "A Short - YouTube", True),),
    browsing={"site": "youtube", "media": {"present": True, "paused": False, "muted": False},
              "comments_visible": False},
)


@pytest.mark.parametrize("spoken,kind,command", [
    ("pause the video", "pause_video", "pause"),
    ("mute", "mute_video", "mute"),
    ("next short", "next_video", "next"),
    ("open the comments", "show_comments", "comments"),
])
def test_media_actions_are_model_chosen_capabilities(spoken, kind, command):
    goal = Goal("g", spoken)
    assert kind in {c.kind for c in contract_options(goal, SHORT).values()}
    engine = RecordingGoalEngine({"objective": kind, "operation": "CLICK", "target": f"media:{command}"})
    engine.prepare(goal, SHORT)
    assert engine.asked[0][0] == "objective"
    assert "unsupported" in engine.asked[0][1]
    groups = action_space(goal, SHORT)
    assert list(groups) == ["CLICK"]
    assert list(groups["CLICK"]) == [f"media:{command}"]
    decision = engine.choose(goal, SHORT)
    assert decision.action == {"type": "media", "command": command}


def test_media_not_offered_without_observed_player():
    page = replace(SHORT, browsing={"site": "youtube", "media": {"present": False}})
    assert not any(c.kind == "pause_video" for c in contract_options(Goal("g", "pause video"), page).values())


@pytest.mark.parametrize("kind,change", [
    ("pause_video", {"media": {"present": True, "paused": True, "muted": False}}),
    ("mute_video", {"media": {"present": True, "paused": False, "muted": True}}),
    ("show_comments", {"comments_visible": True}),
])
def test_media_controls_require_observed_postcondition(kind, change):
    contract = GoalContract("youtube", kind, initial_url=URL, initial_active_tab="one")
    assert not verify(contract, SHORT).satisfied
    observed = replace(SHORT, browsing={**SHORT.browsing, **change})
    assert verify(contract, observed).satisfied
    assert not verify(contract, replace(observed, url=URL + "?wrong=1")).satisfied


def test_next_short_requires_another_short_in_the_same_tab():
    contract = GoalContract("youtube", "next_video", initial_url=URL, initial_active_tab="one")
    assert not verify(contract, SHORT).satisfied
    next_url = "https://www.youtube.com/shorts/abcdefghijk"
    assert verify(contract, replace(SHORT, url=next_url)).satisfied
    assert not verify(contract, replace(SHORT, url="https://www.youtube.com/watch?v=abcdefghijk")).satisfied
    assert not verify(contract, replace(SHORT, url=next_url,
                                        tabs=(Tab("two", next_url, "Other", True),))).satisfied
