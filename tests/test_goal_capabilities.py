"""Contract and controller regressions; canned decisions are not model-accuracy claims."""
import threading
from dataclasses import replace

import pytest
from test_goals import BLANK, WIKI, Browser, Engine, RecordingGoalEngine, decision, event

from laya_voice_browser.goal_contracts import (
    GoalContract,
    awaiting_render,
    contract_options,
    observed_results,
    search_matches,
    verify,
)
from laya_voice_browser.goal_controller import GoalController
from laya_voice_browser.goal_engine import GoalDecision
from laya_voice_browser.goal_fast_path import direct_action
from laya_voice_browser.goals import Goal, action_space
from laya_voice_browser.types import Snapshot, Tab

VIDEO1 = "https://www.youtube.com/watch?v=abcdefghijk"
VIDEO2 = "https://www.youtube.com/watch?v=12345678901"
RESULTS = Snapshot(
    "https://www.youtube.com/results?search_query=ESP32", "ESP32 - YouTube", "ESP32", (), "results",
    browsing={"site": "youtube", "results_ready": True, "results": [
        {"url": VIDEO1, "title": "ESP32 getting started"},
        {"url": VIDEO1 + "&t=4", "title": "Duplicate thumbnail"},
        {"url": VIDEO2, "title": "ESP32 projects"},
    ]})
WATCH = replace(RESULTS, url=VIDEO1, fingerprint="watch", browsing={
    "site": "youtube", "detail_ready": True, "heading": "ESP32 getting started"})
ARTICLE = replace(WIKI, url="https://en.wikipedia.org/wiki/Mercury", title="Mercury - Wikipedia",
                  browsing={"site": "wikipedia", "detail_ready": True, "heading": "Mercury"})


@pytest.mark.parametrize("changes", [
    {"url": "https://www.google.com/search?q=ESP32"},
    {"url": "https://www.youtube.com/results?search_query=ESP8266"},
    {"url": "https://www.youtube.com/"},
    {"browsing": {}},
    {"browsing": {"site": "youtube", "results_ready": True, "results": []}},
    {"browsing": {"site": "youtube", "results_ready": False, "results": RESULTS.browsing["results"]}},
    {"title": "Access Denied"},
])
def test_query_url_or_field_alone_never_proves_search(changes):
    assert not verify(GoalContract("youtube", "search", "ESP32"), replace(RESULTS, **changes)).satisfied


def test_search_and_open_result_have_different_postconditions():
    assert verify(GoalContract("youtube", "search", "ESP32"), RESULTS).satisfied
    contract = GoalContract("youtube", "open_result", "ESP32", ordinal=1)
    assert not verify(contract, RESULTS).satisfied
    assert contract.expected_url == VIDEO1
    assert not verify(contract, replace(WATCH, url=VIDEO2)).satisfied
    assert not verify(contract, replace(WATCH, browsing={"site": "youtube"})).satisfied
    assert verify(contract, WATCH).satisfied
    # Landing on a random video cannot satisfy a search+open goal without observing the requested search.
    assert not verify(GoalContract("youtube", "open_result", "ESP32", ordinal=1), WATCH).satisfied


def test_wikipedia_redirect_requires_exact_heading_and_article():
    assert search_matches(ARTICLE, "wikipedia", "Mercury")
    assert not search_matches(replace(ARTICLE, url=WIKI.url), "wikipedia", "Mercury")
    assert not search_matches(replace(ARTICLE, browsing={
        **ARTICLE.browsing, "heading": "Mercury poisoning"}), "wikipedia", "Mercury")
    assert not search_matches(replace(ARTICLE, browsing={
        **ARTICLE.browsing, "detail_ready": False}), "wikipedia", "Mercury")


def test_github_search_requires_repository_results_not_users_or_topics():
    page = replace(RESULTS, url="https://github.com/search?q=ESP32&type=repositories", browsing={
        "site": "github", "results_ready": True, "results": [
            {"url": "https://github.com/topics/esp32", "title": "Topic"},
            {"url": "https://github.com/espressif/esp-idf", "title": "espressif/esp-idf"}]})
    assert len(observed_results(page)) == 1
    assert search_matches(page, "github", "ESP32")
    assert not search_matches(replace(page, url=page.url.replace("repositories", "users")), "github", "ESP32")


def test_new_tab_is_part_of_the_verified_outcome():
    contract = GoalContract("youtube", "search", "ESP32", new_tab=True, initial_tabs=("old",))
    assert not verify(contract, replace(RESULTS, tabs=(Tab("old", "", "", True),))).satisfied
    assert verify(contract, replace(RESULTS, tabs=(Tab("new", "", "", True),))).satisfied


def test_contract_cannot_drop_an_explicit_site_query_or_result_clause():
    goal = Goal("g", "open YouTube and search for ESP32 and open the first video")
    options = contract_options(goal, BLANK)
    assert options and all(c.site == "youtube" and c.kind == "open_result" for c in options.values())
    assert all(c.query == "ESP32" for c in options.values())
    assert contract_options(Goal("g", "open youtube and github"), BLANK) == {}
    assert contract_options(Goal("g", "search for ESP32 on amazon"), BLANK) == {}


def test_laya_selects_outcome_and_can_reject_side_talk():
    engine = RecordingGoalEngine({"objective": "search", "objective_query": "0"})
    goal = Goal("g", "open wikipedia and search for Mercury")
    engine.prepare(goal, BLANK)
    assert goal.contract == GoalContract("wikipedia", "search", "Mercury", initial_url=BLANK.url)
    assert engine.asked[0][0] == "objective"
    assert "unsupported" in engine.asked[0][1]


def test_capabilities_offer_model_choices_without_matching_phrases(monkeypatch):
    import laya_voice_browser.sites as sites

    def forbidden(*args, **kwargs):
        raise AssertionError("Legacy matcher called")

    monkeypatch.setattr(sites, "match_phrase", forbidden)
    monkeypatch.setattr(sites, "lexical_match", forbidden)
    goal = Goal("g", "search for ESP32 and open the second video",
                contract=GoalContract("youtube", "open_result", "ESP32", ordinal=2))
    verify(goal.contract, RESULTS)
    choices = action_space(goal, RESULTS)["CLICK"]
    assert "result:1" not in choices  # cannot fulfil the model-selected second-result contract
    assert choices["result:2"].action["url"] == VIDEO2
    assert "search:google" not in choices
    assert "search:youtube" not in choices  # already visibly completed, not offered as a repeat
    engine = RecordingGoalEngine({"operation": "CLICK", "target": "result:2"})
    picked = engine.choose(goal, RESULTS)
    assert picked.action["url"] == VIDEO2
    assert picked.candidate.source == "capability"


class ContractEngine(Engine):
    def __init__(self, contract, replies):
        super().__init__(replies)
        self.contract = contract

    def prepare(self, goal, page):
        goal.contract = self.contract
        return GoalDecision("INTERPRET")


def test_verified_state_stops_before_an_extra_model_call_even_at_action_budget():
    engine = ContractEngine(GoalContract("youtube", "search", "ESP32"), [decision(RESULTS.url)])
    c = GoalController(Browser([BLANK, RESULTS]), engine, max_steps=1, announce=lambda _: None)
    try:
        c.submit(event("search YouTube for ESP32"))
        c.wait_idle()
        assert c.goal.status == "verified_done"
        assert len(engine.seen) == len(c.browser.executed) == 1
    finally:
        c.close()


def test_done_on_unsubmitted_query_never_reports_success():
    engine = ContractEngine(GoalContract("wikipedia", "search", "Mercury"), [GoalDecision("DONE")])
    c = GoalController(Browser([WIKI]), engine, announce=lambda _: None)
    try:
        c.submit(event())
        c.wait_idle()
        assert c.goal.status == "unverified_done"
        assert c.browser.executed == []
    finally:
        c.close()


@pytest.mark.parametrize("text,kind", [
    ("scroll down", "scroll"), ("Could you scroll up a little please", "scroll"),
    ("go back", "back"), ("go forward", "forward"),
])
def test_universal_controls_skip_model_and_settling(text, kind):
    messages = []
    c = GoalController(Browser(), Engine(), announce=messages.append)
    c._observe_settled = lambda *args: pytest.fail("Direct command used the settling loop")
    try:
        c.submit(event(text, final=False))
        c.wait_idle()
        assert not c.browser.executed
        c.submit(event(text))
        c.wait_idle()
        assert c.goal.status == "direct_done" and not c.engine.seen
        assert [a["type"] for a in c.browser.executed] == [kind]
        assert any("Universal action:" in message for message in messages)
        assert "goal stopped: direct_done; 1 action" in messages
        c.submit(event(text))
        c.wait_idle()
        assert len(c.browser.executed) == 1
    finally:
        c.close()


@pytest.mark.parametrize("text", [
    "scroll down to the comments", "next page", "go back ten seconds", "forward this email",
    "go back and open youtube", "don't go back", "we should go back", "and scroll down",
    "close tab", "open wikipedia", "scroll down a little and then stop",
])
def test_contextual_or_compound_commands_are_not_direct(text):
    assert direct_action(text) is None


def test_direct_command_interrupts_inflight_goal_and_late_final_cannot_revive_it():
    started, release = threading.Event(), threading.Event()

    class Slow(Engine):
        def choose(self, goal, page):
            started.set()
            assert release.wait(2)
            return decision(WIKI.url)

    c = GoalController(Browser(), Slow(), announce=lambda _: None)
    try:
        c.submit(event())
        assert started.wait(2)
        c.submit(event("go back", id="direct"))
        release.set()
        c.wait_idle()
        assert c.browser.executed == [{"type": "back"}]
        c.submit(event())
        c.wait_idle()
        assert len(c.browser.executed) == 1
    finally:
        release.set()
        c.close()


@pytest.mark.parametrize("text,query", [
    ("search youtube for lofi beats and play the first video", "lofi beats"),
    ("search youtube for jazz and watch the top video", "jazz"),
    ("search wikipedia for cats and show me the first result", "cats"),
])
def test_a_result_clause_never_ends_up_inside_the_query(text, query):
    # "and play the first video" used to stay in the span, so the wrong search ran and then
    # verified, because verification checks for the query that was actually searched.
    from laya_voice_browser.goals import literal_spans

    assert literal_spans(text)[0] == query


@pytest.mark.parametrize("text,ordinal", [
    ("search youtube for cats and open the third video", 3),
    ("on github search for esp32 and open the second repository", 2),
    ("search youtube for jazz and watch the top video", 1),
])
def test_a_spoken_result_number_is_extracted_not_guessed(text, ordinal):
    # Offering 1-3 made Laya choose between them; it scored near-uniform for anything but "first".
    options = contract_options(Goal("g", text), BLANK).values()
    ordinals = {c.ordinal for c in options if c.kind == "open_result"}
    assert ordinals == {ordinal}


def test_an_ordinal_inside_the_query_is_not_the_result_number():
    text = "search wikipedia for first world war and open the second result"
    options = contract_options(Goal("g", text), BLANK).values()
    assert {c.ordinal for c in options if c.kind == "open_result"} == {2}
    assert {c.query for c in options} == {"first world war"}


def test_an_unnumbered_result_request_still_offers_laya_the_choice():
    text = "search youtube for cats and play the video"
    options = contract_options(Goal("g", text), BLANK).values()
    ordinals = {c.ordinal for c in options if c.kind == "open_result"}
    assert ordinals == {1, 2, 3}


def test_show_me_result_cannot_degrade_to_search_only():
    options = contract_options(Goal("g", "search youtube for cats and show me the first result"), BLANK)
    assert options and all(c.kind == "open_result" and c.ordinal == 1 for c in options.values())


def test_site_mentioned_as_query_is_not_a_second_destination():
    options = contract_options(Goal("g", "search wikipedia for GitHub"), BLANK)
    assert options and all(c.site == "wikipedia" and c.query == "GitHub" for c in options.values())


def test_unsupported_extra_clause_is_not_silently_dropped():
    assert not contract_options(Goal("g", "search youtube for cats and close tab"), BLANK)


def test_close_tab_has_model_chosen_outcome_action_and_exact_tab_verification():
    page = replace(BLANK, tabs=(Tab("a", "A", "", True), Tab("b", "B", "", False)))
    engine = RecordingGoalEngine({"objective": "close_tab", "operation": "CLICK",
                                  "target": "browser:close_tab"})
    goal = Goal("g", "close tab")
    engine.prepare(goal, page)
    assert goal.contract.kind == "close_tab"
    assert engine.choose(goal, page).action == {"type": "close_tab"}
    assert not verify(goal.contract, page).satisfied
    assert not verify(goal.contract, replace(page, tabs=(page.tabs[0],))).satisfied
    assert verify(goal.contract, replace(page, tabs=(replace(page.tabs[1], active=True),))).satisfied


def test_contextual_scroll_has_model_chosen_outcome():
    page = replace(WIKI, can_scroll_down=True)
    engine = RecordingGoalEngine({"objective": "scroll_down", "operation": "SCROLL_DOWN"})
    goal = Goal("g", "and scroll down")
    engine.prepare(goal, page)
    assert engine.choose(goal, page).action["type"] == "scroll"
    assert not verify(goal.contract, page).satisfied
    assert verify(goal.contract, replace(page, scroll_y=300)).satisfied
    assert not verify(goal.contract, replace(page, url=RESULTS.url, scroll_y=300)).satisfied


def test_done_recovery_returns_to_model_and_stops_after_verified_result():
    engine = ContractEngine(GoalContract("youtube", "search", "ESP32"),
                            [GoalDecision("DONE"), decision(RESULTS.url)])
    c = GoalController(Browser([BLANK, RESULTS]), engine, announce=lambda _: None)
    try:
        c.submit(event("search YouTube for ESP32"))
        c.wait_idle()
        assert c.goal.status == "verified_done"
        assert c.goal.rejected_done == 1
        assert len(c.browser.executed) == 1 and len(engine.seen) == 2
    finally:
        c.close()


def test_repeated_unverified_done_is_bounded():
    engine = ContractEngine(GoalContract("youtube", "search", "ESP32"), [GoalDecision("DONE")])
    c = GoalController(Browser([BLANK]), engine, announce=lambda _: None)
    try:
        c.submit(event())
        c.wait_idle()
        assert c.goal.status == "unverified_done" and len(engine.seen) == 3
        assert not c.browser.executed
    finally:
        c.close()


def test_recovery_does_not_force_a_browser_action():
    engine = RecordingGoalEngine({"operation": "BLOCKED"})
    goal = Goal("g", "search youtube for ESP32", rejected_done=1,
                verification_feedback="requested search not rendered")
    assert engine.choose(goal, BLANK).operation == "BLOCKED"
    options = engine.asked[0][1]
    assert "DONE" not in options and {"WAIT", "BLOCKED", "CLICK"} <= options.keys()


def test_followup_after_verified_goal_does_not_reexecute_completed_request():
    engine = ContractEngine(GoalContract("youtube", "search", "ESP32"), [decision(RESULTS.url)])
    c = GoalController(Browser([BLANK, RESULTS]), engine, announce=lambda _: None)
    try:
        c.submit(event("search YouTube for ESP32"))
        c.wait_idle()
        assert c.goal.status == "verified_done"
        c.submit(event("and scroll down", final=False, id="followup"))
        assert c.goal.text == "and scroll down" and not c.goal.history
    finally:
        c.close()


def test_known_search_skeleton_waits_but_unsubmitted_query_is_still_actionable():
    contract = GoalContract("youtube", "open_result", "ESP32", ordinal=1)
    skeleton = replace(RESULTS, browsing={"site": "youtube", "results_ready": False})
    assert awaiting_render(contract, skeleton)
    assert not awaiting_render(contract, RESULTS)
    assert not awaiting_render(contract, replace(skeleton, url="https://www.youtube.com/"))
    verify(contract, RESULTS)
    assert awaiting_render(contract, replace(WATCH, browsing={"site": "youtube"}))
    assert not awaiting_render(contract, WATCH)


def test_named_tab_reference_is_not_mistaken_for_opening_a_website():
    page = replace(BLANK, tabs=(Tab("a", "YouTube", "", True), Tab("b", "GitHub", "", False)))
    engine = RecordingGoalEngine({"objective": "switch_tab", "objective_tab": "tab:2",
                                  "operation": "CLICK", "target": "browser:switch_tab"})
    goal = Goal("g", "switch to the GitHub tab")
    engine.prepare(goal, page)
    assert engine.choose(goal, page).action == {"type": "switch_tab", "tab_id": "b"}
    assert verify(goal.contract, replace(page, tabs=(replace(page.tabs[0], active=False),
                                                   replace(page.tabs[1], active=True)))).satisfied


def test_new_tab_precondition_prevents_searching_in_original_tab():
    goal = Goal("g", "search youtube for ESP32 in a new tab", contract=GoalContract(
        "youtube", "search", "ESP32", new_tab=True, initial_tabs=("a",)))
    page = replace(BLANK, tabs=(Tab("a", "old", "", True),))
    choices = action_space(goal, page)
    assert list(choices["CLICK"]) == ["browser:new_tab"]
    assert choices["CLICK"]["browser:new_tab"].action == {"type": "new_tab"}


TABBED = Snapshot(
    "https://en.wikipedia.org/wiki/Alan_Turing", "Alan Turing", "text", (), "fp",
    tabs=(Tab("t1", "Alan Turing", "https://en.wikipedia.org/wiki/Alan_Turing", True),
          Tab("t2", "GitHub", "https://github.com/", False)),
)


@pytest.mark.parametrize("text", ["please don't close this tab", "do not close the tab", "never scroll down"])
def test_a_negated_control_offers_nothing_to_do(text):
    # Live run: "please don't close this tab" closed a tab and reported verified_done.
    assert contract_options(Goal("g", text), TABBED) == {}


@pytest.mark.parametrize("text", ["open the Talk page", "open View history", "show pull requests"])
def test_a_link_on_the_page_is_a_link_outcome_not_a_tab_or_scroll(text):
    # Live run: "open the Talk page" opened a blank tab and verified it, because only controls were
    # offered. It is a link: that is the only outcome offered for it now.
    assert {c.kind for c in contract_options(Goal("g", text), TABBED).values()} == {"open_link"}


@pytest.mark.parametrize("text,kinds", [
    ("close this tab", {"close_tab", "switch_tab"}),
    ("open a new tab", {"new_tab", "open_link"}),
    ("switch to the GitHub tab", {"switch_tab"}),
    ("and scroll down", {"scroll_up", "scroll_down"}),
])
def test_a_control_is_offered_when_its_own_words_are_spoken(text, kinds):
    assert {c.kind for c in contract_options(Goal("g", text), TABBED).values()} == kinds


def _link(id, text, href, role="link"):
    from laya_voice_browser.types import Element
    return Element(id=id, role=role, text=text, tag="a", href=href)


REPO = Snapshot(
    "https://github.com/fastapi/fastapi", "fastapi/fastapi", "text",
    (_link("e1", "Issues 3", "https://github.com/fastapi/fastapi/issues"),
     _link("e2", "Pull requests", "https://github.com/fastapi/fastapi/pulls"),
     _link("e3", "Code", "https://github.com/fastapi/fastapi")),
    "fp",
)


def test_link_options_merge_page_links_with_pack_navigation():
    from laya_voice_browser.goal_contracts import link_options

    urls = {c.action["url"]: c for c in link_options(REPO).values()}
    # The page's own link wins a shared URL; the pack adds destinations the page does not show.
    assert urls["https://github.com/fastapi/fastapi/issues"].label == "Issues 3 (link)"
    assert urls["https://github.com/fastapi/fastapi/releases"].source == "pack"
    # A link to where the browser already is would verify having done nothing.
    assert "https://github.com/fastapi/fastapi" not in urls


def test_repository_templates_are_not_built_off_a_repository_page():
    from laya_voice_browser.goal_contracts import link_options

    search = Snapshot("https://github.com/search?q=x&type=repositories", "Search", "text", (), "fp")
    assert not [c for c in link_options(search).values() if c.source == "pack"]


def test_a_negated_link_request_offers_nothing():
    assert contract_options(Goal("g", "please don't open issues"), REPO) == {}


def test_a_link_outcome_verifies_only_at_its_own_destination():
    from laya_voice_browser.goal_contracts import GoalContract, verify

    contract = GoalContract("github", "open_link", expected_url="https://github.com/fastapi/fastapi/issues")
    there = replace(REPO, url="https://github.com/fastapi/fastapi/issues/")
    assert verify(contract, there).satisfied
    assert not verify(contract, replace(REPO, url="https://github.com/fastapi/fastapi/pulls")).satisfied
    assert not verify(contract, replace(there, title="", text="", elements=())).satisfied


def test_a_chosen_link_is_the_only_tool_offered():
    from laya_voice_browser.goal_contracts import GoalContract

    goal = Goal("g", "open Issues", contract=GoalContract(
        "github", "open_link", expected_url="https://github.com/fastapi/fastapi/issues", link_label="Issues"))
    groups = action_space(goal, REPO)
    assert list(groups) == ["CLICK"]
    [(key, candidate)] = groups["CLICK"].items()
    assert candidate.action == {"type": "navigate", "url": "https://github.com/fastapi/fastapi/issues"}
