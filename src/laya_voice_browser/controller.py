from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote_plus, urlparse

from .browser import Browser, BrowserSessionLost, StalePage, Unavailable
from .laya import LayaEngine
from .policy import evaluate
from .questions import DEBOUNCE_SECONDS, SITE_SEARCH
from .safety import deterministic_destructive
from .spans import (
    command_plan,
    remainder_after,
    repair_speech,
    spoken_number,
    strip_lead,
)
from .status import action_kind
from .types import PolicyResult, Snapshot, TranscriptEvent

PENDING_TTL_SECONDS = 10.0
CHOICE_TTL_SECONDS = 12.0
MAX_CONSUMED_UTTERANCES = 32
_CONFIRM = {"confirm", "yes", "yes confirm", "do it", "go ahead"}
_CANCEL = {"cancel", "no", "never mind", "stop"}


def google_blocked(url: str) -> bool:
    """Google's "unusual traffic" page (google.com/sorry/…)."""
    parsed = urlparse(url)
    return ".google." in f".{parsed.hostname or ''}" and parsed.path.startswith("/sorry")


def _unconsumed(text: str, consumed: str) -> str | None:
    """What is left of `text` after an already-executed prefix, also when one side has had its
    opener ("and can you …") removed by the command planner and the other has not."""
    for said, done in ((text, consumed), (text, strip_lead(consumed, polite=True)),
                       (strip_lead(text, polite=True), strip_lead(consumed, polite=True))):
        remainder = remainder_after(said, done)
        if remainder is not None:
            return remainder
    return None


def _browser_problem(exc: Exception) -> str:
    """A short island label for why the browser could not be used."""
    if "connecting to a Safari instance" in str(exc):
        return "Restart Safari"
    return "Browser failed"


def endpoint_hint(policy: PolicyResult) -> str | None:
    """How finished a mid-sentence phrase sounds, for the app's adaptive end-of-phrase timing."""
    if policy.verdict in {"act", "confirm", "choose"}:
        return "complete"
    failed = next((reason["name"] for reason in policy.reasons if not reason["passed"]), None)
    if failed == "payload_final":
        return "likely_complete"  # the command is clear; the dictated text may still be going
    if policy.verdict == "wait":
        return "incomplete"
    return None


@dataclass(frozen=True)
class PendingAction:
    action: dict[str, Any]
    fingerprint: str
    created_at: float
    expires_at: float


@dataclass(frozen=True)
class PendingChoice:
    """Numbered on-page candidates waiting for a spoken number."""

    template: dict[str, Any]
    candidates: list[dict[str, Any]]
    fingerprint: str
    snapshot: Snapshot
    expires_at: float


class StreamingController:
    """Serialize every Safari/model operation while accepting streaming transcript updates."""

    def __init__(
        self,
        browser: Browser,
        engine: LayaEngine,
        *,
        trace_path: Path | None = None,
        announce: Callable[[str], None] = print,
        status: Callable[..., None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.browser = browser
        self.engine = engine
        self.trace_path = trace_path
        self.announce = announce
        self._status_sink = status
        self._clock = clock
        self._lock = threading.RLock()
        self._idle = threading.Condition(self._lock)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="laya-browser")
        self._timer: threading.Timer | None = None
        self._generation = 0
        self._inflight_jobs = 0
        self._pending: PendingAction | None = None
        self._choice: PendingChoice | None = None
        self.session_lost = False
        self._consumed: OrderedDict[str, str] = OrderedDict()
        self.history: list[dict[str, Any]] = []
        self.last_policy: PolicyResult | None = None

    def submit(self, event: TranscriptEvent) -> None:
        text = repair_speech(event.text)
        if not text or self.session_lost:
            return
        with self._lock:
            consumed = self._consumed.get(event.utterance_id)
        remainder = _unconsumed(text, consumed) if consumed else None
        if remainder is not None:
            if len(remainder.split()) < 2:
                return
            text = remainder
            event = TranscriptEvent(
                text=text,
                final=event.final,
                utterance_id=event.utterance_id,
                at=event.at,
            )

        lowered = text.casefold().strip(" .!?")
        job: tuple[Callable, tuple] | None = None
        clear_badges = False
        with self._lock:
            self._expire_pending_locked()
            number = None
            if self._choice and self._clock() > self._choice.expires_at:
                self._choice = None
                clear_badges = True
            if self._choice:
                number = spoken_number(text, len(self._choice.candidates))
                if number is None and event.final:
                    # Something else was said: drop the numbers and treat it as a new command.
                    self._choice = None
                    clear_badges = True
            if number is not None:
                choice = self._choice
                self._choice = None
                self._generation += 1
                job = (self._execute_choice, (choice, number, event))
            elif self._pending and lowered in _CONFIRM:
                pending = self._pending
                self._pending = None
                self._generation += 1
                job = (self._execute_pending, (pending, event))
            elif self._pending and lowered in _CANCEL:
                self._pending = None
                self._generation += 1
                self.announce("cancelled pending action")
                self._status("listening")
                return
            elif lowered in _CONFIRM | _CANCEL:
                self.announce("no pending action to confirm or cancel")
                return
            else:
                self._generation += 1
                generation = self._generation
                if self._timer:
                    self._timer.cancel()
                clauses = command_plan(text) if event.final else [text]
                if len(clauses) > 1:
                    job = (self._evaluate_chain, (generation, clauses, event))
                else:
                    if event.final and clauses and clauses[0] != text:
                        event = TranscriptEvent(
                            text=clauses[0],
                            final=True,
                            utterance_id=event.utterance_id,
                            at=event.at,
                        )
                    delay = 0.0 if event.final else DEBOUNCE_SECONDS
                    self._timer = threading.Timer(
                        delay, self._queue_evaluation, args=(generation, event)
                    )
                    self._timer.daemon = True
                    self._timer.start()
        if clear_badges:
            self._submit_job(self._clear_badges)
        if job:
            self._submit_job(job[0], *job[1])
        self.announce(f'heard{" (final)" if event.final else ""}: {text}')

    def _queue_evaluation(self, generation: int, event: TranscriptEvent) -> None:
        self._submit_job(self._evaluate, generation, event)

    def _evaluate_chain(
        self, generation: int, clauses: list[str], source_event: TranscriptEvent
    ) -> None:
        self.announce(f"command chain: {' -> '.join(clauses)}")
        for index, clause in enumerate(clauses):
            with self._lock:
                if generation != self._generation:
                    return
            event = TranscriptEvent(
                text=clause,
                final=True,
                utterance_id=f"{source_event.utterance_id}:{index}",
                at=source_event.at,
            )
            policy = self._evaluate(generation, event)
            if policy is None or policy.verdict != "act":
                if index + 1 < len(clauses):
                    self.announce(f"stopped before: {' -> '.join(clauses[index + 1 :])}")
                return

    def _submit_job(self, function: Callable, *args) -> None:
        with self._lock:
            self._inflight_jobs += 1

        def run() -> None:
            try:
                function(*args)
            except BrowserSessionLost as exc:
                self._on_session_lost(exc)
            finally:
                with self._lock:
                    self._inflight_jobs -= 1
                    self._idle.notify_all()

        self._executor.submit(run)

    def _evaluate(self, generation: int, event: TranscriptEvent) -> PolicyResult | None:
        with self._lock:
            if generation != self._generation:
                return
            consumed = self._consumed.get(event.utterance_id)
            remainder = _unconsumed(event.text, consumed) if consumed else None
            if remainder is not None:
                if len(remainder.split()) < 2:
                    return None
                event = TranscriptEvent(
                    text=remainder,
                    final=event.final,
                    utterance_id=event.utterance_id,
                    at=event.at,
                )
        stage_started = time.perf_counter()
        if event.final:
            self._status("thinking")
        try:
            snapshot_started = time.perf_counter()
            snapshot = self.browser.snapshot()
            snapshot_ms = (time.perf_counter() - snapshot_started) * 1000
            decision = self.engine.decide(
                event.text,
                snapshot,
                recent_actions=self.history,
                final=event.final,
                silent_seconds=max(0.0, self._clock() - event.at),
            )
            decision_ready = time.perf_counter()
            with self._lock:
                if generation != self._generation:
                    self._trace(
                        {
                            "at": self._clock(),
                            "transcript": event.text,
                            "discarded": "newer transcript arrived",
                            "latency_ms": decision.latency_ms,
                        }
                    )
                    return None
            silent = max(0.0, self._clock() - event.at)
            policy_started = time.perf_counter()
            policy = evaluate(decision, snapshot, final=event.final, silent_seconds=silent)
            policy_ms = (time.perf_counter() - policy_started) * 1000
            self.last_policy = policy
            speech_to_decision_ms = max(0.0, (self._clock() - event.at) * 1000)
            self.announce(f"Laya {decision.latency_ms:.1f} ms -> {policy.verdict}: {policy.summary}")
            record = {
                "at": self._clock(),
                "transcript": event.text,
                "final": event.final,
                "model": decision.model,
                "timing": {
                    "speech_to_decision_ms": round(speech_to_decision_ms, 2),
                    "queue_and_snapshot_ms": round(snapshot_ms, 2),
                    "model_ms": decision.latency_ms,
                    "policy_ms": round(policy_ms, 2),
                    "total_stage_ms": round((decision_ready - stage_started) * 1000 + policy_ms, 2),
                },
                "stages": decision.stages,
                "answers": decision.answers,
                "policy": {
                    "verdict": policy.verdict,
                    "summary": policy.summary,
                    "action": policy.action,
                    "reasons": policy.reasons,
                },
                "page": {"url": snapshot.url, "title": snapshot.title, "fingerprint": snapshot.fingerprint},
            }
            self._trace(record)
            if not event.final:
                self._endpoint(endpoint_hint(policy))
            if policy.verdict == "confirm" and policy.action:
                self._status("confirm", ttl=PENDING_TTL_SECONDS)
                now = self._clock()
                with self._lock:
                    self._pending = PendingAction(
                        action=policy.action,
                        fingerprint=snapshot.fingerprint,
                        created_at=now,
                        expires_at=now + PENDING_TTL_SECONDS,
                    )
            elif policy.verdict == "act" and policy.action:
                self._execute(
                    policy.action,
                    event,
                    fingerprint=snapshot.fingerprint,
                    decision_ready=decision_ready,
                )
            elif policy.verdict == "choose" and policy.action:
                self._status("choose", ttl=CHOICE_TTL_SECONDS)
                with self._lock:
                    self._choice = PendingChoice(
                        template=policy.action,
                        candidates=policy.candidates,
                        fingerprint=snapshot.fingerprint,
                        snapshot=snapshot,
                        expires_at=self._clock() + CHOICE_TTL_SECONDS,
                    )
                show = getattr(self.browser, "show_candidates", None)
                if show:
                    show([(item["number"], item["id"]) for item in policy.candidates])
            elif policy.verdict == "clarify":
                self._status("unsure", ttl=2.0)
            elif event.final:
                self._status("listening")
            return policy
        except BrowserSessionLost:
            raise
        except Exception as exc:
            if "Safari" in str(exc) or "browser" in str(exc).casefold():
                self._report_browser_problem(exc)
            else:
                self._status("error", ttl=2.5)
            self.announce(f"error: {type(exc).__name__}: {str(exc)[:300]}")
            self._trace(
                {
                    "at": self._clock(),
                    "transcript": event.text,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return None

    def _execute_choice(self, choice: PendingChoice, number: int, event: TranscriptEvent) -> None:
        picked = choice.candidates[number - 1]
        action = {**choice.template, "target_id": picked["id"]}
        self._clear_badges()
        if deterministic_destructive(action, choice.snapshot):
            now = self._clock()
            with self._lock:
                self._pending = PendingAction(action, choice.fingerprint, now, now + PENDING_TTL_SECONDS)
            self._status("confirm", ttl=PENDING_TTL_SECONDS)
            self.announce(f'say "confirm" to {action["type"]} {picked["label"]!r}')
            return
        self.announce(f"picked {number}: {picked['label']}")
        self._execute(action, event, fingerprint=choice.fingerprint, decision_ready=time.perf_counter())

    def _clear_badges(self) -> None:
        clear = getattr(self.browser, "clear_candidates", None)
        if clear:
            try:
                clear()
            except BrowserSessionLost:
                raise
            except Exception:
                pass

    def _on_session_lost(self, exc: Exception) -> None:
        with self._lock:
            if self.session_lost:
                return
            self.session_lost = True
            if self._timer:
                self._timer.cancel()
        self._status("error", label="Browser closed", ttl=4.0)
        self.announce(f"browser session ended ({exc}); restart laya-voice-browser to continue")
        self._trace({"at": self._clock(), "session_lost": str(exc)})

    def _execute_pending(self, pending: PendingAction, event: TranscriptEvent) -> None:
        if self._clock() > pending.expires_at:
            self.announce("confirmation expired; no action executed")
            return
        self._execute(
            pending.action,
            event,
            fingerprint=pending.fingerprint,
            confirmed=True,
            decision_ready=time.perf_counter(),
        )

    def _execute(
        self,
        action: dict[str, Any],
        event: TranscriptEvent,
        *,
        fingerprint: str,
        decision_ready: float,
        confirmed: bool = False,
    ) -> None:
        execution_started = time.perf_counter()
        self._status("acting", kind=action_kind(action))
        try:
            outcome = self.browser.execute(action, expected_fingerprint=fingerprint)
        except StalePage:
            self._status("unsure", label="Page changed", ttl=2.0)
            self.announce("the page changed before execution; discarded the stale decision")
            return
        except Unavailable as exc:
            self._status("unsure", label="Not on this page", ttl=2.0)
            self.announce(str(exc))
            return
        finished = time.perf_counter()
        item = {
            "said": event.text,
            "action": action,
            "confirmed": confirmed,
            "outcome": outcome,
            "at": self._clock(),
            "timing": {
                "decision_to_execution_ms": round((execution_started - decision_ready) * 1000, 2),
                "execution_ms": round((finished - execution_started) * 1000, 2),
                "speech_to_result_ms": round(max(0.0, (self._clock() - event.at) * 1000), 2),
            },
        }
        with self._lock:
            had_choice = self._choice is not None
            self._choice = None
            self.history.append(item)
            self.history = self.history[-10:]
            self._consumed[event.utterance_id] = event.text
            self._consumed.move_to_end(event.utterance_id)
            while len(self._consumed) > MAX_CONSUMED_UTTERANCES:
                self._consumed.popitem(last=False)
        if had_choice:
            self._clear_badges()
        if google_blocked(outcome.get("after_url", "")) and self._recover_from_google_check(action):
            return
        self._status("done", ttl=1.2)
        self.announce(f"executed: {action['type']} -> {outcome['after_url']}")
        self._trace({"execution": item})

    def prepare_browser(self) -> None:
        """Have a working browser ready before the first command (e.g. when voice control turns on):
        open one if there is none, and replace one whose session was stopped or closed."""
        ensure = getattr(self.browser, "ensure_alive", None) or getattr(self.browser, "ensure", None)
        if ensure:
            self._submit_job(self._prepare_browser, ensure)

    def _prepare_browser(self, ensure: Callable[[], Any]) -> None:
        try:
            ensure()
        except Exception as exc:
            self._report_browser_problem(exc)

    def _report_browser_problem(self, exc: Exception) -> None:
        label = _browser_problem(exc)
        self._status("error", label=label, ttl=5.0)
        if label == "Restart Safari":
            self.announce(
                "Safari is still tied to an earlier automation session. Quit Safari (⌘Q) and "
                "double-tap again; Safari reopens your windows if 'Safari opens with' is set to "
                "'All windows from last session'."
            )
        else:
            self.announce(f"could not open the browser: {exc}")

    def _endpoint(self, hint: str | None) -> None:
        sink = getattr(self._status_sink, "endpoint", None)
        if hint and sink:
            try:
                sink(hint)
            except Exception:
                pass

    def _status(self, state: str, **details: Any) -> None:
        """Mirror progress on the notch island; never let display problems affect control."""
        if self._status_sink:
            try:
                self._status_sink(state, **details)
            except Exception:
                pass

    def _recover_from_google_check(self, action: dict[str, Any]) -> bool:
        """Google answered a search with its "unusual traffic" check. In Safari's automation window it
        cannot be solved, so run the same search on DuckDuckGo; elsewhere, ask the user to solve it."""
        self.announce(f"executed: {action['type']} -> Google's \"unusual traffic\" check")
        query = parse_qs(urlparse(str(action.get("url", ""))).query).get("q", [""])[0]
        if getattr(self.browser, "key", None) == "safari" and query:
            self.announce("Google's check cannot be solved in Safari's automation window; using DuckDuckGo")
            self._status("acting", kind="search", label="Using DuckDuckGo")
            fallback = SITE_SEARCH["duckduckgo"].format(query=quote_plus(query))
            self.browser.execute({"type": "navigate", "url": fallback})
            self._status("done", ttl=1.2)
        else:
            self._status("confirm", label="Solve Google's check", ttl=10.0)
        return True

    def _expire_pending_locked(self) -> None:
        if self._pending and self._clock() > self._pending.expires_at:
            self._pending = None
            self.announce("confirmation expired")

    def _trace(self, value: dict[str, Any]) -> None:
        if not self.trace_path:
            return
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")

    def wait_idle(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        with self._idle:
            while True:
                timer_alive = bool(self._timer and self._timer.is_alive())
                if self._inflight_jobs == 0 and not timer_alive:
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for the current decision")
                self._idle.wait(timeout=min(remaining, 0.1))

    def close(self) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
        self._executor.shutdown(wait=True, cancel_futures=True)
