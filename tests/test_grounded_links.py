"""Grounded navigation wiring and safety contracts, not model-accuracy tests."""
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_goals import BLANK, RecordingGoalEngine

from laya_voice_browser.goal_contracts import (
    contract_options,
    describe_destination,
    link_options,
    navigation_request,
)
from laya_voice_browser.goal_engine import UncertainDecision
from laya_voice_browser.goals import Goal
from laya_voice_browser.types import Element, Snapshot, Tab

FIXTURES = Path(__file__).parent / "fixtures"


def page(name):
    raw = json.loads((FIXTURES / f"{name}.json").read_text())
    raw["elements"] = tuple(Element(**e) for e in raw["elements"])
    return Snapshot(**raw)


def test_same_name_article_and_image_have_distinct_observed_metadata():
    choices = link_options(page("wikipedia_main"))
    assert "article" in choices["e22"].label
    assert "/wiki/Alison_Frantz" in choices["e22"].label
    assert "image file" in choices["e21"].label
    assert choices["e21"].label.endswith("jpg")
    assert choices["e21"].action["url"].endswith("class_of_1924.jpg")
    assert choices["e21"].label != choices["e22"].label


def test_metadata_does_not_invent_an_article_for_an_arbitrary_site_or_leak_query():
    label = describe_destination("Report", "https://example.org/wiki/Report?secret=hidden")
    assert "— link —" in label and "secret" not in label and "hidden" not in label
    assert "image file" not in describe_destination("PDF", "https://en.wikipedia.org/wiki/File:Book.pdf")


def test_duplicate_result_anchors_keep_source_and_title_but_one_destination():
    for reverse in (False, True):
        p = page("duckduckgo_results")
        if reverse:
            p = replace(p, elements=tuple(reversed(p.elements)))
        matches = [c for c in link_options(p).values()
                   if c.action["url"] == "https://en.wikipedia.org/wiki/Alan_Turing"]
        assert len(matches) == 1
        assert "Wikipedia" in matches[0].label and "Alan Turing" in matches[0].label


@pytest.mark.parametrize("text", [
    "click the images tab", "can you click the news tab", "go to the Images tab",
])
def test_page_tab_is_not_forced_into_browser_tab_switching(text):
    p = replace(page("duckduckgo_results"), tabs=(
        Tab("current", "Search", "", True), Tab("other", "GitHub", "", False)))
    options = contract_options(Goal("g", text), p)
    assert {c.kind for c in options.values()} == {"open_link"}


def test_named_result_cannot_be_satisfied_by_a_homepage():
    p = page("duckduckgo_results")
    options = contract_options(Goal("g", "open the Wikipedia result"), p)
    assert {c.kind for c in options.values()} == {"open_link"}
    options = contract_options(Goal("g", "open Wikipedia"), p)
    assert {c.kind for c in options.values()} == {"open_link", "open_site"}


def test_model_nominates_before_grounded_outcome_and_keeps_new_tab_requirement():
    engine = RecordingGoalEngine({"target": "e22", "objective": "open_link"})
    p = replace(page("wikipedia_main"), tabs=(Tab("old", "Wikipedia", "", True),))
    goal = Goal("g", "open the Alison Frantz article in a new tab")
    engine.prepare(goal, p)
    assert [q[0] for q in engine.asked] == ["target", "objective"]
    assert "Alison Frantz" in engine.asked[1][1]["open_link"]
    assert "article" in engine.asked[1][1]["open_link"]
    assert "unsupported" in engine.asked[1][1]
    assert goal.contract.expected_url.endswith("/wiki/Alison_Frantz")
    assert goal.contract.new_tab and goal.contract.initial_tabs == ("old",)


def test_nomination_is_not_permission_and_refusal_keeps_trace():
    engine = RecordingGoalEngine({"target": "e22", "objective": "unsupported"})
    goal = Goal("g", "open the Alison Frantz article")
    with pytest.raises(UncertainDecision) as raised:
        engine.prepare(goal, page("wikipedia_main"))
    assert goal.contract is None
    assert raised.value.decision["action"] is None


def test_none_never_falls_back_to_a_homepage_or_another_link():
    engine = RecordingGoalEngine({"target": "none"})
    goal = Goal("g", "open Wikipedia")
    with pytest.raises(UncertainDecision, match="Which destination"):
        engine.prepare(goal, page("duckduckgo_results"))
    assert goal.contract is None
    assert [q[0] for q in engine.asked] == ["target"]


@pytest.mark.parametrize("text", [
    "I said open the article yesterday", "we should open the article later",
    "the instructions say open the article", "I wonder whether to open Wikipedia",
    "don't open the article", "that link says click here",
])
def test_indirect_navigation_is_not_execution_permission(text):
    assert not navigation_request(text)
    engine = RecordingGoalEngine({})  # No model question may bypass the admission check.
    with pytest.raises(UncertainDecision):
        engine.prepare(Goal("g", text), page("wikipedia_main"))
    assert engine.asked == []


@pytest.mark.parametrize("text", [
    "click Turing machine", "could you open the Images tab", "please open Talk",
    "I'd like you to open the photo", "I want you to open the article",
    "and in a new tab can you open the article", "Laya, open Wikipedia",
    "next page", "show me what Alison Frantz looked like",
])
def test_direct_request_admission_does_not_choose_a_destination(text):
    assert navigation_request(text)


def test_compound_search_does_not_degrade_to_a_grounded_link():
    goal = Goal("g", "open YouTube and search for ESP32 and open the second video")
    engine = RecordingGoalEngine({"objective": "open_result", "objective_query": "0",
                                  "objective_result": "2"})
    engine.prepare(goal, BLANK)
    assert goal.contract.kind == "open_result" and goal.contract.query == "ESP32"
    assert goal.contract.ordinal == 2
    assert "target" not in [q[0] for q in engine.asked]
