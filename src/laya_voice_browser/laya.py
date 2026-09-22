from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import sites
from .answers import _choice, _confidence, _probability
from .policy import command_gate, complete_gate, early_intent, intent_gate, payload_gate
from .questions import (
    DETAIL_QUESTIONS,
    MAX_PAGE_TEXT,
    MAX_RECENT_ACTIONS,
    MAX_STATE_ELEMENTS,
    MAX_TARGET_OPTIONS,
    MODEL_DEFAULT,
    fixed_questions,
    span_question,
    target_question,
)
from .spans import (
    deterministic_intent,
    explicit_browser_command,
    explicit_payload,
    mentioned_site,
    spoken_scroll_amount,
    spoken_tab_direction,
    strip_lead,
    tab_command,
    text_candidates,
    universal_command,
    url_candidates,
)
from .types import Element, ModelDecision, Snapshot

_WORD = re.compile(r"[a-z0-9]+", re.I)
_STOP = {
    "a", "an", "and", "button", "click", "for", "go", "in", "link", "of", "on", "open", "page",
    "please", "tab", "that", "the", "this", "to",
}
_MIN_STATE_ELEMENTS = 4
# How sure Laya must be that a site control is meant before it is used.
SITE_ACTION_PROBABILITY = 0.5
# "Is this a command?" and "which operation?" depend on the words, not the page body: a slim state
# halves their latency and scored at least as well on the command set.
_GATE_ELEMENTS = 4
_PREFIX_CACHE_LIMIT = 512
_MLX_CACHE_LIMIT_BYTES = 64 * 1024 * 1024


_FILLABLE_ROLES = {"input", "textbox", "combobox", "searchbox", "textarea", "select"}


def _words(text: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(text)}


def _label_matches(words: set[str], item: Element) -> int:
    """Transcript words found in the label, including inside joined words ("turingarchive")."""
    label = _words(f"{item.text} {item.placeholder}")
    return sum(
        1 for word in words if word in label or (len(word) >= 4 and any(word in part for part in label))
    )


def _rank_elements(
    transcript: str, elements: tuple[Element, ...], *, fillable: bool = False
) -> tuple[list[Element], bool, str | None]:
    """Rank elements by relevance and return (ranked, any_label_match, clear_lexical_target).

    The clear target is the single best label match when no element with a different destination
    matches as well; ties go to Laya instead.
    """
    words = _words(transcript) - _STOP
    if fillable:
        elements = tuple(
            item for item in elements if item.role in _FILLABLE_ROLES or item.tag in _FILLABLE_ROLES
        )
    matches = {item.id: _label_matches(words, item) for item in elements}
    # Among equal matches, prefer the label with fewest extra words: "Images" over "More Images".
    precision = {
        item.id: matches[item.id] / max(1, len(_words(f"{item.text} {item.placeholder}")))
        for item in elements
    }

    def score(item: Element) -> tuple[float, float]:
        overlap = matches[item.id] * 5 + len(words & _words(item.href)) * 2
        main = 2 if item.in_main else 0
        result_link = 1 if "result" in words and item.role == "link" else 0
        return (overlap + main + result_link, -item.top)

    ranked = sorted(elements, key=score, reverse=True)
    best = max(matches.values(), default=0)
    clear = None
    if best:
        best_precision = max(precision[item.id] for item in ranked if matches[item.id] == best)
        tied = [
            item for item in ranked if matches[item.id] == best and precision[item.id] == best_precision
        ]
        destinations = {item.href or item.id for item in tied}
        if len(destinations) == 1:
            clear = tied[0].id
    elif fillable and len(ranked) == 1:
        clear = ranked[0].id
    return ranked, best > 0, clear


def _best_label_matches(transcript: str, elements: list[Element]) -> list[str]:
    """Ids of the elements tied for the most transcript words in their label."""
    words = _words(transcript) - _STOP
    scores = {item.id: _label_matches(words, item) for item in elements}
    best = max(scores.values(), default=0)
    return [item.id for item in elements if best and scores[item.id] == best]


def _short_url(url: str, page_host: str = "") -> str:
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/")
    if host and host == page_host:
        return (path or "/")[:40]
    return f"{host}{path}"[:48]


def _element_label(element: Element, page_host: str) -> str:
    return (
        element.text
        or element.placeholder
        or element.value
        or _short_url(element.href, page_host)
        or element.tag
    )[:40]


def _element_line(element: Element, page_host: str) -> str:
    href = f" {_short_url(element.href, page_host)}" if element.href else ""
    return f'{element.id} {element.role} "{_element_label(element, page_host)}"{href}'


_MODEL_FILES = [
    "model.safetensors", "rl_agent_config.json", "encoder/config.json", "tokenizer/*", "mlx_config.json",
]


def _cached_model(name: str) -> str:
    """The downloaded copy of a Hub model, found without the network (72 ms instead of ~390 ms, and
    no stall when offline). Falls back to the name, so the first run downloads it as usual."""
    if Path(name).expanduser().exists():
        return name
    try:
        from huggingface_hub import snapshot_download

        return snapshot_download(name, allow_patterns=_MODEL_FILES, local_files_only=True)
    except Exception:
        return name


def _gate_state(state: dict) -> dict:
    """The first-stage view: transcript, page, the few most relevant elements and recent actions."""
    slim = {key: value for key, value in state.items() if key != "visible_page_text"}
    slim["interactive_elements"] = state.get("interactive_elements", [])[:_GATE_ELEMENTS]
    return slim


def _recent_lines(history: list[dict[str, Any]]) -> list[str]:
    lines = []
    for item in history[-MAX_RECENT_ACTIONS:]:
        action = item.get("action") or {}
        detail = action.get("url") or action.get("target_id") or action.get("direction") or ""
        after = _short_url(str((item.get("outcome") or {}).get("after_url", "")))
        lines.append(f'"{str(item.get("said", ""))[:60]}" -> {action.get("type")} {detail} -> {after}')
    return lines


def _target_options(elements: list[Element], page_host: str) -> dict[str, str]:
    """Unique "label (role)" option text -> element id. Laya chose labels far better than bare ids."""
    options: dict[str, str] = {}
    for item in elements:
        label = f"{_element_label(item, page_host)} ({item.role})"
        suffix = 2
        while label in options:
            label = f"{_element_label(item, page_host)} ({item.role} {suffix})"
            suffix += 1
        options[label] = item.id
    return options


def _label_answer_to_ids(answer: dict, labels: dict[str, str]) -> dict:
    """Rewrite a label-keyed target answer so the policy sees element ids."""
    if not isinstance(answer, dict):
        return answer
    remap = {**labels, "none": "none"}
    result = dict(answer)
    if answer.get("choice") in remap:
        result["choice"] = remap[answer["choice"]]
    if isinstance(answer.get("probabilities"), dict):
        result["probabilities"] = {remap.get(k, k): v for k, v in answer["probabilities"].items()}
    return result


class LayaEngine:
    """One warmed, process-local Laya-MLX model guarded for concurrent transcript updates.

    Every question is a separate model pass over [question + options + state], capped at 512 tokens,
    so latency scales with the number of questions and state is trimmed to fit instead of being cut
    silently by laya-mlx.
    """

    def __init__(self, model: str | None = None) -> None:
        self.model_name = model or os.getenv("LAYA_MODEL", MODEL_DEFAULT)
        self._agent: Any | None = None
        self._lock = threading.Lock()
        self._prefix_lengths: dict[str, int] = {}

    @property
    def loaded(self) -> bool:
        return self._agent is not None

    def warm(self) -> None:
        with self._lock:
            if self._agent is not None:
                return
            import laya_mlx as laya
            import mlx.core as mx

            # MLX keeps freed GPU buffers for reuse and, uncapped, grew past 1.8 GB in a background
            # process that is idle most of the time; 64 MB costs about 1 ms per decision.
            mx.set_cache_limit(_MLX_CACHE_LIMIT_BYTES)
            self._agent = laya.load(
                _cached_model(self.model_name),
                dtype=os.getenv("LAYA_DTYPE", "float16"),
                batch_size=int(os.getenv("LAYA_BATCH_SIZE", "16")),
                compile=os.getenv("LAYA_COMPILE", "0") == "1",
                cache_prompts=True,
            )
        self._prime()

    def _prime(self) -> None:
        """Run one throwaway decision so the first real command does not pay kernel warm-up."""
        try:
            page = Snapshot("https://example.com/", "Example", "", (Element("e01", "link", "More", "a"),), "")
            self.decide("click more", page, final=False, silent_seconds=0.0)
        except Exception:
            pass

    def _prefix_length(self, question: dict) -> int:
        from laya_mlx.common import build_prefix

        key = json.dumps(question, sort_keys=True, ensure_ascii=False)
        if key not in self._prefix_lengths:
            if len(self._prefix_lengths) >= _PREFIX_CACHE_LIMIT:
                self._prefix_lengths.clear()
            ids, _ = build_prefix(
                self._agent.tok,
                self._agent._to_internal(question),
                self._agent.cfg.get("head_max_len", 192),
            )
            self._prefix_lengths[key] = len(ids)
        return self._prefix_lengths[key]

    def _state_tokens(self, state: dict) -> int:
        from laya_mlx.common import serialize_state

        tok = self._agent.tok
        text = serialize_state(state).replace(tok.mask_token, " ")
        return len(tok(text, add_special_tokens=False)["input_ids"])

    def _fit(self, state: dict, budget: int) -> tuple[dict, int, list[str]]:
        """Trim the least useful state first: page text, then extra elements, then history."""
        state = {**state, "interactive_elements": list(state.get("interactive_elements", []))}
        elements = state["interactive_elements"]
        trimmed: set[str] = set()
        tokens = self._state_tokens(state)
        while tokens > budget:
            if state.get("visible_page_text"):
                text = state["visible_page_text"]
                cut = (tokens - budget) * 4 + 16
                state["visible_page_text"] = text[:-cut] if cut < len(text) else ""
                if not state["visible_page_text"]:
                    del state["visible_page_text"]
                trimmed.add("visible_page_text")
            elif len(elements) > _MIN_STATE_ELEMENTS:
                elements.pop()
                trimmed.add("interactive_elements")
            elif state.get("recent_actions"):
                state["recent_actions"] = state["recent_actions"][1:]
                if not state["recent_actions"]:
                    del state["recent_actions"]
                trimmed.add("recent_actions")
            elif elements:
                elements.pop()
                trimmed.add("interactive_elements")
            else:
                break
            tokens = self._state_tokens(state)
        return state, tokens, sorted(trimmed)

    def _run(self, state: dict, questions: dict, answers: dict, stages: list[dict]) -> None:
        max_len = self._agent.cfg.get("max_len", 512)
        budget = max_len - max(self._prefix_length(q) for q in questions.values()) - 1
        fitted, tokens, trimmed = self._fit(state, budget)
        started = time.perf_counter()
        with self._lock:
            result = self._agent.predict(fitted, questions)
        elapsed = (time.perf_counter() - started) * 1000
        answers.update(result.get("answers", {}) if isinstance(result, dict) else {})
        stages.append(
            {
                "questions": list(questions),
                "ms": round(elapsed, 2),
                "state_tokens": tokens,
                "state_budget": budget,
                "trimmed": trimmed,
            }
        )

    def _state(
        self, transcript: str, snapshot: Snapshot, recent_actions: list[dict[str, Any]] | None
    ) -> tuple[dict, list[Element], bool, str]:
        page_host = urlparse(snapshot.url).netloc.removeprefix("www.")
        ranked, element_match, _ = _rank_elements(transcript, snapshot.elements)
        # Most useful first, so _fit trims from the end. Key names follow the original schema: Laya's
        # completeness and intent heads scored noticeably worse with shorter names on the smoke set.
        state: dict[str, Any] = {
            "transcript": transcript,
            "safari": {"url": _short_url(snapshot.url), "title": snapshot.title[:80]},
            "interactive_elements": [_element_line(item, page_host) for item in ranked[:MAX_STATE_ELEMENTS]],
        }
        recent = _recent_lines(recent_actions or [])
        if recent:
            state["recent_actions"] = recent
        if snapshot.text:
            state["visible_page_text"] = snapshot.text[:MAX_PAGE_TEXT]
        return state, ranked, element_match, page_host

    def ask(
        self,
        transcript: str,
        snapshot: Snapshot,
        question_ids: list[str],
        *,
        recent_actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Ask specific fixed questions directly, bypassing staging; for evaluation scripts."""
        self.warm()
        state, _, _, _ = self._state(transcript[-400:], snapshot, recent_actions)
        state = _gate_state(state)
        fixed = fixed_questions()
        answers: dict[str, Any] = {}
        self._run(state, {qid: fixed[qid] for qid in question_ids}, answers, [])
        return answers

    def decide(
        self,
        transcript: str,
        snapshot: Snapshot,
        *,
        recent_actions: list[dict[str, Any]] | None = None,
        final: bool = False,
        silent_seconds: float = 0.0,
    ) -> ModelDecision:
        self.warm()
        transcript = transcript[-400:]
        state, ranked, element_match, page_host = self._state(transcript, snapshot, recent_actions)
        text_spans = text_candidates(transcript)
        urls = url_candidates(transcript)
        fixed = fixed_questions()
        answers: dict[str, Any] = {}
        stages: list[dict] = []

        # Grammar first: a pack may implement "pause" better than the generic path, but it may not
        # turn "go back" into Google's previous page of results.
        universal = universal_command(transcript)
        # A site control named exactly ("theater mode" on YouTube) needs no model at all.
        exact = None if universal else sites.match_phrase(strip_lead(transcript), snapshot.url)
        if exact:
            return ModelDecision(
                answers={},
                candidates={"text": text_spans, "url": urls},
                latency_ms=0.0,
                model=self.model_name,
                state=state,
                element_match=element_match,
                site={"id": exact.action.id, "text": exact.text, "source": "rule"},
            )
        # Something named on the page wins over a general site control: "toggle the table of contents"
        # is the button with that label, not Wikipedia's "scroll to the top" control.
        _, _, clear_element = _rank_elements(transcript, snapshot.elements)
        skip_pack = universal or clear_element
        lexical = None if skip_pack else sites.lexical_match(transcript, snapshot.url)
        if lexical:
            return ModelDecision(
                answers={},
                candidates={"text": text_spans, "url": urls},
                latency_ms=0.0,
                model=self.model_name,
                state=state,
                element_match=element_match,
                site={"id": lexical.action.id, "text": lexical.text, "source": "lexical"},
            )
        pack = sites.pack_for(snapshot.url)

        # Stage 1: only the gate questions that explicit grammar has not already settled.
        gate = {}
        if not explicit_browser_command(transcript):
            gate["is_command"] = fixed["is_command"]
        if deterministic_intent(transcript, element_match=element_match) is None:
            gate["intent"] = fixed["intent"]
        early = early_intent(transcript, element_match)
        if not final and not early:
            gate["complete"] = fixed["complete"]
        unnamed = deterministic_intent(transcript, element_match=element_match) is None
        if pack and not clear_element and unnamed:
            site_question, site_candidates = sites.site_question(pack, transcript)
            if site_candidates:
                gate["site_action"] = site_question
        if gate:
            self._run(_gate_state(state), gate, answers, stages)

        site_answer = answers.get("site_action") or {}
        site_choice = _choice(site_answer)
        site_probability = float((site_answer.get("probabilities") or {}).get(site_choice, 0.0))
        if site_choice and site_choice != "none" and site_probability >= SITE_ACTION_PROBABILITY:
            return ModelDecision(
                answers=answers,
                candidates={"text": text_spans, "url": urls},
                latency_ms=round(sum(stage["ms"] for stage in stages), 2),
                model=self.model_name,
                state=state,
                element_match=element_match,
                stages=stages,
                site={"id": site_choice, "text": "", "source": "model", "probability": site_probability},
            )

        # Stage 2: the questions this intent needs, only once the policy would act on them.
        intent, intent_ok, _ = intent_gate(answers, transcript, element_match)
        ready = (
            intent_ok
            and command_gate(answers, transcript)[0]
            and complete_gate(answers, final=final, silent_seconds=silent_seconds, early=early)[0]
            and payload_gate(intent, final=final, silent_seconds=silent_seconds, transcript=transcript)
        )
        lexical_target = None
        target_candidates: list[str] = []
        if ready:
            target_labels: dict[str, str] = {}
            if "target" in DETAIL_QUESTIONS.get(intent, ()):
                fillable = intent in {"type_into_field", "select_option"}
                candidates, _, lexical_target = _rank_elements(
                    transcript, snapshot.elements, fillable=fillable
                )
                if not lexical_target:
                    target_labels = _target_options(candidates[:MAX_TARGET_OPTIONS], page_host)
            details = self._detail_questions(intent, transcript, fixed, text_spans, urls, target_labels)
            if details:
                self._run(state, details, answers, stages)
            if "target" in answers:
                answers["target"] = _label_answer_to_ids(answers["target"], target_labels)
                probabilities = answers["target"].get("probabilities") or {}
                ranked_ids = sorted(
                    (key for key in probabilities if key != "none"), key=lambda key: -probabilities[key]
                )
                # Tied label matches are the real alternatives; Laya's ranking fills any gap.
                tied = _best_label_matches(transcript, candidates[:MAX_TARGET_OPTIONS])
                likely = [key for key in ranked_ids if probabilities[key] >= 0.08]
                target_candidates = list(dict.fromkeys([*tied, *likely]))[:3]

        return ModelDecision(
            answers=answers,
            candidates={"text": text_spans, "url": urls},
            latency_ms=round(sum(stage["ms"] for stage in stages), 2),
            model=self.model_name,
            state=state,
            element_match=element_match,
            stages=stages,
            lexical_target=lexical_target,
            target_candidates=target_candidates,
        )

    @staticmethod
    def _detail_questions(
        intent: str,
        transcript: str,
        fixed: dict,
        text_spans: list[str],
        urls: list[str],
        target_labels: dict[str, str],
    ) -> dict:
        questions = {}
        for qid in DETAIL_QUESTIONS.get(intent, ()):
            if qid == "url_span" and len(urls) > 1:
                questions[qid] = span_question(qid, urls)
            elif qid == "site" and not urls and not mentioned_site(transcript):
                questions[qid] = fixed["site"]
            elif qid == "text_span" and text_spans and not explicit_payload(transcript):
                questions[qid] = span_question(qid, text_spans)
            elif qid == "target" and target_labels:
                questions[qid] = target_question(list(target_labels))
            elif qid == "scroll_amount" and spoken_scroll_amount(transcript, "down") is None:
                questions[qid] = fixed[qid]
            elif qid == "tab_direction" and not (spoken_tab_direction(transcript) or tab_command(transcript)):
                questions[qid] = fixed[qid]
            elif qid == "destructive":
                questions[qid] = fixed[qid]
        return questions


__all__ = ["LayaEngine", "_choice", "_confidence", "_probability"]
