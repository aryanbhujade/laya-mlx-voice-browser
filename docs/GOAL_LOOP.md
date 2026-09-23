# Experimental Laya goal loop

Opt-in only. Laya chooses an operation, a compatible browser target, and literal speech text when
needed; the controller executes, observes, and asks again with the whole request and action history.
It does not use the legacy intent parser or site-pack phrase matchers. No generative LLM is involved.

## Run

```bash
source .venv/bin/activate
python -m laya_voice_browser --goal-loop --browser safari \
  --command 'open wikipedia and search for Mercury' --trace runs/my-goal.jsonl
```

Quit Safari normally first if SafariDriver cannot create its session. Enable Safari's Allow Remote
Automation. Tests use a separate automation window, not your signed-in tabs; avoid account actions.
The CLI closes its owned session afterward unless `--keep-open` is supplied.

Goal mode downloads the separate `cklxx/laya-browser` / `v10s` checkpoint (~650 MB), pinned to revision
`8a7e625b481d292d830acf22a2feec81554575fa`. It runs locally through laya-mlx with a 1,024-token context
and 768-token question prefix. Weights stay in the Hugging Face cache, not the repository.

For voice testing, stop the normal app, rebuild the helper with `./native/build.sh`, then run:

```bash
layabrowse daemon --goal-loop --trace runs/voice-goals.jsonl
```

The rebuilt helper is required for double-tap-off cancellation. Do not run two speech/hotkey helpers.
The installed app does not enable goal mode by default. The complete microphone flow remains unverified.

## Boundaries

- Execution waits for final speech; partials invalidate pending decisions. Explicit stop/cancel and
  listening-off cancel work. A browser action already dispatched cannot be recalled.
- Explicit “and / then” continuations within 45 seconds retain the earlier goal and history; general
  corrections and pronouns are not yet supported reliably.
- Decisions are bounded by time, action count, repeated actions, stale-page checks and confidence gates.
  Challenges and empty pages cannot justify success. Credentials and account-changing actions are excluded.
- Success is reported only when the requested outcome is verified in the observed page (below). Laya
  saying `DONE` alone ends as `unverified_done`. Command runs exit 0 for a verified or direct result,
  4 otherwise, and 3 for a lost session.
- Site names, URL templates, literal text candidates and safety filters define available tools; Laya
  selects among them. Upstream accuracy and latency are not LayaBrowse benchmark claims.

## Verified completion

Before acting, Laya chooses the requested **outcome** from a finite set of contracts: open a site, search
it, or open result *n* from its search. Rules propose the contracts from literal speech — the site named,
the query span, a spoken result number — and Laya picks one, or `unsupported`. The contract is then
checked against every observation, so the loop stops on evidence rather than on the model's `DONE`:

- **open_site** — the site's page rendered.
- **search** — the site's search URL carries exactly the query, *and* its result list rendered.
- **open_result** — the search was observed first, and the page is the *n*th result it listed.

Evidence comes from the site pack's `browsing` probe (see [Writing site packs](SITE_PACKS.md)). This is a
pilot on Wikipedia, YouTube and GitHub; other sites are refused rather than attempted unverified. A
browser challenge never counts as success.

Measured on 13 spoken goals with the browser checkpoint: 12 got kind, query and result number all
right. "go to github" abstained (Laya split 0.53/0.47 between unsupported and open_site), which fails
safe as a clarification. The result number is extracted from speech rather than chosen by Laya: offered
1–3, Laya scored near-uniform for anything but "first".

## Direct controls

Whole-utterance `back`, `forward` and `scroll up/down` (with courtesy words and "a little"/"a page") run
with no model pass and no settling wait, and interrupt a goal in progress. Final speech only. Tab
changes, continuations ("and scroll down") and anything qualified ("scroll down to the comments") go
to Laya instead.

## Check

```bash
pytest -q
ruff check src tests scripts/benchmark_goal_loop.py
python scripts/benchmark_goal_loop.py --output runs/goal-fixtures.json
python scripts/benchmark_goal_loop.py --live --browser safari --output runs/goal-live.json
```

Live checks navigate test sites. Traces in ignored `runs/` may contain speech/page content; do not publish
them without sanitizing. Historical experiments and design notes remain in Git history.

Architecture references: [Laya browser training](https://github.com/NandhaKishorM/laya/blob/main/docs/finetune_browser_agent.md),
[laya-mlx](https://github.com/mizorewww/laya-mlx), [Jev Ultrafast](https://github.com/browser-use/jev-ultrafast).
