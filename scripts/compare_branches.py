#!/usr/bin/env python3
"""Paired development evaluation, NOT a live-browser or held-out accuracy benchmark.

Run this same script with --source pointing to each checkout and --mode legacy/goal.
Uses real MLX models and production controllers against deterministic browser observations.
Original public page snapshots exercise real target inventories; synthetic pages exercise chains.
No model answers are mocked. Only browser effects are simulated, without network/account actions.
Unknown operations are harness limitations, reported separately, never silently called success.
Private output includes traces. No application settings are modified.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import fields
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

ROOT = Path(__file__).resolve().parents[1]
HOMES = {"wikipedia": "https://en.wikipedia.org/wiki/Main_Page",
         "youtube": "https://www.youtube.com/", "github": "https://github.com/",
         "ebay": "https://www.ebay.com/", "google": "https://www.google.com/",
         "amazon": "https://www.amazon.com/", "duckduckgo": "https://duckduckgo.com/"}
KEYS = dict(wikipedia="search", youtube="search_query", github="q", ebay="_nkw",
            google="q", amazon="k", duckduckgo="q")
PATHS = dict(wikipedia="/w/index.php", youtube="/results", github="/search",
             ebay="/sch/i.html", google="/search", amazon="/s", duckduckgo="/")


def site(url):
    host = urlparse(url).hostname or ""
    return next((s for s in HOMES if host == f"{s}.com" or host.endswith(f".{s}.com")
                 or (s == "wikipedia" and host.endswith(".wikipedia.org"))), "")


def search_url(s, query):
    host = urlparse(HOMES[s]).netloc
    return f"https://{host}{PATHS[s]}?{KEYS[s]}={quote_plus(query)}" + (
        "&type=repositories" if s == "github" else "")


def result_urls(s, query):
    token = hashlib.sha256(query.encode()).hexdigest()
    if s == "youtube":
        return [f"https://www.youtube.com/watch?v={token[:10]}{n}" for n in range(1, 4)]
    if s == "github":
        return [f"https://github.com/example/{token[:8]}-{n}" for n in range(1, 4)]
    if s == "ebay":
        return [f"https://www.ebay.com/itm/{int(token[:8], 16):011d}{n}" for n in range(1, 4)]
    if s == "wikipedia":
        return [f"https://en.wikipedia.org/wiki/{quote_plus(query.replace(' ', '_'))}_{n}"
                for n in range(1, 4)]
    return [f"https://example.org/{token[:8]}/{n}" for n in range(1, 4)]


def element(id, text, href="", role="link", **kw):
    return dict(id=id, text=text, href=href, role=role,
                tag="a" if role == "link" else "input" if role == "searchbox" else "button", **kw)


class World:
    """Explicit synthetic browser transition model shared by both implementations."""

    def __init__(self, pages, start, Snapshot, Element, Tab):
        self.pages = copy.deepcopy(pages)
        self.Snapshot, self.Element, self.Tab = Snapshot, Element, Tab
        self.tabs = {f"t{i}": {"urls": [url], "at": 0} for i, url in enumerate(start)}
        self.current = next(iter(self.tabs))
        self.next_tab = len(self.tabs)
        self.actions, self.unsupported = [], []
        self.scroll = 500
        self.typed = ""
        self.last_action = None

    @property
    def url(self):
        tab = self.tabs[self.current]
        return tab["urls"][tab["at"]]

    def page(self, url):
        if url in self.pages:
            return copy.deepcopy(self.pages[url])
        s, p = site(url), urlparse(url)
        query = parse_qs(p.query).get(KEYS.get(s, ""), [""])[0]
        title = s or "Example page"
        controls = []
        browsing = {"site": s, "heading": title, "detail_ready": True}
        if s:
            controls = [element("search", f"Search {s}", role="searchbox", input_type="search",
                                placeholder=f"Search {s}", value=""),
                        element("submit", "Search", role="button")]
        if query:
            title = f"{query} - {s} search results"
            results = [{"url": u, "title": f"{query} result {n}"}
                       for n, u in enumerate(result_urls(s, query), 1)]
            browsing = {"site": s, "results_ready": True, "results": results}
            controls.extend(element(f"r{n}", r["title"], r["url"])
                            for n, r in enumerate(results, 1))
        return dict(url=url, title=title, text=title, elements=controls, browsing=browsing)

    def snapshot(self):
        raw = self.page(self.url)
        raw.update(fingerprint=f"{self.current}:{self.url}:{self.scroll}:{self.typed}",
                   document_id=self.url, scroll_y=self.scroll, can_scroll_down=True)
        def convert(cls, data):
            keys = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in keys})
        raw["elements"] = tuple(convert(self.Element, e) for e in raw["elements"])
        raw["tabs"] = tuple(self.Tab(k, self.page(v["urls"][v["at"]])["title"],
                                    v["urls"][v["at"]], k == self.current) for k, v in self.tabs.items())
        return convert(self.Snapshot, raw)

    def navigate(self, url):
        tab = self.tabs[self.current]
        tab["urls"] = tab["urls"][:tab["at"] + 1] + [url]
        tab["at"] += 1
        self.scroll, self.typed = 500, ""

    def execute(self, action, **kwargs):
        from laya_voice_browser.browser import Unavailable
        self.actions.append(dict(action))
        kind, before = action["type"], self.url
        self.last_action = kind
        if kind == "navigate":
            self.navigate(action["url"])
        elif kind == "click":
            e = next((e for e in self.snapshot().elements if e.id == action["target_id"]), None)
            if e and e.href:
                self.navigate(e.href)
            elif e and e.text.casefold().startswith("search") and self.typed:
                self.navigate(search_url(site(self.url), self.typed))
            else:
                self.unsupported.append(action)
                raise Unavailable("Replay cannot simulate this non-navigation element")
        elif kind == "type":
            self.typed = action["text"]
            page = self.page(self.url)
            for e in page["elements"]:
                if e["id"] == action["target_id"]:
                    e["value"] = self.typed
            self.pages[self.url] = page
        elif kind == "press_enter" and self.typed and site(self.url):
            self.navigate(search_url(site(self.url), self.typed))
        elif kind == "scroll":
            self.scroll = max(0, self.scroll + (-320 if action.get("direction") == "up" else 320))
        elif kind == "new_tab":
            self.current = f"t{self.next_tab}"
            self.next_tab += 1
            self.tabs[self.current] = {"urls": ["about:blank"], "at": 0}
        elif kind == "close_tab" and len(self.tabs) > 1:
            del self.tabs[self.current]
            self.current = next(reversed(self.tabs))
        elif kind == "switch_tab":
            key = action.get("tab_id")
            keys = list(self.tabs)
            if key not in self.tabs:
                key = keys[(keys.index(self.current) + (-1 if action.get("direction") == "previous" else 1))
                           % len(keys)]
            self.current = key
        elif kind in {"back", "forward"}:
            tab = self.tabs[self.current]
            tab["at"] = min(len(tab["urls"]) - 1, max(0, tab["at"] + (-1 if kind == "back" else 1)))
        elif kind == "reload":
            pass
        elif kind == "site":
            from laya_voice_browser import sites
            pack = sites.pack_for(self.url)
            control = next((c for c in pack.actions if c.id == action.get("id")), None) if pack else None
            if control and "open" in control.do:
                self.navigate(sites.resolve_open(control.do["open"], self.url, action.get("text", "")))
            elif control and control.id in {"first_video", "first_result"} and "click_css" in control.do:
                # The synthetic result DOM has the same ordered list for both implementations.
                # These pack tools always click the FIRST result, regardless of what was said.
                listed = self.page(self.url).get("browsing", {}).get("results", [])
                if not listed:
                    raise Unavailable("No result exists for the first-result selector")
                self.navigate(listed[0]["url"])
            else:
                self.unsupported.append(action)
                raise Unavailable("Replay does not emulate site keys/selectors/media")
        else:
            self.unsupported.append(action)
            raise Unavailable(f"Replay does not emulate {kind}")
        return {"before_url": before, "after_url": self.url}

    def show_candidates(self, candidates):
        pass

    def clear_candidates(self):
        pass


def cases():
    pages, rows = {}, []
    def add(name, group, start, steps, source="synthetic"):
        rows.append(dict(name=name, group=group, start=start if isinstance(start, list) else [start],
                         steps=steps, source=source))
    def step(text, **expected):
        return dict(text=text, expected=expected)
    for name in ["wikipedia_main", "wikipedia_article", "hacker_news", "duckduckgo_results", "github_home"]:
        raw = json.loads((ROOT / "tests/fixtures" / f"{name}.json").read_text())
        pages[raw["url"]] = raw
    # Reuse target labels/URLs, not the old test's target-accuracy metric: score actual navigation.
    for i, line in enumerate((ROOT / "datasets/page_targets.jsonl").read_text().splitlines()):
        row = json.loads(line)
        if row["intent"] != "click_element" or any(w in row["transcript"] for w in
                ("log in", "login", "create account", "donate", "toggle", "button")):
            continue
        raw = json.loads((ROOT / "tests/fixtures" / f"{row['page']}.json").read_text())
        urls = [e["href"] for e in raw["elements"] if e["id"] in row["targets"] and e.get("href")]
        if "article" in row["transcript"]:
            # The historical target dataset accepted both a portrait and the article. Task success
            # must not accept the image merely because it has the same link label.
            urls = [u for u in urls if "/wiki/File:" not in u]
        if urls:
            add(f"real-link-{i}", "real_page_links", raw["url"],
                [step(row["transcript"], urls=urls)], "saved_real_page")
    for s, query in [("wikipedia", "Mercury"), ("youtube", "ESP32 tutorials"),
                     ("github", "rust cli"), ("ebay", "night vision camera"),
                     ("google", "Python pathlib documentation"), ("amazon", "ESP32 board")]:
        for i, text in enumerate([f"open {s} and search for {query}",
                                  f"can you search {s} for {query}"]):
            add(f"search-{s}-{i}", "site_search", "about:blank", [step(text, search=[s, query])])
        add(f"followup-{s}", "separate_followups", "about:blank", [
            step(f"open {s}", site=s), step(f"and search for {query}", search=[s, query])])
    for s, noun, query in [("youtube", "video", "origami crane"), ("github", "repository", "httpx"),
                            ("ebay", "listing", "Sony camcorder")]:
        for n, word in [(1, "first"), (2, "second"), (3, "third")]:
            destination = result_urls(s, query)[n-1]
            add(f"compound-{s}-{n}", "search_then_result", "about:blank", [
                step(f"search {s} for {query} and open the {word} {noun}",
                     urls=[destination], via_search=[s, query])])
            add(f"ordinal-{s}-{n}", "contextual_result", search_url(s, query), [
                step(f"open the {word} {noun}", urls=[destination])])
        add(f"result-tab-{s}", "destination_new_tab", search_url(s, query), [
            step(f"open the second {noun} in a new tab", urls=[result_urls(s, query)[1]], new_tab=True)])
    category = "https://www.ebay.com/b/Cameras-Photo/625/bn_1865546"
    vintage = "https://www.ebay.com/b/Vintage-Cameras/101643/bn_152346"
    camcorders = "https://www.ebay.com/b/Camcorders/11724/bn_42"
    pages[category] = dict(url=category, title="Cameras & Photo | eBay", text="Shop cameras",
                           elements=[element("vintage", "Vintage Cameras", vintage),
                                     element("camcorders", "Camcorders", camcorders)])
    add("ebay-new-tab-link", "destination_new_tab", category, [
        step("open vintage cameras in a new tab", urls=[vintage], new_tab=True)])
    add("ebay-category-journey", "navigation_journey", category, [
        step("open vintage cameras", urls=[vintage]), step("scroll down", scroll="down"),
        step("scroll back up", scroll="up"), step("go back", urls=[category]),
        step("click on camcorders", urls=[camcorders])])
    for i, text in enumerate(["scroll down", "scroll up", "please scroll down a little",
                              "scroll back up", "and scroll down", "reload this page"]):
        expect = {"action": "reload"} if "reload" in text else {"scroll": "up" if "up" in text else "down"}
        add(f"control-{i}", "browser_controls", category, [step(text, **expect)])
    for text, expect in [("open a new tab", {"new_tab": True}), ("close this tab", {"close_tab": True}),
                          ("switch to the GitHub tab", {"tab": "t1"}),
                          ("next tab", {"tab": "t1"}), ("previous tab", {"tab": "t1"})]:
        add(f"tab-{text}", "tabs", [category, HOMES["github"]], [step(text, **expect)])
    for i, text in enumerate(["don't close this tab", "do not open vintage cameras",
                              "don't open the first listing", "that YouTube video was interesting",
                              "we should go back to the office", "I clicked on cameras earlier",
                              "search for", "open", "buy the first item now"]):
        add(f"negative-{i}", "negative_or_incomplete", [category, HOMES["github"]], [step(text, none=True)])
    for i, text in enumerate(["open", "search YouTube for", "open vintage cameras in a new",
                              "search for Sony", "close this"]):
        row = step(text, none=True)
        row["final"] = False
        add(f"partial-{i}", "unfinished_speech", [category, HOMES["github"]], [row])
    return pages, rows


def check(world, before, expected, actions):
    url, count, tab, scroll = before
    tests = []
    if expected.get("none"):
        return not actions
    if "urls" in expected:
        tests.append(world.url.rstrip("/") in [u.rstrip("/") for u in expected["urls"]])
    if "search" in expected:
        s, query = expected["search"]
        tests.append(site(world.url) == s and parse_qs(urlparse(world.url).query).get(KEYS[s]) == [query])
    if "site" in expected:
        tests.append(site(world.url) == expected["site"])
    if "scroll" in expected:
        tests.append(world.url == url and world.current == tab and
                     (world.scroll > scroll if expected["scroll"] == "down" else world.scroll < scroll))
    if expected.get("new_tab"):
        tests.append(len(world.tabs) == count + 1 and world.current != tab)
    if expected.get("close_tab"):
        tests.append(len(world.tabs) == count - 1 and tab not in world.tabs)
    if "tab" in expected:
        tests.append(world.current == expected["tab"])
    if "action" in expected:
        tests.append(bool(actions) and actions[-1]["type"] == expected["action"])
    return bool(tests) and all(tests)


def wrong_action(world, expected, actions, before):
    if expected.get("none"):
        return bool(actions)
    if "via_search" in expected:
        wanted_site, query = expected["via_search"]
        for action in actions:
            url = action.get("url", "")
            actual_site = site(url)
            values = parse_qs(urlparse(url).query)
            if actual_site and KEYS[actual_site] in values:
                if actual_site != wanted_site or values[KEYS[actual_site]] != [query]:
                    return True
    # An unfinished request may legitimately have opened its site or typed its query. Don't
    # label that a wrong action just because the whole task wasn't completed.
    if expected.get("new_tab") and world.url == "about:blank":
        return False
    if "scroll" in expected:
        return any(a["type"] not in {"scroll"} for a in actions)
    if "search" in expected:
        s, query = expected["search"]
        p = urlparse(world.url)
        return bool(actions) and (site(world.url) not in {s, site(before[0])}
                                  or (parse_qs(p.query).get(KEYS[s]) not in (None, [query])))
    if "urls" in expected and world.url not in {before[0], "about:blank"}:
        wanted = expected["urls"]
        if world.url.rstrip("/") in [u.rstrip("/") for u in wanted]:
            return False
        p = urlparse(world.url)
        # A same-site home/search page is incomplete progress, another detail/link is wrong.
        return world.url not in HOMES.values() and not any(k in parse_qs(p.query) for k in KEYS.values())
    if expected.get("new_tab") or expected.get("close_tab") or "tab" in expected:
        return bool(actions) and not check(world, before, expected, actions)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=["legacy", "goal"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--group", action="append")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve() / "src"))
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use an empty output directory; old traces must not contaminate this run")
    args.output.mkdir(parents=True, exist_ok=True)
    config = args.output / "settings.json"
    config.write_text(json.dumps({"browser": "safari", "search_engine": "google"}))
    os.environ["LAYA_CONFIG"] = str(config.resolve())
    from laya_voice_browser.controller import StreamingController
    from laya_voice_browser.laya import LayaEngine
    from laya_voice_browser.types import Element, Snapshot, Tab, TranscriptEvent
    if args.mode == "goal":
        from laya_voice_browser.goal_controller import GoalController
        from laya_voice_browser.goal_engine import GoalEngine
        engine, controller_type = GoalEngine(), GoalController
    else:
        engine, controller_type = LayaEngine(), StreamingController
    engine.warm()
    pages, scenarios = cases()
    rows = []
    for case in scenarios:
        if args.group and case["group"] not in args.group:
            continue
        world = World(pages, case["start"], Snapshot, Element, Tab)
        messages = []
        controller = controller_type(world, engine, announce=messages.append,
                                     trace_path=args.output / f"{case['name']}.jsonl")
        dependent = True
        try:
            for index, item in enumerate(case["steps"]):
                row = {"case": case["name"], "step": index, "group": case["group"],
                       "source": case["source"], "text": item["text"], "expected": item["expected"]}
                if not dependent:
                    row["result"] = "blocked_dependency"
                else:
                    start = len(world.actions)
                    before = world.url, len(world.tabs), world.current, world.scroll
                    began = time.perf_counter()
                    controller.submit(TranscriptEvent(item["text"], item.get("final", True),
                                                       f"{case['name']}:{index}", time.time()))
                    controller.wait_idle(timeout=60)
                    actions = world.actions[start:]
                    passed = check(world, before, item["expected"], actions)
                    wrong = wrong_action(world, item["expected"], actions, before)
                    status = (controller.goal.status if args.mode == "goal" and controller.goal
                              else controller.last_policy.verdict if controller.last_policy else "none")
                    outcome = ("harness_limit" if world.unsupported else "pass" if passed else
                               "wrong_action" if wrong else "incomplete")
                    row.update(result=outcome, actions=actions, url=world.url, status=status,
                               false_success=status == "verified_done" and not passed,
                               elapsed_ms=round((time.perf_counter() - began) * 1000),
                               messages=messages[-5:])
                    dependent = outcome == "pass"
                rows.append(row)
                print(json.dumps({k: v for k, v in row.items() if k not in {"messages", "expected"}}),
                      flush=True)
                (args.output / "rows.json").write_text(json.dumps(rows, indent=2) + "\n")
        finally:
            controller.close()
    counts = Counter(r["result"] for r in rows)
    by_group = {g: dict(Counter(r["result"] for r in rows if r["group"] == g))
                for g in sorted({r["group"] for r in rows})}
    traces = [json.loads(line) for p in args.output.glob("*.jsonl") for line in p.read_text().splitlines()]
    times = ([r["latency_ms"] for r in traces if "operation" in r and "latency_ms" in r]
             if args.mode == "goal" else [r["timing"]["model_ms"] for r in traces if "timing" in r])
    commit = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
    digest = hashlib.sha256()
    for path in sorted((args.source / "src").rglob("*")):
        if path.suffix in {".py", ".json"}:
            digest.update(str(path.relative_to(args.source)).encode())
            digest.update(path.read_bytes())
    summary = {"mode": args.mode, "model": engine.model_name, "commit": commit,
               "source_digest": digest.hexdigest(),
               "counts": dict(counts), "by_group": by_group, "steps": len(rows),
               "median_decision_model_ms": statistics.median(times) if times else None,
               "warning": "Development replay: real inference, simulated browser; not live or held out"}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
