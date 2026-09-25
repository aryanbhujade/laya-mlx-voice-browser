# ruff: noqa: E501
"""Page-side JavaScript shared by every browser backend, and turning its result into a Snapshot."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .types import Element, Snapshot, Tab

SNAPSHOT_JS = r"""
const destructive = /\b(buy|purchase|pay|place order|delete|remove|send|submit|publish|confirm|sign in|log in)\b/i;
const selectors = [
  'a[href]', 'button', 'input:not([type="hidden"]):not([type="password"]):not([type="file"])', 'textarea', 'select',
  '[role="button"]', '[role="link"]', '[role="tab"]', '[role="option"]',
  '[contenteditable="true"]', '[role="searchbox"]', '[role="combobox"]'
].join(',');
const visible = (el) => {
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width >= 4 && r.height >= 4 && r.bottom > 0 && r.right > 0 &&
    r.top < innerHeight && r.left < innerWidth && s.visibility !== 'hidden' && s.display !== 'none';
};
const label = (el) => (el.getAttribute('aria-label') || el.innerText || el.value ||
  el.placeholder || el.title || el.name || '').replace(/\s+/g, ' ').trim().slice(0, 100);
// Stable node identities survive re-observation; never reuse an index for a replacement node.
const registry = window.__layaNodes ||= {ids: new WeakMap(), next: 0};
const elements = [...document.querySelectorAll(selectors)]
  .filter((el) => !['password', 'file'].includes(el.type) && visible(el)).map((el) => {
  let id = registry.ids.get(el);
  if (!id) { id = `e${String(++registry.next).padStart(2, '0')}`; registry.ids.set(el, id); }
  el.setAttribute('data-laya-id', id);
  const text = label(el);
  return {
    id,
    role: el.getAttribute('role') || ({A:'link',BUTTON:'button',INPUT:'input',TEXTAREA:'textbox',SELECT:'select'}[el.tagName] || el.tagName.toLowerCase()),
    tag: el.tagName.toLowerCase(), text, placeholder: el.placeholder || '',
    value: el.type === 'password' ? '' : (el.value || ''),
    input_type: el.type || '', disabled: Boolean(el.disabled || el.closest('[inert]') || el.getAttribute('aria-disabled') === 'true'),
    readonly: Boolean(el.readOnly),
    checked: ['checkbox', 'radio'].includes(el.type) ? el.checked : null,
    expanded: el.hasAttribute('aria-expanded') ? el.getAttribute('aria-expanded') === 'true' : null,
    href: el.href ? new URL(el.href, location.href).href.slice(0, 180) : '',
    destructive_hint: destructive.test(text),
    in_main: Boolean(el.closest('main,[role="main"],article')),
    top: Math.round(el.getBoundingClientRect().top)
  };
}).slice(0, arguments[0]);
// Read-only capability evidence, from trusted local pack selectors. DOM content is data, not policy.
const pack = (arguments[1] || []).find((p) => p.hosts.some((h) => location.hostname === h || location.hostname.endsWith('.' + h)));
let browsing = {};
if (pack) {
  const rendered = (el) => el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  const resultLinks = [...document.querySelectorAll(pack.result_selector)].filter(rendered);
  const results = [], seen = new Set();
  for (const el of resultLinks) {
    const card = pack.result_card_selector ? el.closest(pack.result_card_selector) : null;
    const cardTitle = card && pack.result_title_selector ? card.querySelector(pack.result_title_selector) : null;
    const href = el.href, title = (cardTitle ? label(cardTitle) : '') || label(el) || label(el.closest('ytd-video-renderer, yt-lockup-view-model') || el);
    if (href && title && !seen.has(href)) { results.push({url: href, title}); seen.add(href); }
    if (results.length >= 30) break;
  }
  const heading = [...document.querySelectorAll(pack.heading_selector)].find(rendered);
  const navigation = (pack.navigation || []).flatMap((control) =>
    [...document.querySelectorAll(control.selector)].filter(el => rendered(el) && el.href && el.getAttribute('aria-disabled') !== 'true')
      .map(el => ({title: control.label, url: el.href})));
  browsing = {site: pack.site, heading: heading ? heading.textContent.trim().slice(0, 200) : '', results, navigation,
    results_ready: [...document.querySelectorAll(pack.results_selector)].some(rendered),
    detail_ready: [...document.querySelectorAll(pack.detail_selector)].some(rendered)};
  if (pack.media_controls) {
    const media = [...document.querySelectorAll('video, audio')]
      .filter((el) => el.getClientRects().length)
      .sort((a, b) => Number(a.paused) - Number(b.paused))[0];
    const shorts = location.pathname.startsWith('/shorts/');
    const comments = document.querySelector('ytd-comments#comments, ytd-comments');
    const commentRect = comments?.getBoundingClientRect();
    const panel = document.querySelector(
      'ytd-engagement-panel-section-list-renderer[target-id="engagement-panel-comments-section"]');
    browsing.media = {present: Boolean(media), paused: media ? Boolean(media.paused) : null,
      muted: media ? Boolean(media.muted) : null};
    browsing.comments_visible = Boolean(
      (!shorts && commentRect && commentRect.width > 0 &&
       commentRect.top < innerHeight && commentRect.bottom > 0)
      || (shorts && panel && panel.getClientRects().length &&
          panel.getAttribute('visibility') === 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED'));
  }
}
return {
  url: location.href,
  title: document.title,
  document_id: String(performance.timeOrigin), scroll_y: scrollY,
  can_scroll_down: scrollY + innerHeight < document.documentElement.scrollHeight - 4,
  text: (document.body?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 5000),
  elements, browsing
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


# Controls the page's main video or audio: the one playing, otherwise the largest on screen. On
# YouTube it presses YouTube's own buttons where they exist, so the player's controls stay in sync.
MEDIA_JS = r"""
const [command, amount] = arguments;
const youtube = /(^|\.)youtube\.com$/.test(location.hostname);
const shorts = youtube && location.pathname.startsWith('/shorts');
// Buttons are not clicked here: they are tagged, and the browser presses them with a real click,
// which players such as YouTube require before they will start.
let press = false;
document.querySelectorAll('[data-laya-press]').forEach((el) => el.removeAttribute('data-laya-press'));
const tag = (...selectors) => {
  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el && el.getClientRects().length) { el.setAttribute('data-laya-press', '1'); press = true; return true; }
  }
  return false;
};
const done = (result) => (result ? {result, press} : null);
const area = (m) => { const r = m.getBoundingClientRect(); return Math.max(0, r.width) * Math.max(0, r.height); };
// Every player counts (a video may not have started loading): playing first, then loaded, then largest.
const players = [...document.querySelectorAll('video, audio')];
const loaded = (m) => (m.currentSrc || m.src ? 1 : 0);
players.sort((a, b) => (a.paused - b.paused) || (loaded(b) - loaded(a)) || (area(b) - area(a)));
const m = players[0];
if (command === 'skip_ad') {
  return done(tag('.ytp-skip-ad-button', '.ytp-ad-skip-button-modern', '.ytp-ad-skip-button') && 'skipped the ad');
}
if (command === 'next' || command === 'previous') {
  const down = command === 'next';
  if (shorts && tag(down ? 'button[aria-label="Next video"]' : 'button[aria-label="Previous video"]',
                    down ? '#navigation-button-down button' : '#navigation-button-up button')) {
    return done(down ? 'next short' : 'previous short');
  }
  if (youtube && down && tag('.ytp-next-button', 'ytd-compact-video-renderer a#thumbnail',
                             'yt-lockup-view-model a', '#related a#thumbnail')) return done('next video');
  if (youtube && !down && tag('.ytp-prev-button')) return done('previous video');
  // Feeds (Reddit, X, Instagram…): bring the next video below, or the one above, to the middle.
  const middle = innerHeight / 2;
  const boxes = players.map((p) => [p, p.getBoundingClientRect()]).filter(([, r]) => r.height > 40);
  const pick = down
    ? boxes.filter(([, r]) => r.top > middle).sort((a, b) => a[1].top - b[1].top)[0]
    : boxes.filter(([, r]) => r.bottom < middle).sort((a, b) => b[1].top - a[1].top)[0];
  if (!pick) return null;
  pick[0].scrollIntoView({block: 'center', behavior: 'smooth'});
  return done(down ? 'next video' : 'previous video');
}
if (command === 'comments' && youtube) {
  if (shorts && tag('button[aria-label^="View "][aria-label$=" comments"]',
                    'ytd-reel-video-renderer #comments-button button',
                    'ytd-shorts #comments-button button',
                    'button[aria-label="Comments"]')) return done('comments opened');
  if (shorts) return null;
  const comments = document.querySelector('ytd-comments#comments, ytd-comments, #comments');
  if (comments) { comments.scrollIntoView({block: 'start'}); return done('comments shown'); }
  return null;
}
if (command === 'fullscreen') {
  if (youtube && !document.fullscreenElement && tag('.ytp-fullscreen-button')) return done('full screen');
  if (m && m.requestFullscreen) { m.requestFullscreen(); return done('full screen'); }
  return null;
}
if (command === 'exit_fullscreen') {
  if (document.fullscreenElement) { document.exitFullscreen(); return done('left full screen'); }
  return done('not in full screen');
}
if (command === 'captions_on' || command === 'captions_off') {
  const on = command === 'captions_on';
  const button = document.querySelector('.ytp-subtitles-button');
  if (youtube && button) {
    if ((button.getAttribute('aria-pressed') === 'true') !== on) tag('.ytp-subtitles-button');
    return done(on ? 'captions on' : 'captions off');
  }
  if (!m || !m.textTracks || !m.textTracks.length) return null;
  for (const track of m.textTracks) track.mode = on ? 'showing' : 'hidden';
  return done(on ? 'captions on' : 'captions off');
}
if (!m) return null;
switch (command) {
  case 'pause':
    if (youtube && !m.paused && tag('.ytp-play-button')) return done('paused');
    m.pause(); return done('paused');
  case 'play':
    if (youtube && m.paused && tag('.ytp-large-play-button', '.ytp-play-button')) return done('playing');
    { const p = m.play(); if (p) p.catch(() => {}); } return done('playing');
  case 'mute':
    if (youtube && !m.muted && tag('.ytp-mute-button')) return done('muted');
    m.muted = true; return done('muted');
  case 'unmute':
    if (youtube && m.muted && tag('.ytp-mute-button')) return done('unmuted');
    m.muted = false; if (m.volume === 0) m.volume = 0.5; return done('unmuted');
  case 'volume_up': m.muted = false; m.volume = Math.min(1, m.volume + 0.15); return done('volume up');
  case 'volume_down': m.volume = Math.max(0, m.volume - 0.15); return done('volume down');
  case 'forward': m.currentTime = Math.min(m.duration || Infinity, m.currentTime + (amount || 10)); return done('skipped ahead');
  case 'back': m.currentTime = Math.max(0, m.currentTime - (amount || 10)); return done('rewound');
  case 'faster': m.playbackRate = Math.min(4, m.playbackRate + 0.25); return done('faster');
  case 'slower': m.playbackRate = Math.max(0.25, m.playbackRate - 0.25); return done('slower');
  case 'normal_speed': m.playbackRate = 1; return done('normal speed');
  case 'rate': m.playbackRate = amount; return done('speed set');
}
return null;
"""


# Find a site-pack control by its label (aria-label, title or visible text: exact, or starting with the
# label) or by CSS, and tag it for a real click. Returns {"label", "href"} or null.
SITE_FIND_JS = r"""
const [labels, selectors] = arguments;
document.querySelectorAll('[data-laya-press]').forEach((el) => el.removeAttribute('data-laya-press'));
const visible = (el) => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
const tag = (el, label) => {
  el.setAttribute('data-laya-press', '1');
  return {label, href: el.href || (el.closest('a') && el.closest('a').href) || ''};
};
for (const selector of selectors || []) {
  const el = [...document.querySelectorAll(selector)].find(visible);
  if (el) return tag(el, selector);
}
const wanted = (labels || []).map((label) => label.toLowerCase());
if (!wanted.length) return null;
const candidates = document.querySelectorAll(
  'button, a, [role=button], [role=link], [role=tab], [role=menuitem], [aria-label], [data-tooltip], input[type=submit]');
const name = (el) => (el.getAttribute('aria-label') || el.getAttribute('data-tooltip') || el.title ||
  el.innerText || el.value || '').replace(/\s+/g, ' ').trim().toLowerCase();
for (const label of wanted) {
  for (const exact of [true, false]) {
    for (const el of candidates) {
      if (!visible(el)) continue;
      const text = name(el);
      if (exact ? text === label : text.startsWith(label)) return tag(el, label);
    }
  }
}
return null;
"""

# Focus the first visible field matching the selectors and select its contents, ready for typing.
FOCUS_FIELD_JS = r"""
const el = arguments[0].map((s) => [...document.querySelectorAll(s)].find((e) => e.getClientRects().length))
  .find(Boolean);
if (!el) return false;
el.scrollIntoView({block: 'center'});
el.focus();
if (typeof el.select === 'function') el.select();
return true;
"""

SCROLL_TO_JS = r"""
// Prefer a visible match; otherwise use one that exists but has not rendered yet (YouTube only fills in
// its comments once they are scrolled towards).
const all = arguments[0].flatMap((s) => [...document.querySelectorAll(s)]);
const el = all.find((e) => e.getClientRects().length) || all[0];
if (!el) return false;
el.scrollIntoView({block: 'start', behavior: 'smooth'});
return true;
"""

_KEY_NAMES = {
    "enter": ("Enter", "Enter", 13, "\r"),
    "escape": ("Escape", "Escape", 27, ""),
    "space": (" ", "Space", 32, " "),
    "tab": ("Tab", "Tab", 9, ""),
    "left": ("ArrowLeft", "ArrowLeft", 37, ""),
    "up": ("ArrowUp", "ArrowUp", 38, ""),
    "right": ("ArrowRight", "ArrowRight", 39, ""),
    "down": ("ArrowDown", "ArrowDown", 40, ""),
    "/": ("/", "Slash", 191, "/"),
    ".": (".", "Period", 190, "."),
    ",": (",", "Comma", 188, ","),
}
_MODIFIER_BITS = {
    "alt": 1,
    "option": 1,
    "ctrl": 2,
    "control": 2,
    "meta": 4,
    "cmd": 4,
    "command": 4,
    "shift": 8,
}


def parse_keys(spec: str) -> tuple[list[str], dict[str, Any]]:
    """ "shift+n" → (["shift"], {"key": "N", "code": "KeyN", "vk": 78, "text": "N"}) for key events."""
    parts = [part.strip().casefold() for part in spec.split("+") if part.strip()]
    modifiers, key = parts[:-1], parts[-1]
    if key in _KEY_NAMES:
        name, code, vk, text = _KEY_NAMES[key]
    elif len(key) == 1 and key.isalnum():
        char = key.upper() if "shift" in modifiers else key
        name, code, vk, text = (
            char,
            (f"Key{key.upper()}" if key.isalpha() else f"Digit{key}"),
            ord(key.upper()),
            char,
        )
    else:
        raise ValueError(f"unsupported key: {spec}")
    return modifiers, {
        "key": name,
        "code": code,
        "vk": vk,
        "text": text,
        "bits": sum(_MODIFIER_BITS[m] for m in modifiers),
    }


def call_script(script: str, *args: Any) -> str:
    """Wrap a script that reads `arguments` so it can run as a plain expression (CDP, extensions)."""
    return f"(function(){{{script}}}).apply(null, {json.dumps(list(args))})"


def snapshot_from_raw(raw: dict[str, Any], *, tabs: tuple[Tab, ...] = ()) -> Snapshot:
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
            input_type=str(item.get("input_type", "")),
            disabled=bool(item.get("disabled", False)),
            readonly=bool(item.get("readonly", False)),
            checked=item.get("checked"),
            expanded=item.get("expanded"),
        )
        for item in raw.get("elements", [])
        if item.get("id")
    )
    compact = {
        "url": raw.get("url", ""),
        "title": raw.get("title", ""),
        "elements": [vars(element) for element in elements],
        "document_id": raw.get("document_id", ""),
        "scroll_y": raw.get("scroll_y", 0),
        "tabs": [vars(tab) for tab in tabs],
        "browsing": raw.get("browsing", {}),
    }
    return Snapshot(
        url=str(raw.get("url", "")),
        title=str(raw.get("title", "")),
        text=str(raw.get("text", "")),
        elements=elements,
        fingerprint=hashlib.sha256(json.dumps(compact, sort_keys=True).encode()).hexdigest(),
        tabs=tabs,
        document_id=str(raw.get("document_id", "")),
        scroll_y=float(raw.get("scroll_y", 0)),
        can_scroll_down=bool(raw.get("can_scroll_down", False)),
        browsing=dict(raw.get("browsing") or {}),
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
    if fresh.document_id != decided.document_id or fresh.tabs != decided.tabs:
        return False
    target = action.get("target_id")
    if not target:
        return True

    def identity(snapshot: Snapshot) -> tuple | None:
        element = next((item for item in snapshot.elements if item.id == target), None)
        return (element.role, element.text, element.href, element.value, element.disabled,
                element.readonly, element.checked, element.expanded) if element else None

    return identity(decided) is not None and identity(decided) == identity(fresh)
