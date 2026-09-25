"""Short-lived browsing goals and an observed, executable action space.

No intent parser or site phrase matcher selects an action here. Rules only expose
capabilities, extract literal arguments, and restrict this experiment to browsing.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus, urlparse

from .browser import NEW_TAB_URL
from .questions import SITE_HOME, SITE_SEARCH
from .safety import deterministic_destructive, side_effect_link
from .spans import as_https, site_for_url, url_candidates
from .types import Element, Snapshot

if TYPE_CHECKING:
    from .goal_contracts import GoalContract

HOMES = {**SITE_HOME, "ebay": "https://www.ebay.com/"}
SEARCHES = {**SITE_SEARCH, "ebay": "https://www.ebay.com/sch/i.html?_nkw={query}"}
MAX_GOAL_CHARS = 500
GOAL_TTL = 45.0
MAX_STEPS = 12
MAX_DECISIONS = 20


def missing_payload(text: str) -> bool:
    """A final ASR segment is not proof of a finished request. This veto chooses no action."""
    return bool(re.search(
        r"\b(?:search(?:\s+(?:for|on))?|look\s+up|go\s+to|open|click(?:\s+on)?|"
        r"type|enter|find)(?:\s+(?:the|a|an))?\s*[.!?]*$", text, re.I,
    ))


def browser_blocker(page: Snapshot) -> str | None:
    """Known browser challenges are not task completion and cannot be solved by this loop."""
    parsed = urlparse(page.url)
    if parsed.path.startswith(("/splashui/challenge", "/sorry/")):
        return "browser_challenge"
    if page.title.casefold().strip(" .") in {"pardon our interruption", "access denied", "robot check"}:
        return "browser_challenge"
    if (page.title.casefold().strip() == "error page | ebay"
            and "something went wrong" in page.text[:500].casefold()):
        return "browser_error"
    if "checking your browser before you access" in page.text[:500].casefold():
        return "browser_challenge"
    return None


@dataclass
class Goal:
    id: str
    text: str
    created_at: float = field(default_factory=time.monotonic)
    history: list[dict[str, Any]] = field(default_factory=list)
    status: str = "listening"
    decisions: int = 0
    prefix: str = ""
    contract: GoalContract | None = None
    verification_feedback: str = ""
    rejected_done: int = 0


@dataclass(frozen=True)
class Candidate:
    label: str
    action: dict[str, Any]
    kind: str = "click"
    source: str = "page"


def scope(url: str) -> str | None:
    from .sites import pack_for

    pack = pack_for(url)
    if pack and pack.browsing.get("site"):
        return pack.browsing["site"]
    return site_for_url(url)


def tab_candidates(page: Snapshot) -> dict[str, Candidate]:
    """Position-labelled choices; opaque browser handles stay in tool arguments, not prompts."""
    current = next((i for i, tab in enumerate(page.tabs) if tab.active), None)
    choices = {}
    for i, tab in enumerate(page.tabs):
        if tab.active:
            continue
        positions = []
        if i == 0:
            positions.append("first")
        if i == len(page.tabs) - 1:
            positions.append("last")
        if current is not None and len(page.tabs) > 1:
            if i == (current - 1) % len(page.tabs):
                positions.append("previous")
            if i == (current + 1) % len(page.tabs):
                positions.append("next")
        title = " ".join(tab.title.split())
        if len(title) > 36:
            title = title[:18] + "…" + title[-14:]
        host = (urlparse(tab.url).hostname or "")[:32]
        identity = " — ".join(part for part in (host, title) if part) or "Untitled / blank"
        choices[f"tab:{i + 1}"] = Candidate(
            f"Tab {i + 1} ({', '.join(positions)}): {identity}",
            {"type": "switch_tab", "tab_id": tab.id}, source="browser")
    return choices


def literal_spans(text: str) -> list[str]:
    """Propose exact substrings, never generated text. Laya chooses between them.

    Quoted text and tails following payload verbs are candidates. A strong command
    connective ends a tail; ordinary conjunctions ('cats and dogs') stay in it.
    Missing payloads deliberately produce no candidate, even for ASR final events.
    """
    result = []
    quoted = [m.group(1) for m in re.finditer(r'["“]([^"”]+)["”]', text)]
    tails = []
    pattern = r"\b(?:search(?:\s+(?:on\s+)?\w+)?\s+for|search\s+for|search|look\s+up|find|type|enter)\s+"
    for match in re.finditer(pattern, text, re.I):
        tail = text[match.end():]
        tail = re.split(
            r"\s+(?:and(?:\s+then)?|then)\s+"
            r"(?=(?:open|click|go|close|scroll|search|press|play|watch|show)\b)",
            tail, maxsplit=1, flags=re.I,
        )[0]
        tail = re.split(r"\s+(?:on|in|using)\s+(?:youtube|github|wikipedia|amazon|ebay|google)\b",
                        tail, maxsplit=1, flags=re.I)[0]
        tail = re.split(r"\s+in\s+(?:a\s+)?new\s+tab\s*[.!?]*$", tail, maxsplit=1, flags=re.I)[0]
        tails.append(tail)
    for value in quoted + tails:
        value = value.strip(' .!?"“”')
        if value and len(value) <= 180 and value.casefold() not in {"for", "the", "a", "on", "in"}:
            if value in text and value not in result:
                result.append(value)
    return result[:6]


def search_field(element: Element) -> bool:
    if element.disabled or element.readonly:
        return False
    editable = element.role in {"searchbox", "combobox", "textbox", "input"} or element.tag == "input"
    return bool(editable and element.input_type not in {"password", "file", "email", "hidden"}
                and (element.input_type == "search" or re.search(
                    r"\bsearch\b", f"{element.text} {element.placeholder}", re.I)))


def safe_click(element: Element, page: Snapshot) -> bool:
    if element.disabled or element.readonly or element.input_type in {"password", "file", "hidden"}:
        return False
    if deterministic_destructive({"type": "click", "target_id": element.id}, page):
        return False
    if re.search(r"\b(?:add to (?:cart|basket|bag|wishlist)|place (?:an? )?order|bid now)\b",
                 element.text, re.I):
        return False
    if element.href:
        parsed = urlparse(element.href)
        mutation = re.search(
            r"(?:^|[/?.&=_-])(?:checkout|purchase|addtocart|add-to-cart|bid|buy)(?:$|[/?.&=_-])",
            parsed.path + "?" + parsed.query, re.I,
        )
        return parsed.scheme in {"http", "https"} and not side_effect_link(element) and not mutation
    # This first experiment does not operate account, purchase or arbitrary form buttons.
    return search_field(element) or bool(re.fullmatch(
        r"(?:open )?search(?: wikipedia| github| youtube)?|go|play|pause|next page|previous page",
        element.text.strip(), re.I,
    ))


def action_space(goal: Goal, page: Snapshot) -> dict[str, dict[str, Candidate]]:
    """All offered targets have an implementation. Selection is exclusively Laya's.

    Browser toolbar tools are explicitly labelled, not presented as observed DOM nodes.
    Search URL tools are site capabilities, not a policy that automatically picks a scope.
    """
    from .goal_contracts import definitions, observed_results

    if goal.contract and goal.contract.new_tab and not any(
            t.active and t.id not in goal.contract.initial_tabs for t in page.tabs):
        return {"CLICK": {"browser:new_tab": Candidate(
            "Open the requested new tab before navigating", {"type": "new_tab"}, source="browser")}}
    if goal.contract and goal.contract.kind == "new_tab" and any(
            t.active and t.id not in goal.contract.initial_tabs for t in page.tabs):
        # The tab already exists. Repair an empty/failed start page, never create another tab.
        if scope(page.url) != "google":
            return {"CLICK": {"browser:start_page": Candidate(
                "Load Google in the new tab", {"type": "navigate", "url": NEW_TAB_URL}, source="browser")}}
        return {}
    # The outcome's ordinal is an argument selected/accepted by Laya, not a fresh ranking problem.
    # Once search is verified, bind it to that observed result; unrelated results and retyping
    # cannot satisfy the remaining work. Laya still chooses CLICK / WAIT / BLOCKED.
    if (goal.contract and goal.contract.kind == "open_result" and goal.contract.search_observed
            and goal.contract.expected_url):
        return {"CLICK": {f"result:{goal.contract.ordinal}": Candidate(
            f"Open requested result {goal.contract.ordinal}",
            {"type": "navigate", "url": goal.contract.expected_url}, source="capability")}}
    # Bound like a numbered result: which link was part of the outcome Laya chose.
    if goal.contract and goal.contract.kind == "open_link":
        if not goal.contract.expected_url:
            return {}
        return {"CLICK": {"link": Candidate(
            goal.contract.label(), {"type": "navigate", "url": goal.contract.expected_url},
            source="capability")}}
    media_commands = {"pause_video": "pause", "play_video": "play", "mute_video": "mute",
                      "unmute_video": "unmute", "next_video": "next", "previous_video": "previous",
                      "show_comments": "comments"}
    if goal.contract and goal.contract.kind in media_commands:
        command = media_commands[goal.contract.kind]
        return {"CLICK": {f"media:{command}": Candidate(
            goal.contract.label(), {"type": "media", "command": command}, source="capability")}}
    # A model-selected primitive outcome only admits compatible tools. Do not ask a second
    # question to choose between closing a tab, clicking a video and going back.
    if goal.contract and not goal.contract.site:
        kind = goal.contract.kind
        if kind in {"scroll_up", "scroll_down"}:
            return {}
        action = {"type": kind}
        if kind == "switch_tab":
            action["tab_id"] = goal.contract.target_tab
        available = (kind == "new_tab" or (kind in {"close_tab", "close_other_tabs"}
                                           and len(page.tabs) > 1)
                     or (kind == "switch_tab" and any(t.id == goal.contract.target_tab for t in page.tabs)))
        return {"CLICK": {f"browser:{kind}": Candidate(
            goal.contract.label(), action, source="browser")}} if available else {}
    clicks: dict[str, Candidate] = {}
    fields: dict[str, Candidate] = {}
    spans = [goal.contract.query] if goal.contract and goal.contract.query else literal_spans(goal.text)
    for element in page.elements:
        label = (element.text or element.placeholder or element.tag)[:50]
        detail = f"{label} ({element.role})"
        if element.value:
            detail += f" = {element.value[:30]!r}"
        if element.checked is not None:
            detail += f" checked={element.checked}"
        if element.expanded is not None:
            detail += f" expanded={element.expanded}"
        if safe_click(element, page):
            clicks[element.id] = Candidate(detail, {"type": "click", "target_id": element.id})
        if search_field(element) and element.value not in spans:
            fields[element.id] = Candidate(detail, {"type": "type", "target_id": element.id}, "fill")

    named = [name for name in HOMES
             if re.search(rf"\b{re.escape(name.replace('_', ' '))}\b", goal.text, re.I)]
    if goal.contract:
        named = [goal.contract.site] if goal.contract.site else []
    for name in named:
        if page.url.rstrip("/") != HOMES[name].rstrip("/"):
            clicks[f"site:{name}"] = Candidate(f"Browser: open {name} website", {
                "type": "navigate", "url": HOMES[name]}, source="browser")
    for index, url in enumerate(url_candidates(goal.text)):
        clicks[f"url:{index}"] = Candidate(f"Browser: open {url}", {
            "type": "navigate", "url": as_https(url)}, source="browser")
    clicks["browser:back"] = Candidate("Browser: go back", {"type": "back"}, source="browser")
    if not goal.contract or goal.contract.kind == "new_tab" or (goal.contract.new_tab and not any(
            t.active and t.id not in goal.contract.initial_tabs for t in page.tabs)):
        clicks["browser:new_tab"] = Candidate(
            "Browser: open a new tab", {"type": "new_tab"}, source="browser")
    if len(page.tabs) > 1:
        clicks["browser:close_tab"] = Candidate("Browser: close current tab", {
            "type": "close_tab"}, source="browser")
    clicks.update(tab_candidates(page))
    if spans:
        sites = [goal.contract.site] if goal.contract else [scope(page.url), *named, "google"]
        for name in dict.fromkeys(sites):
            if name in SEARCHES:
                if goal.contract and goal.contract.search_observed:
                    continue
                clicks[f"search:{name}"] = Candidate(f"Browser: search {name} for the requested topic", {
                    "type": "search", "site": name}, source="browser")
                if goal.contract and name in definitions():
                    clicks[f"search:{name}"] = Candidate(
                        f"{name}: search for {goal.contract.query!r}",
                        {"type": "search", "site": name, "query": goal.contract.query}, source="capability")
    if goal.contract:
        for index, item in enumerate(observed_results(page), 1):
            clicks[f"result:{index}"] = Candidate(
                f"{scope(page.url)}: open result {index}: {item['title'][:55]}",
                {"type": "navigate", "url": item["url"]}, source="capability")
    if (goal.contract and goal.contract.kind in {"search", "open_result"}
            and not goal.contract.search_observed):
        # Once Laya selected a scoped search outcome, unrelated page links/tabs cannot fulfil it.
        # In particular, a new Google tab must not receive a query meant for GitHub/YouTube.
        same_site = scope(page.url) == goal.contract.site
        submit_ids = {e.id for e in page.elements if same_site and e.role == "button"
                      and re.fullmatch(r"(?:google )?search(?: wikipedia| github| youtube)?|go",
                                       e.text.strip(), re.I)}
        clicks = {key: c for key, c in clicks.items()
                  if key == f"search:{goal.contract.site}" or key in submit_ids}
        # The search capability already opens its site. Offering the homepage as a redundant
        # route split confidence between two valid plans without providing another capability.
        if not same_site:
            fields = {}
    groups = {"CLICK": clicks}
    if fields and spans:
        groups["TYPE_TEXT"] = fields
    return groups


def materialize(candidate: Candidate, value: str | None = None) -> dict:
    action = dict(candidate.action)
    if action["type"] == "search":
        from .goal_contracts import definitions

        value = action.get("query") or value
        if not value:
            raise ValueError("Search needs a literal transcript span")
        template = definitions().get(action["site"], {}).get("search_url", SEARCHES[action["site"]])
        return {"type": "navigate", "url": template.format(query=quote_plus(value))}
    if action["type"] == "type":
        if not value:
            raise ValueError("Typing needs a literal transcript span")
        action["text"] = value
    return action


def page_identity(page: Snapshot) -> tuple:
    """Progress includes field values, tab identity and scrolling, not just URL changes."""
    return (page.url, page.document_id, page.scroll_y, repr(page.browsing),
            tuple((t.id, t.active) for t in page.tabs),
            tuple((e.id, e.role, e.text, e.href, e.value, e.disabled, e.readonly,
                   e.checked, e.expanded) for e in page.elements))


def evidence(candidate: Candidate, action: dict, before: Snapshot, after: Snapshot) -> dict:
    """Evidence of this tool's result, NOT a claim that the whole natural-language goal is done."""
    if action["type"] == "type":
        original = next((e for e in before.elements if e.id == action["target_id"]), None)
        observed = before.url == after.url and any(
            (e.id == action["target_id"] or (original and e.text == original.text
                                            and e.placeholder == original.placeholder))
            and e.value == action["text"] for e in after.elements)
    elif action["type"] == "new_tab":
        observed = len(after.tabs) > len(before.tabs)
    elif action["type"] == "close_tab":
        observed = len(after.tabs) < len(before.tabs)
    elif action["type"] == "close_other_tabs":
        active = next((t.id for t in before.tabs if t.active), None)
        observed = len(before.tabs) > 1 and len(after.tabs) == 1 and after.tabs[0].id == active
    else:
        observed = page_identity(before) != page_identity(after)
    return {"action": candidate.label, "kind": candidate.kind, "text": action.get("text"),
            "page_changed": observed, "url": after.url, "executed": action, "source": candidate.source}
