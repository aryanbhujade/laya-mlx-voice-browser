"""Finite goal outcomes selected by Laya, verified against observed browser state.

Supported sites declare observations in their packs. Verification never selects a next action.
Unknown outcomes are not successes; tool execution alone is not goal completion.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from urllib.parse import parse_qs, unquote, urlparse

from .goals import Candidate, Goal, browser_blocker, literal_spans, safe_click, scope, tab_candidates
from .sites import browsing_probes
from .types import Element, Snapshot


@dataclass
class GoalContract:
    site: str
    kind: str  # open_site, search, open_result
    query: str = ""
    ordinal: int = 0
    new_tab: bool = False
    initial_tabs: tuple[str, ...] = ()
    expected_url: str = ""
    search_observed: bool = False
    initial_active_tab: str = ""
    target_tab: str = ""
    initial_url: str = ""
    initial_scroll: float = 0
    link_label: str = ""
    query_from_page: bool = False

    def label(self) -> str:
        if self.kind == "switch_tab":
            return "Switch to the selected browser tab"
        if self.kind in {"pause_video", "play_video", "mute_video", "unmute_video",
                         "next_video", "previous_video", "show_comments"}:
            return self.kind.replace("_", " ")
        if self.kind == "open_link":
            return f"Open {self.link_label}" if self.link_label else "Open a link on this page"
        if self.kind in {"close_tab", "close_other_tabs", "new_tab", "switch_tab",
                         "scroll_up", "scroll_down"}:
            return self.kind.replace("_", " ")
        if self.kind == "open_site":
            return f"Open {self.site}; no search or result opening requested"
        text = f"Search {self.site} for {self.query!r}"
        return text + (f"; then open result number {self.ordinal}" if self.ordinal else "; show results only")


@dataclass(frozen=True)
class Verification:
    satisfied: bool
    reason: str


def definitions() -> dict[str, dict]:
    return {p["site"]: p for p in browsing_probes()}


def normal(text: str) -> str:
    return " ".join(unquote(text).replace("_", " ").casefold().split())


def result_url(site: str, url: str) -> str | None:
    """Canonical identity of an eligible video/article/repository, not arbitrary links."""
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        return None
    if site == "google":
        # Only direct external organic-result destinations, not Google navigation/redirect URLs.
        return url if scope(url) != "google" else None
    if scope(url) != site:
        return None
    if site == "youtube":
        ids = parse_qs(parsed.query).get("v", [])
        if parsed.path == "/watch" and len(ids) == 1 and re.fullmatch(r"[\w-]{11}", ids[0]):
            return f"https://www.youtube.com/watch?v={ids[0]}"
    if site == "github":
        parts = parsed.path.strip("/").split("/")
        if (len(parts) == 2 and all(parts) and parts[0] not in
                {"search", "topics", "collections", "sponsors", "settings", "orgs", "users"}):
            return f"https://github.com/{parts[0]}/{parts[1]}"
    if site == "wikipedia" and parsed.path.startswith("/wiki/"):
        name = unquote(parsed.path[6:])
        if name and ":" not in name and name != "Main_Page":
            return f"https://{parsed.hostname}{parsed.path}"
    if site == "ebay":
        # Listing title/image/tracking URLs all identify one item. Category, ad placeholders,
        # checkout and seller links are not listings and must not affect ordinal numbering.
        match = re.fullmatch(r"/itm/(?:[^/]+/)?([0-9]{12})/?", parsed.path)
        if match and match[1] != "000000000000":
            return f"https://{parsed.hostname}/itm/{match[1]}"
    return None


def observed_results(page: Snapshot) -> list[dict]:
    site = scope(page.url)
    if not site or page.browsing.get("site") != site or not page.browsing.get("results_ready"):
        return []
    results, seen = [], set()
    for item in page.browsing.get("results", []):
        url = result_url(site, item.get("url", ""))
        element = Element("result", "link", item.get("title", ""), "a", href=url or "")
        if (url and item.get("title") and url not in seen
                and (site != "google" or safe_click(element, page))):
            results.append({"url": url, "title": item["title"]})
            seen.add(url)
    return results


def search_matches(page: Snapshot, site: str, query: str) -> bool:
    if browser_blocker(page) or scope(page.url) != site or page.browsing.get("site") != site:
        return False
    parsed = urlparse(page.url)
    params = parse_qs(parsed.query)
    definition = definitions().get(site)
    if not definition or not query:
        return False
    expected_path = urlparse(definition["search_url"]).path
    query_match = [normal(v) for v in params.get(definition["query_key"], [])] == [normal(query)]
    if parsed.path == expected_path and query_match and observed_results(page):
        return site != "github" or params.get("type") == ["repositories"]
    # Wikipedia can redirect a submitted search straight to an exact article/disambiguation page.
    return bool(site == "wikipedia" and result_url(site, page.url) and page.browsing.get("detail_ready")
                and normal(page.browsing.get("heading", "")) == normal(query)
                and normal(parsed.path[6:]) == normal(query))


def awaiting_render(contract: GoalContract | None, page: Snapshot) -> bool:
    """A known destination is loading, not a new decision opportunity. Bounded by the controller."""
    if not contract or contract.site != scope(page.url) or browser_blocker(page):
        return False
    if contract.expected_url and result_url(contract.site, page.url) == contract.expected_url:
        return not (page.browsing.get("detail_ready") and page.browsing.get("heading"))
    definition = definitions().get(contract.site)
    if not definition or not contract.query:
        return False
    parsed = urlparse(page.url)
    params = parse_qs(parsed.query)
    at_search = (parsed.path == urlparse(definition["search_url"]).path
                 and params.get(definition["query_key"]) == [contract.query])
    return at_search and not page.browsing.get("results_ready")


# A control is an interpretation only when its own words were spoken, the same way a search needs a
# query span and a result needs a result clause. Offering every control for any utterance without a
# site or query let "open the Talk page" become a new tab and "please don't close this tab" close one,
# and both then verified, because verification checks the chosen outcome, not whether it was meant.
_CONTROL_WORDS = {
    "scroll": re.compile(r"\bscroll\b|\b(?:up|down)\b", re.I),
    "new_tab": re.compile(r"\b(?:new|another)\s+tab\b", re.I),
    "close_tab": re.compile(r"\bclose\b", re.I),
    "switch_tab": re.compile(r"\btabs?\b", re.I),
}
# Opening a link is offered only when navigation is spoken, like every other outcome.
_NAVIGATE_WORDS = re.compile(
    r"\b(?:open|click|show|view|visit|see|go\s+to|take\s+me\s+to|(?:next|previous)\s+page)\b", re.I)
# A veto, like missing_payload: a negated control is not an instruction to do anything.
_NEGATED = re.compile(r"\b(?:don'?t|do\s+not|never|no\s+need\s+to)\b", re.I)
# A blank-tab outcome cannot satisfy a destination plus a tab modifier. This only bounds
# outcome coverage; Laya still chooses the outcome and the destination (or rejects both).
_BLANK_TAB_REQUEST = re.compile(
    r"^(?:(?:and|then)\s+)?(?:(?:can|could|would) you\s+)?(?:please\s+)?"
    r"(?:open|create|make|give me)\s+(?:a\s+)?(?:new|another)(?:\s+blank)?\s+tab"
    r"(?:\s+(?:please|for me))?[.!?]*$", re.I)

# Admission only: grounding a target must not turn a quoted/past/future command into permission.
# This conservative pilot accepts explicit requests, not arbitrary conversational formulations.
# It never identifies a destination, chooses an outcome, or dispatches a tool.
_NAVIGATION_REQUEST = re.compile(
    r"^(?:(?:hey\s+)?laya[, ]+)?(?:(?:okay|ok|and|then)\b[, ]*)*"
    r"(?:in\s+(?:a\s+)?new\s+tab[, ]+)?"
    r"(?:(?:(?:can|could|would|will)\s+you|i(?:'d| would)\s+like\s+(?:you\s+)?to|"
    r"i\s+want\s+you\s+to)\s+)?(?:please\s+)?"
    r"(?:open|click|show|view|visit|see|go\s+to|take\s+me\s+to|(?:next|previous)\s+page)\b", re.I)


def navigation_request(text: str) -> bool:
    return bool(_NAVIGATION_REQUEST.match(text.strip()))


_ORDINALS = {"first": 1, "1st": 1, "top": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3}


def spoken_ordinals(text: str) -> list[int]:
    """Result numbers literally spoken, like the query span. Extraction, not a choice between them."""
    return sorted({n for word, n in _ORDINALS.items() if re.search(rf"\b{word}\b", text, re.I)})


def _url_key(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    return f"{host}{parsed.path.rstrip('/')}?{parsed.query}#{parsed.fragment}"


def describe_destination(label: str, url: str) -> str:
    """Compact, observed destination metadata; not a prediction of the user's intent.

    Use paths only (no tracking/query payloads). Retain file extensions when shortening so
    a thumbnail and an article with the same accessible name remain distinguishable.
    """
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if re.search(r"\.(?:jpe?g|png|gif|webp|svg)$", path, re.I):
        kind = "image file"
    elif ((parsed.hostname or "").endswith(".wikipedia.org")
          and path.startswith("/wiki/") and ":" not in path[6:]):
        kind = "article"
    else:
        kind = "link"
    destination = (parsed.hostname or "") + path
    if kind in {"article", "image file"}:
        destination = path
    if kind == "image file" and path.startswith("/wiki/File:") and len(path) > 44:
        destination = "/wiki/File:…" + path.rsplit(".", 1)[-1]
    if len(destination) > 64:
        destination = destination[:44] + "…" + destination[-19:]
    return f"{label[:60]} — {kind} — {destination}"


def link_options(page: Snapshot) -> dict[str, Candidate]:
    """Where a visible link, or a navigation the site pack declares, would take the browser.

    Both end at a URL, so both are verified the same way; this merges pack navigation into the same
    choice as the page's own links. Laya chooses among them. Nothing here ranks or matches words.
    """
    from . import sites

    options: dict[str, Candidate] = {}
    seen = {_url_key(page.url)}  # a link to where the browser already is would verify having done nothing
    url_ids: dict[str, str] = {}
    aliases: dict[str, set[str]] = {}
    listing_titles = ({item["url"]: item["title"] for item in observed_results(page)}
                      if scope(page.url) == "ebay" else {})
    for element in page.elements:
        listing = result_url("ebay", element.href) if scope(page.url) == "ebay" else None
        label = listing_titles.get(listing, element.text or "").strip()
        if not element.href or not label or not safe_click(element, page):
            continue
        url = listing or element.href
        key = _url_key(url)
        if key not in seen:
            seen.add(key)
            options[element.id] = Candidate(f"{label[:60]} (link)", {"type": "navigate", "url": url})
            url_ids[key] = element.id
        elif key in url_ids and options[url_ids[key]].label != f"{label[:60]} (link)":
            # A result can expose its title and source in separate anchors. Keep one target,
            # but retain alternate names instead of losing the source when deduplicating.
            aliases.setdefault(url_ids[key], set()).add(label)
    # Pack selectors expose only navigation actually present on this page, including pagination
    # below the viewport. They do not match the user's words or dispatch an action.
    if page.browsing.get("site") == scope(page.url):
        for index, item in enumerate(page.browsing.get("navigation", [])):
            url, title = item.get("url", ""), item.get("title", "")
            element = Element(f"nav:{index}", "link", title, "a", href=url)
            if title and safe_click(element, page) and _url_key(url) not in seen:
                seen.add(_url_key(url))
                options[element.id] = Candidate(title, {"type": "navigate", "url": url}, source="pack")
    # The page's own links come first and win a shared URL. Putting the pack's longer labels first was
    # measured and was worse on real pages (6/12 right with 2 wrong links, against 8/12 with 1).
    pack = sites.pack_for(page.url)
    for action in pack.available(page.url) if pack else ():
        template = action.do.get("open")
        if not template or "{text}" in template or action.confirm or action.side_effect:
            continue
        # Path placeholders only mean something on a page that has them: GitHub's {1}/{2} are a
        # repository's owner and name, and on a search or topic page they would build a wrong URL.
        if "{1}" in template and not result_url(scope(page.url) or "", page.url):
            continue
        url = sites.resolve_open(template, page.url)
        key = _url_key(url)
        if key not in seen:
            seen.add(key)
            options[f"pack:{action.id}"] = Candidate(
                f"{pack.name}: {action.description}", {"type": "navigate", "url": url}, source="pack")
    # Add discriminating information where a name alone cannot identify the destination.
    # Do this after URL deduplication: repeated links to one destination are not ambiguity.
    counts = Counter(normal(c.label) for c in options.values())
    for key, candidate in list(options.items()):
        if counts[normal(candidate.label)] > 1:
            label = candidate.label.removesuffix(" (link)")
            options[key] = replace(candidate, label=describe_destination(label, candidate.action["url"]))
        elif key in aliases:
            label = candidate.label.removesuffix(" (link)")
            names = sorted({label, *aliases[key]}, key=lambda name: (len(name), name.casefold()))
            # Short distinct names keep this compact and independent of DOM/thumbnail order.
            options[key] = replace(candidate, label=" / ".join(name[:40] for name in names[:2]) + " (link)")
    return options


def contract_options(goal: Goal, page: Snapshot) -> dict[str, GoalContract]:
    """Possible interpretations, never a winner. Explicit site mentions constrain scope.

    Payload presence and explicit result-opening clauses veto incomplete contracts; they
    do not dispatch tools. Unsupported multi-site requests must clarify rather than lose a clause.
    """
    from .goals import HOMES

    spans = literal_spans(goal.text)
    # A site name inside a supplied query is topic data, not a second navigation destination.
    navigation_text = goal.text
    for span in sorted(spans, key=len, reverse=True):
        navigation_text = navigation_text.replace(span, "")
    if _NEGATED.search(navigation_text):
        return {}
    named = [s for s in HOMES if re.search(rf"\b{re.escape(s.replace('_', ' '))}\b", navigation_text, re.I)]
    # Existing blank tabs remain usable; don't silently move a supported site's search to Google.
    current_site = scope(page.url)
    new_tab_search = bool(spans and re.search(r"\bnew\s+tab\b", navigation_text, re.I))
    sites = named or ["google" if new_tab_search else current_site or "google"]
    # A restriction against dropping explicitly requested work, not an action-selection rule.
    result_clause = re.search(
        r"\b(?:open|play|watch|click|show)\s+(?:me\s+)?(?:on\s+)?(?:the\s+)?"
        r"(?:first|second|third|top|1st|2nd|3rd|video|result|repository|listing|item)\b", goal.text, re.I)
    # "third" is a literal argument, like the query; offering 1-3 made Laya guess between them and it
    # scored near-uniform for anything but "first". Laya still decides whether a result is requested.
    ordinals = (spoken_ordinals(goal.text[result_clause.start():]) if result_clause else []) or [1, 2, 3]
    tab_reference = re.search(
        r"\b(?:switch|close|next|previous)\b.*\btabs?\b|"
        r"\bgo\s+to\s+(?:the\s+)?(?:(?:first|second|third|last|other|next|previous)\s+tab|"
        r"tab\s+\d+)\b", navigation_text, re.I)
    close_others = re.search(r"\bclose\b.*\b(?:all|other)\b.*\btabs?\b", navigation_text, re.I)
    if close_others:
        if spans or result_clause or len(page.tabs) < 2 or not any(t.active for t in page.tabs):
            return {}
        return {"close_other_tabs": GoalContract("", "close_other_tabs")}
    if not spans and not result_clause:
        if len(named) > 1:
            return {}
        if _NEGATED.search(goal.text):
            return {}
        spoken = {kind for kind, words in _CONTROL_WORDS.items() if words.search(navigation_text)}
        options = {}
        if "scroll" in spoken:
            options.update({kind: GoalContract("", kind) for kind in ("scroll_up", "scroll_down")})
        media = page.browsing.get("media") or {}
        controls = definitions().get(current_site or "", {}).get("media_controls", {})
        # Shortlist affordance families, not winners. Laya still chooses the requested
        # outcome against its opposite and unsupported; a comments button is not a link.
        media_families = {
            "playback": ({"pause_video", "play_video"}, r"\b(?:pause|play)\b"),
            "audio": ({"mute_video", "unmute_video"}, r"\b(?:mute|unmute)\b"),
            "sequence": ({"next_video", "previous_video"}, r"\b(?:next|previous|skip)\b"),
            "comments": ({"show_comments"}, r"\bcomments?\b"),
        }
        offered_media = set()
        if media.get("present") and not re.search(r"\b(?:next|previous) page\b", navigation_text, re.I):
            for kinds, pattern in media_families.values():
                if re.search(pattern, navigation_text, re.I):
                    offered_media.update(kinds & controls.keys())
        options.update({kind: GoalContract(current_site or "", kind) for kind in offered_media})
        if page.tabs:
            if "new_tab" in spoken and _BLANK_TAB_REQUEST.fullmatch(goal.text.strip()):
                options["new_tab"] = GoalContract("", "new_tab")
            if "close_tab" in spoken and len(page.tabs) > 1 and any(t.active for t in page.tabs):
                options["close_tab"] = GoalContract("", "close_tab")
            if tab_reference and "new_tab" not in spoken:
                for key, candidate in tab_candidates(page).items():
                    options[key] = GoalContract("", "switch_tab", target_tab=candidate.action["tab_id"])
        # "switch to the GitHub tab" names a browser tab, not a link; "open X in a new tab" is a link.
        tab_command = bool(tab_reference) and "new_tab" not in spoken
        if _NAVIGATE_WORDS.search(navigation_text) and not tab_command and not offered_media:
            options["open_link"] = GoalContract(scope(page.url) or "", "open_link")
        # A website's homepage cannot fulfil an explicit request for a search result.
        # Keep every safe page destination; Laya still has to identify the requested result.
        named_result = re.search(r"\bresults?\b", navigation_text, re.I)
        if named and not tab_reference and not named_result and named[0] in definitions():
            options[f"open:{named[0]}"] = GoalContract(named[0], "open_site")
        # Nothing spoken maps to an outcome: clarify rather than fall through to reopening the site,
        # which would verify immediately and report success for having done nothing.
        return options
    if len(sites) != 1 or sites[0] not in definitions():
        return {}
    site = sites[0]
    # Until composite control contracts exist, do not silently omit an additional browser command.
    if spans and re.search(r"\b(?:and|then)\s+(?:close|scroll|switch|go back|go forward)\b", goal.text, re.I):
        return {}
    options = {}
    if not spans and not result_clause:
        options[f"open:{site}"] = GoalContract(site, "open_site")
    for index, query in enumerate(spans):
        if not result_clause:
            options[f"search:{site}:{index}"] = GoalContract(site, "search", query)
        for ordinal in ordinals:
            options[f"result:{site}:{index}:{ordinal}"] = GoalContract(site, "open_result", query, ordinal)
    # Follow-up "open the first result" uses observed search scope/query, not invented speech.
    if not spans and result_clause and observed_results(page):
        key = definitions()[site]["query_key"]
        values = parse_qs(urlparse(page.url).query).get(key, [])
        if len(values) == 1:
            for ordinal in ordinals:
                options[f"result:{site}:current:{ordinal}"] = GoalContract(
                    site, "open_result", values[0], ordinal, query_from_page=True)
    return options


def verify(contract: GoalContract, page: Snapshot) -> Verification:
    """Called on every observed state, including after the last permitted action."""
    if contract.kind == "open_link":
        if browser_blocker(page):
            return Verification(False, "browser challenge")
        if contract.new_tab and not any(t.active and t.id not in contract.initial_tabs for t in page.tabs):
            return Verification(False, "requested new tab not active")
        arrived = bool(contract.expected_url) and _url_key(page.url) == _url_key(contract.expected_url)
        ready = arrived and bool(page.title and (page.text or page.elements))
        return Verification(ready, "requested link open" if ready else "requested link not open")
    ids = {t.id for t in page.tabs}
    if contract.kind == "close_tab":
        closed = (bool(contract.initial_active_tab) and contract.initial_active_tab not in ids
                  and ids == set(contract.initial_tabs) - {contract.initial_active_tab})
        return Verification(closed, "requested tab closed" if closed else "requested tab still open")
    if contract.kind == "close_other_tabs":
        closed = (len(contract.initial_tabs) > 1 and ids == {contract.initial_active_tab}
                  and any(t.active and t.id == contract.initial_active_tab for t in page.tabs))
        return Verification(closed, "other tabs closed" if closed else "other tabs still open")
    if contract.kind == "new_tab":
        opened = any(t.active and t.id not in contract.initial_tabs for t in page.tabs)
        ready = (opened and scope(page.url) == "google" and not browser_blocker(page)
                 and bool(page.title and (page.text or page.elements)))
        return Verification(ready, "new tab with Google ready" if ready else "new tab start page not ready")
    if contract.kind == "switch_tab":
        switched = any(t.active and t.id == contract.target_tab for t in page.tabs)
        return Verification(switched, "requested tab active" if switched else "requested tab not active")
    if contract.kind in {"scroll_up", "scroll_down"}:
        same_tab = not contract.initial_active_tab or any(
            t.active and t.id == contract.initial_active_tab for t in page.tabs)
        delta = page.scroll_y - contract.initial_scroll
        moved = page.url == contract.initial_url and same_tab and (
            delta < 0 if contract.kind == "scroll_up" else delta > 0)
        return Verification(moved, "scroll observed" if moved else "requested scroll not observed")
    if contract.kind in {"pause_video", "play_video", "mute_video", "unmute_video",
                         "next_video", "previous_video", "show_comments"}:
        if browser_blocker(page) or scope(page.url) != contract.site:
            return Verification(False, "video page not available")
        media = page.browsing.get("media") or {}
        same_tab = any(t.active and t.id == contract.initial_active_tab for t in page.tabs)
        same_video = page.url == contract.initial_url
        if contract.kind in {"pause_video", "play_video", "mute_video", "unmute_video"}:
            field = "paused" if contract.kind in {"pause_video", "play_video"} else "muted"
            wanted = contract.kind in {"pause_video", "mute_video"}
            satisfied = same_tab and same_video and media.get("present") and media.get(field) is wanted
        elif contract.kind == "show_comments":
            satisfied = same_tab and same_video and page.browsing.get("comments_visible") is True
        else:
            before = urlparse(contract.initial_url)
            after = urlparse(page.url)
            expected_path = "/shorts/" if before.path.startswith("/shorts/") else "/watch"
            satisfied = (same_tab and page.url != contract.initial_url
                         and before.hostname == after.hostname and after.path.startswith(expected_path)
                         and media.get("present"))
        return Verification(bool(satisfied),
                            "media outcome observed" if satisfied else "media outcome pending")
    if browser_blocker(page):
        return Verification(False, "browser challenge")
    if contract.new_tab and not any(t.active and t.id not in contract.initial_tabs for t in page.tabs):
        return Verification(False, "requested new tab not active")
    if (contract.site == "google" and contract.kind == "open_result"
            and contract.search_observed and contract.expected_url):
        # Google results leave Google. Verify the exact observed destination, never just any page.
        ready = (_url_key(page.url) == _url_key(contract.expected_url)
                 and bool(page.title and (page.text or page.elements)))
        return Verification(ready, "requested result rendered" if ready else "requested result not open")
    if scope(page.url) != contract.site or page.browsing.get("site") != contract.site:
        return Verification(False, "requested site not observed")
    if contract.kind == "open_site":
        ready = bool(page.title and (page.text or page.elements))
        return Verification(ready, "site rendered" if ready else "site not rendered")
    matched = search_matches(page, contract.site, contract.query)
    if matched:
        contract.search_observed = True
        if contract.kind == "search":
            return Verification(True, "requested search visibly rendered")
        results = observed_results(page)
        if not contract.expected_url and len(results) >= contract.ordinal:
            contract.expected_url = results[contract.ordinal - 1]["url"]
    if contract.kind == "open_result":
        ready = (contract.search_observed and bool(contract.expected_url)
                 and result_url(contract.site, page.url) == contract.expected_url
                 and bool(page.browsing.get("detail_ready")) and bool(page.browsing.get("heading")))
        reason = "requested result rendered" if ready else "requested result not open"
        return Verification(bool(ready), reason)
    return Verification(False, "requested search not rendered")
