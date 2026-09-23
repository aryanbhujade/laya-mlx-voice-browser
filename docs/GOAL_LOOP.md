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
- `DONE` currently means the model says done, not independent verification. A few live searches worked,
  but premature stopping, extra actions and abstentions remain. This is a rollback checkpoint, not a
  production-ready replacement. Non-DONE command runs exit with code 4; lost sessions use code 3.
- Site names, URL templates, literal text candidates and safety filters define available tools; Laya
  selects among them. Upstream accuracy and latency are not LayaBrowse benchmark claims.

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
