#!/usr/bin/env python3
"""Real local-model probe; --live additionally executes goals in an owned browser session.

No paid APIs, synthetic model replies or legacy rule-policy fallback. Fixture mode
measures one next step, NOT successful task completion. Live mode independently
checks destination/query and reports it separately from Laya's DONE decision.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from laya_voice_browser import browsers
from laya_voice_browser.goal_controller import GoalController
from laya_voice_browser.goal_engine import GoalEngine, UncertainDecision
from laya_voice_browser.goals import Goal, scope
from laya_voice_browser.types import Element, Snapshot, TranscriptEvent

ROOT = Path(__file__).resolve().parents[1]
BLANK = Snapshot("about:blank", "Blank", "", (), "blank")
LIVE_CASES = [
    ("can you open wikipedia and search for Mercury", "wikipedia", "Mercury"),
    ("open youtube and search for ESP32 tutorials", "youtube", "ESP32 tutorials"),
    ("open github and search for ESP32", "github", "ESP32"),
    ("open amazon and search for ESP32 board", "amazon", "ESP32 board"),
    ("open ebay and search for ESP32 board", "ebay", "ESP32 board"),
]


def load_page(name):
    raw = json.loads((ROOT / "tests" / "fixtures" / f"{name}.json").read_text())
    return Snapshot(raw["url"], raw["title"], raw["text"],
                    tuple(Element(**e) for e in raw["elements"]), raw["fingerprint"])


def outcome_matches(page: Snapshot, site: str, query: str) -> bool:
    if scope(page.url) != site:
        return False
    parsed = urlparse(page.url)
    values = parse_qs(parsed.query)
    key = {"wikipedia": "search", "youtube": "search_query", "github": "q",
           "amazon": "k", "ebay": "_nkw"}[site]
    if query.casefold() in [value.casefold() for value in values.get(key, [])]:
        # A URL alone is not rendered results (bot checks can retain the query).
        text = f"{page.title} {page.text}".casefold()
        blocked = any(s in text for s in ["captcha", "unusual traffic", "verify you're human",
                                          "robot check", "access denied", "sorry, we just need"])
        return not blocked and query.casefold() in text and bool(page.elements)
    return (site == "wikipedia" and parsed.path.startswith("/wiki/")
            and query.casefold() in unquote(parsed.path).casefold()
            and query.casefold() in page.title.casefold())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--browser", default="safari")
    parser.add_argument("--model")
    parser.add_argument("--case", type=int, help="Live case index, zero based")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    engine = GoalEngine(args.model)
    engine.warm()
    rows = []
    if args.live:
        browser = browsers.open_browser(args.browser)
        try:
            for index, (text, site, query) in enumerate(LIVE_CASES):
                if args.case is not None and args.case != index:
                    continue
                browser.execute({"type": "navigate", "url": "about:blank"})
                trace = args.output.with_suffix(f".{index}.trace.jsonl") if args.output else None
                c = GoalController(browser, engine, trace_path=trace)
                started = time.perf_counter()
                try:
                    c.submit(TranscriptEvent(text, True, str(index), time.time()))
                    c.wait_idle(timeout=60)
                    page = browser.snapshot()
                    row = {"goal": text, "status": c.goal.status, "actions": len(c.goal.history),
                           "outcome_matches": outcome_matches(page, site, query), "url": page.url,
                           "elapsed_ms": round((time.perf_counter() - started) * 1000)}
                finally:
                    c.close()
                rows.append(row)
                print(json.dumps(row), flush=True)
        finally:
            browser.close()
    else:
        cases = [(text, BLANK, [], "CLICK", {f"site:{site}"}) for text, site, _ in LIVE_CASES]
        cases.extend([
            ("open the talk page", load_page("wikipedia_article"), [], "CLICK", {"e12"}),
            ("can you open wikipedia and search for Mercury", load_page("wikipedia_main"),
             [{"action": "Browser: open wikipedia website", "kind": "click", "page_changed": True}],
             "CLICK", {"e03", "site:wikipedia"}),
            ("and search for ESP32", load_page("github_home"), [], "CLICK", {"github_search"}),
        ])
        for text, page, history, expected_op, targets in cases:
            try:
                decision = engine.choose(Goal("probe", text, history=history), page)
                action = decision.action or {}
                target = action.get("target_id") or action.get("type")
                if "github_search" in targets:
                    hit = "github.com/search?" in action.get("url", "")
                else:
                    destination = f"site:{scope(action.get('url', ''))}"
                    hit = decision.operation == expected_op and (target in targets or destination in targets)
                row = {"goal": text, "page": page.url, "hit": hit, "action": action,
                       "model_ms": round(decision.latency_ms, 1), "answers": decision.answers}
            except UncertainDecision as exc:
                row = {"goal": text, "page": page.url, "hit": False, "abstained": str(exc),
                       "decision": getattr(exc, "decision", None)}
            rows.append(row)
            print(json.dumps({k: v for k, v in row.items() if k not in {"answers", "decision"}}), flush=True)
    result = {"model": engine.model_name, "mode": "live" if args.live else "next_step_fixture",
              "rows": rows}
    times = [r["model_ms"] for r in rows if "model_ms" in r]
    if times:
        result["median_model_ms"] = statistics.median(times)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
