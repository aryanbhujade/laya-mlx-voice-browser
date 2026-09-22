from laya_voice_browser.policy import evaluate
from laya_voice_browser.types import Element, ModelDecision, Snapshot


def snapshot(*elements):
    return Snapshot("https://example.com", "Example", "Example page", tuple(elements), "fingerprint")


def choice(selected, probabilities, confidence=0.9):
    return {"type": "choice", "choice": selected, "probabilities": probabilities, "confidence": confidence}


def base_answers(intent):
    return {
        "intent": choice(intent, {intent: 0.95, "none": 0.05}),
        "site": choice("none", {"none": 0.9, "google": 0.1}),
        "complete": {"type": "noul", "noul": 0.97, "confidence": 0.97},
        "is_command": {"type": "noul", "noul": 0.98, "confidence": 0.98},
        "destructive": {"type": "noul", "noul": 0.02, "confidence": 0.98},
        "scroll_amount": {"type": "score", "score": 1.0},
        "tab_direction": choice("none", {"none": 0.8, "next": 0.2}),
    }


def test_safe_closed_action_can_run_on_partial_speech():
    answers = base_answers("go_back")
    decision = ModelDecision(answers, {"text": [], "url": []}, 8.0, "test", {"transcript": "take me back"})
    result = evaluate(decision, snapshot(), final=False, silent_seconds=0.1)
    assert result.verdict == "act"
    assert result.action == {"type": "back"}


def test_explicit_site_name_overrides_weak_model_site_head():
    answers = base_answers("navigate_url")
    answers["site"] = choice("google", {"google": 0.56, "wikipedia": 0.28, "none": 0.16})
    decision = ModelDecision(
        answers,
        {"text": [], "url": []},
        8.0,
        "test",
        {"transcript": "go to wikipedia"},
    )
    result = evaluate(decision, snapshot(), final=False, silent_seconds=0.1)
    assert result.verdict == "act"
    assert result.action == {"type": "navigate", "url": "https://en.wikipedia.org/wiki/Main_Page"}


def test_payload_waits_for_final_transcript():
    answers = base_answers("search_web")
    answers["text_span"] = choice("alan turing", {"alan turing": 0.9, "none": 0.1})
    decision = ModelDecision(answers, {"text": ["alan turing"], "url": []}, 8.0, "test", {})
    result = evaluate(decision, snapshot(), final=False, silent_seconds=0.1)
    assert result.verdict == "wait"


def test_search_without_named_site_uses_current_supported_site():
    answers = base_answers("search_web")
    answers["text_span"] = choice(
        "bank robbery documentaries", {"bank robbery documentaries": 0.9, "none": 0.1}
    )
    decision = ModelDecision(
        answers,
        {"text": ["bank robbery documentaries"], "url": []},
        8.0,
        "test",
        {"transcript": "search for bank robbery documentaries"},
    )
    page = Snapshot("https://www.youtube.com/", "YouTube", "", (), "youtube")
    result = evaluate(decision, page, final=True, silent_seconds=0.0)
    assert result.action == {
        "type": "navigate",
        "url": "https://www.youtube.com/results?search_query=bank+robbery+documentaries",
    }


def test_unscoped_search_uses_duckduckgo_in_safari_and_google_elsewhere(monkeypatch, tmp_path):
    import json

    answers = base_answers("search_web")
    state = {"transcript": "search for xyz"}
    decision = ModelDecision(answers, {"text": ["xyz"], "url": []}, 8.0, "test", state)
    assert evaluate(decision, snapshot(), final=True, silent_seconds=0.0).action["url"] == (
        "https://duckduckgo.com/?q=xyz"
    )
    config = tmp_path / "chrome.json"
    config.write_text(json.dumps({"browser": "chrome"}))
    monkeypatch.setenv("LAYA_CONFIG", str(config))
    assert evaluate(decision, snapshot(), final=True, silent_seconds=0.0).action["url"] == (
        "https://www.google.com/search?q=xyz"
    )
    config.write_text(json.dumps({"browser": "chrome", "search_engine": "brave"}))
    assert evaluate(decision, snapshot(), final=True, silent_seconds=0.0).action["url"] == (
        "https://search.brave.com/search?q=xyz"
    )


def test_destructive_element_requires_confirmation():
    answers = base_answers("click_element")
    answers["target"] = choice("e01", {"e01": 0.9, "none": 0.1})
    decision = ModelDecision(answers, {"text": [], "url": []}, 8.0, "test", {})
    page = snapshot(Element("e01", "button", "Place order", "button", destructive_hint=True))
    result = evaluate(decision, page, final=True, silent_seconds=0.0)
    assert result.verdict == "confirm"


def test_ordinary_navigation_link_ignores_noisy_destructive_score():
    answers = base_answers("click_element")
    answers["target"] = choice("e01", {"e01": 0.9, "none": 0.1})
    answers["destructive"] = {"type": "noul", "noul": 0.45, "confidence": 0.55}
    decision = ModelDecision(answers, {"text": [], "url": []}, 8.0, "test", {})
    page = snapshot(Element("e01", "link", "Documentary episode one", "a", href="https://video.test/1"))
    result = evaluate(decision, page, final=True, silent_seconds=0.0)
    assert result.verdict == "act"


def test_ambiguous_target_never_clicks():
    answers = base_answers("click_element")
    answers["target"] = choice("e01", {"e01": 0.34, "e02": 0.33, "none": 0.33}, confidence=0.01)
    decision = ModelDecision(answers, {"text": [], "url": []}, 8.0, "test", {})
    page = snapshot(Element("e01", "link", "First", "a"), Element("e02", "link", "Second", "a"))
    result = evaluate(decision, page, final=True, silent_seconds=0.0)
    assert result.verdict == "clarify"


def test_plain_return_is_not_always_treated_as_destructive():
    answers = base_answers("press_enter")
    decision = ModelDecision(answers, {"text": [], "url": []}, 8.0, "test", {"transcript": "press enter"})
    result = evaluate(decision, snapshot(), final=True, silent_seconds=0.0)
    assert result.verdict == "act"


def test_uncertain_text_head_does_not_fall_back_to_whole_transcript():
    answers = base_answers("search_web")
    answers["text_span"] = choice("none", {"none": 0.6, "i wonder about something": 0.4}, confidence=0.1)
    decision = ModelDecision(
        answers,
        {"text": ["i wonder about something"], "url": []},
        8.0,
        "test",
        {"transcript": "i wonder about something"},
    )
    result = evaluate(decision, snapshot(), final=True, silent_seconds=0.0)
    assert result.verdict == "clarify"


def test_navigation_ignores_model_destructive_score():
    answers = base_answers("navigate_url")
    answers["destructive"] = {"type": "noul", "noul": 0.67, "confidence": 0.67}
    decision = ModelDecision(answers, {"text": [], "url": []}, 8.0, "test", {"transcript": "go to wikipedia"})
    result = evaluate(decision, snapshot(), final=True, silent_seconds=0.0)
    assert result.verdict == "act"
    assert result.action == {"type": "navigate", "url": "https://en.wikipedia.org/wiki/Main_Page"}


def test_closed_set_command_acts_before_speech_ends():
    answers = base_answers("go_back")
    answers["complete"] = {"type": "noul", "noul": 0.1, "confidence": 0.9}
    decision = ModelDecision(answers, {"text": [], "url": []}, 0.0, "test", {"transcript": "go back"})
    result = evaluate(decision, snapshot(), final=False, silent_seconds=0.0)
    assert result.verdict == "act"


def test_missing_target_waits_mid_speech_and_clarifies_after():
    answers = base_answers("click_element")
    answers["target"] = choice("none", {"none": 0.9}, confidence=0.9)
    decision = ModelDecision(answers, {"text": [], "url": []}, 8.0, "test", {"transcript": "click"})
    assert evaluate(decision, snapshot(), final=False, silent_seconds=0.1).verdict == "wait"
    assert evaluate(decision, snapshot(), final=True, silent_seconds=0.0).verdict == "clarify"


def test_lexical_target_is_used_without_target_head():
    answers = base_answers("click_element")
    decision = ModelDecision(
        answers, {"text": [], "url": []}, 8.0, "test", {"transcript": "click news"}, lexical_target="e01"
    )
    result = evaluate(decision, snapshot(Element("e01", "link", "News", "a")), final=True, silent_seconds=0.0)
    assert result.action == {"type": "click", "target_id": "e01"}


def test_model_closed_set_intent_needs_a_matching_word():
    # Live trace: partial "Go to" came back as reload at 0.97 confidence.
    answers = base_answers("reload")
    answers["intent"] = choice("reload", {"reload": 0.97, "none": 0.03}, confidence=0.97)
    decision = ModelDecision(answers, {"text": [], "url": []}, 8.0, "test", {"transcript": "Go to"})
    assert evaluate(decision, snapshot(), final=False, silent_seconds=0.1).verdict == "wait"


def test_side_effect_link_still_needs_confirmation():
    answers = base_answers("click_element")
    decision = ModelDecision(
        answers, {"text": [], "url": []}, 8.0, "test", {"transcript": "click hide"}, lexical_target="e01"
    )
    page = snapshot(Element("e01", "link", "hide", "a", href="https://news.ycombinator.com/hide?id=1"))
    assert evaluate(decision, page, final=True, silent_seconds=0.0).verdict == "confirm"


def test_plain_link_does_not_need_confirmation():
    answers = base_answers("click_element")
    answers["destructive"] = {"type": "noul", "noul": 0.9, "confidence": 0.9}
    decision = ModelDecision(
        answers, {"text": [], "url": []}, 8.0, "test", {"transcript": "click turing"}, lexical_target="e01"
    )
    page = snapshot(Element("e01", "link", "Turing machine", "a", href="https://en.wikipedia.org/wiki/Turing"))
    assert evaluate(decision, page, final=True, silent_seconds=0.0).verdict == "act"


def test_inferred_site_side_effect_needs_confirmation():
    decision = ModelDecision(
        {},
        {"text": [], "url": []},
        0.0,
        "test",
        {"transcript": "give this video some love"},
        site={"id": "like", "source": "lexical", "text": ""},
    )
    page = Snapshot("https://www.youtube.com/watch?v=x", "Video", "", (), "youtube")
    result = evaluate(decision, page, final=True, silent_seconds=0.0)
    assert result.verdict == "confirm"


def _search(transcript, query, url):
    answers = base_answers("search_web")
    answers["text_span"] = choice(query, {query: 0.9, "none": 0.1})
    decision = ModelDecision(answers, {"text": [query], "url": []}, 8.0, "test", {"transcript": transcript})
    page = Snapshot(url, "Page", "", (), "fp")
    return evaluate(decision, page, final=True, silent_seconds=0.0).action["url"]


def test_plain_search_on_an_article_searches_the_web():
    url = _search("search for guitar tabs and back tracks", "guitar tabs and back tracks",
                  "https://en.wikipedia.org/wiki/Main_Page")
    assert url.startswith("https://duckduckgo.com/?q=guitar+tabs")


def test_search_here_stays_on_the_current_site():
    url = _search("search for turing here", "turing here", "https://en.wikipedia.org/wiki/Main_Page")
    assert url == "https://en.wikipedia.org/w/index.php?search=turing"


def test_search_from_site_results_refines_that_search():
    url = _search("search for laya mlx", "laya mlx", "https://github.com/search?q=laya&type=repositories")
    assert url.startswith("https://github.com/search?q=laya+mlx")
