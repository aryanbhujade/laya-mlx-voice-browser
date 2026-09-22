import threading

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


def test_navigation_uses_safari_driver_and_records_new_state():
    driver = FakeDriver()
    browser = SafariBrowser(driver=driver)
    before = browser.snapshot()
    result = browser.execute({"type": "navigate", "url": "https://wikipedia.org"}, before.fingerprint)
    assert result["after_url"] == "https://wikipedia.org"
    assert ("get", "https://wikipedia.org") in driver.calls


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
