import threading
import time
from dataclasses import replace

import pytest

from laya_voice_browser.browser import StalePage
from laya_voice_browser.goal_controller import GoalController
from laya_voice_browser.goal_engine import GoalDecision, GoalEngine, UncertainDecision, validate_choice
from laya_voice_browser.goals import (
    Candidate,
    Goal,
    action_space,
    browser_blocker,
    evidence,
    literal_spans,
    materialize,
    missing_payload,
    page_identity,
)
from laya_voice_browser.page import decision_still_valid, snapshot_from_raw
from laya_voice_browser.types import Element, Snapshot, Tab, TranscriptEvent

BLANK = Snapshot("about:blank", "Blank", "", (), "blank")
WIKI = Snapshot("https://en.wikipedia.org/wiki/Main_Page", "Wikipedia", "", (
    Element("e1", "searchbox", "Search Wikipedia", "input", input_type="search"),
    Element("e2", "button", "Search", "button"),
    Element("e3", "link", "Log in", "a", href="https://en.wikipedia.org/login"),
    Element("e4", "link", "Mercury", "a", href="https://en.wikipedia.org/wiki/Mercury"),
), "wiki")
RESULT = replace(WIKI, url="https://en.wikipedia.org/wiki/Mercury", title="Mercury", fingerprint="result")


@pytest.mark.parametrize("text,expected", [
    ("open wikipedia and search for Mercury", ["Mercury"]),
    ("search for cats and dogs", ["cats and dogs"]),
    ("search for ESP32 and click the first result", ["ESP32"]),
    ("search for ESP32 on github", ["ESP32"]),
    ("search for", []), ("go to", []), ("search", []),
    ('find "ESP32 C6"', ["ESP32 C6"]),
])
def test_literal_spans(text, expected):
    assert literal_spans(text) == expected


def test_capabilities_do_not_pick_a_winner_and_keep_both_search_scopes():
    groups = action_space(Goal("g", "open wikipedia and search for Mercury"), WIKI)
    assert {"search:wikipedia", "search:google", "e4"} <= groups["CLICK"].keys()
    assert "site:wikipedia" not in groups["CLICK"]  # already at that exact destination
    assert "e3" not in groups["CLICK"]
    assert list(groups["TYPE_TEXT"]) == ["e1"]
    assert groups["CLICK"]["search:wikipedia"].source == "browser"


@pytest.mark.parametrize("element", [
    Element("e", "input", "Search", "input", input_type="password"),
    Element("e", "input", "Search", "input", disabled=True),
    Element("e", "input", "Search", "input", readonly=True),
    Element("e", "button", "Buy now", "button"),
    Element("e", "link", "Logout", "a", href="https://example.com/logout"),
    Element("e", "link", "Run", "a", href="javascript:alert(1)"),
    Element("e", "link", "Add to cart", "a", href="https://shop.test/item"),
    Element("e", "link", "Continue", "a", href="https://shop.test/checkout"),
])
def test_unsafe_or_unsupported_controls_not_offered(element):
    groups = action_space(Goal("g", "search for ESP32"), replace(WIKI, elements=(element,)))
    assert "e" not in groups["CLICK"]
    assert "TYPE_TEXT" not in groups


def test_materialize_search_encodes_exact_text():
    c = Candidate("Search", {"type": "search", "site": "github"})
    assert materialize(c, "ESP32 C6 & C++")["url"].endswith("q=ESP32+C6+%26+C%2B%2B&type=repositories")
    with pytest.raises(ValueError):
        materialize(c)


@pytest.mark.parametrize("text", ["go to", "can you open", "search for", "open wikipedia and search"])
def test_final_missing_payload_does_not_become_a_browser_action(text):
    assert missing_payload(text)
    c = GoalController(Browser(), Engine(), announce=lambda _: None)
    try:
        c.submit(event(text))
        c.wait_idle()
        assert not c.engine.seen
        assert not c.browser.executed
        assert c.goal.status == "clarify"
    finally:
        c.close()


def test_already_filled_search_is_not_a_type_capability():
    page = replace(WIKI, elements=(replace(WIKI.elements[0], value="Mercury"), *WIKI.elements[1:]))
    groups = action_space(Goal("g", "search for Mercury"), page)
    assert "TYPE_TEXT" not in groups
    assert "e2" in groups["CLICK"]  # submission still requires a model-chosen click


class RecordingGoalEngine(GoalEngine):
    """Test wiring only. Live accuracy is measured by benchmark_goal_loop.py."""

    def __init__(self, replies):
        super().__init__("fake")
        self.replies = replies
        self.asked = []

    def warm(self):
        pass

    def _prefix_fits(self, question):
        return True

    def _ask(self, qid, goal, page, options, rules, decision):
        self.asked.append((qid, dict(options), goal.text))
        reply = self.replies[qid]
        assert reply in options
        return reply


def test_model_selects_operation_target_and_span_even_for_explicit_commands():
    engine = RecordingGoalEngine({"operation": "CLICK", "target": "search:wikipedia", "text_span": "0"})
    d = engine.choose(Goal("g", "open wikipedia and search for Mercury"), BLANK)
    assert [q[0] for q in engine.asked] == ["operation", "target", "text_span"]
    assert d.action["url"] == "https://en.wikipedia.org/w/index.php?search=Mercury"
    assert "Mercury" in d.candidate.label


def test_model_can_choose_done_without_rule_execution():
    engine = RecordingGoalEngine({"operation": "DONE"})
    d = engine.choose(Goal("g", "open wikipedia"), WIKI)
    assert d.operation == "DONE" and d.action is None
    assert len(engine.asked) == 1


def test_model_target_wins_not_lexical_label_match():
    engine = RecordingGoalEngine({"operation": "CLICK", "target": "e2"})
    d = engine.choose(Goal("g", "open Mercury"), WIKI)
    # An intentionally bad canned choice proves there is no lexical winner replacing Laya.
    assert d.action == {"type": "click", "target_id": "e2"}


def test_cancelled_utterance_cannot_be_revived_by_a_late_final():
    c = GoalController(Browser(), Engine(), announce=lambda _: None)
    try:
        c.submit(event(final=False))
        c.cancel()
        c.submit(event(final=True))
        c.wait_idle()
        assert not c.engine.seen
    finally:
        c.close()


def test_voice_off_ignores_late_speech_until_resumed():
    c = GoalController(Browser(), Engine(), announce=lambda _: None)
    try:
        c.pause()
        c.submit(event())
        c.wait_idle()
        assert not c.engine.seen
        c.resume()
        c.submit(event())
        c.wait_idle()
        assert c.engine.seen
    finally:
        c.close()


@pytest.mark.parametrize("page,status", [
    (replace(BLANK, url="https://www.ebay.com/splashui/challenge", title="Pardon Our Interruption..."),
     "browser_challenge"),
    (replace(BLANK, url="https://www.youtube.com/results?q=x", title=""), "page_not_ready"),
])
def test_blocked_or_empty_web_pages_cannot_be_declared_done(page, status):
    c = GoalController(Browser([page]), Engine([GoalDecision("DONE")]),
                       ready_timeout=0.1, announce=lambda _: None)
    try:
        c.submit(event())
        c.wait_idle()
        assert c.goal.status == status
        assert c.engine.seen == []
        assert c.browser.executed == []
    finally:
        c.close()


def test_articles_about_captchas_are_not_browser_challenges():
    page = replace(WIKI, title="CAPTCHA - Wikipedia", text="CAPTCHA is a type of test")
    assert browser_blocker(page) is None


@pytest.mark.parametrize("answer", [
    {}, {"choice": "x", "probabilities": {"x": 1}},
    {"choice": "a", "probabilities": {"a": float("nan"), "b": 0}},
    {"choice": "a", "probabilities": {"a": 0.1, "b": 0.9}},
    {"choice": "a", "probabilities": {"a": 0.51, "b": 0.49}},
])
def test_bad_or_ambiguous_choices_never_execute(answer):
    with pytest.raises(UncertainDecision):
        validate_choice(answer, {"a": "A", "b": "B"})


def test_progress_and_staleness_include_values_scroll_tabs_and_document():
    filled = replace(WIKI, elements=(replace(WIKI.elements[0], value="Mercury"), *WIKI.elements[1:]),
                     fingerprint="filled")
    assert page_identity(WIKI) != page_identity(filled)
    assert not decision_still_valid(WIKI, filled, WIKI.fingerprint, {"target_id": "e1"})
    assert page_identity(WIKI) != page_identity(replace(WIKI, scroll_y=300))
    assert page_identity(WIKI) != page_identity(replace(WIKI, document_id="new"))
    assert page_identity(WIKI) != page_identity(replace(WIKI, tabs=(Tab("a", "", "", True),)))
    assert evidence(Candidate("type", {}, "fill"), {"type": "type", "target_id": "e1", "text": "Mercury"},
                    WIKI, filled)["page_changed"]
    raw = {"url": "x", "elements": [{"id": "e", "value": "old"}]}
    assert snapshot_from_raw(raw).fingerprint != snapshot_from_raw({
        **raw, "elements": [{"id": "e", "value": "new"}]}).fingerprint


class Browser:
    def __init__(self, pages=None):
        self.pages = pages or [BLANK, WIKI, RESULT]
        self.index = 0
        self.executed = []
        self.stale_once = False

    def snapshot(self):
        return self.pages[min(self.index, len(self.pages) - 1)]

    def execute(self, action, expected_fingerprint=None):
        if self.stale_once:
            self.stale_once = False
            raise StalePage()
        assert expected_fingerprint == self.snapshot().fingerprint
        self.executed.append(action)
        self.index += 1
        return {"ok": True, "after_url": self.snapshot().url}


def decision(url):
    action = {"type": "navigate", "url": url}
    return GoalDecision("CLICK", Candidate(url, action), action)


class Engine:
    model_name = "scripted-controller-test-not-real-model"

    def __init__(self, replies=None):
        self.replies = replies or [decision(WIKI.url), decision(RESULT.url), GoalDecision("DONE")]
        self.seen = []

    def choose(self, goal, page):
        self.seen.append((goal.text, page.url, len(goal.history)))
        return self.replies[min(len(self.seen) - 1, len(self.replies) - 1)]

    def prepare(self, goal, page):
        return GoalDecision("INTERPRET")


def event(text="open wikipedia and search for Mercury", final=True, id="g"):
    return TranscriptEvent(text, final, id, time.time())


def test_loop_preserves_entire_goal_reobserves_and_asks_model_again():
    browser, engine = Browser(), Engine()
    controller = GoalController(browser, engine, announce=lambda _: None)
    try:
        controller.submit(event())
        controller.wait_idle()
        assert len(browser.executed) == 2
        assert engine.seen == [(event().text, BLANK.url, 0), (event().text, WIKI.url, 1),
                               (event().text, RESULT.url, 2)]
        assert controller.goal.status == "unverified_done"
        controller.submit(event())
        controller.wait_idle()
        assert len(browser.executed) == 2
    finally:
        controller.close()


def test_partial_never_executes_and_continuation_prefix_survives_asr_revision():
    c = GoalController(Browser(), Engine(), announce=lambda _: None)
    try:
        c.submit(event("open wikipedia", False))
        c.wait_idle()
        assert not c.engine.seen
        c.submit(event("and search", False, "g2"))
        c.submit(event("and search for Mercury", False, "g2"))
        assert c.goal.text == "open wikipedia; and search for Mercury"
        c.submit(event("open youtube", False, "g3"))
        assert c.goal.text == "open youtube"  # unrelated new request replaces the goal
    finally:
        c.close()


@pytest.mark.parametrize("cancel", ["partial", "stop", "voice_off"])
def test_new_speech_and_stop_discard_inflight_prediction(cancel):
    started, release = threading.Event(), threading.Event()

    class SlowEngine(Engine):
        def choose(self, goal, page):
            started.set()
            assert release.wait(2)
            return decision(WIKI.url)

    c = GoalController(Browser(), SlowEngine(), announce=lambda _: None)
    try:
        c.submit(event())
        assert started.wait(2)
        if cancel == "voice_off":
            c.pause()
        else:
            c.submit(event("stop" if cancel == "stop" else "actually open youtube", False))
        release.set()
        c.wait_idle()
        assert c.browser.executed == []
    finally:
        release.set()
        c.close()


def test_waits_and_repeated_actions_are_bounded():
    for engine, pages, expected in [(Engine([GoalDecision("WAIT")]), [WIKI], "stalled"),
                                    (Engine([decision(WIKI.url)]), [WIKI], "repeated_action")]:
        c = GoalController(Browser(pages), engine, announce=lambda _: None)
        try:
            c.submit(event())
            c.wait_idle()
            assert c.goal.status == expected
            assert len(c.browser.executed) <= 1
        finally:
            c.close()


def test_stale_action_is_repredicted_not_replayed():
    b, e = Browser(), Engine([decision(WIKI.url), GoalDecision("BLOCKED")])
    b.stale_once = True
    c = GoalController(b, e, announce=lambda _: None)
    try:
        c.submit(event())
        c.wait_idle()
        assert b.executed == []
        assert len(e.seen) == 2
    finally:
        c.close()
