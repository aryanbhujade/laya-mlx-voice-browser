from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import parse_qs, quote_plus, urlparse

from . import browsers, sites
from .answers import _choice, _confidence, _probability
from .config import load as load_settings
from .questions import (
    PAYLOAD_SILENCE_SECONDS,
    SILENCE_COMPLETE_SECONDS,
    SITE_HOME,
    SITE_SEARCH,
    THRESHOLDS,
)
from .safety import deterministic_destructive, ordinary_navigation_link
from .spans import (
    INSTANT_MEDIA,
    as_https,
    deterministic_intent,
    explicit_browser_command,
    explicit_payload,
    media_command,
    mentioned_site,
    site_for_url,
    spoken_scroll_amount,
    spoken_tab_direction,
    tab_command,
)
from .types import ModelDecision, PolicyResult, Snapshot, Tab

# Intents whose words describe *what* to act on, so they wait for the end of the phrase: a search
# query, dictated text, or the element to click ("click create…" must not click "Create" early).
_PAYLOAD_INTENTS = {
    "search_web",
    "type_into_field",
    "select_option",
    "click_element",
    "switch_tab",
    "close_tab",
}
# Only these act on page content; navigation, history, scroll and tabs cannot submit or change anything.
_PAGE_ACTIONS = {"click", "type", "select", "press_enter"}
# Explicit commands no further words can change or make dangerous, so they may run mid-speech.
EARLY_INTENTS = {"go_back", "go_forward", "reload", "open_new_tab"}
# The 15-way intent head is overconfident (its temperature bucket is clamped), so a model-only
# closed-set intent must at least be consistent with the words spoken: "Go to" is never reload.
_INTENT_KEYWORDS = {
    "go_back": r"\bback\b|\bprevious\s+page\b",
    "go_forward": r"\bforward\b|\bnext\s+page\b",
    "reload": r"\b(?:reload|refresh|again)\b",
    "open_new_tab": r"\bnew\s+tab\b",
    "close_tab": r"\bclose\b",
    "switch_tab": r"\btabs?\b",
    "scroll_down": r"\b(?:scroll|down|bottom|below|lower)\b",
    "scroll_up": r"\b(?:scroll|up|top|above|higher)\b",
    "press_enter": r"\b(?:enter|return|submit)\b",
}


def _reason(reasons: list[dict], name: str, value, threshold, passed: bool) -> None:
    reasons.append({"name": name, "value": value, "threshold": threshold, "passed": passed})


def _selected_span(decision: ModelDecision, name: str) -> str | None:
    answer = decision.answers.get(name, {})
    selected = _choice(answer)
    if selected and selected != "none" and _confidence(answer) >= THRESHOLDS["span_confidence"]:
        return selected
    return None


def _scroll_amount(answer: dict, direction: str) -> str:
    value = answer.get("score", answer.get("expected_score", 1)) if isinstance(answer, dict) else 1
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 1
    if score < 0.5:
        return "little"
    if score > 1.5:
        return "end" if direction == "down" else "top"
    return "page"


def _build_action(intent: str, decision: ModelDecision, snapshot: Snapshot) -> tuple[dict | None, str]:
    answers = decision.answers
    transcript = str(decision.state.get("transcript", ""))
    if intent == "navigate_url":
        url = _selected_span(decision, "url_span")
        if not url and decision.candidates["url"]:
            url = decision.candidates["url"][0]
        site = mentioned_site(transcript) or _choice(answers.get("site"))
        if url:
            try:
                return {"type": "navigate", "url": as_https(url)}, f"open {url}"
            except ValueError:
                return None, "the spoken web address is invalid"
        if site in SITE_HOME:
            return {"type": "navigate", "url": SITE_HOME[site]}, f"open {site}"
        return None, "no supported website was identified"
    if intent == "search_web":
        query = explicit_payload(transcript) or _selected_span(decision, "text_span")
        if not query and decision.candidates["text"]:
            first = decision.candidates["text"][0]
            if first.casefold() != transcript.casefold():
                query = first
        if query:
            query = _HERE.sub("", query).strip() or query
        if not query:
            return None, "no complete search text was identified"
        site = mentioned_site(transcript) or _current_site_scope(transcript, snapshot.url)
        settings = load_settings()
        engine = browsers.web_search_engine(settings.search_engine, browsers.resolve(settings.browser))
        template = SITE_SEARCH.get(site) or SITE_SEARCH[engine]
        return {"type": "navigate", "url": template.format(query=quote_plus(query))}, f"search for {query}"
    if intent in {"click_element", "type_into_field", "select_option"}:
        target_answer = answers.get("target", {})
        target = _choice(target_answer)
        probabilities = target_answer.get("probabilities", {}) if isinstance(target_answer, dict) else {}
        probability = float(probabilities.get(target, 0.0)) if target else 0.0
        if decision.lexical_target:
            # A unique label match is stronger evidence than Laya's target head on real pages.
            target = decision.lexical_target
        elif (
            not target
            or target == "none"
            or _confidence(target_answer) < THRESHOLDS["target_confidence"]
            or probability < THRESHOLDS["target_probability"]
        ):
            return None, _AMBIGUOUS
        if target not in {element.id for element in snapshot.elements}:
            return None, "the selected page target is stale"
        if intent == "click_element":
            return {"type": "click", "target_id": target}, f"click {target}"
        text = explicit_payload(transcript) or _selected_span(decision, "text_span")
        if not text and decision.candidates["text"]:
            first = decision.candidates["text"][0]
            if first.casefold() != transcript.casefold():
                text = first
        if not text:
            return None, "no complete text payload was identified"
        kind = "select" if intent == "select_option" else "type"
        return {"type": kind, "target_id": target, "text": text}, f"{kind} {text!r} in {target}"
    if intent == "press_enter":
        return {"type": "press_enter"}, "press Return"
    if intent in {"scroll_down", "scroll_up"}:
        direction = "down" if intent == "scroll_down" else "up"
        return {
            "type": "scroll",
            "direction": direction,
            "amount": spoken_scroll_amount(transcript, direction)
            or _scroll_amount(answers.get("scroll_amount", {}), direction),
        }, intent.replace("_", " ")
    if intent == "go_back":
        return {"type": "back"}, "go back"
    if intent == "go_forward":
        return {"type": "forward"}, "go forward"
    if intent == "reload":
        return {"type": "reload"}, "reload"
    if intent == "open_new_tab":
        return {"type": "new_tab"}, "open a new tab"
    if intent == "media":
        media = media_command(transcript)
        if not media:
            return None, "no media command"
        return {"type": "media", **media}, MEDIA_SUMMARIES.get(media["command"], media["command"])
    if intent in {"close_tab", "switch_tab"} and tab_command(transcript):
        return _tab_action(tab_command(transcript), snapshot)
    if intent == "close_tab":
        return {"type": "close_tab"}, "close the tab"
    if intent == "switch_tab":
        direction = spoken_tab_direction(transcript) or _choice(answers.get("tab_direction")) or "next"
        if direction == "none":
            direction = "next"
        return {"type": "switch_tab", "direction": direction}, f"switch to the {direction} tab"
    return None, "no supported action"


_AMBIGUOUS = "the page target is ambiguous"
MEDIA_SUMMARIES = {
    "pause": "pause",
    "play": "play",
    "mute": "mute",
    "unmute": "unmute",
    "volume_up": "volume up",
    "volume_down": "volume down",
    "forward": "skip ahead",
    "back": "rewind",
    "faster": "speed up",
    "slower": "slow down",
    "normal_speed": "normal speed",
    "rate": "set the speed",
    "fullscreen": "full screen",
    "exit_fullscreen": "exit full screen",
    "captions_on": "captions on",
    "captions_off": "captions off",
    "next": "next video",
    "previous": "previous video",
    "skip_ad": "skip the ad",
}
_TAB_WORD = re.compile(r"[a-z0-9]+")


def _tab_words(tab: Tab) -> set[str]:
    host = urlparse(tab.url).hostname or ""
    return set(_TAB_WORD.findall(f"{tab.title} {host}".casefold()))


def _tab_action(command: dict, snapshot: Snapshot) -> tuple[dict | None, str]:
    """Turn "close the YouTube tab", "tab 3", "next tab" … into an action on a specific tab."""
    kind, tabs = command["kind"], snapshot.tabs
    if kind == "close_other_tabs":
        return {"type": "close_other_tabs"}, "close the other tabs"
    verb = "close" if kind == "close_tab" else "switch to"
    if command.get("current") or (kind == "close_tab" and len(command) == 1):
        if kind == "switch_tab":
            return None, "already on this tab"
        return {"type": "close_tab"}, "close this tab"
    if "direction" in command:
        direction = command["direction"]
        return {"type": kind, "direction": direction}, f"{verb} the {direction} tab"
    if not tabs:
        return None, "the open tabs are not known yet"
    if "index" in command:
        if not 1 <= command["index"] <= len(tabs):
            return None, f"there is no tab {command['index']} ({len(tabs)} open)"
        tab = tabs[command["index"] - 1]
    else:
        wanted = set(_TAB_WORD.findall(command.get("name", "")))
        scores = {tab.id: len(wanted & _tab_words(tab)) for tab in tabs}
        best = max(scores.values(), default=0)
        matches = [tab for tab in tabs if best and scores[tab.id] == best]
        if not matches:
            return None, f'no open tab matches "{command.get("name", "")}"'
        if len(matches) > 1:
            titles = "; ".join(tab.title[:40] or tab.url[:40] for tab in matches[:3])
            return None, f"several tabs match: {titles}"
        tab = matches[0]
    label = (tab.title or tab.url)[:50]
    return {"type": kind, "tab_id": tab.id}, f'{verb} the tab "{label}"'


# Sites where a plain "search for …" almost always means searching that site.
_SCOPED_BY_DEFAULT = {"youtube"}
_HERE = re.compile(r"\s+(?:here|on\s+this\s+(?:site|page|website))\s*$", re.I)


def _on_search_results(site: str, url: str) -> bool:
    """True on the site's own search results, where a new query refines the search."""
    template = urlparse(SITE_SEARCH[site].format(query="x"))
    page = urlparse(url)
    keys = [key for key, values in parse_qs(template.query).items() if values == ["x"]]
    return page.path.rstrip("/") == template.path.rstrip("/") and any(
        key in parse_qs(page.query) for key in keys
    )


def _current_site_scope(transcript: str, url: str) -> str | None:
    """Search the current site only when that is clearly meant; otherwise search the web."""
    site = site_for_url(url)
    if not site or site not in SITE_SEARCH:
        return None
    if _HERE.search(transcript) or site in _SCOPED_BY_DEFAULT or _on_search_results(site, url):
        return site
    return None


def _numbered_choice(
    intent: str, decision: ModelDecision, snapshot: Snapshot, reasons: list[dict]
) -> PolicyResult | None:
    """Offer the best 2-3 candidates as numbered choices instead of a dead-end clarification."""
    labels = {item.id: item.text or item.placeholder or item.href or item.tag for item in snapshot.elements}
    ids = [item for item in decision.target_candidates if item in labels]
    if len(ids) < 2:
        return None
    template, _ = _build_action(intent, replace(decision, lexical_target=ids[0]), snapshot)
    if not template:
        return None
    template = {key: value for key, value in template.items() if key != "target_id"}
    candidates = [
        {"number": number, "id": element_id, "label": labels[element_id][:60]}
        for number, element_id in enumerate(ids, 1)
    ]
    listing = ", ".join(f"{item['number']}: {item['label']}" for item in candidates)
    return PolicyResult(
        "choose",
        f"which one? say the number ({listing})",
        action=template,
        reasons=reasons,
        candidates=candidates,
    )


def _site_result(
    decision: ModelDecision,
    snapshot: Snapshot,
    *,
    final: bool,
    silent_seconds: float,
    reasons: list[dict],
) -> PolicyResult:
    """A site-pack control: an exact phrase acts; Laya's choice must also be addressed to the browser,
    and account-changing controls it picks are confirmed first."""
    site = decision.site or {}
    action = sites.action_by_id(snapshot.url, str(site.get("id")))
    if action is None:
        return PolicyResult("clarify", "that control is not available on this site", reasons=reasons)
    chosen_by_model = site.get("source") == "model"
    inferred = site.get("source") in {"lexical", "model"}
    if chosen_by_model:
        # Two weak signals together: the speech must be addressed to the browser *and* shaped like a
        # request. Laya alone confidently matches controls in ordinary talk ("my inbox is a disaster").
        spoken = str(decision.state.get("transcript", ""))
        command_ok, command_value = command_gate(decision.answers, spoken)
        requested = sites.looks_like_request(spoken)
        _reason(
            reasons,
            "is_command",
            f"{command_value}; request={requested}",
            THRESHOLDS["is_command"],
            command_ok and requested,
        )
        if not (command_ok and requested):
            return PolicyResult("ignore", "speech is not a browser command", reasons=reasons)
    _reason(reasons, "site_action", f"{action.site}:{action.id} ({site.get('source')})", None, True)
    done = final or silent_seconds >= PAYLOAD_SILENCE_SECONDS
    if not (done or action.instant):
        return PolicyResult("wait", "waiting for the end of the phrase", reasons=reasons)
    do, text = action.do, str(site.get("text", ""))
    if "open" in do:
        built = {"type": "navigate", "url": sites.resolve_open(do["open"], snapshot.url, text)}
    elif "media" in do:
        built = {"type": "media", "command": do["media"]}
    else:
        built = {"type": "site", "site": action.site, "id": action.id, "do": do, "text": text}
    if action.confirm or (inferred and action.side_effect):
        return PolicyResult(
            "confirm", f'say "confirm" to {action.description}', action=built, reasons=reasons
        )
    return PolicyResult("act", action.description, action=built, reasons=reasons)


def command_gate(answers: dict, transcript: str) -> tuple[bool, str]:
    is_command = _probability(answers.get("is_command"))
    # Anything the rules understand ("close the other tabs") is addressed to the browser.
    explicit = explicit_browser_command(transcript) or deterministic_intent(transcript) is not None
    return is_command >= THRESHOLDS["is_command"] or explicit, f"{is_command:.4f}; explicit={explicit}"


def intent_gate(answers: dict, transcript: str, element_match: bool) -> tuple[str, bool, str]:
    intent_answer = answers.get("intent", {})
    rule_intent = deterministic_intent(transcript, element_match=element_match)
    intent = rule_intent or _choice(intent_answer) or "none"
    confidence = _confidence(intent_answer)
    keyword = intent not in _INTENT_KEYWORDS or bool(re.search(_INTENT_KEYWORDS[intent], transcript, re.I))
    ok = intent != "none" and (
        rule_intent is not None or (confidence >= THRESHOLDS["intent_confidence"] and keyword)
    )
    return intent, ok, f"{intent}:{confidence:.4f}; rule={rule_intent is not None}; keyword={keyword}"


def early_intent(transcript: str, element_match: bool) -> bool:
    intent = deterministic_intent(transcript, element_match=element_match)
    if intent == "media":
        return (media_command(transcript) or {}).get("command") in INSTANT_MEDIA
    return intent in EARLY_INTENTS


def complete_gate(
    answers: dict, *, final: bool, silent_seconds: float, early: bool = False
) -> tuple[bool, float]:
    complete = _probability(answers.get("complete"))
    ok = early or complete >= THRESHOLDS["complete"] or final or silent_seconds >= SILENCE_COMPLETE_SECONDS
    return ok, round(complete, 4)


def payload_gate(intent: str, *, final: bool, silent_seconds: float, transcript: str = "") -> bool:
    if intent in {"switch_tab", "close_tab"}:
        # "next tab" / "close this tab" are complete as said; a tab's name or number may still be coming.
        reference = tab_command(transcript) or {}
        if not ("name" in reference or "index" in reference):
            return True
    return intent not in _PAYLOAD_INTENTS or final or silent_seconds >= PAYLOAD_SILENCE_SECONDS


def evaluate(
    decision: ModelDecision,
    snapshot: Snapshot,
    *,
    final: bool,
    silent_seconds: float,
) -> PolicyResult:
    answers = decision.answers
    transcript = str(decision.state.get("transcript", ""))
    reasons: list[dict] = []
    if decision.site:
        return _site_result(decision, snapshot, final=final, silent_seconds=silent_seconds, reasons=reasons)
    command_ok, command_value = command_gate(answers, transcript)
    _reason(reasons, "is_command", command_value, THRESHOLDS["is_command"], command_ok)
    if not command_ok:
        return PolicyResult("ignore", "speech is not a browser command", reasons=reasons)

    intent, intent_ok, intent_value = intent_gate(answers, transcript, decision.element_match)
    _reason(reasons, "intent", intent_value, THRESHOLDS["intent_confidence"], intent_ok)
    if not intent_ok:
        return PolicyResult("wait", "waiting for a confident command", reasons=reasons)

    complete_ok, complete = complete_gate(
        answers,
        final=final,
        silent_seconds=silent_seconds,
        early=early_intent(transcript, decision.element_match),
    )
    _reason(reasons, "complete", complete, THRESHOLDS["complete"], complete_ok)
    if not complete_ok:
        return PolicyResult("wait", "waiting for the rest of the command", reasons=reasons)

    if intent in _PAYLOAD_INTENTS:
        payload_ok = payload_gate(intent, final=final, silent_seconds=silent_seconds, transcript=transcript)
        _reason(reasons, "payload_final", round(silent_seconds, 3), PAYLOAD_SILENCE_SECONDS, payload_ok)
        if not payload_ok:
            return PolicyResult("wait", "waiting for the end of the dictated text", reasons=reasons)

    action, summary = _build_action(intent, decision, snapshot)
    if not action:
        # Mid-speech the missing piece may still be coming; only ask once the speaker has stopped.
        done = final or silent_seconds >= SILENCE_COMPLETE_SECONDS
        if done and summary == _AMBIGUOUS:
            choice_result = _numbered_choice(intent, decision, snapshot, reasons)
            if choice_result:
                return choice_result
        return PolicyResult("clarify" if done else "wait", summary, reasons=reasons)

    destructive_score = _probability(answers.get("destructive"))
    page_action = action["type"] in _PAGE_ACTIONS
    safe_link = ordinary_navigation_link(action, snapshot)
    destructive = action["type"] == "close_other_tabs" or (
        page_action
        and not safe_link
        and (destructive_score >= THRESHOLDS["destructive"] or deterministic_destructive(action, snapshot))
    )
    destructive_value = f"{destructive_score:.4f}; page_action={page_action}; ordinary_link={safe_link}"
    _reason(reasons, "destructive", destructive_value, THRESHOLDS["destructive"], not destructive)
    if destructive:
        return PolicyResult("confirm", f'say "confirm" to {summary}', action=action, reasons=reasons)
    return PolicyResult("act", summary, action=action, reasons=reasons)
