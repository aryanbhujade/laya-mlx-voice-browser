import threading
import time

import pytest

from laya_voice_browser.safari import SafariBrowser


class FakeSwitch:
    def __init__(self, driver):
        self.driver = driver

    def new_window(self, kind):
        self.driver.window_handles.append("second")
        self.driver.current_window_handle = "second"

    def window(self, handle):
        self.driver.current_window_handle = handle


class FakeDriver:
    def __init__(self):
        self.current_url = "https://example.com"
        self.window_handles = ["first"]
        self.current_window_handle = "first"
        self.switch_to = FakeSwitch(self)
        self.calls = []

    def get(self, url):
        self.current_url = url
        self.calls.append(("get", url))

    def execute_script(self, script, *args):
        if "const destructive" in script:
            return {"url": self.current_url, "title": "Example", "text": "Hello", "elements": []}
        if "location.href, document.readyState" in script:
            return [self.current_url, "complete"]
        if "return innerHeight" in script:
            return 800
        self.calls.append(("script", args))

    def quit(self):
        self.calls.append(("quit",))


def test_failed_session_initialization_releases_safari_pairing():
    class BadTimeout(FakeDriver):
        def set_page_load_timeout(self, seconds):
            raise RuntimeError("could not configure SafariDriver")

    driver = BadTimeout()
    with pytest.raises(RuntimeError, match="configure"):
        SafariBrowser(driver=driver)
    assert ("quit",) in driver.calls


def test_navigation_uses_safari_driver_and_records_new_state():
    driver = FakeDriver()
    browser = SafariBrowser(driver=driver)
    before = browser.snapshot()
    result = browser.execute({"type": "navigate", "url": "https://wikipedia.org"}, before.fingerprint)
    assert result["after_url"] == "https://wikipedia.org"
    assert ("get", "https://wikipedia.org") in driver.calls


def test_page_load_timeout_keeps_partially_loaded_page_and_session():
    class TimeoutException(Exception):
        pass

    class SlowPage(FakeDriver):
        def set_page_load_timeout(self, seconds):
            self.calls.append(("page_timeout", seconds))

        def get(self, url):
            super().get(url)
            if url.endswith("ebay.com/"):
                raise TimeoutException("page took too long")

    driver = SlowPage()
    browser = SafariBrowser(driver=driver)
    outcome = browser.execute({"type": "navigate", "url": "https://www.ebay.com/"})
    assert ("page_timeout", 10.0) in driver.calls
    assert outcome["after_url"] == "https://www.ebay.com/"
    assert browser.health() == "alive"


def test_unanswered_health_probe_means_busy_and_does_not_overlap_another_probe(monkeypatch):
    from laya_voice_browser import safari

    monkeypatch.setattr(safari, "_ALIVE_TIMEOUT_SECONDS", 0.01)
    release = threading.Event()

    class SlowProbe(FakeDriver):
        def execute_script(self, script, *args):
            if script == "return 1":
                assert release.wait(1)
            return super().execute_script(script, *args)

    browser = SafariBrowser(driver=SlowProbe())
    assert browser.health() == "busy"
    assert browser.health() == "busy"
    release.set()
    deadline = time.monotonic() + 1
    while browser.health() == "busy" and time.monotonic() < deadline:
        time.sleep(0.005)
    assert browser.health() == "alive"


def test_only_a_proven_lost_session_is_reported_gone():
    class NoSuchWindowException(Exception):
        pass

    class MissingWindow(FakeDriver):
        def execute_script(self, script, *args):
            if script == "return 1":
                raise NoSuchWindowException("window closed")
            return super().execute_script(script, *args)

    browser = SafariBrowser(driver=MissingWindow())
    assert browser.health() == "gone"


def test_back_survives_invalid_safaridriver_history_command_without_page_snapshot():
    class InvalidArgumentException(Exception):
        pass

    class BrokenPageDriver(FakeDriver):
        def back(self):
            raise InvalidArgumentException("An invalid command argument was specified")

        def execute_script(self, script, *args):
            if "const destructive" in script:
                raise InvalidArgumentException("Snapshot unavailable")
            if script == "history.back()":
                self.current_url = "https://example.com/previous"
                self.calls.append(("history.back",))
                return None
            return super().execute_script(script, *args)

    driver = BrokenPageDriver()
    browser = SafariBrowser(driver=driver)
    result = browser.execute({"type": "back"})
    assert result["after_url"] == "https://example.com/previous"
    assert ("history.back",) in driver.calls


class DelayedLink:
    def __init__(self, driver):
        self.driver = driver

    def click(self):
        timer = threading.Timer(0.05, setattr, args=(self.driver, "current_url", "https://example.com/new"))
        timer.daemon = True
        timer.start()


class DelayedClickDriver(FakeDriver):
    def execute_script(self, script, *args):
        if "const destructive" in script:
            return {
                "url": self.current_url,
                "title": "Example",
                "text": "New",
                "elements": [
                    {
                        "id": "e01",
                        "role": "link",
                        "tag": "a",
                        "text": "New",
                        "href": "https://example.com/new",
                    }
                ],
            }
        return super().execute_script(script, *args)

    def find_elements(self, by, selector):
        return [DelayedLink(self)]


def test_click_waits_for_link_navigation_before_observing_outcome():
    driver = DelayedClickDriver()
    browser = SafariBrowser(driver=driver)
    before = browser.snapshot()
    result = browser.execute({"type": "click", "target_id": "e01"}, before.fingerprint)
    assert result["after_url"] == "https://example.com/new"


def test_lazy_content_elsewhere_does_not_cancel_an_action():
    from laya_voice_browser.page import decision_still_valid
    from laya_voice_browser.types import Element, Snapshot

    link = Element("e01", "link", "Create account", "a", href="https://w.org/create")
    decided = Snapshot("https://w.org/", "W", "", (link,), "before")
    loaded_more = Snapshot("https://w.org/", "W", "", (link, Element("e02", "link", "News", "a")), "after")
    moved = Snapshot("https://w.org/", "W", "", (Element("e01", "link", "Donate", "a"), link), "shifted")
    left = Snapshot("https://w.org/other", "W", "", (link,), "other")
    click = {"type": "click", "target_id": "e01"}
    assert decision_still_valid(decided, loaded_more, "before", click)
    assert not decision_still_valid(decided, moved, "before", click)  # e01 is now a different element
    assert not decision_still_valid(decided, left, "before", click)
    assert not decision_still_valid(None, loaded_more, "before", click)


def test_typing_releases_command_before_literal_text(monkeypatch):
    from selenium.webdriver.common.keys import Keys

    calls = []

    class Chain:
        def __init__(self, driver):
            pass

        def key_down(self, key):
            calls.append(("down", key))
            return self

        def key_up(self, key):
            calls.append(("up", key))
            return self

        def send_keys(self, value):
            calls.append(("keys", value))
            return self

        def perform(self):
            calls.append(("perform",))

    class Field:
        def click(self):
            calls.append(("focus",))

    monkeypatch.setattr("selenium.webdriver.common.action_chains.ActionChains", Chain)
    browser = SafariBrowser(driver=FakeDriver())
    monkeypatch.setattr(browser, "_element", lambda _: Field())
    browser.execute({"type": "type", "target_id": "e1", "text": "Mercury"})
    assert calls == [("focus",), ("down", Keys.COMMAND), ("keys", "a"),
                     ("up", Keys.COMMAND), ("keys", "Mercury"), ("perform",)]
