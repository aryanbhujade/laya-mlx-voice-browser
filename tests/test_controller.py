import threading
import time

from laya_voice_browser.controller import PendingAction, StreamingController
from laya_voice_browser.safari import StalePage
from laya_voice_browser.types import ModelDecision, Snapshot, TranscriptEvent


class FakeBrowser:
    def __init__(self):
        self.fingerprint = "page-a"
        self.executions = []

    def snapshot(self):
        return Snapshot("https://example.com", "Example", "Example", (), self.fingerprint)

    def execute(self, action, expected_fingerprint=None):
        if expected_fingerprint != self.fingerprint:
            raise StalePage("changed")
        self.executions.append((action, expected_fingerprint, threading.get_ident()))
        return {"after_url": "https://example.com", "ok": True}


class BlockingBrowser(FakeBrowser):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def execute(self, action, expected_fingerprint=None):
        self.started.set()
        self.release.wait(2)
        return super().execute(action, expected_fingerprint)


def answers(intent="go_back"):
    return {
        "intent": {
            "type": "choice",
            "choice": intent,
            "confidence": 0.9,
            "probabilities": {intent: 0.95, "none": 0.05},
        },
        "complete": {"type": "noul", "noul": 0.9, "confidence": 0.9},
        "is_command": {"type": "noul", "noul": 0.9, "confidence": 0.9},
        "destructive": {"type": "noul", "noul": 0.01, "confidence": 0.99},
        "site": {
            "type": "choice",
            "choice": "none",
            "confidence": 0.9,
            "probabilities": {"none": 0.9, "google": 0.1},
        },
        "scroll_amount": {"type": "score", "score": 1},
        "tab_direction": {
            "type": "choice",
            "choice": "none",
            "confidence": 0.9,
            "probabilities": {"none": 0.9, "next": 0.1},
        },
    }


class FakeEngine:
    def __init__(self, block_first=False):
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.block_first = block_first

    def decide(self, transcript, snapshot, recent_actions=None, **kwargs):
        self.calls.append(transcript)
        if self.block_first and len(self.calls) == 1:
            self.started.set()
            self.release.wait(2)
        return ModelDecision(answers(), {"text": [], "url": []}, 5.0, "fake", {"transcript": transcript})


def event(text, utterance="u"):
    return TranscriptEvent(text, True, utterance, time.time())


def test_confirm_rechecks_original_page_fingerprint():
    browser = FakeBrowser()
    controller = StreamingController(browser, FakeEngine(), announce=lambda _: None)
    controller._pending = PendingAction(
        {"type": "click", "target_id": "e01"},
        "page-a",
        time.time(),
        time.time() + 10,
    )
    browser.fingerprint = "page-b"
    controller.submit(event("confirm"))
    controller.wait_idle()
    controller.close()
    assert browser.executions == []


def test_expired_confirmation_never_executes():
    browser = FakeBrowser()
    controller = StreamingController(browser, FakeEngine(), announce=lambda _: None)
    controller._pending = PendingAction({"type": "click", "target_id": "e01"}, "page-a", 0, 1)
    controller.submit(event("confirm"))
    controller.wait_idle()
    controller.close()
    assert browser.executions == []


def test_final_update_queues_behind_inference_instead_of_being_lost():
    browser = FakeBrowser()
    engine = FakeEngine(block_first=True)
    controller = StreamingController(browser, engine, announce=lambda _: None)
    controller.submit(event("go back", "u1"))
    assert engine.started.wait(1)
    controller.submit(event("reload", "u2"))
    engine.release.set()
    controller.wait_idle()
    controller.close()
    assert engine.calls == ["go back", "reload"]
    assert len(browser.executions) == 1


def test_consumed_utterances_are_bounded():
    browser = FakeBrowser()
    controller = StreamingController(browser, FakeEngine(), announce=lambda _: None)
    for index in range(40):
        controller._consumed[str(index)] = "go back"
        controller._consumed.move_to_end(str(index))
        while len(controller._consumed) > 32:
            controller._consumed.popitem(last=False)
    controller.close()
    assert len(controller._consumed) == 32


def test_final_duplicate_queued_during_execution_is_not_run_twice():
    browser = BlockingBrowser()
    engine = FakeEngine()
    controller = StreamingController(browser, engine, announce=lambda _: None)
    controller.submit(event("go back", "same"))
    assert browser.started.wait(1)
    controller.submit(event("go back", "same"))
    browser.release.set()
    controller.wait_idle()
    controller.close()
    assert engine.calls == ["go back"]
    assert len(browser.executions) == 1


def test_final_command_chain_executes_each_clause_in_order():
    browser = FakeBrowser()
    engine = FakeEngine()
    controller = StreamingController(browser, engine, announce=lambda _: None)
    controller.submit(event("go back and reload", "chain"))
    controller.wait_idle()
    controller.close()
    assert engine.calls == ["go back", "reload"]
    assert len(browser.executions) == 2


def test_conversational_new_tab_request_reaches_controller_as_two_commands():
    browser = FakeBrowser()
    engine = FakeEngine()
    controller = StreamingController(browser, engine, announce=lambda _: None)
    controller.submit(event("and in a new tab can you search for information about xyz", "plan"))
    controller.wait_idle()
    controller.close()
    assert engine.calls == ["open a new tab", "search for information about xyz"]


class ChoiceEngine(FakeEngine):
    def decide(self, transcript, snapshot, recent_actions=None, **kwargs):
        self.calls.append(transcript)
        base = answers("click_element")
        base["target"] = {
            "type": "choice",
            "choice": "e01",
            "confidence": 0.05,
            "probabilities": {"e01": 0.4, "e02": 0.35, "none": 0.25},
        }
        return ModelDecision(
            base,
            {"text": [], "url": []},
            5.0,
            "fake",
            {"transcript": transcript},
            target_candidates=["e01", "e02"],
        )


class ChoiceBrowser(FakeBrowser):
    def __init__(self):
        super().__init__()
        self.badges = []

    def snapshot(self):
        from laya_voice_browser.types import Element

        elements = (
            Element("e01", "link", "Alison Frantz", "a", href="https://example.com/file"),
            Element("e02", "link", "Alison Frantz", "a", href="https://example.com/article"),
        )
        return Snapshot("https://example.com", "Example", "Example", elements, self.fingerprint)

    def show_candidates(self, candidates):
        self.badges = candidates

    def clear_candidates(self):
        self.badges = []


def test_ambiguous_target_offers_numbers_and_spoken_number_clicks():
    browser = ChoiceBrowser()
    engine = ChoiceEngine()
    controller = StreamingController(browser, engine, announce=lambda _: None)
    controller.submit(event("click alison frantz", "u1"))
    controller.wait_idle()
    assert browser.badges == [(1, "e01"), (2, "e02")]
    controller.submit(event("the second one", "u2"))
    controller.wait_idle()
    controller.close()
    assert engine.calls == ["click alison frantz"]
    assert browser.executions[0][0] == {"type": "click", "target_id": "e02"}
    assert browser.badges == []


class LostBrowser(FakeBrowser):
    def snapshot(self):
        from laya_voice_browser.browser import BrowserSessionLost

        raise BrowserSessionLost("gone")


def test_lost_session_is_reported_once_and_stops_processing():
    messages = []
    controller = StreamingController(LostBrowser(), FakeEngine(), announce=messages.append)
    controller.submit(event("go back", "u1"))
    controller.wait_idle()
    controller.submit(event("reload", "u2"))
    controller.wait_idle()
    controller.close()
    assert controller.session_lost
    assert sum("session ended" in message for message in messages) == 1


def test_controller_reports_progress_to_the_island():
    statuses = []
    controller = StreamingController(
        FakeBrowser(), FakeEngine(), announce=lambda _: None, status=lambda state, **kw: statuses.append(
            (state, kw.get("kind"))
        )
    )
    controller.submit(event("go back", "u1"))
    controller.wait_idle()
    controller.close()
    assert statuses == [("thinking", None), ("acting", "back"), ("done", None)]


def test_mid_sentence_evaluations_tell_the_app_how_finished_the_phrase_sounds():
    from laya_voice_browser.controller import endpoint_hint
    from laya_voice_browser.types import PolicyResult

    def reasons(*names_passed):
        return [{"name": name, "passed": passed} for name, passed in names_passed]

    assert endpoint_hint(PolicyResult("act", "go back")) == "complete"
    dictating = PolicyResult("wait", "", reasons=reasons(("intent", True), ("payload_final", False)))
    assert endpoint_hint(dictating) == "likely_complete"
    assert endpoint_hint(PolicyResult("wait", "", reasons=reasons(("intent", False)))) == "incomplete"
    assert endpoint_hint(PolicyResult("ignore", "")) is None
