#!/usr/bin/env python3
"""Three live, signed-out browsing tasks with expectations independent of Laya's contract.

No account actions. Saves private local traces/screenshots under ignored runs/.
This is a development smoke test, not a held-out accuracy benchmark.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from laya_voice_browser.browsers import open_browser
from laya_voice_browser.goal_controller import GoalController
from laya_voice_browser.goal_engine import GoalEngine
from laya_voice_browser.types import TranscriptEvent

CASES = [
    ("wikipedia", "open Wikipedia and search for Mercury", "search", "Mercury", 0),
    ("youtube", "search YouTube for ESP32 and show me the first video", "open_result", "ESP32", 1),
    ("github", "open GitHub and search for ESP32", "search", "ESP32", 0),
]


class ObservedBrowser:
    """Record what actually happened; never use the model's chosen contract as the oracle."""

    def __init__(self, browser, case):
        self.browser = browser
        self.site, _, self.kind, self.query, _ = case
        self.actions = 0
        self.first_success_at = None
        self.first_video = None
        self.success = False
        self.pages = []

    def snapshot(self):
        page = self.browser.snapshot()
        parsed = urlparse(page.url)
        params = parse_qs(parsed.query)
        observed = page.browsing
        host = parsed.hostname or ""
        valid = False
        if self.site == "wikipedia":
            valid = (host == "en.wikipedia.org" and parsed.path == "/wiki/Mercury"
                     and observed.get("heading") == "Mercury" and observed.get("detail_ready"))
        elif self.site == "github":
            repos = [r for r in observed.get("results", []) if re.fullmatch(
                r"https://github.com/(?!topics/|collections/|sponsors/)[\w.-]+/[\w.-]+", r.get("url", ""))]
            valid = (host == "github.com" and parsed.path == "/search" and params.get("q") == ["ESP32"]
                     and params.get("type") == ["repositories"] and observed.get("results_ready") and repos)
        elif self.site == "youtube":
            if (host.endswith("youtube.com") and parsed.path == "/results"
                    and params.get("search_query") == ["ESP32"] and observed.get("results_ready")):
                videos = [parse_qs(urlparse(r.get("url", "")).query).get("v", [""])[0]
                          for r in observed.get("results", [])
                          if urlparse(r.get("url", "")).path == "/watch"]
                if videos and self.first_video is None:
                    self.first_video = videos[0]
            valid = (bool(self.first_video) and host.endswith("youtube.com") and parsed.path == "/watch"
                     and params.get("v") == [self.first_video] and observed.get("detail_ready")
                     and bool(observed.get("heading")))
        self.success = bool(valid)
        if self.success and self.first_success_at is None:
            self.first_success_at = self.actions
        self.pages.append(asdict(page))
        return page

    def execute(self, action, **kwargs):
        result = self.browser.execute(action, **kwargs)
        self.actions += 1
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", default="safari")
    parser.add_argument("--site", choices=[c[0] for c in CASES])
    parser.add_argument("--output", type=Path,
                        default=Path("runs") / datetime.now().strftime("milestone-%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    engine = GoalEngine()
    engine.warm()
    browser = open_browser(args.browser)
    rows = []
    try:
        for case in CASES:
            site, text, kind, query, ordinal = case
            if args.site and args.site != site:
                continue
            browser.execute({"type": "navigate", "url": "about:blank"})
            observed = ObservedBrowser(browser, case)
            controller = GoalController(observed, engine, trace_path=args.output / f"{site}.jsonl")
            started = time.perf_counter()
            try:
                controller.submit(TranscriptEvent(text, True, site, time.time()))
                controller.wait_idle(timeout=60)
                page = observed.snapshot()
                contract = controller.goal.contract
                contract_matches = bool(contract and (contract.site, contract.kind, contract.query,
                                                       contract.ordinal) == (site, kind, query, ordinal))
                row = {"site": site, "goal": text, "status": controller.goal.status,
                       "contract_matches_expected": contract_matches,
                       "outcome_matches_expected": observed.success,
                       "actions": observed.actions, "first_success_at": observed.first_success_at,
                       "extra_actions": (None if observed.first_success_at is None else
                                         observed.actions - observed.first_success_at),
                       "elapsed_ms": round((time.perf_counter() - started) * 1000), "url": page.url}
                rows.append(row)
                print(json.dumps(row), flush=True)
                (args.output / f"{site}-observations.json").write_text(json.dumps(observed.pages, indent=2))
                if hasattr(browser, "driver"):
                    browser.driver.save_screenshot(str(args.output / f"{site}.png"))
            finally:
                controller.close()
    finally:
        browser.close()
    (args.output / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    passed = rows and all(r["status"] == "verified_done" and r["contract_matches_expected"]
                          and r["outcome_matches_expected"] and r["extra_actions"] == 0 for r in rows)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
