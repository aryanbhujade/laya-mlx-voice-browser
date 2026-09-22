import json
from pathlib import Path

import pytest

from laya_voice_browser.spans import (
    command_plan,
    deterministic_intent,
    explicit_browser_command,
    explicit_payload,
    mentioned_site,
    remainder_after,
    spoken_number,
)

ROWS = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[1] / "datasets" / "chains.jsonl").read_text().splitlines()
    if line.strip()
]


@pytest.mark.parametrize("row", ROWS, ids=[row["transcript"][:40] for row in ROWS])
def test_command_plan_matches_labelled_chain(row):
    assert command_plan(row["transcript"]) == row["plan"]


def test_polite_openers_reach_the_grammar_mid_speech():
    assert deterministic_intent("can you open wikipedia") == "navigate_url"
    assert deterministic_intent("could you please go back") == "go_back"
    assert explicit_browser_command("can you scroll down")
    assert deterministic_intent("can you") is None


def test_get_up_is_github_only_after_a_navigation_verb():
    assert mentioned_site("can you open get up") == "github"
    assert mentioned_site("search for how to get up early") is None


def test_amazon_is_a_named_site_for_navigation():
    assert mentioned_site("open Amazon") == "amazon"
    assert deterministic_intent("open Amazon") == "navigate_url"
    assert command_plan("open Amazon") == ["open Amazon"]


def test_amazon_names_the_shop_only_after_a_navigation_or_shopping_phrase():
    assert mentioned_site("search amazon for wireless headphones") == "amazon"
    assert mentioned_site("buy batteries on amazon") == "amazon"
    assert mentioned_site("order a keyboard from amazon") == "amazon"


def test_the_amazon_the_place_is_not_the_shop():
    assert mentioned_site("search for the amazon river") is None
    assert mentioned_site("search for amazon rainforest documentaries") is None
    assert mentioned_site("go to the amazon") is None
    assert explicit_payload("search for the amazon river") == "the amazon river"


def test_amazon_splits_a_purpose_chain_like_the_other_sites():
    assert command_plan("go to Amazon to search for headphones") == [
        "open amazon",
        "search amazon for headphones",
    ]


def test_remainder_ignores_recognizer_revisions():
    assert remainder_after("Go to YouTube. And search for cats", "go to you tube") == "And search for cats"
    assert remainder_after("go to youtube", "go to youtube") == ""
    assert remainder_after("open github", "go to") is None


def test_spoken_numbers_pick_only_bare_choices():
    assert spoken_number("two", 3) == 2
    assert spoken_number("the second one", 3) == 2
    assert spoken_number("number 3", 3) == 3
    assert spoken_number("to", 3) == 2
    assert spoken_number("five", 3) is None
    assert spoken_number("go to wikipedia", 3) is None


def test_direct_speaking_style_leaves_polite_requests_to_the_model(monkeypatch, tmp_path):
    import json

    config = tmp_path / "direct.json"
    config.write_text(json.dumps({"speaking_style": "direct"}))
    monkeypatch.setenv("LAYA_CONFIG", str(config))
    assert deterministic_intent("could you go back to what you said") is None
    assert deterministic_intent("go back") == "go_back"
    assert command_plan("and then can you search for cats") == ["can you search for cats"]
