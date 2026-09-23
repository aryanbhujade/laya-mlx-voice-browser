#!/usr/bin/env python3
"""Turn a service log into labelled completeness data.

The `complete` head decides whether to act on speech that is still arriving. Apple Speech already
labels this for free: every partial transcript that the final one extends was, at that moment,
incomplete, and the final is complete. No hand annotation is involved.

The output contains whatever was said to the microphone, including searches and page titles. It is
written outside the repository by default and must be reviewed and redacted before it is shared.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HEARD = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} heard(?P<final> \(final\))?: (?P<text>.+)$")


def utterances(lines: list[str]) -> list[tuple[list[str], str]]:
    """Group consecutive partials with the final transcript that ended them."""
    grouped, partials = [], []
    for line in lines:
        found = HEARD.match(line.rstrip("\n"))
        if not found:
            continue
        text = found.group("text").strip()
        if found.group("final"):
            grouped.append((partials, text))
            partials = []
        else:
            partials.append(text)
    return grouped


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "log", type=Path, nargs="?",
        default=Path.home() / "Library/Logs/laya-voice-browser/service.log",
    )
    parser.add_argument("--out", type=Path, default=Path.home() / "laya-completeness.jsonl")
    args = parser.parse_args()

    grouped = utterances(args.log.read_text(encoding="utf-8", errors="replace").splitlines())
    rows, seen = [], set()
    for index, (partials, final) in enumerate(grouped):
        for partial in partials:
            # A partial the final merely repeats was already the whole command; only a partial the
            # final goes on to extend was genuinely unfinished.
            if normalise(partial) == normalise(final):
                continue
            if not normalise(final).startswith(normalise(partial)):
                continue  # the recognizer revised rather than extended; the label is unclear
            key = ("p", normalise(partial))
            if key in seen:
                continue
            seen.add(key)
            rows.append({"transcript": partial, "complete": False, "utterance": index})
        key = ("f", normalise(final))
        if key not in seen:
            seen.add(key)
            rows.append({"transcript": final, "complete": True, "utterance": index})

    args.out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    incomplete = sum(1 for row in rows if not row["complete"])
    print(json.dumps({
        "utterances": len(grouped),
        "rows": len(rows),
        "incomplete": incomplete,
        "complete": len(rows) - incomplete,
        "majority_baseline": round(max(incomplete, len(rows) - incomplete) / max(1, len(rows)), 3),
        "out": str(args.out),
    }, indent=2))
    print("\nReview and redact before sharing: transcripts contain whatever was spoken.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
