import plistlib

from laya_voice_browser import browsers, chromium
from laya_voice_browser.chromium import ChromiumBrowser, read_devtools_endpoint

CHROME = chromium.CHROMIUM_APPS[0]


class FakeCDP:
    """Answers DevTools calls for one page; records what was sent."""

    def __init__(self, covered=False):
        self.calls = []
        self.covered = covered
        self.url = "https://example.com/"

    def call(self, method, params=None, *, session=None, timeout=15.0):
        self.calls.append((method, params))
        if method == "Target.getTargets":
            return {"targetInfos": [{"targetId": "T1", "type": "page", "url": self.url}]}
        if method == "Target.attachToTarget":
            return {"sessionId": "S1"}
        if method == "Runtime.evaluate":
            return {"result": {"value": self._evaluate(params["expression"])}}
        return {}

    def _evaluate(self, expression):
        if "visibilityState" in expression:
            return ["visible", True]
        if "const destructive" in expression:
            return {"url": self.url, "title": "Example", "text": "", "elements": [
                {"id": "e01", "role": "link", "tag": "a", "text": "More", "href": "https://example.com/more"}
            ]}
        if "elementFromPoint" in expression:
            return {"x": 40, "y": 20, "clear": not self.covered, "href": ""}
        if expression == "location.href":
            return self.url
        if "readyState" in expression:
            return [self.url, "complete"]
        return True

    def close(self):
        pass


def methods(cdp):
    return [method for method, _ in cdp.calls]


def test_devtools_endpoint_comes_from_the_profile(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text("51234\n/devtools/browser/abc\n")
    assert read_devtools_endpoint(tmp_path) == "ws://127.0.0.1:51234/devtools/browser/abc"
    assert read_devtools_endpoint(tmp_path / "missing") is None


def test_click_sends_real_mouse_events_at_the_element():
    cdp = FakeCDP()
    browser = ChromiumBrowser(CHROME, connection=cdp)
    before = browser.snapshot()
    browser.execute({"type": "click", "target_id": "e01"}, before.fingerprint)
    mouse = [params["type"] for method, params in cdp.calls if method == "Input.dispatchMouseEvent"]
    assert mouse == ["mouseMoved", "mousePressed", "mouseReleased"]


def test_covered_element_is_clicked_directly_instead():
    cdp = FakeCDP(covered=True)
    browser = ChromiumBrowser(CHROME, connection=cdp)
    browser.execute({"type": "click", "target_id": "e01"}, browser.snapshot().fingerprint)
    assert "Input.dispatchMouseEvent" not in methods(cdp)


def test_typing_uses_real_text_input():
    cdp = FakeCDP()
    browser = ChromiumBrowser(CHROME, connection=cdp)
    browser.execute({"type": "type", "target_id": "e01", "text": "hello"}, browser.snapshot().fingerprint)
    assert ("Input.insertText", {"text": "hello"}) in cdp.calls


def test_auto_follows_a_supported_default_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(browsers, "app_path", lambda app: "/Applications/x.app")
    assert browsers.resolve("auto", "com.google.chrome") == "chrome"
    assert browsers.resolve("auto", "com.apple.safari") == "safari"
    assert browsers.resolve("auto", "org.mozilla.firefox") == "safari"
    assert browsers.resolve("edge") == "edge"


def test_default_browser_is_read_from_launch_services(tmp_path):
    preferences = tmp_path / "ls.plist"
    preferences.write_bytes(plistlib.dumps({"LSHandlers": [
        {"LSHandlerURLScheme": "mailto", "LSHandlerRoleAll": "com.apple.mail"},
        {"LSHandlerURLScheme": "https", "LSHandlerRoleAll": "com.google.Chrome"},
    ]}))
    assert browsers.default_browser_bundle_id(preferences) == "com.google.chrome"
    assert browsers.default_browser_bundle_id(tmp_path / "none.plist") == "com.apple.safari"


def test_a_slow_page_is_not_mistaken_for_a_closed_browser():
    import pytest

    class SlowSocket:
        def send(self, message):
            pass

        def recv(self, timeout=None):
            raise TimeoutError("timed out")

    connection = chromium.CDPConnection.__new__(chromium.CDPConnection)
    connection._socket = SlowSocket()
    connection._next_id = 0
    with pytest.raises(TimeoutError):
        connection.call("Runtime.evaluate", {}, timeout=0.01)
