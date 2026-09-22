from laya_voice_browser.spans import (
    as_https,
    command_chain,
    command_plan,
    deterministic_intent,
    explicit_browser_command,
    mentioned_site,
    normalize_spoken_url,
    site_for_url,
    text_candidates,
    url_candidates,
)


def test_extracts_verbatim_search_payload():
    candidates = text_candidates("search YouTube for lofi hip hop")
    assert candidates[0] == "lofi hip hop"


def test_normalizes_spoken_domain():
    assert normalize_spoken_url("go to example dot com") == "go to example.com"
    assert url_candidates("go to example dot com") == ["example.com"]
    assert as_https("example.com") == "https://example.com"


def test_explicit_known_site_is_deterministic():
    assert mentioned_site("please go to Wikipedia") == "wikipedia"
    assert mentioned_site("search YouTube for jazz") == "youtube"


def test_browser_imperative_is_deterministic_but_side_talk_is_not():
    assert explicit_browser_command("please open wikipedia")
    assert explicit_browser_command("scroll down a page")
    assert not explicit_browser_command("we should get lunch after this")
    assert deterministic_intent("scroll down a page") == "scroll_down"
    assert deterministic_intent("we should get lunch after this") is None


def test_splits_explicit_command_chain_but_not_query_conjunctions():
    assert command_chain(
        "go to youtube and search for documentaries about bank robberies"
    ) == ["go to youtube", "search for documentaries about bank robberies"]
    assert command_chain("search for rock and roll documentaries") == [
        "search for rock and roll documentaries"
    ]


def test_recognizes_search_scope_from_current_url():
    assert site_for_url("https://www.youtube.com/watch?v=abc") == "youtube"
    assert site_for_url("https://en.wikipedia.org/wiki/Alan_Turing") == "wikipedia"
    assert site_for_url("https://example.com") is None


def test_plans_conversational_new_tab_search():
    assert command_plan("and in a new tab can you search for information about xyz") == [
        "open a new tab",
        "search for information about xyz",
    ]


def test_plans_and_then_polite_followup():
    assert command_plan("and then can you search for skateboarding tutorials") == [
        "search for skateboarding tutorials"
    ]


def test_plans_site_open_with_implied_search():
    assert command_plan("and can you open github to see repos for ESP32") == [
        "open github",
        "search github for ESP32",
    ]


def test_normalizes_common_github_recognition_error():
    assert mentioned_site("can you open get up") == "github"
    assert url_candidates("can you open get up.com") == ["github.com"]
