"""Site packs: what a website can do, described so LayaBrowse can operate it.

Each `*.json` file in this folder describes one site:

    {
      "name": "YouTube",
      "hosts": ["youtube.com"],
      "actions": [
        {
          "id": "theater",
          "description": "switch to theater mode",        # what Laya chooses between
          "say": ["theater mode", "(make it|go) wide"],   # instant rule phrases (full match, regex)
          "terms": ["make the video bigger"],              # natural examples for ranking / exact match
          "do": {"key": "t"},                             # how to do it (see below)
          "confirm": false,                               # true: always say "confirm" first
          "side_effect": false,                           # true: confirm when Laya (not a phrase) chose it
          "instant": false,                               # true: may run before the phrase ends
          "paths": ["^/watch"]                            # only on these URL paths; omit if
                                                          # the control exists site-wide
        }
      ]
    }

"do" is one of:
    {"key": "shift+n"}                                     press keys
    {"click": ["Like", "I like this"]}                     click the visible element with that label
    {"click_css": ["#pnnext", "a#next"]}                   click the first visible match
    {"fill": ["input[name=q]"], "submit": true}            type the phrase's <text> into a field
    {"open": "https://mail.google.com/mail/u/0/#sent"}     go to a URL; "{1}", "{2}" are the current
                                                           path's segments (e.g. a GitHub owner/repo)
    {"scroll_to": ["#comments"]}                           scroll the first visible match into view
    {"media": "next"}                                      a media command (see page.MEDIA_JS)

Phrases may capture free text as (?P<text>...), used by "fill" and "open" ("{text}").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse


@dataclass(frozen=True)
class SiteAction:
    site: str
    id: str
    description: str
    do: dict[str, Any]
    say: tuple[re.Pattern, ...] = ()
    terms: tuple[str, ...] = ()
    confirm: bool = False
    instant: bool = False
    side_effect: bool = False
    # Paths this control exists on. A player control is meaningless on a page with no player, so
    # "scroll down" on a list of search results is an ordinary scroll, not "jump to the comments".
    paths: tuple[re.Pattern, ...] = ()

    def on_page(self, url: str) -> bool:
        if not self.paths:
            return True
        path = urlparse(url).path or "/"
        return any(pattern.search(path) for pattern in self.paths)


@dataclass(frozen=True)
class SitePack:
    name: str
    hosts: tuple[str, ...]
    actions: tuple[SiteAction, ...] = field(default_factory=tuple)

    def serves(self, host: str) -> bool:
        return any(host == known or host.endswith("." + known) for known in self.hosts)

    def available(self, url: str) -> tuple[SiteAction, ...]:
        """The controls this page actually has."""
        return tuple(action for action in self.actions if action.on_page(url))


@lru_cache(maxsize=1)
def packs() -> tuple[SitePack, ...]:
    loaded = []
    for path in sorted(Path(__file__).parent.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        action_ids = [str(item["id"]) for item in raw["actions"]]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError(f"duplicate action id in {path.name}")
        actions = tuple(
            SiteAction(
                site=raw["name"],
                id=item["id"],
                description=item["description"],
                do=item["do"],
                say=tuple(re.compile(rf"^(?:{phrase})$", re.I) for phrase in item.get("say", [])),
                terms=tuple(str(term) for term in item.get("terms", [])),
                confirm=bool(item.get("confirm")),
                instant=bool(item.get("instant")),
                side_effect=bool(item.get("side_effect")),
                paths=tuple(re.compile(pattern) for pattern in item.get("paths", [])),
            )
            for item in raw["actions"]
        )
        loaded.append(SitePack(raw["name"], tuple(raw["hosts"]), actions))
    return tuple(loaded)


def pack_for(url: str) -> SitePack | None:
    host = (urlparse(url).hostname or "").casefold()
    return next((pack for pack in packs() if pack.serves(host)), None)


@dataclass(frozen=True)
class SiteMatch:
    action: SiteAction
    text: str = ""


_COURTESY = re.compile(r"\s*(?:,?\s*(?:please|thanks|thank you|for me|now))+\s*$", re.I)


def strip_courtesy(phrase: str) -> str:
    """Trailing politeness is not part of the command: "more results please" → "more results"."""
    return _COURTESY.sub("", phrase.strip(" .!?")).strip(" .!?")


def match_phrase(phrase: str, url: str) -> SiteMatch | None:
    """The site action a phrase names exactly (after openers like "can you" are removed)."""
    pack = pack_for(url)
    if not pack:
        return None
    phrase = strip_courtesy(phrase)
    for action in pack.available(url):
        for pattern in action.say:
            found = pattern.match(phrase)
            if found:
                return SiteMatch(action, (found.groupdict().get("text") or "").strip())
        if _tokens(phrase) and any(_tokens(phrase) == _tokens(term) for term in action.terms):
            return SiteMatch(action)
    return None


_WORD = re.compile(r"[a-z0-9]+")
_MAX_OPTIONS = 9
_STOP = {
    "a",
    "an",
    "and",
    "can",
    "could",
    "do",
    "does",
    "for",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "please",
    "that",
    "the",
    "them",
    "they",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
    "you",
}


def _tokens(text: str) -> frozenset[str]:
    return frozenset(word for word in _WORD.findall(text.casefold()) if word not in _STOP)


# Speech shaped like a request: an imperative, a question about the page, or "I want to …".
# A statement such as "my inbox is a disaster" is not one, however confidently Laya matches a control.
_REQUEST = re.compile(
    r"^(?:(?:can|could|would|will) you (?:please )?|please )?"
    r"(?:add|archive|browse|buy|choose|click|continue|delete|expand|favorite|find|get|give|go|"
    r"keep|let me|look|mark|mix|move|mute|open|pause|pin|play|pop|purchase|put|read|refresh|"
    r"remove|reply|respond|resume|save|scroll|send|share|show|shrink|skip|sort|star|start|stop|"
    r"subscribe|switch|take|turn|unmute|view|watch|write)\b|"
    r"^(?:where|what|which|how|did|is|are)\b|^i (?:need|want|would like) to\b",
    re.I,
)


def looks_like_request(phrase: str) -> bool:
    """Whether speech asks for something, as opposed to describing it."""
    return bool(_REQUEST.search(strip_courtesy(phrase)))


# Words that introduce almost any command, so matching only these says nothing about *which*
# control was meant: "open the alison frantz article" would otherwise match Wikipedia's "open a
# random article" and hijack a command that names something on the page.
_GENERIC = frozenset(
    "open show go back take get see view make put use give find look read scroll click play start "
    "article page video item product thing one result post".split()
)


def lexical_match(phrase: str, url: str) -> SiteMatch | None:
    """A clear natural-example match for command-shaped speech; otherwise leave the tie to Laya."""
    pack = pack_for(url)
    phrase = strip_courtesy(phrase)
    words = _tokens(phrase)
    if not pack or not words or not _REQUEST.search(phrase):
        return None

    def score(action: SiteAction) -> tuple[int, float]:
        examples = (action.description, *action.terms)
        matches = [(len(words & _tokens(example)), len(_tokens(example))) for example in examples]
        overlap, size = max(matches, key=lambda item: (item[0], item[0] / max(1, item[1])))
        return overlap, overlap / max(1, size)

    ranked = sorted(
        ((score(action), action) for action in pack.available(url)),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, best = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else (0, 0.0)
    if best_score[0] < 2 or best_score[1] < 0.5 or best_score == second_score:
        return None
    examples = _tokens(" ".join((best.description, *best.terms)))
    matched = words & examples
    if not matched - _GENERIC and matched != words:
        # Only everyday words matched, and the speaker said more besides: this could be any control,
        # and the words that would tell them apart were ignored. When nothing was left over
        # ("take me back to the start of this article") the everyday words are the whole request.
        return None
    return SiteMatch(best)


def site_question(pack: SitePack, transcript: str, url: str = "") -> tuple[dict, list[SiteAction]]:
    """Laya's choice between this site's controls, ranked by overlap with what was said and capped
    at nine plus "none" (larger choices fall in a badly calibrated confidence bucket)."""
    words = _tokens(transcript)

    def overlap(action: SiteAction) -> int:
        searchable = " ".join(
            [
                action.description,
                action.id.replace("_", " "),
                *action.terms,
                *(pattern.pattern for pattern in action.say),
            ]
        )
        return len(words & _tokens(searchable))

    def option_text(action: SiteAction) -> str:
        examples = sorted(action.terms, key=lambda term: len(words & _tokens(term)), reverse=True)
        if not examples or not (words & _tokens(examples[0])):
            return action.description
        return examples[0]

    candidates = pack.available(url) if url else pack.actions
    ranked = [action for action in sorted(candidates, key=overlap, reverse=True) if overlap(action) > 0][
        :_MAX_OPTIONS
    ]
    question = {
        "type": "choice",
        "instructions": f"Which {pack.name} control does the speaker want? None if it is not one of these.",
        "criteria": {**{action.id: option_text(action) for action in ranked}, "none": "none of these"},
    }
    return question, ranked


def action_by_id(url: str, action_id: str) -> SiteAction | None:
    pack = pack_for(url)
    if not pack:
        return None
    return next((action for action in pack.available(url) if action.id == action_id), None)


def resolve_open(template: str, url: str, text: str = "") -> str:
    """Fill an "open" URL template from the current page and the spoken text."""
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    host = (parsed.hostname or "").removeprefix("www.")
    value = template.replace("{text}", quote_plus(text)).replace("{host}", host)
    for index in range(1, 6):
        value = value.replace(f"{{{index}}}", parts[index - 1] if len(parts) >= index else "")
    return value
