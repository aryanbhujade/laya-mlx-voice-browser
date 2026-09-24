"""Synthetic contract regressions, not evidence of live shopping-site accuracy."""
from dataclasses import replace

import pytest
from test_goals import BLANK, RecordingGoalEngine

from laya_voice_browser.goal_contracts import (
    GoalContract,
    contract_options,
    link_options,
    observed_results,
    result_url,
    search_matches,
    verify,
)
from laya_voice_browser.goal_engine import UncertainDecision
from laya_voice_browser.goal_fast_path import direct_action
from laya_voice_browser.goals import Goal, action_space, browser_blocker, scope
from laya_voice_browser.types import Element, Snapshot, Tab

ITEM1 = "https://www.ebay.com/itm/123456789012"
ITEM2 = "https://www.ebay.com/itm/234567890123"
SEARCH = "https://www.ebay.com/sch/i.html?_nkw=night+vision+camera"
RESULTS = Snapshot(SEARCH, "Night vision camera for sale", "Results", (), "results",
                   tabs=(Tab("old", "Results", SEARCH, True),), browsing={
                       "site": "ebay", "results_ready": True, "results": [
                           {"url": "https://www.ebay.com/itm/000000000000", "title": "Shop on eBay"},
                           {"url": ITEM1 + "?tracking=thumbnail", "title": "Camera A"},
                           {"url": ITEM1.replace("/itm/", "/itm/Camera-A/"), "title": "Camera A"},
                           {"url": ITEM2 + "?tracking=title", "title": "Camera B"},
                           {"url": "https://example.com/itm/345678901234", "title": "Other site"},
                       ]})


def test_listing_cards_deduplicate_by_item_identity_not_tracking_or_title():
    assert observed_results(RESULTS) == [
        {"url": ITEM1, "title": "Camera A"}, {"url": ITEM2, "title": "Camera B"}]
    assert result_url("ebay", "https://www.ebay.com/b/Vintage-Cameras/101643") is None
    assert result_url("ebay", ITEM1 + "/checkout") is None
    assert scope("https://www.ebay.de/") == "ebay"
    assert scope("https://ebay.com.example.org/") != "ebay"
    page = replace(RESULTS, elements=(
        Element("e1", "link", "View item", "a", href=ITEM1 + "?image=1"),
        Element("e2", "link", "Camera A", "a", href=ITEM1 + "?title=1"),
    ))
    listings = [c for c in link_options(page).values() if c.action["url"] == ITEM1]
    assert len(listings) == 1
    assert listings[0].label == "Camera A (link)"


def test_search_needs_matching_query_and_real_listing_observations():
    assert search_matches(RESULTS, "ebay", "night vision camera")
    assert not search_matches(RESULTS, "ebay", "Sony camcorder")
    assert not search_matches(replace(RESULTS, browsing={
        "site": "ebay", "results_ready": True, "results": []}), "ebay", "night vision camera")
    assert not search_matches(replace(RESULTS, title="Pardon our interruption"),
                              "ebay", "night vision camera")
    error = replace(RESULTS, title="Error Page | eBay", text="SORRY Something went wrong on our end")
    assert browser_blocker(error) == "browser_error"
    assert not verify(GoalContract("ebay", "open_site"), error).satisfied


@pytest.mark.parametrize("text", ["open the second listing", "click on the second item",
                                  "open the second link", "show me the second result"])
def test_followup_result_uses_observed_query_without_asking_for_unspoken_text(text):
    engine = RecordingGoalEngine({"objective": "open_result", "objective_result": "2"})
    goal = Goal("g", text)
    engine.prepare(goal, RESULTS)
    assert goal.contract.query_from_page
    assert goal.contract.query == "night vision camera"
    assert goal.contract.expected_url == ITEM2
    assert goal.contract.search_observed
    assert "objective_query" not in [qid for qid, _, _ in engine.asked]
    choices = action_space(goal, RESULTS)["CLICK"]
    assert [c.action for c in choices.values()] == [{"type": "navigate", "url": ITEM2}]


def test_new_tab_result_resolves_before_leaving_source_page_and_verifies_item_identity():
    engine = RecordingGoalEngine({"objective": "open_result", "objective_result": "2"})
    goal = Goal("g", "open the second listing in a new tab")
    engine.prepare(goal, RESULTS)
    assert [c.action for c in action_space(goal, RESULTS)["CLICK"].values()] == [{"type": "new_tab"}]
    blank = replace(BLANK, tabs=(replace(RESULTS.tabs[0], active=False), Tab("new", "", "", True)))
    assert [c.action for c in action_space(goal, blank)["CLICK"].values()] == [
        {"type": "navigate", "url": ITEM2}]
    item = replace(blank, url=ITEM2, title="Camera B", text="Camera B", browsing={
        "site": "ebay", "heading": "Camera B", "detail_ready": True})
    assert verify(goal.contract, item).satisfied
    assert not verify(goal.contract, replace(item, url=ITEM1)).satisfied
    assert not verify(goal.contract, replace(item, tabs=RESULTS.tabs)).satisfied
    assert not verify(goal.contract, replace(item, browsing={})).satisfied


def test_result_out_of_range_never_opens_a_blank_tab():
    engine = RecordingGoalEngine({"objective": "open_result", "objective_result": "3"})
    with pytest.raises(UncertainDecision, match="not present"):
        engine.prepare(Goal("g", "open the third listing in a new tab"), RESULTS)


def test_new_tab_category_resolves_link_on_original_page():
    url = "https://www.ebay.com/b/Vintage-Cameras/101643/bn_152346"
    page = replace(RESULTS, elements=(Element("e1", "link", "Vintage Cameras", "a", href=url),))
    engine = RecordingGoalEngine({"objective": "open_link", "target": "e1"})
    goal = Goal("g", "open vintage cameras in a new tab")
    assert {c.kind for c in contract_options(goal, page).values()} == {"open_link"}
    engine.prepare(goal, page)
    assert goal.contract.expected_url == url
    blank = replace(BLANK, tabs=(Tab("new", "", "", True),))
    assert [c.action for c in action_space(goal, blank)["CLICK"].values()] == [
        {"type": "navigate", "url": url}]


def test_search_contract_is_offered_on_ebay_and_negations_never_execute():
    options = contract_options(Goal("g", "can you search for night vision camera"), RESULTS)
    assert any(c.kind == "search" and c.site == "ebay" for c in options.values())
    assert contract_options(Goal("g", "don't search eBay for cameras"), RESULTS) == {}
    assert contract_options(Goal("g", "don't open the first listing"), RESULTS) == {}
    options = contract_options(Goal("g", "search for cameras in a new tab"), RESULTS)
    assert options and all(c.query == "cameras" for c in options.values())


def test_observed_pagination_is_a_capability_not_a_phrase_dispatch():
    url = SEARCH + "&_pgn=2"
    page = replace(RESULTS, browsing={**RESULTS.browsing, "navigation": [
        {"url": url, "title": "Next page of listings"},
        {"url": "javascript:alert(1)", "title": "Bad navigation"}]})
    assert link_options(page)["nav:0"].action == {"type": "navigate", "url": url}
    assert "nav:1" not in link_options(page)
    assert "nav:0" not in link_options(RESULTS)
    assert {c.kind for c in contract_options(Goal("g", "next page"), page).values()} == {"open_link"}


def test_scroll_back_up_is_not_browser_history_and_qualified_commands_still_use_model():
    assert direct_action("could you scroll back up please") == {
        "type": "scroll", "direction": "up", "amount": "page"}
    assert direct_action("scroll back up to vintage cameras") is None
    assert direct_action("don't scroll back up") is None
    assert direct_action("go back") == {"type": "back"}


def test_ebay_detail_without_observed_search_is_not_a_verified_result():
    item = replace(RESULTS, url=ITEM1, browsing={
        "site": "ebay", "heading": "Camera A", "detail_ready": True})
    assert not verify(GoalContract("ebay", "open_result", "night vision camera", 1), item).satisfied
