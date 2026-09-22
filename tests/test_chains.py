import json
from pathlib import Path

import pytest

from laya_voice_browser.spans import (
    command_plan,
    deterministic_intent,
    explicit_browser_command,
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
