#!/usr/bin/env python3
"""Measure end-to-end Laya decisions (latency, tokens, target accuracy) on saved Safari page snapshots."""
from __future__ import annotations

import argparse
import json
import statistics
import warnings
from pathlib import Path

from laya_voice_browser.laya import LayaEngine
from laya_voice_browser.policy import evaluate, intent_gate
from laya_voice_browser.types import Element, Snapshot

ROOT = Path(__file__).resolve().parents[1]


def load_snapshot(name: str) -> Snapshot:
    raw = json.loads((ROOT / "tests" / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
    return Snapshot(
        url=raw["url"],
        title=raw["title"],
        text=raw["text"],
        elements=tuple(Element(**item) for item in raw["elements"]),
        fingerprint=raw["fingerprint"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_dataset = ROOT / "datasets" / "page_targets.jsonl"
    parser.add_argument("dataset", type=Path, nargs="?", default=default_dataset)
    parser.add_argument("--model")
    parser.add_argument("--repeat", type=int, default=3, help="Timed repetitions per row (median is kept)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    warnings.filterwarnings("ignore")

    lines = args.dataset.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    engine = LayaEngine(args.model)
    engine.warm()
    latencies, questions, correct_target, correct_intent, acted = [], [], 0, 0, 0
    for row in rows:
        snapshot = load_snapshot(row["page"])
        runs = [
            engine.decide(row["transcript"], snapshot, final=True, silent_seconds=1.0)
            for _ in range(args.repeat + 1)
        ][1:]
        decision = runs[-1]
        latencies.append(statistics.median(run.latency_ms for run in runs))
        questions.append(len(decision.answers))
        policy = evaluate(decision, snapshot, final=True, silent_seconds=1.0)
        action = policy.action or {}
        target = action.get("target_id")
        hit = target in row["targets"]
        correct_target += hit
        intent = intent_gate(decision.answers, row["transcript"], decision.element_match)[0]
        correct_intent += intent == row["intent"]
        acted += policy.verdict in {"act", "confirm"}
        if args.verbose or not hit:
            print(
                f"{'ok  ' if hit else 'MISS'} {row['page']:18} {row['transcript']!r:45} -> {policy.verdict}"
                f" {target} (want {row['targets']}) {policy.summary}"
            )
    n = len(rows)
    print(
        json.dumps(
            {
                "model": engine.model_name,
                "rows": n,
                "target_accuracy": round(correct_target / n, 3),
                "intent_accuracy": round(correct_intent / n, 3),
                "act_or_confirm_rate": round(acted / n, 3),
                "median_model_ms": round(statistics.median(latencies), 1),
                "mean_model_ms": round(statistics.mean(latencies), 1),
                "mean_questions": round(statistics.mean(questions), 2),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
