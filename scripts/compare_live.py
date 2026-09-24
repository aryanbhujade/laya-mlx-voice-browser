#!/usr/bin/env python3
"""Paired live Safari development journeys. Owned signed-out session; no purchases/account changes.

Run sequentially for --mode legacy and goal with each --source. Public sites/results can change
between runs; observations establish expected result destinations at runtime, not from model contracts.
Outputs are private screenshots/traces. Blocked pages/dependent steps are NOT model-accuracy failures.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


def identity(url):
    p = urlparse(url)
    if p.path == "/watch":
        return p.netloc, p.path, parse_qs(p.query).get("v")
    return p.netloc, unquote(p.path).rstrip("/"), parse_qs(p.query), p.fragment


def blocked(browser):
    title, url = browser.driver.execute_script("return [document.title,location.href]")
    title = title.lower().strip(' .')
    return (title in {"pardon our interruption", "access denied", "robot check", "error page | ebay"}
            or "/splashui/challenge" in url or "/sorry/" in url)


def results(browser):
    p = urlparse(browser.driver.current_url)
    selectors = {
        "github.com": "[data-testid='results-list'] a[href]",
        "www.youtube.com": "ytd-video-renderer a#video-title, yt-lockup-view-model a[href*='/watch?']",
        "www.google.com": "#search a:has(h3)",
        "www.ebay.com": ".srp-results a[href*='/itm/']",
    }
    selector = selectors.get(p.hostname)
    if not selector:
        return []
    links = browser.driver.execute_script(
        "return [...document.querySelectorAll(arguments[0])].filter(a=>a.getClientRects().length)"
        ".map(a=>a.href)", selector)
    out = []
    for url in links:
        u = urlparse(url)
        if p.hostname == "github.com" and (u.hostname != "github.com"
                or len(u.path.strip('/').split('/')) != 2 or u.path.startswith('/topics/')):
            continue
        if p.hostname == "www.youtube.com" and (u.path != "/watch" or "list" in parse_qs(u.query)):
            continue
        if not any(identity(url) == identity(other) for other in out):
            out.append(url)
    return out


def observe(browser):
    p = browser.snapshot()
    return dict(url=p.url, title=p.title, tabs=[(t.id, t.active) for t in p.tabs],
                scroll=browser.driver.execute_script("return scrollY"), blocked=blocked(browser))


def settle(browser, expected_url=None):
    """Don't score Safari's transient previous document or a search skeleton as the result."""
    deadline = time.monotonic() + 8
    stable, last = 0, None
    while True:
        page = observe(browser)
        stamp = page['url'], page['title']
        stable = stable + 1 if stamp == last else 0
        last = stamp
        is_search = urlparse(page['url']).path in {'/search', '/results', '/sch/i.html'}
        ready = (page['url'] == 'about:blank' or bool(page['title'])) and (not is_search or results(browser))
        wanted = expected_url is None or identity(page['url']) == identity(expected_url)
        if page['blocked'] or (stable >= 3 and ready and wanted) or time.monotonic() >= deadline:
            return page
        time.sleep(.25)


class Recorder:
    def __init__(self, browser):
        self.browser, self.actions = browser, []

    def snapshot(self):
        return self.browser.snapshot()

    def execute(self, action, **kwargs):
        outcome = self.browser.execute(action, **kwargs)
        self.actions.append(action)
        return outcome

    def show_candidates(self, candidates):
        self.browser.show_candidates(candidates)

    def clear_candidates(self):
        self.browser.clear_candidates()


def journeys():
    wiki = "https://en.wikipedia.org/wiki/Grace_Hopper"
    return [
        ("wiki-compound", "about:blank", [
            ("open Wikipedia and search for Mercury", {"url": "https://en.wikipedia.org/wiki/Mercury"})]),
        ("wiki-followups", "about:blank", [
            ("open Wikipedia", {"host": "en.wikipedia.org"}),
            ("and search for Ada Lovelace", {"url": "https://en.wikipedia.org/wiki/Ada_Lovelace"})]),
        ("youtube", "about:blank", [
            ("open YouTube and search for origami crane tutorials",
             {"search": ["www.youtube.com", "search_query", "origami crane tutorials"]}),
            ("open the first video", {"result": 1}),
            ("go back", {"search": ["www.youtube.com", "search_query", "origami crane tutorials"]}),
            ("open the second video in a new tab", {"result": 2, "new_tab": True}),
            ("close this tab", {"close_tab": True})]),
        ("github", "https://github.com/", [
            ("search for rust cli", {"search": ["github.com", "q", "rust cli"]}),
            ("open the second repository", {"result": 2}),
            ("open Issues", {"label": "Issues"}),
            ("go back", {"back": True})]),
        ("google", "https://www.google.com/", [
            ("search Google for Python pathlib documentation",
             {"search": ["www.google.com", "q", "Python pathlib documentation"]}),
            ("click the first link", {"result": 1})]),
        ("ebay", "https://www.ebay.com/", [
            ("can you search for night vision camera",
             {"search": ["www.ebay.com", "_nkw", "night vision camera"]}),
            ("open the first listing", {"result": 1})]),
        ("ebay-categories", "https://www.ebay.com/b/Cameras-Photo/625/bn_1865546", [
            ("open vintage cameras in a new tab", {"label": "Vintage Cameras", "new_tab": True}),
            ("close this tab", {"close_tab": True}),
            ("click on camcorders", {"label": "Camcorders"})]),
        ("wiki-controls", wiki, [
            ("scroll down a page", {"scroll": "down"}),
            ("scroll back up", {"scroll": "up"})]),
        ("wiki-new-tab", wiki, [
            ("open the Talk page in a new tab", {"label": "Talk", "new_tab": True}),
            ("please don't close this tab", {"none": True}),
            ("close this tab", {"close_tab": True})]),
        ("side-talk", wiki, [("we should go back to the office", {"none": True})]),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=["legacy", "goal"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--journey", action="append")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use an empty output directory; old traces must not contaminate this run")
    sys.path.insert(0, str(args.source.resolve() / 'src'))
    from laya_voice_browser.browsers import open_browser
    from laya_voice_browser.controller import StreamingController
    from laya_voice_browser.laya import LayaEngine
    from laya_voice_browser.types import TranscriptEvent
    if args.mode == 'goal':
        from laya_voice_browser.goal_controller import GoalController
        from laya_voice_browser.goal_engine import GoalEngine
        engine, controller_type = GoalEngine(), GoalController
    else:
        engine, controller_type = LayaEngine(), StreamingController
    args.output.mkdir(parents=True, exist_ok=True)
    engine.warm()
    browser = open_browser('safari')
    rows = []
    try:
        for name, start, steps in journeys():
            if args.journey and name not in args.journey:
                continue
            while len(browser.snapshot().tabs) > 1:
                browser.execute({'type': 'close_tab'})
            browser.execute({'type': 'navigate', 'url': start})
            setup = settle(browser, start)
            if not setup['blocked'] and identity(setup['url']) != identity(start):
                raise RuntimeError(f"Harness setup did not reach {start}; don't score it")
            recorder = Recorder(browser)
            messages = []
            c = controller_type(recorder, engine, announce=messages.append,
                                trace_path=args.output / f'{name}.jsonl')
            previous_ok = True
            try:
                for i, (text, wanted) in enumerate(steps):
                    expected = dict(wanted)
                    row = dict(journey=name, step=i, text=text)
                    if not previous_ok:
                        row['result'] = 'blocked_dependency'
                    elif blocked(browser):
                        row['result'] = 'browser_blocked'
                        previous_ok = False
                    else:
                        before = settle(browser)
                        if 'result' in wanted:
                            links = results(browser)
                            if len(links) >= wanted['result']:
                                expected['url'] = links[wanted['result'] - 1]
                            else:
                                row['result'] = 'oracle_unavailable'
                        if 'label' in wanted:
                            matches = browser.driver.execute_script(
                                "return [...document.querySelectorAll('a[href]')].filter(a=>"
                                "a.getClientRects().length && (a.innerText.trim()===arguments[0] || "
                                "a.innerText.trim().startsWith(arguments[0]+' '))).map(a=>a.href)",
                                wanted['label'])
                            if matches:
                                expected['url'] = matches[0]
                            else:
                                row['result'] = 'oracle_unavailable'
                        if 'result' not in row:
                            offset = len(recorder.actions)
                            c.submit(TranscriptEvent(text, True, f'{name}-{i}', time.time()))
                            c.wait_idle(timeout=60)
                            after = settle(browser, expected.get('url'))
                            actions = recorder.actions[offset:]
                            checks = []
                            if 'url' in expected:
                                checks.append(identity(after['url']) == identity(expected['url']))
                            if 'host' in wanted:
                                checks.append(urlparse(after['url']).hostname == wanted['host'])
                            if 'search' in wanted:
                                host, key, query = wanted['search']
                                p = urlparse(after['url'])
                                checks.append(p.hostname == host and parse_qs(p.query).get(key) == [query]
                                              and bool(results(browser)))
                            if 'scroll' in wanted:
                                delta = after['scroll'] - before['scroll']
                                checks.append(after['url'] == before['url'] and
                                              (delta > 0 if wanted['scroll'] == 'down' else delta < 0))
                            if wanted.get('new_tab'):
                                checks.append(len(after['tabs']) == len(before['tabs']) + 1)
                            if wanted.get('close_tab'):
                                checks.append(len(after['tabs']) == len(before['tabs']) - 1)
                            if wanted.get('none'):
                                checks.append(not actions)
                            if wanted.get('back'):
                                checks.append(bool(actions) and actions[-1]['type'] == 'back'
                                              and after['url'] != before['url'])
                            wrong_dispatch = (wanted.get('none') and bool(actions)) or (
                                'scroll' in wanted and any(a['type'] != 'scroll' for a in actions))
                            # A wrong Back action that lands on an old challenge is still an agent
                            # error, not a website blocker. Don't hide it behind the resulting page.
                            result = ('fail' if wrong_dispatch else 'browser_blocked' if after['blocked'] else
                                      'pass' if checks and all(checks) else 'fail')
                            row.update(result=result, expected=expected, before=before, after=after,
                                       actions=actions, messages=messages[-5:])
                        previous_ok = row['result'] == 'pass'
                    browser.driver.save_screenshot(str(args.output / f'{name}-{i}.png'))
                    rows.append(row)
                    (args.output / 'rows.json').write_text(json.dumps(rows, indent=2) + '\n')
                    print(json.dumps(row), flush=True)
            finally:
                c.close()
    finally:
        browser.close()
    print(json.dumps(dict(Counter(r['result'] for r in rows))))


if __name__ == '__main__':
    main()
