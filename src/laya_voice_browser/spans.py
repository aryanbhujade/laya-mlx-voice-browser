from __future__ import annotations

import re
from urllib.parse import urlparse

_FILLER = re.compile(r"\b(?:please|thanks|thank you|now|okay|ok|um|uh|and then)\b", re.I)
_PAYLOAD = [
    re.compile(p, re.I)
    for p in (
        r"\b(?:search|look)\s+(?:for|up)\s+",
        r"\bsearch\s+(?:on\s+)?(?:google|duckduckgo|wikipedia|youtube|github|amazon|reddit|the web)\s+for\s+",
        r"\bsearch\s+",
        r"\bgoogle\s+",
        r"\bfind\s+",
        r"\btype\s+(?:in\s+)?",
        r"\benter\s+",
        r"\bwrite\s+",
    )
]
_DESTINATION = re.compile(
    r"\s+(?:in|into|on|inside|to)\s+(?:the\s+)?(?:[\w-]+\s+){0,4}"
    r"(?:box|field|input|bar|form|textarea|search)\b.*$",
    re.I,
)
_DOMAIN = re.compile(
    r"(?:https?://)?(?:[a-z0-9-]+\.)+(?:com|org|net|io|ai|dev|co|edu|gov|app|me|tv|uk|us)"
    r"(?:/[^\s]*)?",
    re.I,
)

_KNOWN_SITES = {
    "google": ("google",),
    "duckduckgo": ("duckduckgo", "duck duck go"),
    "youtube": ("youtube", "you tube"),
    "wikipedia": ("wikipedia",),
    "github": ("github", "git hub", "get hub", "github.com"),
    "reddit": ("reddit",),
    "hacker_news": ("hacker news", "y combinator news"),
}

_COMMAND_PREFIX = re.compile(
    r"^(?:please\s+)?(?:go\s+to|open|visit|search|look\s+up|google|find|click|press|type|enter|"
    r"write|select|choose|scroll|go\s+back|back|go\s+forward|forward|reload|refresh|new\s+tab|"
    r"close\s+(?:this\s+)?tab|switch\s+tabs?|next\s+tab|previous\s+tab)\b",
    re.I,
)

# Openers that precede a command. Connectives ("and then …") are always dropped; polite requests
# ("can you please open …") only in the "polite" speaking style. In the "direct" style they are left
# for the model, so conversation like "could you go back to what you said" rarely triggers anything.
_CONNECTIVES = re.compile(r"^(?:(?:and\s+then|and|then|so|okay|ok|now)\s+)*", re.I)
_POLITE = re.compile(r"^(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|please\s+)", re.I)
# Misrecognitions accepted only right after a navigation verb: "open get up" is GitHub, but
# "how to get up early" is not.
_NAVIGATION_ALIASES = {"github": ("get up",)}
_CONJUNCTION = re.compile(r"\s*,?\s+(?P<conj>and\s+then|then|and)\s+", re.I)
# After a search or typed text, "and" only starts a new command when an unmistakable command
# follows; weak verbs (back, find, visit, enter, select) are usually part of the query.
_STRONG_AFTER_PAYLOAD = re.compile(
    r"^(?:please\s+)?(?:click|tap|scroll|go\s+back|go\s+forward|reload|refresh|"
    r"(?:press|hit)\s+(?:enter|return)|(?:open\s+)?(?:a\s+)?new\s+tab|close\s+(?:this\s+|the\s+)?tab|"
    r"switch\s+tabs?|next\s+tab|previous\s+tab)\b",
    re.I,
)
_OBJECT_VERB = re.compile(
    r"^(?:search(?:\s+\w+)?\s+for|search|look\s+up|google|find|click(?:\s+on)?|tap(?:\s+on)?|press|"
    r"choose|type(?:\s+in)?|enter|write|select|open|go\s+to|visit)\s+",
    re.I,
)
_NEEDS_OBJECT = {"navigate_url", "search_web", "click_element", "type_into_field", "select_option"}
_CLAUSE_PAYLOAD = {"search_web", "type_into_field", "select_option"}
_NORMALIZE = re.compile(r"[^a-z0-9]+")
_NUMBER_WORDS = {
    "one": 1, "first": 1, "two": 2, "second": 2, "three": 3, "third": 3, "four": 4, "fourth": 4,
    "five": 5, "fifth": 5, "six": 6, "sixth": 6, "seven": 7, "seventh": 7, "eight": 8, "eighth": 8,
    "nine": 9, "ninth": 9,
}
_NUMBER_HOMOPHONES = {"won": 1, "to": 2, "too": 2, "for": 4}
_PICK_FILLER = {
    "the", "number", "option", "pick", "choose", "select", "click", "take", "that", "please", "one",
    "link", "item", "result", "with", "on", "this", "um", "uh", "yes", "go",
}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def polite_style() -> bool:
    from .config import load

    return load().speaking_style != "direct"


def strip_lead(text: str, *, polite: bool | None = None) -> str:
    """Drop openers so the rules see the command itself (polite requests only in the polite style)."""
    text = _CONNECTIVES.sub("", clean(text), count=1)
    if polite if polite is not None else polite_style():
        text = _POLITE.sub("", text, count=1)
    return text


def remainder_after(text: str, consumed: str) -> str | None:
    """Text after an already-executed prefix, ignoring case, spacing and punctuation.

    Apple Speech revises partials ("you tube" -> "YouTube."), so an exact prefix test misses.
    """
    target = _NORMALIZE.sub("", consumed.casefold())
    if not target:
        return None
    seen = ""
    for index, char in enumerate(text):
        seen += _NORMALIZE.sub("", char.casefold())
        if seen == target:
            return text[index + 1 :].strip(" ,.;:-")
        if not target.startswith(seen):
            return None
    return None


def spoken_number(text: str, limit: int) -> int | None:
    """A bare pick like "two", "the second one", "number 3"; None when anything else was said."""
    words = [word for word in re.findall(r"[a-z0-9]+", clean(text).casefold())]
    meaningful = [word for word in words if word not in _PICK_FILLER]
    if len(meaningful) == 1:
        word = meaningful[0]
        value = int(word) if word.isdigit() else _NUMBER_WORDS.get(word)
        if value is None and len(words) == 1:
            value = _NUMBER_HOMOPHONES.get(word)
        if value is not None and 1 <= value <= limit:
            return value
    if words in (["one"], ["the", "one"]) and limit >= 1:
        return 1
    return None


def _clause_intent(text: str) -> str | None:
    """Intent of one clause from grammar alone, assuming an unnamed object is on the page."""
    return deterministic_intent(text, element_match=True)


def _clause_complete(text: str, intent: str) -> bool:
    body = strip_lead(text)
    if intent == "navigate_url":
        return bool(mentioned_site(body) or url_candidates(body))
    if intent in _NEEDS_OBJECT:
        rest = _OBJECT_VERB.sub("", body, count=1)
        return rest != body and bool(re.search(r"[a-z0-9]", rest, re.I))
    return True


def _valid_split(left: str, right: str, conjunction: str) -> bool:
    left_intent = _clause_intent(left)
    right_intent = _clause_intent(right)
    if not left_intent or not right_intent or not _clause_complete(right, right_intent):
        return False
    if left_intent in _CLAUSE_PAYLOAD and conjunction.casefold() == "and":
        body = strip_lead(right)
        navigates_somewhere = right_intent == "navigate_url"
        return navigates_somewhere or bool(_STRONG_AFTER_PAYLOAD.search(body))
    return True


def command_chain(transcript: str) -> list[str]:
    """Split at "and"/"then" only where both sides are complete commands on their own.

    "search for guitar tabs and back tracks" stays one search; "type my name and press enter" and
    "go to youtube and search for cats" become two commands.
    """
    text = clean(transcript)
    if not text:
        return []
    parts: list[str] = []
    start = 0
    for match in _CONJUNCTION.finditer(text):
        left = text[start : match.start()]
        right = text[match.end() :]
        if _valid_split(left, right, match.group("conj")):
            parts.append(left)
            start = match.end()
    parts.append(text[start:])
    return [part.strip(" ,.;:-") for part in parts if part.strip(" ,.;:-")]


def command_plan(transcript: str) -> list[str]:
    """Expand common conversational phrasing into an ordered list of browser commands."""
    text = clean(transcript).strip(" ,.;:-")
    text = re.sub(r"^(?:(?:and\s+then|and|then)\s+)?", "", text, flags=re.I)
    if polite_style():
        text = _POLITE.sub("", text, count=1)
        text = re.sub(
            r"\b(and(?:\s+then)?|then)\s+(?:(?:can|could|would|will)\s+you\s+)",
            r"\1 ",
            text,
            flags=re.I,
        )

    new_tab = re.match(
        r"^(?:in\s+)?(?:a\s+)?new\s+tab\s*,?\s+"
        r"(?:(?:can|could|would|will)\s+you\s+)?(.+)$",
        text,
        flags=re.I,
    )
    if new_tab:
        remainder = new_tab.group(1).strip(" ,.;:-")
        return ["open a new tab", *command_chain(remainder)]

    purpose = re.match(
        r"^(?P<open>(?:go\s+to|open|visit)\s+"
        r"(?:google|duck\s*duck\s*go|you\s*tube|wikipedia|git\s*hub|reddit|hacker\s+news))"
        r"\s+to\s+(?:search(?:\s+for)?|find|look\s+for|see)\s+(?P<query>.+)$",
        text,
        flags=re.I,
    )
    if purpose:
        site = mentioned_site(purpose.group("open"))
        query = purpose.group("query").strip(" ,.;:-")
        query = re.sub(
            r"^(?:repos(?:itories)?|videos?|information)\s+(?:for|about|on)\s+",
            "",
            query,
            flags=re.I,
        )
        if site and query:
            return [f"open {site}", f"search {site} for {query}"]

    return command_chain(text)


def _push(items: list[str], value: str) -> None:
    value = _FILLER.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" .,!?\t\n")
    if not value or len(value) > 160:
        return
    if value.casefold() not in {item.casefold() for item in items}:
        items.append(value)


def explicit_payload(transcript: str) -> str | None:
    """The text to search or type when the command states it plainly: "search for enigma machine" →
    "enigma machine". None when the rest also names a place ("…into the search box", "…on YouTube")
    or the command does not start with a text verb; the model then chooses among candidates."""
    text = strip_lead(clean(transcript))
    quoted = re.search(r'["“”\']([^"“”\']{1,160})["“”\']', text)
    if quoted:
        return quoted.group(1).strip() or None
    matches = [match for pattern in _PAYLOAD if (match := pattern.search(text)) and match.start() == 0]
    if not matches:
        return None
    tail = text[max(matches, key=lambda item: len(item.group(0))).end() :]
    if _DESTINATION.search(tail) or mentioned_site(tail) or re.search(r"\b(?:on|in|at)\s+\w+\s*$", tail):
        return None
    candidates: list[str] = []
    _push(candidates, tail)
    return candidates[0] if candidates else None


def text_candidates(transcript: str) -> list[str]:
    text = clean(transcript)
    if not text:
        return []
    result: list[str] = []
    for match in re.finditer(r'["“”\']([^"“”\']{1,160})["“”\']', text):
        _push(result, match.group(1))
    matches = [match for pattern in _PAYLOAD if (match := pattern.search(text))]
    for match in sorted(matches, key=lambda item: (item.start(), -len(item.group(0)))):
        tail = text[match.end() :]
        _push(result, _DESTINATION.sub("", tail))
        _push(result, tail)
    marker = text.casefold().find(" for ")
    if marker >= 0:
        _push(result, _DESTINATION.sub("", text[marker + 5 :]))
    if " " in text:
        _push(result, _DESTINATION.sub("", text.split(" ", 1)[1]))
    _push(result, text)
    return result[:8]


def normalize_spoken_url(text: str) -> str:
    value = clean(text).casefold()
    value = re.sub(r"\bget\s+(?:hub|up)\s*\.?\s*com\b", "github.com", value)
    value = re.sub(r"\s+dot\s+", ".", value)
    value = re.sub(r"\s*\.\s*", ".", value)
    value = re.sub(r"\s+slash\s+", "/", value)
    return value


def url_candidates(transcript: str) -> list[str]:
    result: list[str] = []
    for match in _DOMAIN.finditer(normalize_spoken_url(transcript)):
        value = match.group(0).rstrip(".,!?")
        if value not in result:
            result.append(value)
    return result[:6]


def as_https(value: str) -> str:
    value = value.strip()
    candidate = value if "://" in value else f"https://{value}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Not a valid HTTP(S) URL")
    return candidate


def mentioned_site(transcript: str) -> str | None:
    value = clean(transcript).casefold()
    for site, names in _KNOWN_SITES.items():
        if any(re.search(rf"\b{re.escape(name)}\b", value) for name in names):
            return site
    for site, names in _NAVIGATION_ALIASES.items():
        for name in names:
            if re.search(rf"\b(?:go\s+to|open|visit)\s+(?:the\s+)?{re.escape(name)}\b", value):
                return site
    return None


def site_for_url(url: str) -> str | None:
    """Return a supported site's search scope for a page already open there."""
    hostname = (urlparse(url).hostname or "").casefold()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    for site, suffixes in {
        "google": ("google.com",),
        "duckduckgo": ("duckduckgo.com",),
        "youtube": ("youtube.com", "youtu.be"),
        "wikipedia": ("wikipedia.org",),
        "github": ("github.com",),
        "reddit": ("reddit.com",),
        "hacker_news": ("news.ycombinator.com",),
    }.items():
        if any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in suffixes):
            return site
    return None


def explicit_browser_command(transcript: str) -> bool:
    return bool(_COMMAND_PREFIX.search(strip_lead(transcript)))


def deterministic_intent(transcript: str, *, element_match: bool = False) -> str | None:
    """Intent from explicit grammar; `element_match` means a visible element label shares a word."""
    value = strip_lead(transcript).casefold()
    if re.search(r"^(?:please\s+)?(?:go\s+to|open|visit)\b", value) and not re.search(
        r"\bnew\s+tab\b", value
    ):
        # "open wikipedia" names a site; "open the talk page" names something on the page.
        if mentioned_site(value) or url_candidates(value):
            # "open the wikipedia result" names a site but points at something on this page.
            if element_match and re.search(r"\b(?:result|link|article|button)\b", value):
                return "click_element"
            return "navigate_url"
        return "click_element" if element_match else None
    patterns = (
        (r"^(?:please\s+)?(?:open\s+a\s+new\s+tab|new\s+tab)\b", "open_new_tab"),
        (r"^(?:please\s+)?close\s+(?:this\s+)?tab\b", "close_tab"),
        (r"^(?:please\s+)?(?:switch\s+tabs?|next\s+tab|previous\s+tab)\b", "switch_tab"),
        (r"^(?:please\s+)?press\s+(?:enter|return)\b", "press_enter"),
        (r"^(?:please\s+)?(?:search|look\s+up|google|find)\b", "search_web"),
        (r"^(?:please\s+)?(?:click|press|choose)\b", "click_element"),
        (r"^(?:please\s+)?(?:type|enter|write)\b", "type_into_field"),
        (r"^(?:please\s+)?select\b", "select_option"),
        (r"^(?:please\s+)?scroll\s+(?:down|to\s+the\s+bottom)\b", "scroll_down"),
        (r"^(?:please\s+)?scroll\s+(?:up|back\s+to\s+the\s+top)\b", "scroll_up"),
        (r"^(?:please\s+)?(?:go\s+back|back)\b", "go_back"),
        (r"^(?:please\s+)?(?:go\s+forward|forward)\b", "go_forward"),
        (r"^(?:please\s+)?(?:reload|refresh)\b", "reload"),
    )
    for pattern, intent in patterns:
        if re.search(pattern, value):
            return intent
    return None


def spoken_scroll_amount(transcript: str, direction: str) -> str | None:
    value = clean(transcript).casefold()
    if re.search(r"\b(?:bottom|end|top)\b", value):
        return "end" if direction == "down" else "top"
    if re.search(r"\b(?:bit|little|slightly)\b", value):
        return "little"
    if re.search(r"\bpage\b", value):
        return "page"
    return None


def spoken_tab_direction(transcript: str) -> str | None:
    value = clean(transcript).casefold()
    for direction, pattern in (
        ("previous", r"\b(?:previous|last|prior)\s+tab\b"),
        ("first", r"\bfirst\s+tab\b"),
        ("next", r"\b(?:next|another|other)\s+tab\b|\bswitch\s+tabs?\b"),
    ):
        if re.search(pattern, value):
            return direction
    return None
