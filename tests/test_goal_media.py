"""Model-selected, observed YouTube media capabilities in the goal loop."""
from dataclasses import replace

import pytest
from test_goals import RecordingGoalEngine

from laya_voice_browser.goal_contracts import GoalContract, contract_options, result_url, verify
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


def test_shorts_are_eligible_search_results_but_not_the_shorts_homepage():
    assert result_url("youtube", "https://www.youtube.com/shorts/5uT9mf_gpSQ?feature=share") == URL
    assert result_url("youtube", "https://www.youtube.com/shorts") is None
    assert result_url("youtube", "https://www.youtube.com/shorts/not-a-video-id") is None


def test_theater_mode_requires_watch_page_and_observed_mode():
    watch_url = "https://www.youtube.com/watch?v=5uT9mf_gpSQ"
    watch = replace(SHORT, url=watch_url, browsing={
        "site": "youtube", "media": {"present": True, "theater": False}})
    assert "theater_on" not in {c.kind for c in contract_options(Goal("g", "theater mode"), SHORT).values()}
    assert "theater_on" in {c.kind for c in contract_options(Goal("g", "theater mode"), watch).values()}
    contract = GoalContract("youtube", "theater_on", initial_url=watch_url, initial_active_tab="one")
    assert not verify(contract, watch).satisfied
    assert verify(contract, replace(watch, browsing={"site": "youtube", "media": {
        "present": True, "theater": True}})).satisfied
    goal = Goal("g", "theater mode")
    engine = RecordingGoalEngine({"objective": "theater_on", "operation": "CLICK", "target": "media:theater"})
    engine.prepare(goal, watch)
    assert engine.choose(goal, watch).action == {"type": "media", "command": "theater"}


def test_skip_ad_only_offered_when_skip_button_is_observed():
    playing_ad = replace(SHORT, browsing={"site": "youtube", "media": {
        "present": True, "ad_showing": True, "skip_ad_available": True}})
    goal = Goal("g", "skip the ad")
    assert "skip_ad" in {c.kind for c in contract_options(goal, playing_ad).values()}
    assert "skip_ad" not in {c.kind for c in contract_options(goal, SHORT).values()}
    not_an_ad = replace(playing_ad, browsing={"site": "youtube", "media": {
        "present": True, "ad_showing": False, "skip_ad_available": True}})
    assert "skip_ad" not in {c.kind for c in contract_options(goal, not_an_ad).values()}
    engine = RecordingGoalEngine({"objective": "skip_ad", "operation": "CLICK", "target": "media:skip_ad"})
    engine.prepare(goal, playing_ad)
    assert engine.choose(goal, playing_ad).action == {"type": "media", "command": "skip_ad"}
    contract = GoalContract("youtube", "skip_ad", initial_url=URL, initial_active_tab="one")
    assert not verify(contract, playing_ad).satisfied
    assert verify(contract, replace(playing_ad, browsing={"site": "youtube", "media": {
        "present": True, "ad_showing": False, "skip_ad_available": False}})).satisfied


def test_spoken_first_short_ignores_earlier_normal_video_results():
    search_url = "https://www.youtube.com/results?search_query=ESP32+camera+shorts"
    search = Snapshot(search_url, "ESP32 camera shorts - YouTube", "Results", (), "results",
                      tabs=(Tab("one", search_url, "Results", True),), browsing={
                          "site": "youtube", "results_ready": True,
                          "results": [
                              {"url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "Normal video"},
                              {"url": URL, "title": "ESP32 camera Short"},
                          ]})
    goal = Goal("g", "Open the first Short")
    engine = RecordingGoalEngine({"objective": "open_result", "objective_result": "1"})
    engine.prepare(goal, search)
    assert goal.contract.result_type == "short"
    assert goal.contract.expected_url == URL
    assert list(action_space(goal, search)["CLICK"]) == ["result:1"]
