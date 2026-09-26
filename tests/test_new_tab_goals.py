"""New-tab regression coverage; scripted engines test wiring, not model accuracy."""
from dataclasses import replace

import pytest
from test_goals import BLANK, WIKI, Browser, RecordingGoalEngine, event
from test_safari import FakeDriver

from laya_voice_browser.browser import NEW_TAB_URL
from laya_voice_browser.goal_contracts import GoalContract, contract_options, observed_results, verify
from laya_voice_browser.goal_controller import GoalController
from laya_voice_browser.goals import Goal, action_space, scope, tab_candidates
from laya_voice_browser.safari import SafariBrowser
from laya_voice_browser.types import Snapshot, Tab

TABS = (
    Tab("opaque-window-" + "a" * 100, "", "about:blank"),
    Tab("opaque-window-" + "b" * 100, "GitHub", "https://github.com/", True),
    Tab("opaque-window-" + "c" * 100, "", ""),
)
PAGE = replace(BLANK, tabs=TABS)
GOOGLE = Snapshot(NEW_TAB_URL, "Google", "Search", (), "google", browsing={"site": "google"})
RESULTS = replace(GOOGLE, url=NEW_TAB_URL + "search?q=Steve+Jobs", browsing={
    "site": "google", "results_ready": True, "results": [
        {"title": "Steve Jobs", "url": "https://en.wikipedia.org/wiki/Steve_Jobs"},
        {"title": "Steve Jobs biography", "url": "https://example.org/steve-jobs"},
    ],
})


def test_safari_new_tab_loads_google_without_replacing_existing_tab():
    driver = FakeDriver()
    browser = SafariBrowser(driver=driver)
    before = browser.snapshot()
    result = browser.execute({"type": "new_tab"}, before.fingerprint)
    assert driver.window_handles == ["first", "second"]
    assert driver.current_window_handle == "second"
    assert result["after_url"] == NEW_TAB_URL
    assert driver.calls[-1] == ("get", NEW_TAB_URL)
    assert browser._tab_titles["first"][1] == before.url
    assert browser._tab_titles["second"][1] == NEW_TAB_URL


def test_safari_handle_order_changes_do_not_renumber_existing_tabs():
    driver = FakeDriver()
    browser = SafariBrowser(driver=driver)
    browser.snapshot()
    browser.execute({"type": "new_tab"})
    driver.window_handles = ["second", "first"]
    assert [t.id for t in browser.snapshot().tabs] == ["first", "second"]
    browser.execute({"type": "switch_tab", "direction": "first"})
    assert driver.current_window_handle == "first"


@pytest.mark.parametrize("text", ["search for Steve Jobs", "can you search for ESP32 boards"])
@pytest.mark.parametrize("page", [BLANK, replace(BLANK, url="", title=""), GOOGLE])
def test_search_is_available_from_blank_or_google_without_a_rule_selected_action(text, page):
    options = contract_options(Goal("g", text), page)
    assert options and {c.site for c in options.values()} == {"google"}
    engine = RecordingGoalEngine({"objective": "search", "objective_query": "0"})
    goal = Goal("g", text)
    engine.prepare(goal, page)
    assert [q[0] for q in engine.asked] == ["objective", "objective_query"]
    assert "unsupported" in engine.asked[0][1]
    assert goal.contract.site == "google"
    assert action_space(goal, page)["CLICK"]["search:google"].action["query"] == goal.contract.query


def test_explicit_site_and_existing_site_search_are_preserved():
    for text, page, expected in [
        ("search for Mercury", WIKI, "wikipedia"),
        ("search for ESP32 on GitHub", GOOGLE, "github"),
        ("in a new tab search GitHub for ESP32", GOOGLE, "github"),
        ("open a new tab and search for Steve Jobs", WIKI, "google"),
    ]:
        options = contract_options(Goal("g", text), page)
        assert options and {c.site for c in options.values()} == {expected}
    assert not contract_options(Goal("g", "search for iPhones on Amazon"), GOOGLE)


@pytest.mark.parametrize("text", [
    "go to the first tab", "can you go to the other tab", "go to tab 3",
    "switch to the previous tab", "next tab", "go to the last tab",
])
def test_blank_tabs_are_selectable_by_position_and_never_offered_as_page_links(text):
    options = contract_options(Goal("g", text), PAGE)
    assert {c.kind for c in options.values()} == {"switch_tab"}
    assert {c.target_tab for c in options.values()} == {TABS[0].id, TABS[2].id}
    candidates = tab_candidates(PAGE)
    assert list(candidates) == ["tab:1", "tab:3"]
    assert "first, previous" in candidates["tab:1"].label
    assert "last, next" in candidates["tab:3"].label
    assert "Untitled / blank" in candidates["tab:1"].label
    assert "opaque-window" not in str({k: c.label for k, c in candidates.items()})


def test_laya_tab_choice_maps_back_to_real_handle():
    engine = RecordingGoalEngine({"objective": "switch_tab", "objective_tab": "tab:1",
                                  "operation": "CLICK", "target": "browser:switch_tab"})
    goal = Goal("g", "go to the first tab")
    engine.prepare(goal, PAGE)
    assert engine.choose(goal, PAGE).action == {"type": "switch_tab", "tab_id": TABS[0].id}
    assert TABS[0].id not in goal.contract.label()


def test_new_tab_only_is_not_done_when_empty_and_repairs_instead_of_opening_more():
    contract = GoalContract("", "new_tab", new_tab=True, initial_tabs=("old",))
    blank = replace(BLANK, tabs=(Tab("old", "", ""), Tab("new", "", "", True)))
    goal = Goal("g", "new tab", contract=contract)
    assert not verify(contract, blank).satisfied
    actions = action_space(goal, blank)["CLICK"]
    assert [c.action for c in actions.values()] == [{"type": "navigate", "url": NEW_TAB_URL}]
    loaded = replace(GOOGLE, tabs=blank.tabs)
    assert verify(contract, loaded).satisfied
    assert action_space(goal, loaded) == {}
    assert not verify(contract, replace(loaded, title="", text="")).satisfied
    assert not verify(contract, replace(loaded, url=NEW_TAB_URL + "sorry/")).satisfied


def test_google_search_needs_visible_results_not_just_a_url_or_query_field():
    contract = GoalContract("google", "search", "Steve Jobs")
    assert verify(contract, RESULTS).satisfied
    assert not verify(contract, GOOGLE).satisfied
    assert not verify(contract, replace(RESULTS, browsing={})).satisfied
    assert not verify(contract, replace(RESULTS, url=NEW_TAB_URL + "search?q=Steve+Wozniak")).satisfied
    assert not verify(contract, replace(RESULTS, browsing={
        **RESULTS.browsing, "results_ready": False})).satisfied


def test_google_external_result_verification_preserves_new_tab_and_full_destination():
    contract = GoalContract("google", "open_result", "Steve Jobs", ordinal=2)
    assert not verify(contract, RESULTS).satisfied
    assert contract.expected_url == "https://example.org/steve-jobs"
    landed = replace(GOOGLE, url=contract.expected_url, title="Biography", text="Steve Jobs", browsing={})
    assert verify(contract, landed).satisfied
    assert not verify(contract, replace(landed, url="https://example.org/")).satisfied
    assert not verify(contract, replace(landed, title="", text="")).satisfied
    assert not verify(GoalContract("google", "open_result", "Steve Jobs", ordinal=2), landed).satisfied
    contract.new_tab = True
    contract.initial_tabs = ("old",)
    assert not verify(contract, replace(landed, tabs=(Tab("old", "", "", True),))).satisfied
    assert verify(contract, replace(landed, tabs=(Tab("new", "", "", True),))).satisfied


def test_google_result_evidence_excludes_internal_and_unsafe_destinations():
    page = replace(RESULTS, browsing={**RESULTS.browsing, "results": [
        *RESULTS.browsing["results"],
        {"title": "Images", "url": NEW_TAB_URL + "search?tbm=isch&q=Steve"},
        {"title": "Fake", "url": "javascript:alert(1)"},
        {"title": "Checkout", "url": "https://shop.example/checkout"},
    ]})
    assert len(observed_results(page)) == 2
    assert scope("https://www.google.co.in/search?q=test") == "google"


def test_close_others_cannot_degrade_to_close_current():
    goal = Goal("g", "close all other tabs")
    assert {c.kind for c in contract_options(goal, PAGE).values()} == {"close_other_tabs"}
    engine = RecordingGoalEngine({"objective": "close_other_tabs", "operation": "CLICK",
                                  "target": "browser:close_other_tabs"})
    engine.prepare(goal, PAGE)
    assert engine.choose(goal, PAGE).action == {"type": "close_other_tabs"}
    assert not verify(goal.contract, PAGE).satisfied
    remaining = replace(PAGE, tabs=(TABS[1],))
    assert verify(goal.contract, remaining).satisfied
    assert not verify(goal.contract, replace(PAGE, tabs=(TABS[0],))).satisfied
    assert not contract_options(Goal("g", "close all other tabs"), remaining)


def test_scoped_search_cannot_type_into_the_wrong_site_or_click_unrelated_links():
    goal = Goal("g", "open GitHub and search for ESP32", contract=GoalContract("github", "search", "ESP32"))
    groups = action_space(goal, WIKI)
    assert "TYPE_TEXT" not in groups
    assert set(groups["CLICK"]) == {"search:github"}
    goal.contract = GoalContract("wikipedia", "search", "ESP32")
    groups = action_space(goal, WIKI)
    assert set(groups["TYPE_TEXT"]) == {"e1"}
    assert set(groups["CLICK"]) == {"e2", "search:wikipedia"}


def test_browser_challenge_does_not_trap_a_tab_switch_request():
    challenge = replace(PAGE, url="https://www.google.com/sorry/index", title="Verification required")
    after = replace(BLANK, tabs=tuple(replace(t, active=i == 0) for i, t in enumerate(TABS)))
    browser = Browser([challenge, after])
    engine = RecordingGoalEngine({"objective": "switch_tab", "objective_tab": "tab:1",
                                  "operation": "CLICK", "target": "browser:switch_tab"})
    controller = GoalController(browser, engine, announce=lambda _: None)
    try:
        controller.submit(event("go to the first tab"))
        controller.wait_idle()
        assert controller.goal.status == "verified_done"
        assert browser.executed == [{"type": "switch_tab", "tab_id": TABS[0].id}]
    finally:
        controller.close()


def test_browser_challenge_does_not_trap_a_request_to_leave_for_another_site():
    challenge = replace(PAGE, url="https://www.google.com/sorry/index", title="Verification required")
    youtube = Snapshot("https://www.youtube.com/", "YouTube", "Videos", (), "youtube",
                       browsing={"site": "youtube"})
    browser = Browser([challenge, youtube])
    engine = RecordingGoalEngine({"objective": "open_site", "operation": "CLICK",
                                  "target": "site:youtube"})
    controller = GoalController(browser, engine, announce=lambda _: None)
    try:
        controller.submit(event("go to YouTube"))
        controller.wait_idle()
        assert controller.goal.status == "verified_done"
        assert browser.executed == [{"type": "navigate", "url": "https://www.youtube.com/"}]
    finally:
        controller.close()
