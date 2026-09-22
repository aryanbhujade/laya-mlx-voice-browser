# ruff: noqa: E501
"""Page-side JavaScript shared by every browser backend, and turning its result into a Snapshot."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .types import Element, Snapshot

SNAPSHOT_JS = r"""
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

CANDIDATES_JS = r"""
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

SCROLL_JS = r"""
const [amount, direction] = arguments;
if (amount === 'end') { scrollTo(0, document.body.scrollHeight); return; }
if (amount === 'top') { scrollTo(0, 0); return; }
const pixels = amount === 'little' ? 320 : 0.82 * innerHeight;
scrollBy(0, (direction === 'up' ? -1 : 1) * pixels);
"""


def call_script(script: str, *args: Any) -> str:
    """Wrap a script that reads `arguments` so it can run as a plain expression (CDP, extensions)."""
    return f"(function(){{{script}}}).apply(null, {json.dumps(list(args))})"


def snapshot_from_raw(raw: dict[str, Any]) -> Snapshot:
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
    return Snapshot(
        url=str(raw.get("url", "")),
        title=str(raw.get("title", "")),
        text=str(raw.get("text", "")),
        elements=elements,
        fingerprint=hashlib.sha256(json.dumps(compact, sort_keys=True).encode()).hexdigest(),
    )


def decision_still_valid(
    decided: Snapshot | None, fresh: Snapshot, expected_fingerprint: str, action: dict[str, Any]
) -> bool:
    """Whether an action decided on one snapshot may still run on the page as it is now.

    Pages keep changing (lazy content, ads, timestamps), so instead of demanding an identical page
    we require the same URL and, for element actions, the very same element: same role, label and
    link under the same id. Without the decision snapshot, fall back to an identical page.
    """
    if fresh.fingerprint == expected_fingerprint:
        return True
    if decided is None or decided.fingerprint != expected_fingerprint or fresh.url != decided.url:
        return False
    target = action.get("target_id")
    if not target:
        return True

    def identity(snapshot: Snapshot) -> tuple | None:
        element = next((item for item in snapshot.elements if item.id == target), None)
        return (element.role, element.text, element.href) if element else None

    return identity(decided) is not None and identity(decided) == identity(fresh)
