"""Check the comparison's independent scoring, without models or live browser access."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from laya_voice_browser.types import Element, Snapshot, Tab

spec = importlib.util.spec_from_file_location(
    "compare_branches", Path(__file__).resolve().parents[1] / "scripts/compare_branches.py")
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def test_article_oracle_rejects_portrait_with_identical_label():
    _, cases = comparison.cases()
    case = next(c for c in cases if c["name"] == "real-link-5")
    assert case['steps'][0]['expected']['urls'] == ['https://en.wikipedia.org/wiki/Alison_Frantz']


def test_search_then_result_cannot_hide_command_words_in_query():
    url = comparison.search_url('youtube', 'origami crane and open the first video')
    assert comparison.wrong_action(SimpleNamespace(url=url), {'via_search': ['youtube', 'origami crane']},
                                   [{'type': 'navigate', 'url': url}], ('about:blank', 1, 't0', 0))


def test_correct_search_is_incomplete_progress_not_a_wrong_action():
    url = comparison.search_url('youtube', 'origami crane')
    expected = {'via_search': ['youtube', 'origami crane'],
                'urls': comparison.result_urls('youtube', 'origami crane')[:1]}
    assert not comparison.wrong_action(SimpleNamespace(url=url), expected,
                                       [{'type': 'navigate', 'url': url}], ('about:blank', 1, 't0', 0))


def test_first_listing_tool_always_opens_first_even_if_speaker_wanted_second():
    world = comparison.World({}, [comparison.search_url('ebay', 'camera')], Snapshot, Element, Tab)
    world.execute({'type': 'site', 'id': 'first_result'})
    assert world.url == comparison.result_urls('ebay', 'camera')[0]
    assert not world.unsupported


def test_no_action_safety_check_rejects_any_action():
    before = ('about:blank', 1, 't0', 0)
    assert not comparison.check(None, before, {'none': True}, [{'type': 'new_tab'}])
    assert comparison.check(None, before, {'none': True}, [])
