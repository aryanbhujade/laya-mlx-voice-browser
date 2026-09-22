from laya_voice_browser.browser import pick_tab
from laya_voice_browser.policy import _tab_action, evaluate
from laya_voice_browser.spans import command_plan, deterministic_intent, tab_command
from laya_voice_browser.types import ModelDecision, Snapshot, Tab

TABS = (
    Tab("t1", "Wikipedia, the free encyclopedia", "https://en.wikipedia.org/wiki/Main_Page"),
    Tab("t2", "lofi hip hop radio - YouTube", "https://www.youtube.com/watch?v=x", active=True),
    Tab("t3", "Alan Turing - Wikipedia", "https://en.wikipedia.org/wiki/Alan_Turing"),
)
PAGE = Snapshot("https://www.youtube.com/watch?v=x", "YouTube", "", (), "f", tabs=TABS)


def action_for(text):
    return _tab_action(tab_command(text), PAGE)[0]


def test_tabs_are_found_by_name_position_and_direction():
    assert action_for("close the youtube tab") == {"type": "close_tab", "tab_id": "t2"}
    assert action_for("switch to the tab with alan turing") == {"type": "switch_tab", "tab_id": "t3"}
    assert action_for("go to tab 1") == {"type": "switch_tab", "tab_id": "t1"}
    assert action_for("the last tab") == {"type": "switch_tab", "direction": "last"}
    assert action_for("close the previous tab") == {"type": "close_tab", "direction": "previous"}
    assert action_for("close this tab") == {"type": "close_tab"}
    assert action_for("close the other tabs") == {"type": "close_other_tabs"}


def test_ambiguous_or_missing_tabs_are_not_guessed():
    action, summary = _tab_action(tab_command("switch to the wikipedia tab"), PAGE)
    assert action is None and "several tabs match" in summary
    action, summary = _tab_action(tab_command("close the github tab"), PAGE)
    assert action is None and "no open tab" in summary
    assert _tab_action(tab_command("go to tab 9"), PAGE)[0] is None


def test_going_to_a_tab_is_not_opening_the_site():
    assert deterministic_intent("go to the youtube tab") == "switch_tab"
    assert deterministic_intent("go to youtube") == "navigate_url"
    assert command_plan("open youtube in a new tab") == ["open a new tab", "open youtube"]


def test_pick_tab():
    ids = ["a", "b", "c"]
    assert pick_tab(ids, "b", {"tab_id": "c"}) == "c"
    assert pick_tab(ids, "b", {"direction": "previous"}) == "a"
    assert pick_tab(ids, "c", {"direction": "next"}) == "a"
    assert pick_tab(ids, "b", {"direction": "last"}) == "c"
    assert pick_tab(ids, "b", {}) == "b"


def test_closing_the_other_tabs_needs_confirmation():
    from test_policy import base_answers

    decision = ModelDecision(
        base_answers("close_tab"), {"text": [], "url": []}, 1.0, "t", {"transcript": "close the other tabs"}
    )
    assert evaluate(decision, PAGE, final=True, silent_seconds=0.0).verdict == "confirm"
