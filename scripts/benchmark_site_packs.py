#!/usr/bin/env python3
"""Measure end-to-end site-pack routing, including exact rules and Laya's loose-phrase fallback."""
from __future__ import annotations

import argparse
import json
import statistics
import warnings
from pathlib import Path

from laya_voice_browser.laya import LayaEngine
from laya_voice_browser.policy import evaluate
from laya_voice_browser.types import Snapshot

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset", type=Path, nargs="?", default=ROOT / "datasets" / "site_controls.jsonl"
    )
    parser.add_argument("--model")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    warnings.filterwarnings("ignore")

    rows = [
        json.loads(line)
        for line in args.dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    engine = LayaEngine(args.model)
    engine.warm()
    correct = wrong_actions = questions = 0
    latencies: list[float] = []
    sources: dict[str, int] = {}
    for row in rows:
        snapshot = Snapshot(row["url"], row.get("title", "Page"), "", (), row["url"])
        decision = engine.decide(row["transcript"], snapshot, final=True, silent_seconds=1.0)
        result = evaluate(decision, snapshot, final=True, silent_seconds=1.0)
        predicted = str((decision.site or {}).get("id") or "none")
        expected = str(row.get("expected") or "none")
        executed = predicted if result.verdict in {"act", "confirm"} else "none"
        hit = executed == expected
        correct += hit
        wrong_actions += expected == "none" and executed != "none"
        questions += len(decision.answers)
        latencies.append(decision.latency_ms)
        source = str((decision.site or {}).get("source") or "none")
        sources[source] = sources.get(source, 0) + 1
        if args.verbose or not hit:
            site_answer = decision.answers.get("site_action") or {}
            site_probability = (site_answer.get("probabilities") or {}).get(
                site_answer.get("choice"), 0.0
            )
            print(
                f"{'ok  ' if hit else 'MISS'} {row['site']:12} {row['transcript']!r:52} "
                f"-> {executed:16} {source:7} {result.verdict:7} p={site_probability:.3f} "
                f"choice={site_answer.get('choice', '-')}"
            )

    total = len(rows)
    print(
        json.dumps(
            {
                "model": engine.model_name,
                "rows": total,
                "accuracy": round(correct / total, 3),
                "wrong_actions": wrong_actions,
                "median_model_ms": round(statistics.median(latencies), 1),
                "mean_questions": round(questions / total, 2),
                "sources": sources,
            },
            indent=2,
        )
    )
    return 0 if correct == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
