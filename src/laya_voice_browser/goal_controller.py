"""Experimental speech → goal → observe/choose/act/observe loop."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict

from .browser import BrowserSessionLost, StalePage, Unavailable
from .controller import StreamingController
from .goal_engine import UncertainDecision
from .goal_fast_path import direct_action
from .goals import (
    GOAL_TTL,
    MAX_DECISIONS,
    MAX_GOAL_CHARS,
    MAX_STEPS,
    Goal,
    browser_blocker,
    evidence,
    missing_payload,
    page_identity,
)
from .spans import repair_speech
from .types import TranscriptEvent


class GoalController(StreamingController):
    """Reuse only the serial executor/status/trace plumbing, NOT the old command policy.

    Every partial invalidates an in-flight decision. This initial experiment waits for
    an ASR final before executing; final is NOT taken as evidence of a valid payload.
    A new utterance is a new goal, except explicit continuations within the goal TTL.
    """

    def __init__(self, *args, max_steps: int = MAX_STEPS, **kwargs):
        super().__init__(*args, **kwargs)
        self.goal: Goal | None = None
        self.max_steps = max_steps
        self._last_submission: tuple | None = None
        self._enabled = True
        self._closed = False
        self._cancelled_ids: list[str] = []
        self._direct_ids: list[str] = []

    def cancel(self, reason: str = "cancelled") -> None:
        with self._lock:
            self._generation += 1
            self._last_submission = None
            if self.goal:
                self.goal.status = reason
                self._cancelled_ids = (self._cancelled_ids + [self.goal.id])[-32:]
        self._status("listening")

    def pause(self) -> None:
        self._enabled = False
        self.cancel("voice_off")

    def resume(self) -> None:
        self._enabled = True

    def submit(self, event: TranscriptEvent) -> None:
        text = repair_speech(event.text).strip()
        if (not text or self.session_lost or not self._enabled or self._closed
                or event.utterance_id in self._cancelled_ids or event.utterance_id in self._direct_ids):
            return
        if text.casefold().strip(" .!?") in {"stop", "cancel", "never mind", "nevermind"}:
            self.cancel()
            return
        with self._lock:
            signature = (event.utterance_id, text, event.final)
            if signature == self._last_submission:
                return
            self._last_submission = signature
            self._generation += 1
            generation = self._generation
            old = self.goal
            direct = direct_action(text) if event.final else None
            if direct and old:
                old.status = "interrupted"
                if old.id != event.utterance_id:
                    self._cancelled_ids = (self._cancelled_ids + [old.id])[-32:]
            alive = (old and time.monotonic() - old.created_at < GOAL_TTL
                     and old.status not in {"cancelled", "voice_off", "expired", "closed",
                                            "interrupted", "direct_done"})
            same = alive and old.id == event.utterance_id
            continuation = alive and re.match(r"^(?:and|then)\b", text, re.I)
            history = old.history if (same or continuation) else []
            prefix = old.prefix if same else (f"{old.text}; " if continuation else "")
            whole = prefix + text
            self.goal = Goal(event.utterance_id, whole, history=history,
                             created_at=old.created_at if (same or continuation) else time.monotonic(),
                             decisions=old.decisions if (same or continuation) else 0, prefix=prefix)
            goal = self.goal
        self.announce(f'goal{" (final)" if event.final else " (listening)"}: {whole}')
        if direct:
            self._submit_job(self._run_direct, generation, goal, direct)
        elif len(whole) > MAX_GOAL_CHARS:
            goal.status = "too_long"
            self._status("unsure", label="Try a shorter request", ttl=3.0)
        elif event.final and missing_payload(text):
            goal.status = "clarify"
            self._status("unsure", label="Finish the request", ttl=3.0)
            self._trace({"goal_id": goal.id, "goal": whole, "stopped": "missing payload"})
        elif event.final:
            self._submit_job(self._run_goal, generation, goal)

    def _current(self, generation: int, goal: Goal) -> bool:
        with self._lock:
            return generation == self._generation and time.monotonic() - goal.created_at < GOAL_TTL

    def _run_direct(self, generation: int, goal: Goal, action: dict) -> None:
        """Same serial browser queue, no model pass and no navigation-settling delay."""
        if not self._current(generation, goal):
            return
        started = time.perf_counter()
        try:
            page = self.browser.snapshot()
            if not self._current(generation, goal):
                return
            self._direct_ids = (self._direct_ids + [goal.id])[-32:]
            self.browser.execute(action, expected_fingerprint=page.fingerprint)
            goal.history.append({"executed": action, "source": "universal"})
            goal.status = "direct_done"
            self._trace({"goal_id": goal.id, "execution": action, "source": "universal", "model_ms": 0,
                         "dispatch_ms": round((time.perf_counter() - started) * 1000, 2)})
        except BrowserSessionLost:
            goal.status = "browser_lost"
            raise
        except Exception as exc:
            goal.status = "clarify"
            self.announce(f"Direct command failed: {exc}")
        if self._current(generation, goal):
            self._status("done" if goal.status == "direct_done" else "unsure", ttl=1.0)

    def _verified(self, goal: Goal, page) -> bool:
        from .goal_contracts import verify

        if goal.contract is None:
            return False
        result = verify(goal.contract, page)
        self._trace({"goal_id": goal.id, "contract": asdict(goal.contract),
                     "verification": asdict(result), "observation": asdict(page)})
        if result.satisfied:
            goal.status = "verified_done"
        return result.satisfied

    def _observe_settled(self, generation: int, goal: Goal):
        """Bounded hydration wait; consecutive fresh observations, not a model WAIT guess.

        Navigation may return before a site replaces its initial search field. At least
        0.6 s after a tool action, require stable controls; never wait more than 1.2 s.
        Speech can cancel this wait. Browser calls retain their backend timeout.
        """
        started = time.monotonic()
        page = self.browser.snapshot()
        stable = 0
        while time.monotonic() - started < 1.2 and self._current(generation, goal):
            time.sleep(0.1)
            fresh = self.browser.snapshot()
            stable = stable + 1 if page_identity(page) == page_identity(fresh) else 0
            page = fresh
            if stable >= 2 and time.monotonic() - started >= 0.6:
                break
        return page

    def _run_goal(self, generation: int, goal: Goal) -> None:
        seen: set[str] = set()
        waits = 0
        prepared = False
        try:
            while self._current(generation, goal):
                self._status("thinking")
                page = self.browser.snapshot()
                blocker = browser_blocker(page)
                if blocker:
                    goal.status = blocker
                    self.announce("Browser verification is required; the goal has not been completed")
                    break
                if page.url not in {"about:blank", ""} and not (page.title or page.text or page.elements):
                    # No observable website content: a URL alone cannot justify DONE.
                    waits += 1
                    if waits >= 3:
                        goal.status = "page_not_ready"
                        break
                    self._observe_settled(generation, goal)
                    continue
                if not prepared:
                    interpretation = self.engine.prepare(goal, page)
                    if not self._current(generation, goal):
                        return
                    prepared = True
                    self._trace({"goal_id": goal.id, "interpretation": asdict(interpretation),
                                 "contract": asdict(goal.contract) if goal.contract else None})
                if self._verified(goal, page):
                    break
                if len(goal.history) >= self.max_steps or goal.decisions >= MAX_DECISIONS:
                    goal.status = "budget_exhausted"
                    break
                decision = self.engine.choose(goal, page)
                goal.decisions += 1
                record = {"goal_id": goal.id, "goal": goal.text, "step": len(goal.history),
                          "model": self.engine.model_name, "operation": decision.operation,
                          "action": decision.action, "answers": decision.answers,
                          "questions": decision.questions, "model_ms": round(decision.latency_ms, 2),
                          "page": {"url": page.url, "fingerprint": page.fingerprint}}
                if not self._current(generation, goal):
                    self._trace({**record, "discarded": "goal revised or cancelled"})
                    return
                self._trace(record)
                self.announce(f"Laya goal: {decision.operation} {decision.action or ''} "
                              f"({decision.latency_ms:.0f} ms)")
                if decision.operation in {"DONE", "BLOCKED"}:
                    fresh = self.browser.snapshot()
                    if page_identity(page) != page_identity(fresh):
                        continue
                    # Never display a successful completion solely because Laya said DONE.
                    if not self._verified(goal, fresh):
                        goal.status = "unverified_done" if decision.operation == "DONE" else "blocked"
                    break
                if decision.operation == "WAIT":
                    waits += 1
                    if waits >= 3:
                        goal.status = "stalled"
                        break
                    time.sleep(0.2)
                    continue
                waits = 0
                if not decision.action or not decision.candidate:
                    raise UncertainDecision("No executable candidate")
                key = json.dumps([decision.action, page_identity(page)], sort_keys=True)
                if key in seen:
                    goal.status = "repeated_action"
                    break
                # Strict re-observation complements backend stale checks (which deliberately
                # tolerate page animation in legacy mode). Never reinterpret a stale target.
                fresh = self.browser.snapshot()
                if page_identity(page) != page_identity(fresh):
                    continue
                if not self._current(generation, goal):
                    return
                self._status("acting")
                try:
                    self.browser.execute(decision.action, expected_fingerprint=fresh.fingerprint)
                except StalePage:
                    continue
                seen.add(key)
                # Log execution BEFORE observing. Failure to observe must never replay a click.
                item = {"action": decision.candidate.label, "kind": decision.candidate.kind,
                        "text": decision.action.get("text"), "page_changed": None,
                        "executed": decision.action, "source": decision.candidate.source}
                goal.history.append(item)
                self._trace({"goal_id": goal.id, "execution": item})
                after = self._observe_settled(generation, goal)
                item.update(evidence(decision.candidate, decision.action, page, after))
                self._trace({"goal_id": goal.id, "observation": item})
                if not self._current(generation, goal):
                    return
                if self._verified(goal, after):
                    break
                if len(goal.history) >= 2 and all(h["page_changed"] is False for h in goal.history[-2:]):
                    goal.status = "stalled"
                    break
            else:
                if generation == self._generation:
                    goal.status = "expired"
        except BrowserSessionLost:
            goal.status = "browser_lost"
            raise
        except (UncertainDecision, Unavailable) as exc:
            goal.status = "clarify"
            self.announce(str(exc))
            self._trace({"goal_id": goal.id, "stopped": str(exc),
                         "decision": getattr(exc, "decision", None)})
        except Exception as exc:
            goal.status = "error"
            self.announce(f"goal error: {type(exc).__name__}: {exc}")
            self._trace({"goal_id": goal.id, "error": f"{type(exc).__name__}: {exc}"})
        if generation == self._generation:
            self.announce(f"goal stopped: {goal.status}; {len(goal.history)} actions")
            self._status("done" if goal.status == "verified_done" else "unsure", ttl=2.0)
            self._trace({"goal_id": goal.id, "goal_status": goal.status, "actions": len(goal.history)})

    def close(self) -> None:
        self._closed = True
        self.cancel("closed")
        super().close()
