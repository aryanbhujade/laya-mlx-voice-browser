#!/usr/bin/env python3
"""Measure what Laya adds over the deterministic layer.

Most decisions are settled by grammar, site-pack rules and lexical ranking before the model is asked
anything. Reporting only the pipeline's accuracy therefore credits the model for work the rules did.
This runs each benchmark twice — rules alone, then the whole pipeline — and reports the difference,
so a claim about the model can be checked rather than assumed.
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

from laya_voice_browser import sites
from laya_voice_browser.laya import LayaEngine
from laya_voice_browser.policy import evaluate, intent_gate
from laya_voice_browser.spans import deterministic_intent, media_command, strip_lead
from laya_voice_browser.types import Element, Snapshot

ROOT = Path(__file__).resolve().parents[1]


def rows(name: str) -> list[dict]:
    path = ROOT / "datasets" / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fixture(name: str) -> Snapshot:
    raw = json.loads((ROOT / "tests" / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
    return Snapshot(
        url=raw["url"], title=raw["title"], text=raw["text"],
        elements=tuple(Element(**item) for item in raw["elements"]), fingerprint=raw["fingerprint"],
    )


def report(name: str, results: list[tuple[str, bool, bool]], verbose: bool) -> dict:
    """results: (description, rules-only correct, full-pipeline correct)."""
    rules = sum(1 for _, r, _ in results if r)
    full = sum(1 for _, _, f in results if f)
    rescued = [d for d, r, f in results if f and not r]
    broken = [d for d, r, f in results if r and not f]
    total = len(results)
    print(f"\n{name}  ({total} rows)")
    print(f"  rules only     {rules}/{total} = {rules / total:.3f}")
    print(f"  with Laya      {full}/{total} = {full / total:.3f}")
    print(f"  Laya rescues   {len(rescued)}     Laya breaks {len(broken)}")
    if verbose or rescued or broken:
        for description in rescued:
            print(f"    + {description}")
        for description in broken:
            print(f"    - {description}")
    return {
        "rows": total,
        "rules_only": round(rules / total, 3),
        "with_laya": round(full / total, 3),
        "rescued": len(rescued),
        "broken": len(broken),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    warnings.filterwarnings("ignore")
    engine = LayaEngine(args.model)
    engine.warm()
    summary = {}

    # Intent on spoken commands: grammar alone, then the pipeline.
    results = []
    for row in rows("browser_commands"):
        transcript, expected = row["transcript"], row["intent"]
        rule_intent = deterministic_intent(transcript)
        if rule_intent is None and media_command(transcript):
            rule_intent = "media"
        snapshot = Snapshot("https://duckduckgo.com/", "DuckDuckGo", "", (), "d")
        decision = engine.decide(transcript, snapshot, final=True, silent_seconds=1.0)
        intent, ok, _ = intent_gate(decision.answers, transcript, decision.element_match)
        full = (intent if ok else "none") == expected
        results.append((f"{transcript!r} want={expected}", (rule_intent or "none") == expected, full))
    summary["intent"] = report("INTENT (browser_commands)", results, args.verbose)

    # Site controls: pack rules and lexical ranking alone, then the pipeline.
    results = []
    for row in rows("site_controls"):
        transcript, url = row["transcript"], row["url"]
        expected = row.get("expected") or "none"
        match = sites.match_phrase(strip_lead(transcript), url) or sites.lexical_match(transcript, url)
        snapshot = Snapshot(url, row.get("title", "Page"), "", (), url)
        decision = engine.decide(transcript, snapshot, final=True, silent_seconds=1.0)
        result = evaluate(decision, snapshot, final=True, silent_seconds=1.0)
        chosen = str((decision.site or {}).get("id") or "none")
        executed = chosen if result.verdict in {"act", "confirm"} else "none"
        rules_give = match.action.id if match else "none"
        results.append((f"{transcript!r} want={expected}", rules_give == expected, executed == expected))
    summary["site_controls"] = report("SITE CONTROLS (site_controls)", results, args.verbose)

    # Click targets: lexical ranking alone, then the pipeline (which may use Laya's target head).
    results = []
    for row in rows("page_targets"):
        snapshot = fixture(row["page"])
        decision = engine.decide(row["transcript"], snapshot, final=True, silent_seconds=1.0)
        result = evaluate(decision, snapshot, final=True, silent_seconds=1.0)
        wanted = set(row["targets"])
        lexical = decision.lexical_target
        chosen = (result.action or {}).get("target_id")
        results.append((f"{row['transcript']!r} on {row['page']}",
                        lexical in wanted, chosen in wanted))
    summary["targets"] = report("CLICK TARGETS (page_targets)", results, args.verbose)

    print("\n" + json.dumps({"model": engine.model_name, **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
