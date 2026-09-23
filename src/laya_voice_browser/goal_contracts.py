"""Finite goal outcomes selected by Laya, verified against observed browser state.

This is deliberately a three-site pilot. Verification never selects a next action.
Unknown outcomes are not successes; tool execution alone is not goal completion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from .goals import Goal, browser_blocker, literal_spans, scope
from .sites import browsing_probes
from .types import Snapshot


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

    def label(self) -> str:
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
    if parsed.scheme not in {"https", "http"} or scope(url) != site:
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
    return None


def observed_results(page: Snapshot) -> list[dict]:
    site = scope(page.url)
    if not site or page.browsing.get("site") != site or not page.browsing.get("results_ready"):
        return []
    results, seen = [], set()
    for item in page.browsing.get("results", []):
        url = result_url(site, item.get("url", ""))
        if url and item.get("title") and url not in seen:
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


_ORDINALS = {"first": 1, "1st": 1, "top": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3}


def spoken_ordinals(text: str) -> list[int]:
    """Result numbers literally spoken, like the query span. Extraction, not a choice between them."""
    return sorted({n for word, n in _ORDINALS.items() if re.search(rf"\b{word}\b", text, re.I)})


def contract_options(goal: Goal, page: Snapshot) -> dict[str, GoalContract]:
    """Possible interpretations, never a winner. Explicit site mentions constrain scope.

    Payload presence and explicit result-opening clauses veto incomplete contracts; they
    do not dispatch tools. Unsupported multi-site requests must clarify rather than lose a clause.
    """
    from .goals import HOMES

    named = [s for s in HOMES if re.search(rf"\b{re.escape(s.replace('_', ' '))}\b", goal.text, re.I)]
    sites = named or [scope(page.url)]
    if len(sites) != 1 or sites[0] not in definitions():
        return {}
    site = sites[0]
    spans = literal_spans(goal.text)
    # A restriction against dropping explicitly requested work, not an action-selection rule.
    result_clause = re.search(
        r"\b(?:open|play|watch|click)\s+(?:on\s+)?(?:the\s+)?"
        r"(?:first|second|third|top|1st|2nd|3rd|video|result|repository)\b", goal.text, re.I)
    # "third" is a literal argument, like the query; offering 1-3 made Laya guess between them and it
    # scored near-uniform for anything but "first". Laya still decides whether a result is requested.
    ordinals = (spoken_ordinals(goal.text[result_clause.start():]) if result_clause else []) or [1, 2, 3]
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
                    site, "open_result", values[0], ordinal)
    return options


def verify(contract: GoalContract, page: Snapshot) -> Verification:
    """Called on every observed state, including after the last permitted action."""
    if browser_blocker(page):
        return Verification(False, "browser challenge")
    if scope(page.url) != contract.site or page.browsing.get("site") != contract.site:
        return Verification(False, "requested site not observed")
    if contract.new_tab and not any(t.active and t.id not in contract.initial_tabs for t in page.tabs):
        return Verification(False, "requested new tab not active")
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
