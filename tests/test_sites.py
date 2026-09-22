import json
from pathlib import Path

from laya_voice_browser import sites
from laya_voice_browser.spans import universal_command

SITE_DIR = Path(sites.__file__).parent
PRIMARY_OPERATIONS = {"key", "click", "click_css", "fill", "open", "scroll_to", "media"}


def test_all_site_pack_files_load_and_have_valid_actions():
    loaded = sites.packs()
    assert {pack.name for pack in loaded} >= {
        "Amazon",
        "eBay",
        "Etsy",
        "GitHub",
        "Gmail",
        "Google Search",
        "Netflix",
        "Spotify",
        "Wikipedia",
        "YouTube",
    }
    for path in SITE_DIR.glob("*.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["name"]
        assert raw["hosts"]
        ids = [action["id"] for action in raw["actions"]]
        assert len(ids) == len(set(ids)), path.name
        for action in raw["actions"]:
            assert action["description"]
            assert len(PRIMARY_OPERATIONS & action["do"].keys()) == 1, (path.name, action["id"])


def test_pack_lookup_accepts_www_and_subdomains():
    assert sites.pack_for("https://www.youtube.com/watch?v=abc").name == "YouTube"
    assert sites.pack_for("https://smile.amazon.co.uk/example").name == "Amazon"
    assert sites.pack_for("https://mail.google.com/mail/u/0/#inbox").name == "Gmail"
    assert sites.pack_for("https://example.com/") is None


def test_every_natural_term_resolves_to_its_own_action():
    for pack in sites.packs():
        url = f"https://www.{pack.hosts[0]}/"
        for action in pack.actions:
            for term in action.terms:
                match = sites.match_phrase(term, url)
                assert match is not None, (pack.name, action.id, term)
                assert match.action.id == action.id, (pack.name, action.id, term)


def test_user_facing_loose_phrases_resolve_without_the_model():
    theater = sites.match_phrase("please make the video bigger", "https://www.youtube.com/watch?v=x")
    archive = sites.match_phrase(
        "could you get rid of this email but keep it", "https://mail.google.com/mail/u/0/#inbox"
    )
    assert theater and theater.action.id == "theater"
    assert archive and archive.action.id == "archive"


def test_unrelated_speech_does_not_offer_random_site_controls():
    pack = sites.pack_for("https://www.youtube.com/watch?v=x")
    question, candidates = sites.site_question(pack, "that was interesting")
    assert candidates == []
    assert question["criteria"] == {"none": "none of these"}


def test_site_question_ranks_the_relevant_control_first():
    pack = sites.pack_for("https://www.youtube.com/watch?v=x")
    question, candidates = sites.site_question(pack, "could you expand the video player")
    assert candidates[0].id == "theater"
    assert list(question["criteria"])[0] == "theater"
    assert len(question["criteria"]) <= 10


def test_clear_natural_request_gets_a_lexical_match():
    match = sites.lexical_match(
        "can you expand the player a bit", "https://www.youtube.com/watch?v=x"
    )
    assert match and match.action.id == "theater"


def test_narrative_speech_is_not_a_lexical_command():
    assert (
        sites.lexical_match(
            "I archived that message yesterday", "https://mail.google.com/mail/u/0/#inbox"
        )
        is None
    )


def test_open_templates_preserve_site_domain_and_encode_text():
    assert sites.resolve_open(
        "https://{host}/gp/cart/view.html", "https://www.amazon.co.uk/product"
    ) == "https://amazon.co.uk/gp/cart/view.html"
    assert sites.resolve_open(
        "https://github.com/{1}/{2}/issues", "https://github.com/openai/codex/tree/main"
    ) == "https://github.com/openai/codex/issues"
    assert sites.resolve_open(
        "https://mail.google.com/mail/u/0/#search/{text}",
        "https://mail.google.com/mail/u/0/#inbox",
        "bank statements 2026",
    ).endswith("#search/bank+statements+2026")


def test_account_changing_controls_are_guarded():
    guarded = {
        "add_to_cart",
        "buy_now",
        "delete",
        "dislike",
        "favorite",
        "like",
        "star",
        "subscribe",
        "watch_item",
    }
    for pack in sites.packs():
        for action in pack.actions:
            if action.id in guarded:
                assert action.confirm or action.side_effect, (pack.name, action.id)


def test_model_chosen_controls_need_request_shaped_speech():
    """Measured: Laya confidently matches controls in ordinary talk ("my inbox is a disaster" →
    inbox, p=0.90), and the is_command head does not catch it. Requiring request shape as well does."""
    from laya_voice_browser.sites import looks_like_request

    assert looks_like_request("respond to everyone")
    assert looks_like_request("show me more results please")
    assert looks_like_request("could you open the issues")
    assert not looks_like_request("my inbox is a complete disaster honestly")
    assert not looks_like_request("the cart was full of stuff I did not need")
    assert not looks_like_request("he never replied to me about the invoice")


def test_a_confident_model_control_is_ignored_in_ordinary_talk():
    from laya_voice_browser.policy import evaluate
    from laya_voice_browser.types import ModelDecision, Snapshot

    page = Snapshot("https://mail.google.com/mail/u/0/#inbox", "Gmail", "", (), "f")
    answers = {"is_command": {"type": "noul", "noul": 0.9, "confidence": 0.9}}
    talking = ModelDecision(
        answers, {"text": [], "url": []}, 1.0, "t",
        {"transcript": "my inbox is a complete disaster honestly"},
        site={"id": "inbox", "text": "", "source": "model", "probability": 0.9},
    )
    assert evaluate(talking, page, final=True, silent_seconds=1.0).verdict == "ignore"
    asking = ModelDecision(
        answers, {"text": [], "url": []}, 1.0, "t", {"transcript": "show me my inbox"},
        site={"id": "inbox", "text": "", "source": "model", "probability": 0.9},
    )
    assert evaluate(asking, page, final=True, silent_seconds=1.0).verdict == "act"


def test_everyday_words_alone_do_not_match_a_control():
    """"open the alison frantz article" matched Wikipedia's "open a random article" on "open" and
    "article" alone, hijacking a command that named a link on the page."""
    from laya_voice_browser.sites import lexical_match

    wikipedia = "https://en.wikipedia.org/wiki/Main_Page"
    assert lexical_match("open the alison frantz article", wikipedia) is None
    assert lexical_match("show me any article", wikipedia).action.id == "random"


def test_a_named_page_element_beats_a_general_site_control():
    from laya_voice_browser.laya import LayaEngine
    from laya_voice_browser.types import Element, Snapshot

    class Offline(LayaEngine):
        def __init__(self):
            super().__init__("test")
            self.asked: list[list[str]] = []

        def warm(self):
            pass

        def _run(self, state, questions, answers, stages):
            self.asked.append(sorted(questions))
            stages.append({"questions": list(questions), "ms": 0.0})

    button = Element("e09", "button", "Toggle the table of contents", "button", in_main=True)
    page = Snapshot("https://en.wikipedia.org/wiki/Alan_Turing", "Alan Turing", "", (button,), "f")
    engine = Offline()
    decision = engine.decide("toggle the table of contents", page, final=True)
    assert decision.site is None, "the labelled button should win over Wikipedia's contents control"
    assert not any("site_action" in asked for asked in engine.asked)


def test_a_site_pack_may_not_redefine_a_universal_browser_command():
    # "go back" is browser history everywhere, not Google's previous page of results.
    assert universal_command("go back")
    assert universal_command("scroll down")
    assert universal_command("forward")
    for phrase, url in [
        ("go back", "https://www.google.com/search?q=x"),
        ("go back", "https://open.spotify.com/"),
        ("scroll down", "https://www.youtube.com/watch?v=abc"),
    ]:
        assert universal_command(phrase), phrase
        assert sites.lexical_match(phrase, url) is not None  # the pack would have claimed it


def test_a_site_control_that_only_starts_with_a_universal_word_still_matches():
    # "forward this email" is Gmail's control; only the bare command belongs to the browser.
    assert not universal_command("forward this email")
    assert not universal_command("scroll down to the comments")
    match = sites.match_phrase("forward this email", "https://mail.google.com/mail/u/0/#inbox")
    assert match is not None and match.action.id == "forward"


def test_back_alone_cannot_identify_a_control():
    # "back" introduces many commands, so it may not pick one while other words go unmatched.
    assert sites.lexical_match(
        "i need to go back to the office later", "https://www.google.com/search?q=x"
    ) is None
    assert sites.lexical_match(
        "i need to go back to the office later", "https://open.spotify.com/"
    ) is None


def test_everyday_words_still_match_when_they_are_the_whole_request():
    match = sites.lexical_match(
        "take me back to the start of this article", "https://en.wikipedia.org/wiki/Turing"
    )
    assert match is not None and match.action.id == "contents"


def test_archiving_an_email_is_gated_when_it_was_inferred():
    action = sites.action_by_id("https://mail.google.com/mail/u/0/#inbox", "archive")
    assert action is not None and action.side_effect
