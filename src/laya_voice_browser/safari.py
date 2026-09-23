# ruff: noqa: E501
from __future__ import annotations

import threading
import time
from typing import Any

from .browser import BrowserSessionLost, NoMedia, StalePage, Unavailable, pick_tab
from .page import (
    CANDIDATES_JS,
    FOCUS_FIELD_JS,
    MEDIA_JS,
    SCROLL_TO_JS,
    SITE_FIND_JS,
    SNAPSHOT_JS,
    decision_still_valid,
    parse_keys,
    snapshot_from_raw,
)
from .questions import MAX_OBSERVED_ELEMENTS
from .safety import deterministic_destructive
from .types import Snapshot, Tab

__all__ = ["BrowserSessionLost", "SafariBrowser", "StalePage", "deterministic_destructive"]


_NAVIGATION_WAIT_SECONDS = 3.0
# Selenium waits 120 s by default; a stopped session should fail fast so the next command reopens.
_COMMAND_TIMEOUT_SECONDS = 20.0
_ALIVE_TIMEOUT_SECONDS = 2.5


def _session_lost(exc: Exception) -> bool:
    """The session or driver is gone: stopped from Safari's banner, window closed, or driver dead."""
    name = type(exc).__name__
    return (
        name in {"InvalidSessionIdException", "NoSuchWindowException", "MaxRetryError", "ProtocolError"}
        or isinstance(exc, (ConnectionError, TimeoutError))
        or (name == "WebDriverException" and "session" in str(exc).casefold())
    )


class SafariBrowser:
    """A real Safari session controlled through Apple's bundled safaridriver."""

    def __init__(self, start_url: str = "https://example.com", *, driver: Any | None = None) -> None:
        if driver is None:
            try:
                from selenium import webdriver

                driver = webdriver.Safari()
            except Exception as exc:
                raise RuntimeError(
                    "Safari automation could not start. In Safari, enable Develop > Allow Remote "
                    "Automation, then run `safaridriver --enable` once if macOS requests it. "
                    f"SafariDriver reported: {exc}"
                ) from exc
            try:
                # Fill the screen as a normal window (zoomed), not macOS full-screen mode.
                driver.maximize_window()
            except Exception:
                pass
        self.driver = driver
        client = getattr(getattr(driver, "command_executor", None), "_client_config", None)
        if client is not None:
            client.timeout = _COMMAND_TIMEOUT_SECONDS
        self.driver.get(start_url)
        self._last_snapshot: Snapshot | None = None
        # WebDriver can only read the current tab's title, so remember each tab's as it is visited.
        self._tab_titles: dict[str, tuple[str, str]] = {}

    def close(self) -> None:
        if self.driver is not None:
            self.driver.quit()
            self.driver = None

    def alive(self) -> bool:
        """A quick check that the session still answers; "Stop Session" can leave it hanging."""
        if self.driver is None:
            return False
        result: list[bool] = []

        def probe() -> None:
            try:
                self.driver.execute_script("return 1")
                result.append(True)
            except Exception:
                result.append(False)

        worker = threading.Thread(target=probe, daemon=True)
        worker.start()
        worker.join(_ALIVE_TIMEOUT_SECONDS)
        return bool(result and result[0])

    def snapshot(self) -> Snapshot:
        try:
            from .sites import browsing_probes

            raw = self.driver.execute_script(SNAPSHOT_JS, MAX_OBSERVED_ELEMENTS, browsing_probes())
        except Exception as exc:
            if _session_lost(exc):
                raise BrowserSessionLost("The Safari automation window is gone") from exc
            raise
        snapshot = snapshot_from_raw(raw, tabs=self._tabs(raw))
        self._last_snapshot = snapshot
        return snapshot

    def _press_keys(self, spec: str) -> None:
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.keys import Keys

        modifiers, key = parse_keys(spec)
        special = {
            "Enter": Keys.ENTER,
            "Escape": Keys.ESCAPE,
            "Tab": Keys.TAB,
            "ArrowLeft": Keys.LEFT,
            "ArrowUp": Keys.UP,
            "ArrowRight": Keys.RIGHT,
            "ArrowDown": Keys.DOWN,
        }
        names = {
            "shift": Keys.SHIFT,
            "alt": Keys.ALT,
            "option": Keys.ALT,
            "ctrl": Keys.CONTROL,
            "control": Keys.CONTROL,
            "meta": Keys.COMMAND,
            "cmd": Keys.COMMAND,
            "command": Keys.COMMAND,
        }
        held = [names[modifier] for modifier in modifiers]
        chain = ActionChains(self.driver)
        for modifier in held:
            chain.key_down(modifier)
        chain.send_keys(special.get(key["key"], key["text"] or key["key"]))
        for modifier in reversed(held):
            chain.key_up(modifier)
        chain.perform()

    def _site(self, action: dict[str, Any]) -> None:
        do = action["do"]
        if "key" in do:
            self._press_keys(do["key"])
        elif "click" in do or "click_css" in do:
            if not self.driver.execute_script(SITE_FIND_JS, do.get("click", []), do.get("click_css", [])):
                raise Unavailable(f"there is no {action['id'].replace('_', ' ')} control on this page")
            self.driver.execute_script("document.querySelector('[data-laya-press]')?.click()")
        elif "fill" in do:
            if not self.driver.execute_script(FOCUS_FIELD_JS, do["fill"]):
                raise Unavailable("that field is not on this page")
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.keys import Keys

            text = action.get("text", "") + (Keys.ENTER if do.get("submit") else "")
            ActionChains(self.driver).send_keys(text).perform()
        elif "scroll_to" in do:
            if not self.driver.execute_script(SCROLL_TO_JS, do["scroll_to"]):
                raise Unavailable("that section is not on this page")
        else:
            raise ValueError(f"unsupported site action: {do}")

    def _tabs(self, raw: dict[str, Any]) -> tuple[Tab, ...]:
        current = self.driver.current_window_handle
        self._tab_titles[current] = (str(raw.get("title", "")), str(raw.get("url", "")))
        return tuple(
            Tab(handle, *self._tab_titles.get(handle, ("", "")), active=handle == current)
            for handle in self.driver.window_handles
        )

    def _element(self, element_id: str):
        from selenium.webdriver.common.by import By

        found = self.driver.find_elements(By.CSS_SELECTOR, f'[data-laya-id="{element_id}"]')
        if len(found) != 1:
            raise StalePage(f"Element {element_id} is missing or ambiguous; observe again")
        return found[0]

    def _wait_for_navigation(self, before_url: str) -> None:
        """Wait until Safari's URL and JavaScript document have both reached the new page."""
        deadline = time.monotonic() + _NAVIGATION_WAIT_SECONDS
        while time.monotonic() < deadline:
            if self.driver.current_url != before_url:
                try:
                    document_url, ready_state = self.driver.execute_script(
                        "return [location.href, document.readyState]"
                    )
                except Exception:
                    return
                if document_url != before_url and ready_state in {"interactive", "complete"}:
                    return
            time.sleep(0.02)

    def show_candidates(self, candidates: list[tuple[int, str]]) -> None:
        self.driver.execute_script(CANDIDATES_JS, [[number, element_id] for number, element_id in candidates])

    def clear_candidates(self) -> None:
        self.driver.execute_script(CANDIDATES_JS, [])

    def execute(self, action: dict[str, Any], expected_fingerprint: str | None = None) -> dict[str, Any]:
        try:
            return self._execute(action, expected_fingerprint)
        except Exception as exc:
            if _session_lost(exc):
                raise BrowserSessionLost("The Safari automation window is gone") from exc
            raise

    def _execute(self, action: dict[str, Any], expected_fingerprint: str | None) -> dict[str, Any]:
        if expected_fingerprint and self._last_snapshot:
            decided = self._last_snapshot
            if not decision_still_valid(decided, self.snapshot(), expected_fingerprint, action):
                raise StalePage("Safari changed after the decision; no action was executed")
        kind = action["type"]
        before_url = self.driver.current_url
        if kind == "navigate":
            self.driver.get(action["url"])
        elif kind == "click":
            target = next(
                (
                    item
                    for item in (self._last_snapshot.elements if self._last_snapshot else ())
                    if item.id == action["target_id"]
                ),
                None,
            )
            self._element(action["target_id"]).click()
            if target and target.href and target.href != before_url:
                self._wait_for_navigation(before_url)
        elif kind == "type":
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.keys import Keys

            element = self._element(action["target_id"])
            element.click()
            # Safari can retain a modifier across Element.send_keys calls. Release
            # Command explicitly before sending literal text, or letters become shortcuts.
            ActionChains(self.driver).key_down(Keys.COMMAND).send_keys("a").key_up(Keys.COMMAND).send_keys(
                action["text"]
            ).perform()
        elif kind == "press_enter":
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.keys import Keys

            ActionChains(self.driver).send_keys(Keys.ENTER).perform()
        elif kind == "scroll":
            amount = action.get("amount", "page")
            if amount == "end":
                self.driver.execute_script("scrollTo(0, document.body.scrollHeight)")
            elif amount == "top":
                self.driver.execute_script("scrollTo(0, 0)")
            else:
                direction = -1 if action.get("direction") == "up" else 1
                pixels = (
                    320 if amount == "little" else 0.82 * self.driver.execute_script("return innerHeight")
                )
                self.driver.execute_script("scrollBy(0, arguments[0])", direction * pixels)
        elif kind == "back":
            self.driver.back()
        elif kind == "forward":
            self.driver.forward()
        elif kind == "reload":
            self.driver.refresh()
        elif kind == "media":
            done = self.driver.execute_script(MEDIA_JS, action["command"], action.get("amount"))
            if not done:
                raise NoMedia(f"nothing on this page can {action['command'].replace('_', ' ')}")
            if done.get("press"):
                self.driver.execute_script("document.querySelector('[data-laya-press]')?.click()")
        elif kind == "site":
            self._site(action)
        elif kind == "new_tab":
            self.driver.switch_to.new_window("tab")
        elif kind == "close_tab":
            handles = self.driver.window_handles
            if len(handles) <= 1:
                raise RuntimeError("Refusing to close Safari's only controlled tab")
            current = self.driver.current_window_handle
            victim = pick_tab(handles, current, action)
            self.driver.switch_to.window(victim)
            self.driver.close()
            self._tab_titles.pop(victim, None)
            remaining = [handle for handle in handles if handle != victim]
            self.driver.switch_to.window(current if current in remaining else remaining[-1])
        elif kind == "close_other_tabs":
            current = self.driver.current_window_handle
            for handle in self.driver.window_handles:
                if handle != current:
                    self.driver.switch_to.window(handle)
                    self.driver.close()
                    self._tab_titles.pop(handle, None)
            self.driver.switch_to.window(current)
        elif kind == "switch_tab":
            handles = self.driver.window_handles
            current = self.driver.current_window_handle
            self.driver.switch_to.window(pick_tab(handles, current, {"direction": "next", **action}))
        elif kind == "select":
            from selenium.webdriver.support.ui import Select

            element = self._element(action["target_id"])
            wanted = action.get("text", "")
            select = Select(element)
            matches = [option for option in select.options if wanted.casefold() in option.text.casefold()]
            if not matches:
                raise RuntimeError(f"No dropdown option matches {wanted!r}")
            select.select_by_visible_text(matches[0].text)
        else:
            raise ValueError(f"Unsupported action: {kind}")
        time.sleep(0.08)
        after = self.snapshot()
        return {
            "ok": True,
            "action": action,
            "before_url": before_url,
            "after_url": after.url,
            "page_changed": after.fingerprint != expected_fingerprint if expected_fingerprint else None,
        }
