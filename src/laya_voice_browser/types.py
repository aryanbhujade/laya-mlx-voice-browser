from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Element:
    id: str
    role: str
    text: str
    tag: str
    href: str = ""
    placeholder: str = ""
    value: str = ""
    destructive_hint: bool = False
    in_main: bool = False
    top: float = 0.0

    def compact(self) -> str:
        label = self.text or self.placeholder or self.value or self.tag
        suffix = f" -> {self.href[:80]}" if self.href else ""
        return f'{self.id} {self.role} "{label[:64]}"{suffix}'


@dataclass(frozen=True)
class Tab:
    id: str
    title: str
    url: str
    active: bool = False


@dataclass(frozen=True)
class Snapshot:
    url: str
    title: str
    text: str
    elements: tuple[Element, ...]
    fingerprint: str
    tabs: tuple[Tab, ...] = ()


@dataclass(frozen=True)
class TranscriptEvent:
    text: str
    final: bool
    utterance_id: str
    at: float


@dataclass
class ModelDecision:
    answers: dict[str, Any]
    candidates: dict[str, list[str]]
    latency_ms: float
    model: str
    state: dict[str, Any]
    element_match: bool = False
    stages: list[dict[str, Any]] = field(default_factory=list)
    lexical_target: str | None = None
    # A site-pack control: {"id", "text", "source": "rule" | "model"}.
    site: dict[str, Any] | None = None
    # Best 2-3 elements when the target is uncertain, for numbered on-page choices.
    target_candidates: list[str] = field(default_factory=list)


@dataclass
class PolicyResult:
    verdict: str
    summary: str
    action: dict[str, Any] | None = None
    reasons: list[dict[str, Any]] = field(default_factory=list)
    # For verdict "choose": [{"number": 1, "id": "e07", "label": "Talk"}, ...]
    candidates: list[dict[str, Any]] = field(default_factory=list)
