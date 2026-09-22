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
    "amazon": ("amazon.com",),
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
# Site names that are ordinary words too. They name the site only after a navigation or shopping
# phrase, with no article and no geography behind them: "buy batteries on amazon" is the shop,
# while "the amazon", "search for the amazon river" and "amazon rainforest" are the place.
_AMBIGUOUS_SITES = {"amazon": ("amazon",)}
_SITE_LEAD = r"(?:go\s+to|open|visit|browse|shop\s+on|search|order\s+from|buy\s+from|on|at|from)"
_NOT_THE_SITE_AFTER = r"(?:rain\s*forest|river|basin|jungle|delta|region|tribes?|reefs?|prime\s+day)"
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


_SITE_NAMES = "|".join(
    re.escape(name)
    for names in (*_KNOWN_SITES.values(), *_AMBIGUOUS_SITES.values())
    for name in sorted(names, key=len, reverse=True)
)
# "search for cats on YouTube" says where to search, not what to search for.
_SITE_SCOPE = re.compile(rf"\s+(?:on|in|at|from|over\s+on|using)\s+(?:the\s+)?(?:{_SITE_NAMES})\s*$", re.I)
# A leading "on GitHub, …" is an opener naming where, not part of the command.
_SITE_OPENER = re.compile(rf"^(?:on|in|at|over\s+on|using)\s+(?:the\s+)?(?:{_SITE_NAMES})\s*,?\s+", re.I)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


# Apple Speech hears "GitHub" as "get up" often enough to matter, and it even revises a correct
# partial into the wrong one. Repair it only where a site name belongs, so "how to get up early" and
# "i need to get up" are untouched. _SITE_LEAD is the same navigation/scoping context used for
# ambiguous site names below.
_MISHEARD_DOMAIN = re.compile(r"\bget\s*up(?=\s*(?:\.|\s+dot\s+)\s*com\b)", re.I)
_MISHEARD_SITE = re.compile(
    r"\b(go\s+to|open|visit|browse|search|on|at|from|in)\s+get\s+up\b"
    r"(?!\s+(?:early|earlier|late|now|and\s+go))",
    re.I,
)


def repair_speech(transcript: str) -> str:
    """Undo recognizer mishearings that only matter where a site name belongs."""
    text = _MISHEARD_DOMAIN.sub("github", clean(transcript))
    return _MISHEARD_SITE.sub(lambda found: f"{found.group(1)} GitHub", text)


def polite_style() -> bool:
    from .config import load

    return load().speaking_style != "direct"


def strip_lead(text: str, *, polite: bool | None = None) -> str:
    """Drop openers so the rules see the command itself (polite requests only in the polite style)."""
    text = _CONNECTIVES.sub("", clean(text), count=1)
    if polite if polite is not None else polite_style():
        text = _POLITE.sub("", text, count=1)
    # "On GitHub, search for X" names where, then the command. mentioned_site still sees the site in
    # the full transcript, so dropping the opener scopes the search rather than losing it.
    text = _SITE_OPENER.sub("", text, count=1)
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

    trailing_new_tab = re.match(r"^(?P<command>.+?)\s+in\s+(?:a\s+)?new\s+tab$", text, flags=re.I)
    if trailing_new_tab:
        # "open youtube in a new tab" → open a tab, then open YouTube there.
        return ["open a new tab", *command_chain(trailing_new_tab.group("command"))]

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
        r"(?:google|duck\s*duck\s*go|you\s*tube|wikipedia|git\s*hub|amazon|reddit|hacker\s+news))"
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




def strip_site_scope(text: str) -> str:
    """Drop a trailing "on <site>" so it does not end up inside the search query."""
    return _SITE_SCOPE.sub("", clean(text)).strip(" ,.;:-")


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
    scoped = strip_site_scope(tail)
    if scoped != tail and scoped:
        return scoped  # "…on YouTube" named the place; the rest is the query
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
    """Spoken addresses written out ("example dot com slash Page" → "example.com/Page"). Case is kept:
    paths and queries are case-sensitive (a YouTube video id); `as_https` lowercases only the host."""
    value = clean(text)
    value = re.sub(r"\bget\s+(?:hub|up)\s*\.?\s*com\b", "github.com", value, flags=re.I)
    value = re.sub(r"\s+dot\s+", ".", value, flags=re.I)
    value = re.sub(r"\s*\.\s*", ".", value)
    value = re.sub(r"\s+slash\s+", "/", value, flags=re.I)
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
    return parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower()).geturl()


def mentioned_site(transcript: str) -> str | None:
    value = clean(transcript).casefold()
    for site, names in _KNOWN_SITES.items():
        if any(re.search(rf"\b{re.escape(name)}\b", value) for name in names):
            return site
    for site, names in _NAVIGATION_ALIASES.items():
        for name in names:
            if re.search(rf"\b(?:go\s+to|open|visit)\s+(?:the\s+)?{re.escape(name)}\b", value):
                return site
    for site, names in _AMBIGUOUS_SITES.items():
        for name in names:
            pattern = rf"\b{_SITE_LEAD}\s+{re.escape(name)}\b(?!\s+{_NOT_THE_SITE_AFTER}\b)"
            if re.search(pattern, value):
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
        "amazon": ("amazon.com", "amazon.co.uk", "amazon.in", "amazon.ca", "amazon.com.au"),
        "reddit": ("reddit.com",),
        "hacker_news": ("news.ycombinator.com",),
    }.items():
        if any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in suffixes):
            return site
    return None


# Browser commands whose meaning no website may redefine: "go back" is browser history, never
# Google's previous page of results, and "scroll down" is never "jump to the comments". The whole
# utterance must be the command — "forward this email" names Gmail's control, not history — and a
# pack may still *implement* an intent better than the generic path, as Spotify does for "pause".
_UNIVERSAL_PHRASE = re.compile(
    r"^(?:go\s+)?(?:back|forward)$|"
    r"^(?:reload|refresh)(?:\s+(?:this|the)?\s*page)?$|"
    r"^(?:open\s+)?(?:a\s+)?new\s+tab$|"
    r"^close\s+(?:this|the)?\s*tab$|"
    r"^(?:switch\s+tabs?|next\s+tab|previous\s+tab|last\s+tab)$|"
    r"^scroll\s+(?:up|down)(?:\s+(?:a\s+)?(?:little|bit|lot|more|again|even\s+more))*$",
    re.I,
)
# "please" and "for me" are not part of the command, and neither is a trailing "thanks".
_TRAILING_COURTESY = re.compile(r"(?:,?\s*(?:please|thanks|thank\s+you|for\s+me|now))+$", re.I)


def universal_command(transcript: str) -> bool:
    """Whether the whole utterance is a browser command a site pack must not override."""
    # Politeness is stripped whatever the speaking style: this decides *which* command the words
    # name, not whether to obey it, and the command gate still judges that.
    phrase = strip_lead(clean(transcript), polite=True).strip(" .,!?")
    phrase = _TRAILING_COURTESY.sub("", phrase).strip(" .,!?")
    return bool(_UNIVERSAL_PHRASE.match(phrase))


def explicit_browser_command(transcript: str) -> bool:
    return bool(_COMMAND_PREFIX.search(strip_lead(transcript)))


def deterministic_intent(transcript: str, *, element_match: bool = False) -> str | None:
    """Intent from explicit grammar; `element_match` means a visible element label shares a word."""
    # "Can you scroll down more" is a command in either speaking style: the whole utterance is a
    # universal control, and every one of them is harmless and reversible. The direct style exists
    # for conversation like "could you go back to what you said", which is not one of these.
    value = strip_lead(transcript, polite=True if universal_command(transcript) else None).casefold()
    if media_command(value):
        return "media"
    tabs = tab_command(value)
    if tabs:
        # "go to the YouTube tab" is about a tab, not about opening YouTube.
        return "switch_tab" if tabs["kind"] == "switch_tab" else "close_tab"
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
        ("previous", r"\b(?:previous|prior)\s+tab\b"),
        ("first", r"\bfirst\s+tab\b"),
        ("last", r"\blast\s+tab\b"),
        ("next", r"\b(?:next|another|other)\s+tab\b|\bswitch\s+tabs?\b"),
    ):
        if re.search(pattern, value):
            return direction
    return None


_MEDIA_NOUN = (
    r"(?:\s+(?:the|this|that|it|my))?"
    r"(?:\s+(?:video|song|music|audio|sound|clip|player|tab|track|podcast|stream))?"
)
_SECONDS = (
    r"(?P<amount>\d+|a|one|two|three|four|five|six|seven|eight|nine|ten"
    r"|fifteen|twenty|thirty|forty|fifty|sixty)"
)
_SECOND_WORDS = {
    "a": 1, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
}
_TIME = _SECONDS + r"\s+(?P<unit>seconds?|minutes?)$"
_VOLUME = r"(?:it|the\s+volume|the\s+sound)"
_MEDIA_PATTERNS = (
    (rf"^(?:pause|hold){_MEDIA_NOUN}$", "pause"),
    (rf"^(?:play|resume|unpause|continue){_MEDIA_NOUN}(?:\s+playing)?$", "play"),
    (rf"^un-?mute{_MEDIA_NOUN}$|^turn\s+(?:the\s+)?sound\s+(?:back\s+)?on$", "unmute"),
    (rf"^mute{_MEDIA_NOUN}$|^turn\s+(?:the\s+)?sound\s+off$", "mute"),
    (rf"^(?:turn\s+{_VOLUME}\s+up|volume\s+up|louder|increase\s+(?:the\s+)?volume)$", "volume_up"),
    (
        rf"^(?:turn\s+{_VOLUME}\s+down|volume\s+down|quieter"
        r"|(?:lower|decrease)\s+(?:the\s+)?volume)$",
        "volume_down",
    ),
    (r"^(?:skip|jump|go|fast)\s+(?:ahead|forward)(?:\s+by)?\s+" + _TIME, "forward"),
    (r"^(?:skip\s+ahead|fast\s+forward)$", "forward"),
    (r"^(?:rewind|go\s+back|jump\s+back|skip\s+back)(?:\s+by)?\s+" + _TIME, "back"),
    (r"^rewind$", "back"),
    (r"^(?:speed\s+(?:it\s+)?up|play\s+faster|faster)$", "faster"),
    (r"^(?:slow\s+(?:it\s+)?down|play\s+slower|slower)$", "slower"),
    (r"^(?:normal\s+speed|reset\s+(?:the\s+)?speed|play\s+at\s+normal\s+speed)$", "normal_speed"),
    (
        r"^(?:play\s+at|set\s+(?:the\s+)?speed\s+to)\s+(?P<rate>\d+(?:\.\d+)?)\s*(?:x|times)?"
        r"(?:\s+speed)?$",
        "rate",
    ),
    (r"^(?:exit|leave|close)\s+full\s*screen$", "exit_fullscreen"),
    (r"^(?:(?:go|make\s+it|switch\s+to)\s+)?full\s*screen$", "fullscreen"),
    (
        r"^(?:turn\s+on|show|enable)\s+(?:the\s+)?(?:captions|subtitles)$|^(?:captions|subtitles)\s+on$",
        "captions_on",
    ),
    (
        r"^(?:turn\s+off|hide|disable)\s+(?:the\s+)?(?:captions|subtitles)$"
        r"|^(?:captions|subtitles)\s+off$",
        "captions_off",
    ),
    (
        r"^(?:(?:scroll|go|skip|move)\s+(?:down\s+)?to\s+the\s+)?next\s+(?:video|short|song|clip|one)$"
        r"|^skip\s+(?:this|the)\s+(?:video|song)$",
        "next",
    ),
    (r"^skip\s+(?:(?:this|the)\s+)?ads?$", "skip_ad"),
    (
        r"^(?:(?:scroll|go|move)\s+(?:up\s+)?(?:back\s+)?to\s+the\s+)?previous\s+"
        r"(?:video|short|song|clip|one)$|^last\s+video$",
        "previous",
    ),
)
# Commands that nothing said afterwards can change, so they may run while the phrase continues.
INSTANT_MEDIA = {"pause", "play", "mute", "unmute"}


def media_command(transcript: str) -> dict | None:
    """Video and audio control: {"command": "pause" | "mute" | "forward" | …, "amount": seconds or rate}."""
    value = strip_lead(transcript).casefold().strip(" .!?")
    for pattern, command in _MEDIA_PATTERNS:
        match = re.match(pattern, value)
        if not match:
            continue
        result: dict = {"command": command}
        groups = match.groupdict()
        if command in {"forward", "back"}:
            word = groups.get("amount") or "10"
            amount = int(word) if word.isdigit() else _SECOND_WORDS.get(word) or _NUMBER_WORDS.get(word, 10)
            result["amount"] = amount * (60 if (groups.get("unit") or "").startswith("minute") else 1)
        if command == "rate":
            result["amount"] = min(4.0, max(0.25, float(groups["rate"])))
        return result
    return None


_TAB_CLOSE = re.compile(r"^(?:close|shut|kill|get\s+rid\s+of|remove)\b")
_TAB_SWITCH = re.compile(r"^(?:switch|go|move|jump|change|show|open|take\s+me|bring\s+up|select|pick|use)\b")
_TAB_POSITION = re.compile(
    r"\btab\s+(?:number\s+)?(?P<number>\d+|one|two|three|four|five|six|seven|eight|nine)\b"
    r"|\b(?P<ordinal>first|second|third|fourth|fifth|sixth|seventh|eighth|ninth)\s+tab\b"
)
_TAB_NAME_STOP = {
    "close", "shut", "kill", "get", "rid", "remove", "switch", "go", "move", "jump", "change", "show", "open",
    "take", "me", "bring", "up", "select", "pick", "use", "to", "the", "a", "tab", "tabs", "of", "with",
    "that", "which", "has", "is", "on", "for", "called", "named", "one", "back", "over", "please", "about",
}


def tab_command(transcript: str) -> dict | None:
    """A command about browser tabs: {"kind": "switch_tab" | "close_tab" | "close_other_tabs", plus one of
    "index" (1-based), "direction" (next/previous/first/last) or "name" (words to match titles)}."""
    value = strip_lead(transcript).casefold().strip(" .!?")
    if not re.search(r"\btabs?\b", value) or re.search(r"\bnew\s+tab\b", value):
        return None
    closing = bool(_TAB_CLOSE.search(value))
    others = r"\b(?:all\s+(?:the\s+)?)?other\s+tabs\b|\ball\s+(?:the\s+)?other\b|\bevery\s+other\s+tab\b"
    if closing and re.search(others, value):
        return {"kind": "close_other_tabs"}
    reference: dict = {}
    position = _TAB_POSITION.search(value)
    direction = spoken_tab_direction(value)
    if position:
        word = position.group("number") or position.group("ordinal")
        reference["index"] = int(word) if word.isdigit() else _NUMBER_WORDS[word]
    elif re.search(r"\b(?:this|current)\s+tab\b", value):
        reference["current"] = True
    elif direction:
        reference["direction"] = direction
    else:
        words = [word for word in re.findall(r"[a-z0-9]+", value) if word not in _TAB_NAME_STOP]
        if words:
            reference["name"] = " ".join(words)
    verbless = re.match(
        r"^(?:the\s+)?(?:(?:next|previous|first|last|\w+)\s+tab|tab\s+(?:number\s+)?\w+)$", value
    )
    if closing:
        return {"kind": "close_tab", **reference}
    if _TAB_SWITCH.search(value) or verbless or reference.get("direction"):
        return {"kind": "switch_tab", **reference} if reference else None
    return None
