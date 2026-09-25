#!/usr/bin/env python3
"""Varied live browsing journeys on an unchanged app build, with independent effect checks.

Typed final/partial events exercise the real controller/model/browser, not microphone recognition.
Scenario setup is explicitly NOT credited to Laya. No purchases, logins or account mutations.
Private page traces/screenshots/results are written only to the selected local output directory.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

from laya_voice_browser.browsers import open_browser
from laya_voice_browser.goal_controller import GoalController
from laya_voice_browser.goal_engine import GoalEngine
from laya_voice_browser.types import TranscriptEvent


def step(id, text, expect, *, requires=None, final=True):
    return dict(id=id, text=text, expect=expect, requires=requires, final=final)


SCENARIOS = {
    "blank-tab-navigation": (["https://www.google.com/", "about:blank",
                             "https://github.com/fastapi/fastapi"], [
        step("first", "go to the first tab", {"tab_ref": "setup0"}),
        step("next-blank", "next tab", {"tab_ref": "setup1"}, requires="first"),
        step("last", "go to the last tab", {"tab_ref": "setup2"}),
        step("previous-blank", "go to the previous tab", {"tab_ref": "setup1"}, requires="last"),
        step("named", "switch to the GitHub tab", {"tab_ref": "setup2"}),
        step("close-others-unsupported", "close all other tabs", {"no_action": True}),
        step("new-google", "open a new tab", {"new_tab": True, "site": "google.com"}),
        step("close-new", "close this tab", {"close_tab": True}, requires="new-google"),
    ]),
    "google-new-tabs": ("about:blank", [
        step("blank-search", "search for Steve Jobs", {"search": ["google.com", "q", "Steve Jobs"]}),
        step("new-google", "open a new tab", {"new_tab": True, "site": "google.com"}),
        step("github", "in a new tab open GitHub and search for ESP32",
             {"new_tab": True, "search": ["github.com", "q", "ESP32"]}, requires="new-google"),
        step("generic-new-search", "open a new tab and search for Ada Lovelace",
             {"new_tab": True, "search": ["google.com", "q", "Ada Lovelace"]}),
    ]),
    "ebay-categories": ("https://www.ebay.com/", [
        step("electronics", "can you click on electronics", {"label": "Electronics"}),
        step("cameras", "click on cameras and photo", {"label": "Cameras & Photo"},
             requires="electronics"),
        step("vintage-tab", "open vintage cameras in a new tab",
             {"label": "Vintage Cameras", "new_tab": True}, requires="cameras"),
        step("down", "scroll down", {"scroll": "down"}, requires="vintage-tab"),
        step("up", "scroll back up", {"scroll": "up"}, requires="down"),
        step("close", "close this tab", {"close_tab": True}, requires="vintage-tab"),
        step("camcorders", "click on camcorders", {"label": "Camcorders"}, requires="close"),
        step("back", "go back", {"ref": "cameras"}, requires="camcorders"),
    ]),
    "ebay-search": ("https://www.ebay.com/", [
        step("search", "can you search for night vision camera",
             {"search": ["ebay.com", "_nkw", "night vision camera"]}),
        step("first", "open the first listing", {"result": 1}, requires="search"),
        step("back", "go back", {"ref": "search"}, requires="first"),
        step("second-tab", "open the second listing in a new tab",
             {"result": 2, "new_tab": True}, requires="back"),
        step("close", "close this tab", {"close_tab": True}, requires="second-tab"),
    ]),
    "ebay-followups": ("https://www.ebay.com/sch/i.html?_nkw=Sony+camcorder", [
        step("second", "click on the second item", {"result": 2}),
        step("back", "go back", {"ref": "setup"}, requires="second"),
        step("next-page", "go to the next page of listings", {"pagination": "next"}, requires="back"),
        step("negated", "don't open the first listing", {"no_action": True}),
        step("no-purchase", "buy the first item now", {"no_action": True}),
    ]),
    "web-search": ("about:blank", [
        step("google", "Search Google for Python pathlib documentation",
             {"search": ["google.com", "q", "Python pathlib documentation"]}),
        step("plain-web", "search for beginner astronomy guides",
             {"search": ["google.com", "q", "beginner astronomy guides"]}),
    ]),
    "google-links": ("https://www.google.com/search?q=Python+pathlib+documentation", [
        step("first", "open the first link", {"result": 1}),
        step("back", "go back", {"ref": "setup"}, requires="first"),
        step("second", "click the second link", {"result": 2}, requires="back"),
    ]),
    "wikipedia": ("about:blank", [
        step("article", "Could you open Wikipedia and look up Ada Lovelace?",
             {"url": "https://en.wikipedia.org/wiki/Ada_Lovelace"}),
        step("down", "Could you scroll down a little please", {"scroll": "down"}, requires="article"),
        step("up", "scroll up", {"scroll": "up"}, requires="down"),
        step("talk", "open the Talk page", {"label": "Talk"}, requires="up"),
        step("back", "go back", {"ref": "article"}, requires="talk"),
        step("site-in-query", "search Wikipedia for GitHub", {"url": "https://en.wikipedia.org/wiki/GitHub"}),
    ]),
    "repositories": ("about:blank", [
        step("search", "Can you search GitHub for fastapi?", {"search": ["github.com", "q", "fastapi"]}),
        step("first", "open the first repository", {"result": 1}, requires="search"),
        step("down", "scroll down a page", {"scroll": "down"}, requires="first"),
        step("up", "scroll up a page", {"scroll": "up"}, requires="down"),
        step("issues", "open Issues", {"label": "Issues"}, requires="up"),
    ]),
    "result-history": ("https://github.com/search?q=rust+cli&type=repositories", [
        step("first", "open the first repository", {"result": 1}),
        step("back", "go back", {"ref": "setup"}, requires="first"),
        step("second", "open the second repository", {"result": 2}, requires="back"),
        step("back-again", "go back", {"ref": "setup"}, requires="second"),
        step("forward", "go forward", {"ref": "second"}, requires="back-again"),
    ]),
    "tabs": ("https://en.wikipedia.org/wiki/Golden_retriever", [
        step("new", "open a new tab", {"new_tab": True}),
        step("github", "in this tab open GitHub", {"site": "github.com"}, requires="new"),
        step("switch", "switch to the Wikipedia tab", {"tab_ref": "setup"}, requires="github"),
        step("next", "next tab", {"tab_ref": "github"}, requires="switch"),
        step("previous", "previous tab", {"tab_ref": "setup"}, requires="next"),
        step("negated-close", "please don't close this tab", {"no_action": True}),
        step("close", "close this tab", {"close_tab": True}, requires="previous"),
    ]),
    "youtube": ("about:blank", [
        step("search", "Find origami crane tutorials on YouTube",
             {"search": ["youtube.com", "search_query", "origami crane tutorials"]}),
        step("second", "play the second video", {"result": 2}, requires="search"),
        step("back", "go back", {"ref": "search"}, requires="second"),
        step("third", "show me the third video", {"result": 3}, requires="back"),
        step("down", "scroll down", {"scroll": "down"}, requires="third"),
        step("up", "scroll up a little", {"scroll": "up"}, requires="down"),
        step("pause", "pause the video", {"paused": True}, requires="third"),
    ]),
    "new-tab-search": ("https://en.wikipedia.org/wiki/Golden_retriever", [
        step("httpx", "in a new tab search GitHub for httpx",
             {"search": ["github.com", "q", "httpx"], "new_tab": True}),
        step("return", "switch to the Wikipedia tab", {"tab_ref": "setup"}, requires="httpx"),
        step("more", "and scroll down", {"scroll": "down"}, requires="return"),
    ]),
    "shopping-and-negatives": ("about:blank", [
        step("amazon", "search Amazon for mechanical pencils",
             {"search": ["amazon.com", "k", "mechanical pencils"]}),
        step("ebay", "search eBay for used cameras", {"search": ["ebay.com", "_nkw", "used cameras"]}),
        step("side-talk", "that YouTube video was interesting", {"no_action": True}),
        step("partial", "search GitHub for", {"no_action": True}, final=False),
        step("missing-query", "search GitHub for", {"no_action": True}),
        step("cancel", "stop", {"no_action": True}),
    ]),
    "isolated-article-controls": ("https://en.wikipedia.org/wiki/Grace_Hopper", [
        step("down", "Could you scroll down a little please", {"scroll": "down"}),
        step("up", "scroll up", {"scroll": "up"}),
        step("talk", "open the Talk page", {"label": "Talk"}),
        step("history", "open View history", {"label": "View history"}),
        step("context-down", "and scroll down", {"scroll": "down"}),
        step("context-up", "and scroll up", {"scroll": "up"}),
        step("more", "a little bit more", {"scroll": "up"}),
    ]),
    "isolated-repo-controls": ("https://github.com/fastapi/fastapi", [
        step("down", "scroll down a page", {"scroll": "down"}),
        step("up", "scroll up a page", {"scroll": "up"}),
        step("issues", "open Issues", {"label": "Issues"}),
        step("pulls", "show pull requests", {"label": "Pull requests"}),
    ]),
    "isolated-result-history": ("https://github.com/search?q=rust+cli&type=repositories", [
        step("second-short", "open the second repository", {"result": 2}),
        step("second-full", "search GitHub for rust cli and open the second repository", {"result": 2}),
        step("back", "go back", {"ref": "setup"}, requires="second-full"),
        step("forward", "go forward", {"ref": "second-full"}, requires="back"),
        step("back-again", "go back", {"ref": "setup"}, requires="forward"),
        step("first-full", "search GitHub for rust cli and open the first repository",
             {"result": 1}, requires="back-again"),
    ]),
    "isolated-video-controls": ("https://www.youtube.com/results?search_query=origami+crane+tutorials", [
        step("second-short", "play the second video", {"result": 2}),
        step("second-full", "search YouTube for origami crane tutorials and open the second video",
             {"result": 2}),
        step("back", "go back", {"ref": "setup"}, requires="second-full"),
        step("third-full", "search YouTube for origami crane tutorials and open the third video",
             {"result": 3}, requires="back"),
        step("down", "scroll down", {"scroll": "down"}, requires="third-full"),
        step("up", "scroll up a little", {"scroll": "up"}, requires="down"),
        step("pause", "pause the video", {"paused": True}, requires="third-full"),
    ]),
    "isolated-tabs": (["https://en.wikipedia.org/wiki/Grace_Hopper", "https://github.com/fastapi/fastapi"], [
        step("wiki", "switch to the Wikipedia tab", {"tab_ref": "setup0"}),
        step("named", "switch to the Grace Hopper tab", {"tab_ref": "setup0"}),
        step("next", "next tab", {"tab_ref": "setup1"}, requires="named"),
        step("previous", "previous tab", {"tab_ref": "setup0"}, requires="next"),
        step("github", "switch to the GitHub tab", {"tab_ref": "setup1"}),
        step("close", "close this tab", {"close_tab": True}),
        step("new", "open a new tab", {"new_tab": True}),
        step("close-new", "close tab", {"close_tab": True}, requires="new"),
    ]),
    "fresh-scroll-followups": ("https://en.wikipedia.org/wiki/Apollo_11", [
        step("context-down", "and scroll down", {"scroll": "down"}),
        step("more", "a little bit more", {"scroll": "down"}),
        step("context-up", "and scroll up", {"scroll": "up"}),
        step("direct-down", "please scroll down a bit", {"scroll": "down"}),
        step("direct-up", "can you scroll up please", {"scroll": "up"}),
    ]),
    "fresh-tab-previous": (["https://en.wikipedia.org/wiki/Grace_Hopper",
                            "https://github.com/fastapi/typer"], [
        step("previous", "previous tab", {"tab_ref": "setup0"}),
    ]),
    "fresh-tab-next": (["https://github.com/fastapi/typer", "https://en.wikipedia.org/wiki/Grace_Hopper"], [
        step("next", "next tab", {"tab_ref": "setup0"}),
    ]),
    "fresh-history": ({"history": ["https://en.wikipedia.org/wiki/Grace_Hopper",
                                   "https://en.wikipedia.org/wiki/Apollo_11"]}, [
        step("back", "go back", {"ref": "setup0"}),
        step("forward", "go forward", {"ref": "setup1"}, requires="back"),
    ]),
}


def identity(url):
    p = urlparse(url)
    if (p.hostname or "").endswith("ebay.com"):
        item = re.fullmatch(r"/itm/(?:[^/]+/)?(\d{12})/?", p.path)
        if item:
            return f"{p.hostname}:item:{item[1]}"
    if p.hostname in {"www.youtube.com", "youtube.com"} and p.path == "/watch":
        return "youtube:" + parse_qs(p.query).get("v", [""])[0]
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", p.query, p.fragment))


def active(page):
    return next((t.id for t in page.tabs if t.active), "")


def destination_matches(url, requested):
    actual, wanted = urlparse(url), urlparse(requested)
    return ((actual.hostname or "").removeprefix("www.") == (wanted.hostname or "").removeprefix("www.")
            and unquote(actual.path).casefold() == unquote(wanted.path).casefold()
            and all(parse_qs(actual.query).get(k) == v for k, v in parse_qs(wanted.query).items()))


def rendered(browser, timeout=10, requested=None):
    deadline = time.monotonic() + timeout
    while True:
        page = browser.snapshot()
        search = urlparse(page.url).path in {"/search", "/results", "/sch/i.html"}
        ready = bool(page.title and (page.text or page.elements))
        correct_destination = not requested or destination_matches(page.url, requested)
        if correct_destination and ready and (not search or not page.browsing
                                               or page.browsing.get("results_ready")):
            return page
        if ((page.url == "about:blank" and correct_destination) or time.monotonic() >= deadline):
            return page
        time.sleep(0.25)


def target(browser, page, spec, refs):
    expected = dict(spec)
    if "pagination" in spec:
        url = browser.driver.execute_script(
            "return document.querySelector('a.pagination__next[href]')?.href || null")
        if not url:
            raise ValueError("next page is not observed")
        expected["url"] = url
    if "ref" in spec:
        expected["url"] = refs[spec["ref"]].url
    if "tab_ref" in spec:
        expected["tab"] = active(refs[spec["tab_ref"]])
    if "label" in spec:
        needle = spec["label"].casefold()
        matches = [e for e in page.elements if e.href and
                   (e.text.casefold() == needle or e.text.casefold().startswith(needle + " "))]
        if not matches:
            raise ValueError("requested link not in observed controls")
        expected["url"] = matches[0].href
    if "result" in spec:
        links = page.browsing.get("results", [])
        if "google." in (urlparse(page.url).hostname or ""):
            links = browser.driver.execute_script(
                "return [...document.querySelectorAll('#search a')].filter(a=>a.querySelector('h3'))"
                ".map(a=>({url:a.href,title:a.innerText}))")
        urls = []
        page_host = urlparse(page.url).hostname or ""
        for link in links:
            url = link["url"]
            parsed = urlparse(url)
            if not url.startswith("https://"):
                continue
            if page_host in {"www.ebay.com", "ebay.com"}:
                item = re.fullmatch(r"/itm/(?:[^/]+/)?(\d{12})/?", parsed.path)
                if not item or item[1] == "000000000000":
                    continue
            # A result card's homepage or docs link is not a result. Counting doc.rust-lang.org as
            # GitHub's second repository failed a run in which Laya had opened the right one.
            if "google." not in page_host and parsed.hostname != page_host:
                continue
            if parsed.hostname == "github.com" and (len(parsed.path.strip("/").split("/")) != 2
                                                     or parsed.path.startswith("/topics/")):
                continue
            if parsed.hostname == "www.youtube.com" and (parsed.path != "/watch"
                    or "v" not in parse_qs(parsed.query) or "list" in parse_qs(parsed.query)):
                continue
            if identity(url) not in [identity(u) for u in urls]:
                urls.append(url)
        if len(urls) < spec["result"]:
            raise ValueError("requested result not rendered; cannot establish an independent target")
        expected["url"] = urls[spec["result"] - 1]
    return expected


def check(browser, before, after, expected, actions):
    tests = []
    if "url" in expected:
        tests.append(identity(after.url) == identity(expected["url"])
                     and bool(after.title and after.elements))
    if "site" in expected:
        tests.append((urlparse(after.url).hostname or "").removeprefix("www.") == expected["site"])
    if "search" in expected:
        site, key, query = expected["search"]
        parsed = urlparse(after.url)
        tests.append((parsed.hostname or "").removeprefix("www.") == site
                     and parse_qs(parsed.query).get(key) == [query]
                     and bool(after.title and (after.text or after.elements)))
        if site == "ebay.com":
            tests.append(bool(after.browsing.get("results_ready") and after.browsing.get("results")))
    if "scroll" in expected:
        delta = after.scroll_y - before.scroll_y
        tests.append(after.url == before.url and active(after) == active(before)
                     and (delta > 0 if expected["scroll"] == "down" else delta < 0))
    if "tab" in expected:
        tests.append(active(after) == expected["tab"])
    if expected.get("new_tab"):
        old, new = {t.id for t in before.tabs}, {t.id for t in after.tabs}
        tests.append(old < new and len(new) == len(old) + 1 and active(after) not in old)
    if expected.get("close_tab"):
        tests.append({t.id for t in after.tabs} == {t.id for t in before.tabs} - {active(before)})
    if expected.get("no_action"):
        tests.append(not actions and after.url == before.url and after.tabs == before.tabs
                     and after.scroll_y == before.scroll_y)
    if expected.get("paused"):
        tests.append(browser.driver.execute_script(
            "const v=document.querySelector('video');return !!v && v.paused"))
    return bool(tests) and all(tests)


class RecordingBrowser:
    """Count this step's actual dispatches, not history inherited from earlier utterances."""

    def __init__(self, browser):
        self.browser = browser
        self.actions = []

    def snapshot(self):
        return self.browser.snapshot()

    def execute(self, action, **kwargs):
        result = self.browser.execute(action, **kwargs)
        self.actions.append(dict(action))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", choices=list(SCENARIOS))
    parser.add_argument("--output", type=Path,
                        default=Path("runs") / datetime.now().strftime("exercise-%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    engine = GoalEngine()
    engine.warm()
    browser = open_browser("safari")
    rows = []
    try:
        for name in args.scenario or SCENARIOS:
            start, steps = SCENARIOS[name]
            # Harness-owned cleanup/setup, explicitly excluded from model action counts.
            while len(browser.snapshot().tabs) > 1:
                browser.execute({"type": "close_tab"})
            refs, passed = {}, set()
            urls = (start["history"] if isinstance(start, dict)
                    else start if isinstance(start, list) else [start])
            for index, url in enumerate(urls):
                if index and not isinstance(start, dict):
                    browser.execute({"type": "new_tab"})
                browser.execute({"type": "navigate", "url": url})
                refs[f"setup{index}"] = rendered(browser, requested=url)
                if not destination_matches(refs[f"setup{index}"].url, url):
                    raise RuntimeError(f"Harness setup did not reach {url}; do not score this scenario")
            refs["setup"] = rendered(browser)
            recorded = RecordingBrowser(browser)
            controller = GoalController(recorded, engine)
            try:
                for item in steps:
                    key = f"{name}-{item['id']}"
                    row = {"case": key, "text": item["text"], "setup_url": start}
                    if item["requires"] and item["requires"] not in passed:
                        row.update(result="blocked_dependency", reason=item["requires"])
                    else:
                        before = rendered(browser)
                        try:
                            expected = target(browser, before, item["expect"], refs)
                        except (KeyError, ValueError) as exc:
                            row.update(result="blocked_observation", reason=str(exc),
                                       url=before.url, title=before.title)
                            (args.output / f"{key}-pages.json").write_text(json.dumps(
                                {"before": asdict(before)}, indent=2))
                            browser.driver.save_screenshot(str(args.output / f"{key}.png"))
                        else:
                            controller.trace_path = args.output / f"{key}.jsonl"
                            recorded.actions = []
                            started = time.perf_counter()
                            controller.submit(TranscriptEvent(item["text"], item["final"], key, time.time()))
                            controller.wait_idle(timeout=60)
                            actions = recorded.actions
                            after = rendered(browser, requested=expected.get("url") if actions else None)
                            status = controller.goal.status if controller.goal else "none"
                            effect = check(browser, before, after, expected, actions)
                            success = effect and (item["expect"].get("no_action")
                                                  or status in {"verified_done", "direct_done"})
                            row.update(result="pass" if success else "fail", status=status,
                                       expected=expected, observed_effect=effect, url=after.url,
                                       actions=actions,
                                       false_success=status == "verified_done" and not effect,
                                       elapsed_ms=round((time.perf_counter() - started) * 1000))
                            if success:
                                passed.add(item["id"])
                                refs[item["id"]] = after
                            (args.output / f"{key}-pages.json").write_text(json.dumps(
                                {"before": asdict(before), "after": asdict(after)}, indent=2))
                            browser.driver.save_screenshot(str(args.output / f"{key}.png"))
                    rows.append(row)
                    (args.output / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
                    print(json.dumps(row), flush=True)
            finally:
                controller.close()
    finally:
        browser.close()
    return 0 if all(r["result"] == "pass" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
