from __future__ import annotations

from typing import Any


def _choice(answer: Any) -> str | None:
    return answer.get("choice") if isinstance(answer, dict) else None


def _probability(answer: Any) -> float:
    if not isinstance(answer, dict):
        return 0.0
    for key in ("noul", "probability", "confidence"):
        value = answer.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _confidence(answer: Any) -> float:
    if not isinstance(answer, dict):
        return 0.0
    value = answer.get("confidence")
    if isinstance(value, (int, float)):
        return float(value)
    probabilities = answer.get("probabilities")
    if isinstance(probabilities, dict) and probabilities:
        ordered = sorted((float(v) for v in probabilities.values()), reverse=True)
        return ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0)
    return 0.0
