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


def test_plain_payloads_are_taken_by_rule_and_ambiguous_ones_left_to_the_model():
    from laya_voice_browser.spans import explicit_payload

    assert explicit_payload("search for enigma machine") == "enigma machine"
    assert explicit_payload("can you search for rock and roll documentaries") == "rock and roll documentaries"
    assert explicit_payload("search youtube for lofi hip hop") == "lofi hip hop"
    assert explicit_payload("look up alan turing") == "alan turing"
    assert explicit_payload('type "hello world"') == "hello world"
    assert explicit_payload("type hello world into the search box") is None
    assert explicit_payload("I want to learn about enigma") is None
    # A trailing site name says where to search. Leaving this to the model produced the whole
    # phrase as the query, so YouTube was searched for "cats on YouTube".
    assert explicit_payload("search for cats on youtube") == "cats"
    assert explicit_payload("search raspberry pie on github") == "raspberry pie"
    assert explicit_payload("search for the amazon river") == "the amazon river"


def test_github_misheard_as_get_up_is_repaired_where_a_site_belongs():
    # Apple Speech produced all of these; it even revised a correct "GitHub" partial into "get up".
    from laya_voice_browser.spans import mentioned_site, repair_speech

    for phrase in [
        "Search raspberry pie on get up",
        "Can you search get up for ESP 32 projects",
        "Search ESPN 32 projects on get up",
        "On get up can you search for raspberry pie",
        "open get up",
        "go to get up dot com",
        "visit get up.com",
    ]:
        assert mentioned_site(repair_speech(phrase)) == "github", phrase


def test_getting_up_is_left_alone():
    from laya_voice_browser.spans import repair_speech

    for phrase in [
        "search for how to get up early",
        "i need to get up",
        "what time do you get up",
        "search for get up and go",
        "remind me to get up in an hour",
    ]:
        assert repair_speech(phrase) == phrase, phrase


def test_a_site_name_says_where_to_search_not_what():
    from laya_voice_browser.spans import explicit_payload, mentioned_site, strip_lead

    # Trailing scope.
    assert explicit_payload("search for cats on youtube") == "cats"
    assert mentioned_site("search for cats on youtube") == "youtube"
    # Leading scope: an opener, so the rules see the command, and the site is still found.
    assert strip_lead("On GitHub can you search for raspberry pie") == "search for raspberry pie"
    assert explicit_payload("On GitHub can you search for raspberry pie") == "raspberry pie"
    assert mentioned_site("On GitHub can you search for raspberry pie") == "github"
    # Only a trailing scope phrase is dropped; a site name inside the query stays.
    from laya_voice_browser.spans import strip_site_scope

    assert strip_site_scope("github actions tutorials") == "github actions tutorials"
    assert strip_site_scope("the amazon river") == "the amazon river"
    assert explicit_payload("search for the amazon river") == "the amazon river"
