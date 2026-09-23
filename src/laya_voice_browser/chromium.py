"""Chrome, Edge, Brave, Opera and other Chromium browsers over the Chrome DevTools Protocol.

LayaBrowse runs its own browser window with a dedicated profile (sign in once, it stays signed in):
Chromium refuses remote debugging on the everyday default profile. Clicks and keys are sent as
real input events, so pages treat them like a person's, unlike WebDriver or extension scripts.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .browser import BrowserSessionLost, NoMedia, StalePage, Unavailable, pick_tab
from .page import (
    CANDIDATES_JS,
    FOCUS_FIELD_JS,
    MEDIA_JS,
    SCROLL_JS,
    SCROLL_TO_JS,
    SITE_FIND_JS,
    SNAPSHOT_JS,
    call_script,
    decision_still_valid,
    parse_keys,
    snapshot_from_raw,
)
from .questions import MAX_OBSERVED_ELEMENTS
from .types import Snapshot, Tab

LAUNCH_TIMEOUT_SECONDS = 20.0
NAVIGATION_TIMEOUT_SECONDS = 10.0
LINK_WAIT_SECONDS = 1.5
TAB_SWITCH_SECONDS = 1.0


@dataclass(frozen=True)
class ChromiumApp:
    key: str
    name: str
    bundle_id: str


CHROMIUM_APPS = (
    ChromiumApp("chrome", "Google Chrome", "com.google.Chrome"),
    ChromiumApp("edge", "Microsoft Edge", "com.microsoft.edgemac"),
    ChromiumApp("brave", "Brave Browser", "com.brave.Browser"),
    ChromiumApp("chromium", "Chromium", "org.chromium.Chromium"),
    ChromiumApp("vivaldi", "Vivaldi", "com.vivaldi.Vivaldi"),
    ChromiumApp("opera", "Opera", "com.operasoftware.Opera"),
    ChromiumApp("opera_gx", "Opera GX", "com.operasoftware.OperaGX"),
)


def profile_dir(app: ChromiumApp) -> Path:
    return Path.home() / "Library" / "Application Support" / "laya-voice-browser" / "profiles" / app.key


def app_path(app: ChromiumApp) -> Path | None:
    for folder in (Path("/Applications"), Path.home() / "Applications"):
        candidate = folder / f"{app.name}.app"
        if candidate.exists():
            return candidate
    found = subprocess.run(
        ["mdfind", f"kMDItemCFBundleIdentifier == '{app.bundle_id}'"], capture_output=True, text=True
    ).stdout.split("\n")
    return Path(found[0]) if found and found[0].endswith(".app") else None


def installed_apps() -> list[ChromiumApp]:
    return [app for app in CHROMIUM_APPS if app_path(app)]


def launch_arguments(app: ChromiumApp) -> list[str]:
    return [
        "--remote-debugging-port=0",
        f"--user-data-dir={profile_dir(app)}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def read_devtools_endpoint(profile: Path) -> str | None:
    """Chromium writes the chosen port and browser path to DevToolsActivePort when the port is 0."""
    try:
        port, path = (profile / "DevToolsActivePort").read_text().splitlines()[:2]
    except (OSError, ValueError):
        return None
    return f"ws://127.0.0.1:{port.strip()}{path.strip()}"


class CDPError(RuntimeError):
    pass


class CDPConnection:
    """One WebSocket to the browser; page commands are multiplexed with flattened sessions."""

    def __init__(self, url: str) -> None:
        from websockets.sync.client import connect

        try:
            self._socket = connect(url, max_size=None, open_timeout=5, compression=None)
        except OSError as exc:
            raise BrowserSessionLost(f"cannot reach the browser at {url}") from exc
        self._next_id = 0

    def call(
        self, method: str, params: dict | None = None, *, session: str | None = None, timeout: float = 15.0
    ) -> dict[str, Any]:
        from websockets.exceptions import ConnectionClosed

        self._next_id += 1
        message: dict[str, Any] = {"id": self._next_id, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        deadline = time.monotonic() + timeout
        try:
            self._socket.send(json.dumps(message))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{method} timed out")
                reply = json.loads(self._socket.recv(timeout=remaining))
                if reply.get("id") != message["id"]:
                    continue  # events and stale replies
                if "error" in reply:
                    raise CDPError(f"{method}: {reply['error'].get('message', reply['error'])}")
                return reply.get("result", {})
        except TimeoutError:
            raise  # a slow page, not a lost browser (TimeoutError is itself an OSError)
        except (ConnectionClosed, OSError) as exc:
            raise BrowserSessionLost("the browser closed") from exc

    def close(self) -> None:
        try:
            self._socket.close()
        except Exception:
            pass


class ChromiumBrowser:
    """Controls the tab you are looking at in LayaBrowse's Chromium window."""

    def __init__(self, app: ChromiumApp, *, connection: CDPConnection | None = None) -> None:
        self.app = app
        self._cdp = connection or self._connect_or_launch()
        self._sessions: dict[str, str] = {}
        self._target: str | None = None
        self._last_snapshot: Snapshot | None = None
        self._order: list[str] = []

    # -- connection -------------------------------------------------------------------------------

    def _connect_or_launch(self) -> CDPConnection:
        profile = profile_dir(self.app)
        endpoint = read_devtools_endpoint(profile)
        if endpoint:
            try:
                return CDPConnection(endpoint)
            except BrowserSessionLost:
                (profile / "DevToolsActivePort").unlink(missing_ok=True)
        path = app_path(self.app)
        if not path:
            raise RuntimeError(f"{self.app.name} is not installed")
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "DevToolsActivePort").unlink(missing_ok=True)
        # `open -n` starts a separate instance on LayaBrowse's profile next to your everyday browser.
        subprocess.run(["open", "-na", str(path), "--args", *launch_arguments(self.app)], check=True)
        deadline = time.monotonic() + LAUNCH_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            endpoint = read_devtools_endpoint(profile)
            if endpoint:
                try:
                    return CDPConnection(endpoint)
                except BrowserSessionLost:
                    pass
            time.sleep(0.2)
        raise RuntimeError(
            f"{self.app.name} did not start remote debugging within {LAUNCH_TIMEOUT_SECONDS:.0f}s"
        )

    def close(self) -> None:
        # Leave the window open: it is the user's browser, only our connection goes away.
        self._cdp.close()

    def alive(self) -> bool:
        try:
            self._cdp.call("Target.getTargets", timeout=2)
            return True
        except Exception:
            return False

    # -- pages ------------------------------------------------------------------------------------

    def _pages(self) -> list[dict[str, Any]]:
        """Open tabs in the order you see them. The DevTools Protocol has no tab-strip order, so it is
        kept here: new tabs go last, and a tab opened from a link goes right after its opener (where
        Chromium puts it)."""
        targets = self._cdp.call("Target.getTargets")["targetInfos"]
        pages = {
            target["targetId"]: target
            for target in targets
            if target["type"] == "page"
            and not target["url"].startswith(("devtools://", "chrome-extension://"))
        }
        self._order = [tab_id for tab_id in self._order if tab_id in pages]
        for tab_id, page in pages.items():
            if tab_id in self._order:
                continue
            opener = page.get("openerId")
            if opener in self._order:
                position = self._order.index(opener) + 1
                while position < len(self._order) and pages[self._order[position]].get("openerId") == opener:
                    position += 1  # after the opener's earlier children, like Chromium
                self._order.insert(position, tab_id)
            else:
                self._order.append(tab_id)
        return [pages[tab_id] for tab_id in self._order]

    def _session(self, target_id: str) -> str:
        if target_id not in self._sessions:
            attached = self._cdp.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
            self._sessions[target_id] = attached["sessionId"]
        return self._sessions[target_id]

    def _evaluate(self, target_id: str, expression: str, timeout: float = 15.0) -> Any:
        result = self._cdp.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True, "userGesture": True},
            session=self._session(target_id),
            timeout=timeout,
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            raise CDPError(
                details.get("exception", {}).get("description") or details.get("text", "script failed")
            )
        return result.get("result", {}).get("value")

    def _current(self) -> str:
        """The tab Laya is working in: the one it last used while that is still showing, otherwise
        whichever tab the user has brought to the front themselves."""
        pages = self._pages()
        self._last_pages = pages
        ids = [page["targetId"] for page in pages]
        if not ids:
            self._target = self._cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            return self._target
        if self._target in ids and self._visible(self._target):
            return self._target
        for target_id in ids:
            if target_id != self._target and self._visible(target_id):
                self._target = target_id
                return target_id
        if self._target not in ids:
            self._target = ids[0]
        return self._target

    def _call_page(self, method: str, params: dict | None = None) -> dict[str, Any]:
        return self._cdp.call(method, params, session=self._session(self._target or self._current()))

    def _visible(self, target_id: str) -> bool:
        try:
            return self._evaluate(target_id, "document.visibilityState", 2) == "visible"
        except (CDPError, TimeoutError):
            return False

    def _activate(self, target_id: str) -> None:
        """Bring a tab to the front and wait until Chromium has actually switched to it."""
        self._target = target_id
        self._cdp.call("Target.activateTarget", {"targetId": target_id})
        deadline = time.monotonic() + TAB_SWITCH_SECONDS
        while time.monotonic() < deadline and not self._visible(target_id):
            time.sleep(0.03)

    # -- Browser interface ------------------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        current = self._current()
        from .sites import browsing_probes

        raw = self._evaluate(current, call_script(SNAPSHOT_JS, MAX_OBSERVED_ELEMENTS, browsing_probes()))
        tabs = tuple(
            Tab(page["targetId"], page.get("title", ""), page.get("url", ""), page["targetId"] == current)
            for page in getattr(self, "_last_pages", [])
        )
        snapshot = snapshot_from_raw(raw or {}, tabs=tabs)
        self._last_snapshot = snapshot
        return snapshot

    def show_candidates(self, candidates: list[tuple[int, str]]) -> None:
        self._evaluate(self._current(), call_script(CANDIDATES_JS, [list(item) for item in candidates]))

    def clear_candidates(self) -> None:
        self._evaluate(self._current(), call_script(CANDIDATES_JS, []))

    def execute(self, action: dict[str, Any], expected_fingerprint: str | None = None) -> dict[str, Any]:
        if expected_fingerprint and self._last_snapshot:
            decided = self._last_snapshot
            if not decision_still_valid(decided, self.snapshot(), expected_fingerprint, action):
                raise StalePage("the page changed after the decision; no action was executed")
        target = self._current()
        before_url = self._evaluate(target, "location.href")
        kind = action["type"]
        if kind == "navigate":
            self._call_page("Page.navigate", {"url": action["url"]})
            self._wait_loaded(
                target, before_url, NAVIGATION_TIMEOUT_SECONDS, require_change=action["url"] != before_url
            )
        elif kind == "click":
            self._click(target, action["target_id"], before_url)
        elif kind == "type":
            self._focus_field(target, action["target_id"])
            self._call_page("Input.insertText", {"text": action["text"]})
        elif kind == "select":
            chosen = self._evaluate(
                target, call_script(_SELECT_JS, action["target_id"], action.get("text", ""))
            )
            if not chosen:
                raise RuntimeError(f"No dropdown option matches {action.get('text')!r}")
        elif kind == "press_enter":
            for event in ("keyDown", "keyUp"):
                self._call_page(
                    "Input.dispatchKeyEvent",
                    {
                        "type": event,
                        "key": "Enter",
                        "code": "Enter",
                        "windowsVirtualKeyCode": 13,
                        "nativeVirtualKeyCode": 13,
                        **({"text": "\r", "unmodifiedText": "\r"} if event == "keyDown" else {}),
                    },
                )
            self._wait_loaded(target, before_url, LINK_WAIT_SECONDS, require_change=True)
        elif kind == "scroll":
            self._evaluate(
                target, call_script(SCROLL_JS, action.get("amount", "page"), action.get("direction"))
            )
        elif kind in {"back", "forward"}:
            history = self._call_page("Page.getNavigationHistory")
            index = history["currentIndex"] + (-1 if kind == "back" else 1)
            if 0 <= index < len(history["entries"]):
                self._call_page("Page.navigateToHistoryEntry", {"entryId": history["entries"][index]["id"]})
                self._wait_loaded(target, before_url, NAVIGATION_TIMEOUT_SECONDS, require_change=True)
        elif kind == "reload":
            self._call_page("Page.reload")
            time.sleep(0.15)
            self._wait_loaded(target, None, NAVIGATION_TIMEOUT_SECONDS, require_change=False)
        elif kind == "media":
            self._media(target, action)
        elif kind == "site":
            self._site(target, action, before_url)
        elif kind == "new_tab":
            self._activate(self._cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"])
        elif kind == "close_tab":
            ids = [page["targetId"] for page in self._pages()]
            if len(ids) <= 1:
                raise RuntimeError("Refusing to close the only tab")
            victim = pick_tab(ids, target, action)
            self._cdp.call("Target.closeTarget", {"targetId": victim})
            self._sessions.pop(victim, None)
            if victim == target:
                self._activate(next(tab_id for tab_id in ids if tab_id != victim))
        elif kind == "close_other_tabs":
            for tab_id in [page["targetId"] for page in self._pages()]:
                if tab_id != target:
                    self._cdp.call("Target.closeTarget", {"targetId": tab_id})
                    self._sessions.pop(tab_id, None)
        elif kind == "switch_tab":
            ids = [page["targetId"] for page in self._pages()]
            self._activate(pick_tab(ids, target, {"direction": "next", **action}))
        else:
            raise ValueError(f"Unsupported action: {kind}")
        time.sleep(0.05)
        after = self.snapshot()
        return {
            "ok": True,
            "action": action,
            "before_url": before_url,
            "after_url": after.url,
            "page_changed": after.fingerprint != expected_fingerprint if expected_fingerprint else None,
        }

    # -- actions ----------------------------------------------------------------------------------

    def _click(self, target: str, element_id: str, before_url: str) -> None:
        point = self._evaluate(target, call_script(_POINT_JS, element_id))
        if not point:
            raise StalePage(f"Element {element_id} is missing; observe again")
        if not point["clear"]:
            # Something covers the element's centre (a banner, a sticky header): click it directly.
            self._evaluate(target, call_script(_CLICK_JS, element_id))
        else:
            base = {"x": point["x"], "y": point["y"], "button": "left", "clickCount": 1}
            self._call_page(
                "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": point["x"], "y": point["y"]}
            )
            self._call_page("Input.dispatchMouseEvent", {"type": "mousePressed", **base})
            self._call_page("Input.dispatchMouseEvent", {"type": "mouseReleased", **base})
        if point.get("href") and point["href"] != before_url:
            self._wait_loaded(target, before_url, LINK_WAIT_SECONDS, require_change=True)

    def _press_tagged(self, target: str) -> None:
        """A real click on the element a page script tagged with data-laya-press."""
        point = self._evaluate(target, call_script(_POINT_JS.replace("data-laya-id", "data-laya-press"), "1"))
        if not point:
            return
        base = {"x": point["x"], "y": point["y"], "button": "left", "clickCount": 1}
        self._call_page("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": point["x"], "y": point["y"]})
        self._call_page("Input.dispatchMouseEvent", {"type": "mousePressed", **base})
        self._call_page("Input.dispatchMouseEvent", {"type": "mouseReleased", **base})

    def _press_keys(self, spec: str) -> None:
        _, key = parse_keys(spec)
        common = {
            "key": key["key"],
            "code": key["code"],
            "windowsVirtualKeyCode": key["vk"],
            "nativeVirtualKeyCode": key["vk"],
            "modifiers": key["bits"],
        }
        typed = {"text": key["text"], "unmodifiedText": key["text"]} if key["text"] else {}
        self._call_page("Input.dispatchKeyEvent", {"type": "keyDown", **common, **typed})
        self._call_page("Input.dispatchKeyEvent", {"type": "keyUp", **common})

    def _site(self, target: str, action: dict[str, Any], before_url: str) -> None:
        do = action["do"]
        if "key" in do:
            self._press_keys(do["key"])
        elif "click" in do or "click_css" in do:
            found = self._evaluate(
                target, call_script(SITE_FIND_JS, do.get("click", []), do.get("click_css", []))
            )
            if not found:
                raise Unavailable(f"there is no {action['id'].replace('_', ' ')} control on this page")
            self._press_tagged(target)
            if found.get("href") and found["href"] != before_url:
                self._wait_loaded(target, before_url, LINK_WAIT_SECONDS, require_change=True)
        elif "fill" in do:
            if not self._evaluate(target, call_script(FOCUS_FIELD_JS, do["fill"])):
                raise Unavailable("that field is not on this page")
            self._call_page("Input.insertText", {"text": action.get("text", "")})
            if do.get("submit"):
                self._press_keys("enter")
                self._wait_loaded(target, before_url, LINK_WAIT_SECONDS, require_change=True)
        elif "scroll_to" in do:
            if not self._evaluate(target, call_script(SCROLL_TO_JS, do["scroll_to"])):
                raise Unavailable("that section is not on this page")
        else:
            raise ValueError(f"unsupported site action: {do}")

    def _media(self, target: str, action: dict[str, Any]) -> None:
        before = self._evaluate(target, "location.href")
        done = self._evaluate(target, call_script(MEDIA_JS, action["command"], action.get("amount")))
        if not done:
            raise NoMedia(f"nothing on this page can {action['command'].replace('_', ' ')}")
        if done.get("press"):
            self._press_tagged(target)
        if action["command"] in {"next", "previous"}:
            self._wait_loaded(target, before, LINK_WAIT_SECONDS, require_change=True)

    def _focus_field(self, target: str, element_id: str) -> None:
        if not self._evaluate(target, call_script(_FOCUS_JS, element_id)):
            raise StalePage(f"Field {element_id} is missing; observe again")

    def _wait_loaded(
        self, target: str, before_url: str | None, timeout: float, *, require_change: bool
    ) -> None:
        """Wait until the document is ready (and, if a navigation was expected, the URL moved on).

        Never fails the action: a slow page is still observed afterwards.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                url, state = self._evaluate(target, "[location.href, document.readyState]", 2)
            except (CDPError, TimeoutError):
                time.sleep(0.05)  # the old document is gone and the new one is not ready yet
                continue
            if state in {"interactive", "complete"} and (not require_change or url != before_url):
                return
            time.sleep(0.05)


_POINT_JS = r"""
const el = document.querySelector(`[data-laya-id="${arguments[0]}"]`);
if (!el) return null;
el.scrollIntoView({block: 'center', inline: 'center'});
const r = el.getBoundingClientRect();
const x = r.left + r.width / 2, y = r.top + r.height / 2;
const hit = document.elementFromPoint(x, y);
return {x, y, clear: !!hit && (hit === el || el.contains(hit) || hit.contains(el)), href: el.href || ''};
"""

_CLICK_JS = r"""
const el = document.querySelector(`[data-laya-id="${arguments[0]}"]`);
if (el) el.click();
return !!el;
"""

_FOCUS_JS = r"""
const el = document.querySelector(`[data-laya-id="${arguments[0]}"]`);
if (!el) return false;
el.scrollIntoView({block: 'center'});
el.focus();
if (el.isContentEditable) {
  const range = document.createRange();
  range.selectNodeContents(el);
  const selection = getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
} else if (typeof el.select === 'function') {
  el.select();
}
return true;
"""

_SELECT_JS = r"""
const [id, wanted] = arguments;
const el = document.querySelector(`[data-laya-id="${id}"]`);
if (!el || !el.options) return null;
const option = [...el.options].find((o) => o.text.toLowerCase().includes(wanted.toLowerCase()));
if (!option) return null;
el.value = option.value;
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
return option.text;
"""
