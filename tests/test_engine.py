from laya_voice_browser.laya import LayaEngine, _label_answer_to_ids, _rank_elements, _target_options
from laya_voice_browser.spans import deterministic_intent, spoken_scroll_amount, spoken_tab_direction
from laya_voice_browser.types import Element, Snapshot


def link(id_, text, href="", role="link", in_main=False):
    return Element(id_, role, text, "a", href=href, in_main=in_main)


PAGE = Snapshot(
    "https://duckduckgo.com/?q=alan+turing",
    "alan turing at DuckDuckGo",
    "Results",
    (
        Element("e02", "combobox", "alan turing", "input"),
        link("e06", "Images", "https://duckduckgo.com/?ia=images"),
        link("e18", "More Images", "https://duckduckgo.com/?q=more"),
        link("e23", "Wikipedia", "https://en.wikipedia.org/wiki/Alan_Turing"),
        link("e25", "Wikipedia", "https://en.wikipedia.org/wiki/Alan_Turing"),
        link("e29", "Search domain en.wikipedia.org", "https://duckduckgo.com/?site=wikipedia"),
        link("e30", "turingarchive.org", "http://www.turingarchive.org/"),
    ),
    "fingerprint",
)


class RecordingEngine(LayaEngine):
    """Records which questions each stage asks, answering with canned values."""

    def __init__(self, canned=None):
        super().__init__("test")
        self.asked = []
        self.canned = canned or {}

    def warm(self):
        pass

    def _run(self, state, questions, answers, stages):
        self.asked.append(sorted(questions))
        answers.update({qid: self.canned[qid] for qid in questions if qid in self.canned})
        stages.append({"questions": list(questions), "ms": 1.0})


def test_exact_short_label_beats_longer_label():
    _, _, clear = _rank_elements("click the images tab", PAGE.elements)
    assert clear == "e06"


def test_same_destination_duplicates_are_not_ambiguous():
    _, _, clear = _rank_elements("open the wikipedia result", PAGE.elements)
    assert clear in {"e23", "e25"}


def test_word_inside_joined_label_matches():
    _, _, clear = _rank_elements("open the turing archive", PAGE.elements)
    assert clear == "e30"


def test_typing_only_considers_fillable_elements():
    ranked, _, clear = _rank_elements("type enigma into the search box", PAGE.elements, fillable=True)
    assert [item.id for item in ranked] == ["e02"]
    assert clear == "e02"


def test_open_names_site_or_page_element():
    assert deterministic_intent("open wikipedia") == "navigate_url"
    assert deterministic_intent("open the talk page", element_match=True) == "click_element"
    assert deterministic_intent("open the talk page") is None
    assert deterministic_intent("open the wikipedia result", element_match=True) == "click_element"
    assert deterministic_intent("open a new tab") == "open_new_tab"


def test_spoken_scroll_and_tab_rules():
    assert spoken_scroll_amount("scroll down a little", "down") == "little"
    assert spoken_scroll_amount("scroll to the bottom", "down") == "end"
    assert spoken_scroll_amount("scroll back to the top", "up") == "top"
    assert spoken_scroll_amount("scroll down", "down") is None
    assert spoken_tab_direction("go to the previous tab") == "previous"
    assert spoken_tab_direction("switch tabs") == "next"


def test_label_keyed_target_answer_maps_back_to_ids():
    options = _target_options([PAGE.elements[3], PAGE.elements[4]], "duckduckgo.com")
    assert list(options.values()) == ["e23", "e25"]
    assert len(set(options)) == 2
    label = next(iter(options))
    answer = _label_answer_to_ids({"choice": label, "probabilities": {label: 0.7, "none": 0.3}}, options)
    assert answer["choice"] == "e23"
    assert answer["probabilities"] == {"e23": 0.7, "none": 0.3}


def test_explicit_final_navigation_asks_no_questions():
    engine = RecordingEngine()
    decision = engine.decide("go to wikipedia", PAGE, final=True)
    assert engine.asked == []
    assert decision.latency_ms == 0


def test_clear_lexical_click_skips_target_question():
    engine = RecordingEngine({"destructive": {"type": "noul", "noul": 0.05}})
    decision = engine.decide("click the images tab", PAGE, final=True)
    assert engine.asked == [["destructive"]]
    assert decision.lexical_target == "e06"


def test_unclear_command_asks_gate_then_only_needed_details():
    canned = {
        "is_command": {"type": "noul", "noul": 0.9},
        "intent": {"type": "choice", "choice": "search_web", "confidence": 0.9},
        "text_span": {"type": "choice", "choice": "enigma", "confidence": 0.9},
    }
    engine = RecordingEngine(canned)
    engine.decide("I want to learn about enigma", PAGE, final=True)
    assert engine.asked == [["intent", "is_command"], ["text_span"]]


def test_state_puts_elements_before_page_text():
    engine = RecordingEngine()
    state, *_ = engine._state("click images", PAGE, [])
    assert list(state) == ["transcript", "safari", "interactive_elements", "visible_page_text"]
    assert state["interactive_elements"][0].startswith("e06 link")


def test_exact_natural_site_term_skips_the_model():
    engine = RecordingEngine()
    page = Snapshot("https://www.youtube.com/watch?v=x", "Video", "", (), "youtube")
    decision = engine.decide("please make the video bigger", page, final=True)
    assert engine.asked == []
    assert decision.site == {"id": "theater", "text": "", "source": "rule"}


def test_unrelated_speech_does_not_ask_the_site_control_question():
    canned = {
        "is_command": {"type": "noul", "noul": 0.1},
        "intent": {"type": "choice", "choice": "none", "confidence": 0.9},
    }
    engine = RecordingEngine(canned)
    page = Snapshot("https://www.youtube.com/watch?v=x", "Video", "", (), "youtube")
    engine.decide("that was interesting", page, final=True)
    assert engine.asked == [["intent", "is_command"]]


def test_clear_natural_site_request_skips_the_model():
    engine = RecordingEngine()
    page = Snapshot("https://www.youtube.com/watch?v=x", "Video", "", (), "youtube")
    decision = engine.decide("can you expand the player a bit", page, final=True)
    assert engine.asked == []
    assert decision.site == {"id": "theater", "text": "", "source": "lexical"}
