# Experimental model-led goal loop

Branch: `experiment/laya-goal-loop`. Not enabled by default; no changes to the installed service's settings.

The goal is for **Laya to choose the browser's next action**, observe its effect, and continue towards the
whole spoken request. This experiment does not call the legacy intent parser, lexical winner, site-pack
phrase matcher, or fallback policy. It uses no generative LLM or cloud inference.

## Try it

Use the existing development environment. The first goal-mode run downloads a separate ~650 MB checkpoint.
The model stays in the Hugging Face cache, outside the repository. Subsequent loads prefer that local copy.

```bash
source .venv/bin/activate
python -m laya_voice_browser --goal-loop --browser safari \
  --command 'can you open wikipedia and search for Mercury' \
  --trace runs/my-goal.jsonl
```

Quit Safari normally before the test if SafariDriver cannot establish an automation session. Allow Remote
Automation must still be enabled. This opens a Safari automation window, not your ordinary signed-in tabs.
Do not use it for purchases or account actions. By default the test closes its owned browser session afterward;
`--keep-open` uses the existing CLI's keep-open behavior.

Voice development entry point: `layabrowse daemon --goal-loop --trace runs/voice-goals.jsonl`.
The native helper must be rebuilt from this branch to send the new `voice_off` cancellation event; an older
binary only sends `voice_on`. Do not rely on double-tap-off cancellation with that older binary.
Stop the normal LayaBrowse app first; do not run two native speech/hotkey helpers simultaneously. The normal
installed app does not pass this flag. This voice entry point is wired and unit-tested, but the new mode's
complete microphone/hotkey flow has **not** been live-verified.

After stopping the normal app, rebuild with `./native/build.sh`, then run the goal-mode daemon above.
This rebuild updates the local development app bundle; it is not necessary for typed `--command` tests.

In this experiment, partial transcripts revise the goal and invalidate pending decisions, but execution waits
for an ASR final. A final such as “search for” is still rejected for missing its object. Double-tap off cancels
the loop; explicit `stop`/`cancel` does too. A tool action already dispatched cannot be undone by cancellation.

## What Laya decides

```text
whole request + current page + executed history
    → Laya operation choice
    → Laya compatible target choice
    → Laya literal text-span choice, when needed
    → validation → browser tool → fresh observation
    → ask Laya again, or stop/clarify
```

- Operations: `CLICK`, `TYPE_TEXT`, available scrolling, `WAIT`, `DONE`, `BLOCKED`.
- CLICK targets include observed links/search controls and explicitly labelled **Browser** tools:
  named site/URL navigation, site search, back, new/close/switch tab.
- TYPE_TEXT targets are supported, writable search fields. A field already holding a proposed literal
  value is not offered as a no-op typing target.
- Search tools use the existing site URL templates plus eBay. Both current-site and web-search choices can
  be offered; **Laya chooses the scope**. This is not a rule automatically redirecting every search to Google.
- Arguments are exact speech substrings or explicitly spoken/known site URLs. Missing text means clarify.
- `DONE` means **the model says done**, not independent proof of success. The benchmark checks outcomes
  separately. Non-DONE typed runs exit with code 4; browser-session loss uses code 3.

Literal-span extraction, supported-site names, URL templates, capability filters and safety vetoes are still
deterministic software. They define possible tools/arguments; they do not choose which offered action wins.
This is deliberately not a claim that the app contains no rules.

Within 45 seconds, an explicit “and …”/“then …” continuation retains the earlier goal and executed history.
An unrelated new utterance replaces the goal. Partial revisions preserve the continuation prefix. This
limited continuation rule is not general dialogue understanding; pronouns, corrections and nested requests
still need evaluation.

## What the three upstream repositories taught us

### Laya

[Model and sequence implementation](https://github.com/NandhaKishorM/laya/blob/main/laya/common.py):
each question encodes its type, instructions, option markers and state. A bidirectional encoder and decision
layers score those options. `choice` returns a categorical distribution; `noul` uses false/true options;
`score` takes an expectation over ordered rubric levels. None generates field text or executable code.

`confidence` for choices is **one minus normalized entropy**, not the probability that an action is correct.
`action.act_probability` belongs to the trained escalation head; it is not authorization to operate a browser.
Proper-scoring-rule training and temperature scaling do not guarantee calibration on our browsing distribution.

The particularly relevant discovery was upstream's
[browser fine-tuning report](https://github.com/NandhaKishorM/laya/blob/main/docs/finetune_browser_agent.md).
It reports large gains on operation/target decisions over zero-shot checkpoints, but only partial live task
success. Those are upstream measurements, not LayaBrowse results.

### Laya-MLX

[Runtime](https://github.com/mizorewww/laya-mlx/blob/main/laya_mlx/agent.py) and
[README](https://github.com/mizorewww/laya-mlx): MLX preserves the architecture and question/result schema.
Questions have independent encoder computations; batching is not a shared representation of the whole page.
The prefix and state both consume context. Options can be shortened during prefix construction, so checking
only the final state length is insufficient.

The experiment rejects over-budget goal/instruction/option inputs instead of silently truncating them.
Page text is trimmed first; the full goal and the retained history must fit. Target sets that cannot fit a
single prefix use model-chosen group finalists and a final model comparison. No embedding/word-overlap
shortlist discards targets, but grouped selection itself can introduce errors and extra latency.

### Jev Ultrafast

[Policy](https://github.com/browser-use/jev-ultrafast/blob/main/jev_ultrafast/model.py),
[questions](https://github.com/browser-use/jev-ultrafast/blob/main/jev_ultrafast/questions.py),
[loop](https://github.com/browser-use/jev-ultrafast/blob/main/jev_ultrafast/agent.py): a persistent goal,
fresh observations, dynamic operation/compatible-target **choice** questions, execution history and bounded
repetition. Its current browser loop does not use noul/score questions. An additional generative model supplies
typed strings; LayaBrowse intentionally replaces that component with literal speech spans.

Our browser tools differ from Jev's DOM-only action space: a model-selected site-search URL is an explicit
capability, not a simulated DOM click. Our questions run in stages instead of speculatively evaluating every
target head; this avoids unused local model passes. Source code was not copied wholesale.

## Checkpoint and input contract

Default in goal mode only:

- Repository: [cklxx/laya-browser](https://huggingface.co/cklxx/laya-browser)
- Revision: `8a7e625b481d292d830acf22a2feec81554575fa`
- Subfolder: `v10s`, mmBERT-based 322M browser-trained checkpoint
- Context: 1,024 tokens; prefix budget: 768; FP16 MLX inference
- Loaded directly by laya-mlx's weight adapter; no conversion or training required for this experiment

Goal is in each question's instructions; state contains page URL/title/text and the last four executed
actions. Target descriptions carry labels, roles, current values and observed control state. This follows
the browser checkpoint's compact v3 layout, with our additional browser tools and shorter instructions.
Those differences are distribution shifts and are **not** assumed accuracy-neutral.

`--model` can select another checkpoint for comparison. Base checkpoints' smaller prefix budgets may reject
these questions; the program will not silently force the browser schema into 192 tokens.

## Guards and known limits

- Up to 12 actions, 20 loop decisions, three consecutive WAITs, and a 45-second goal lifetime. The lifetime
  cannot interrupt a browser call already running; backend timeouts still apply.
- Every new speech update invalidates pending work. Cancelled utterances cannot restart via late finals.
- Re-observe before execution; discard stale predictions. Stable node IDs, document identity, field values,
  tab identity and scrolling now participate in observations. Hydration settling is bounded to 0.6–1.2 seconds
  after an action; it is not an assurance that every web app is ready.
- Repeated/no-progress actions stop. Execution is logged before the next observation to avoid retrying a
  completed action when observation fails.
- Known bot-check/challenge pages stop for human attention. A URL with no observed title, text or controls
  cannot justify DONE; it receives a bounded readiness wait. These checks veto unsupported states, not pick
  substitute actions. They do not bypass website challenges.
- Probability integrity is validated. The chosen final option must have probability ≥0.50 and margin ≥0.10.
  These are conservative **un-calibrated experimental thresholds**, not a promised wrong-action rate.
- Password/upload/disabled/read-only controls and recognizable purchase/account-changing actions are excluded.
  Arbitrary forms/buttons, checkout, login and messaging are out of scope. Semantic label/URL filtering is not
  a security boundary against a malicious website. Use signed-out test sessions.
- At most 80 observed controls; no general shadow-DOM/iframe support. Dropping a target at observation time
  still limits model recall. Dropdown/filter/media capabilities are not at parity with the standard mode.

## Measurements from development, 2026-09-23

These are small development probes, not a locked test set or a broad success-rate claim.

- The published browser-checkpoint Wikipedia fixture loaded and selected TYPE_TEXT and its search target.
- An eight-case next-step probe passed six cases and abstained on two. This measures individual choices,
  not goal completion. The blank-page checker was subsequently tightened to check the named destination,
  not merely that some navigation occurred; this stricter version awaits a fresh model run.
- First five-site Safari run: matching query/result pages observed for GitHub, Amazon and eBay; Wikipedia and
  YouTube did not complete. None reliably ended with the model choosing DONE.
- A subsequent settled Wikipedia run reached the Mercury article/disambiguation page through model-chosen
  navigation, typing and Search submission. It still made an unnecessary further typing action and then
  clarified. After adding no-op typing guards, a repeat also reached Mercury, but unnecessarily reopened
  the homepage first (five actions, about 12.5 seconds). Exact current-destination navigation is now omitted
  from the offered capabilities as another no-op; this does not select a replacement action.
- That Wikipedia run recorded approximately 50–162 ms of model inference per decision; total run about
  8.9 seconds. These numbers exclude question preparation from model time and include browser/loading work
  in total time. They are not microphone-to-action latency.
- Shortening versus restoring the original operation instructions did not repair stopping on the recorded
  GitHub result state. A later completion-head probe was also negative: `noul` assigned P(done)=0.9939 to
  Wikipedia's homepage after typing Mercury but before submission, and 0.9851 to the completed Mercury page.
  A separate DONE/CONTINUE choice still chose CONTINUE on that completed page (0.9769). Neither experimental
  completion head was added to the runtime. These few examples illustrate failure, not a calibrated metric.

The latest five-site rerun was mixed: GitHub both showed matching results and ended with Laya choosing DONE;
Amazon showed results but clarified; Wikipedia stopped after typing; YouTube chose DONE on an empty observed
page; eBay chose DONE on a browser-challenge page. Empty-page/challenge vetoes were added after that run.
Do not interpret any earlier reached-page result as consistent end-to-end success.

Raw local traces stay in ignored `runs/`; they may contain speech and page content. Do not publish them
without reviewing and sanitizing them.

## Reproduce and next work

```bash
pytest -q
ruff check src tests scripts/benchmark_goal_loop.py
python scripts/benchmark_goal_loop.py --output runs/goal-fixtures.json
python scripts/benchmark_goal_loop.py --live --browser safari --output runs/goal-live.json
```

The next priority is stopping accuracy: label real before/after states with remaining work and DONE, include
multi-step negatives, and measure held-out goal completion and extra actions—not only target top-1. The
browser checkpoint is a useful starting point, not a guarantee. Only then compare a completion head or
browser-domain fine-tuning, followed by streaming execution and more capabilities. Do not turn this mode on
by default until goal completion, wrong actions, cancellation and microphone flows pass live evaluation.
