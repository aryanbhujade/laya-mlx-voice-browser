#!/usr/bin/env python3
"""Replay labelled commands as mid-speech partials and report unsafe early actions and latency."""
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
    default_dataset = ROOT / "datasets" / "browser_commands.jsonl"
    parser.add_argument("dataset", type=Path, nargs="?", default=default_dataset)
    parser.add_argument("--model")
    args = parser.parse_args()
    warnings.filterwarnings("ignore")

    lines = args.dataset.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    engine = LayaEngine(args.model)
    engine.warm()
    page = Snapshot("https://example.com/", "Example Domain", "Example Domain", (), "fixture")
    unsafe, early, latencies = [], 0, []
    for row in rows:
        # Mid-speech: not final and only 0.1 s of silence, the hardest case for acting early.
        decision = engine.decide(row["transcript"], page, final=False, silent_seconds=0.1)
        policy = evaluate(decision, page, final=False, silent_seconds=0.1)
        latencies.append(decision.latency_ms)
        acted = policy.verdict in {"act", "confirm"}
        should_hold = not row["is_command"] or not row["complete"]
        if acted and should_hold:
            unsafe.append(row["transcript"])
        early += acted and not should_hold
        print(f"{policy.verdict:8} {decision.latency_ms:6.1f} ms  {row['transcript']!r:40} {policy.summary}")
    held_rows = sum(1 for row in rows if not row["is_command"] or not row["complete"])
    print(
        json.dumps(
            {
                "rows": len(rows),
                "unsafe_early_actions": unsafe,
                "should_hold_rows": held_rows,
                "complete_commands_acted_mid_speech": f"{early}/{len(rows) - held_rows}",
                "median_model_ms": round(statistics.median(latencies), 1),
            },
            indent=2,
        )
    )
    return 1 if unsafe else 0


if __name__ == "__main__":
    raise SystemExit(main())
