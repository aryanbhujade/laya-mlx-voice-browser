# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .browser import BrowserSessionLost, StalePage
from .questions import MAX_OBSERVED_ELEMENTS
from .safety import deterministic_destructive
from .types import Element, Snapshot

__all__ = ["BrowserSessionLost", "SafariBrowser", "StalePage", "deterministic_destructive"]

_SNAPSHOT_JS = r"""
const destructive = /\b(buy|purchase|pay|place order|delete|remove|send|submit|publish|confirm|sign in|log in)\b/i;
const selectors = [
  'a[href]', 'button', 'input:not([type="hidden"])', 'textarea', 'select',
  '[role="button"]', '[role="link"]', '[role="tab"]', '[role="option"]',
  '[contenteditable="true"]'
].join(',');
const visible = (el) => {
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width >= 4 && r.height >= 4 && r.bottom > 0 && r.right > 0 &&
    r.top < innerHeight && r.left < innerWidth && s.visibility !== 'hidden' && s.display !== 'none';
};
const label = (el) => (el.getAttribute('aria-label') || el.innerText || el.value ||
  el.placeholder || el.title || el.name || '').replace(/\s+/g, ' ').trim().slice(0, 100);
document.querySelectorAll('[data-laya-id]').forEach((el) => el.removeAttribute('data-laya-id'));
let n = 0;
const elements = [...document.querySelectorAll(selectors)].filter(visible).map((el) => {
  let id = el.getAttribute('data-laya-id');
  if (!id) { id = `e${String(++n).padStart(2, '0')}`; el.setAttribute('data-laya-id', id); }
  const text = label(el);
  return {
    id,
    role: el.getAttribute('role') || ({A:'link',BUTTON:'button',INPUT:'input',TEXTAREA:'textbox',SELECT:'select'}[el.tagName] || el.tagName.toLowerCase()),
    tag: el.tagName.toLowerCase(), text, placeholder: el.placeholder || '', value: el.value || '',
    href: el.href ? new URL(el.href, location.href).href.slice(0, 180) : '',
    destructive_hint: destructive.test(text),
    in_main: Boolean(el.closest('main,[role="main"],article')),
    top: Math.round(el.getBoundingClientRect().top)
  };
}).slice(0, arguments[0]);
return {
  url: location.href,
  title: document.title,
  text: (document.body?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 5000),
  elements
};
"""

_NAVIGATION_WAIT_SECONDS = 3.0

_CANDIDATES_JS = r"""
document.querySelectorAll('.__laya-badge').forEach((el) => el.remove());
for (const [n, id] of arguments[0]) {
  const el = document.querySelector(`[data-laya-id="${id}"]`);
  if (!el) continue;
  const r = el.getBoundingClientRect();
  const badge = document.createElement('div');
  badge.className = '__laya-badge';
  badge.textContent = String(n);
  badge.style.cssText = `position:absolute;z-index:2147483000;pointer-events:none;
    left:${Math.max(0, r.left + scrollX - 10)}px;top:${Math.max(0, r.top + scrollY - 10)}px;
    background:#2563eb;color:#fff;font:700 14px/1 -apple-system,sans-serif;padding:5px 8px;
    border-radius:999px;border:2px solid #fff;box-shadow:0 2px 10px rgba(0,0,0,.4)`;
  document.body.appendChild(badge);
}
"""


def _session_lost(exc: Exception) -> bool:
    name = type(exc).__name__
    return name in {"InvalidSessionIdException", "NoSuchWindowException"} or (
        name == "WebDriverException" and "session" in str(exc).casefold()
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
        self.driver.get(start_url)
        self._last_snapshot: Snapshot | None = None

    def close(self) -> None:
        if self.driver is not None:
            self.driver.quit()
            self.driver = None

    def snapshot(self) -> Snapshot:
        try:
            raw = self.driver.execute_script(_SNAPSHOT_JS, MAX_OBSERVED_ELEMENTS)
        except Exception as exc:
            if _session_lost(exc):
                raise BrowserSessionLost("The Safari automation window is gone") from exc
            raise
        elements = tuple(
            Element(
                id=str(item.get("id", "")),
                role=str(item.get("role", "")),
                text=str(item.get("text", "")),
                tag=str(item.get("tag", "")),
                href=str(item.get("href", "")),
                placeholder=str(item.get("placeholder", "")),
                value=str(item.get("value", "")),
                destructive_hint=bool(item.get("destructive_hint")),
                in_main=bool(item.get("in_main")),
                top=float(item.get("top", 0.0)),
            )
            for item in raw.get("elements", [])
            if item.get("id")
        )
        compact = {
            "url": raw.get("url", ""),
            "title": raw.get("title", ""),
            "elements": [element.compact() for element in elements],
        }
        snapshot = Snapshot(
            url=str(raw.get("url", "")),
            title=str(raw.get("title", "")),
            text=str(raw.get("text", "")),
            elements=elements,
            fingerprint=hashlib.sha256(json.dumps(compact, sort_keys=True).encode()).hexdigest(),
        )
        self._last_snapshot = snapshot
        return snapshot

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
        self.driver.execute_script(_CANDIDATES_JS, [[number, element_id] for number, element_id in candidates])

    def clear_candidates(self) -> None:
        self.driver.execute_script(_CANDIDATES_JS, [])

    def execute(self, action: dict[str, Any], expected_fingerprint: str | None = None) -> dict[str, Any]:
        try:
            return self._execute(action, expected_fingerprint)
        except Exception as exc:
            if _session_lost(exc):
                raise BrowserSessionLost("The Safari automation window is gone") from exc
            raise

    def _execute(self, action: dict[str, Any], expected_fingerprint: str | None) -> dict[str, Any]:
        if expected_fingerprint and self._last_snapshot:
            fresh = self.snapshot()
            if fresh.fingerprint != expected_fingerprint:
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
            from selenium.webdriver.common.keys import Keys

            element = self._element(action["target_id"])
            element.click()
            element.send_keys(Keys.COMMAND, "a")
            element.send_keys(action["text"])
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
                pixels = 320 if amount == "little" else 0.82 * self.driver.execute_script("return innerHeight")
                self.driver.execute_script("scrollBy(0, arguments[0])", direction * pixels)
        elif kind == "back":
            self.driver.back()
        elif kind == "forward":
            self.driver.forward()
        elif kind == "reload":
            self.driver.refresh()
        elif kind == "new_tab":
            self.driver.switch_to.new_window("tab")
        elif kind == "close_tab":
            if len(self.driver.window_handles) <= 1:
                raise RuntimeError("Refusing to close Safari's only controlled tab")
            self.driver.close()
            self.driver.switch_to.window(self.driver.window_handles[-1])
        elif kind == "switch_tab":
            handles = self.driver.window_handles
            current = handles.index(self.driver.current_window_handle)
            direction = action.get("direction", "next")
            target = 0 if direction == "first" else (current + (-1 if direction == "previous" else 1)) % len(handles)
            self.driver.switch_to.window(handles[target])
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
