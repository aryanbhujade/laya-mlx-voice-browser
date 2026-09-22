#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from laya_voice_browser.laya import LayaEngine, _choice, _probability
from laya_voice_browser.questions import THRESHOLDS
from laya_voice_browser.types import Snapshot


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure raw Laya browser-command decisions on labeled data")
    parser.add_argument("dataset", type=Path, nargs="?", default=Path("datasets/browser_commands.jsonl"))
    parser.add_argument("--model")
    parser.add_argument("--predictions", type=Path)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row.get("transcript"), str) or not isinstance(row.get("intent"), str):
            raise ValueError(f"Invalid row {number}")
        rows.append(row)
    return rows


def main() -> int:
    args = arguments()
    rows = load_rows(args.dataset)
    engine = LayaEngine(args.model)
    engine.warm()
    page = Snapshot("https://example.com", "Example", "Example Domain", (), "fixture")
    counts = Counter()
    predictions = []
    for row in rows:
        answers = engine.ask(row["transcript"], page, ["intent", "is_command", "complete", "site"])
        predicted_intent = _choice(answers.get("intent")) or "none"
        predicted_command = _probability(answers.get("is_command")) >= THRESHOLDS["is_command"]
        predicted_complete = _probability(answers.get("complete")) >= THRESHOLDS["complete"]
        predicted_site = _choice(answers.get("site")) or "none"
        counts["rows"] += 1
        counts["intent_correct"] += predicted_intent == row["intent"]
        counts["command_correct"] += predicted_command == row["is_command"]
        counts["complete_correct"] += predicted_complete == row["complete"]
        if "site" in row:
            counts["site_rows"] += 1
            counts["site_correct"] += predicted_site == row["site"]
        predictions.append(
            {
                **row,
                "predicted": {
                    "intent": predicted_intent,
                    "is_command": predicted_command,
                    "complete": predicted_complete,
                    "site": predicted_site,
                    "is_command_probability": _probability(answers.get("is_command")),
                    "complete_probability": _probability(answers.get("complete")),
                },
            }
        )
    report = {
        "model": engine.model_name,
        "rows": counts["rows"],
        "intent_accuracy": counts["intent_correct"] / counts["rows"],
        "command_accuracy": counts["command_correct"] / counts["rows"],
        "complete_accuracy": counts["complete_correct"] / counts["rows"],
        "site_accuracy": counts["site_correct"] / counts["site_rows"] if counts["site_rows"] else None,
        "thresholds": THRESHOLDS,
    }
    print(json.dumps(report, indent=2))
    if args.predictions:
        args.predictions.parent.mkdir(parents=True, exist_ok=True)
        args.predictions.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in predictions),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
