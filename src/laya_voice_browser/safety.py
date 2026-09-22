"""Browser-independent rules for actions that must be confirmed before they run."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .types import Element, Snapshot

_DESTRUCTIVE_LABEL = re.compile(
    r"\b(?:buy|purchase|pay|place order|checkout|check out|delete|remove|send|submit|publish|"
    r"sign in|log in|sign out|log out|logout|unsubscribe|deactivate|transfer|cancel subscription)\b",
    re.I,
)
# Plain-looking links that still change an account: votes, hides, follows, logouts.
_SIDE_EFFECT_LABEL = re.compile(
    r"\b(?:upvote|downvote|vote|hide|flag|report|like|unlike|follow|unfollow|subscribe|mute|block|"
    r"archive|star|unstar|save|bookmark)\b",
    re.I,
)
_SIDE_EFFECT_URL = re.compile(
    r"(?:^|[/?&=_.-])(?:vote|upvote|downvote|hide|flag|report|delete|remove|logout|log_out|log-out|"
    r"signout|sign_out|sign-out|unsubscribe|subscribe|follow|unfollow|like|mute|block|archive|star)"
    r"(?:$|[/?&=_.-])",
    re.I,
)


def _target(action: dict[str, Any], snapshot: Snapshot) -> Element | None:
    return next((item for item in snapshot.elements if item.id == action.get("target_id")), None)


def side_effect_link(element: Element) -> bool:
    # Only short labels are controls ("hide", "upvote"); "Stories you might like" is just a link.
    if len(element.text.split()) <= 3 and _SIDE_EFFECT_LABEL.search(element.text):
        return True
    parsed = urlparse(element.href)
    return bool(_SIDE_EFFECT_URL.search(f"{parsed.path}?{parsed.query}"))


def ordinary_navigation_link(action: dict[str, Any], snapshot: Snapshot) -> bool:
    """A click on a link that only navigates, so the model's destructive guess can be skipped."""
    if action.get("type") != "click":
        return False
    target = _target(action, snapshot)
    return bool(
        target
        and target.href
        and not target.destructive_hint
        and not _DESTRUCTIVE_LABEL.search(target.text)
        and not side_effect_link(target)
    )


def deterministic_destructive(action: dict[str, Any], snapshot: Snapshot) -> bool:
    if action.get("type") not in {"click", "press_enter", "select"}:
        return False
    target = _target(action, snapshot)
    if target is None:
        return False
    return (
        target.destructive_hint
        or bool(_DESTRUCTIVE_LABEL.search(target.text))
        or (bool(target.href) and side_effect_link(target))
    )
