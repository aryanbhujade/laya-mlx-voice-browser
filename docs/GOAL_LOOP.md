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
- Explicit “and / then” continuations within 45 seconds retain unfinished work. After verified
  completion they start a fresh request on the current page; general corrections and pronouns remain limited.
- Decisions are bounded by time, action count, repeated actions, stale-page checks and confidence gates.
  Challenges and empty pages cannot justify success. Credentials and account-changing actions are excluded.
- Success is reported only when the requested outcome is verified in the observed page (below). Laya
  saying `DONE` alone ends as `unverified_done`. Command runs exit 0 for a verified or direct result,
  4 otherwise, and 3 for a lost session.
- Site names, URL templates, literal text candidates and safety filters define available tools; Laya
  selects among them. Upstream accuracy and latency are not LayaBrowse benchmark claims.

## Verified completion

Before acting, Laya chooses the requested **outcome** from a finite set of contracts: open a site, search
it, open result *n*, operate a tab, or scroll. Rules propose contracts from literal speech — the site named,
the query span, a spoken result number — and Laya picks one, or `unsupported`. The contract is then
checked against every observation, so the loop stops on evidence rather than on the model's `DONE`:

- **open_site** — the site's page rendered.
- **search** — the site's search URL carries exactly the query, *and* its result list rendered.
- **open_result** — the search was observed first, and the page is the *n*th result it listed.
- **tabs / scrolling** — the requested tab identity/count or same-page scroll position changed as requested.

Verification checks that the **chosen** outcome happened, not that it was the one meant, so the proposal
step carries correctness. A tab or scroll contract is offered only when its own words are spoken, as a
search needs a query and a result needs a result clause; a negated control ("don't close this tab") is
vetoed. Before this, a broad live run had "please don't close this tab" close a tab and "open the Talk
page" open a blank one, both reported as verified.

**Links** — "open the Talk page", "show pull requests". A link on the page and a navigation the site pack
declares (GitHub's issues or releases, YouTube's history) both end at a URL, so they are one outcome:
Laya chooses among the page's links and the pack's destinations, or "none of these", and the loop checks
the browser arrived. Offered only when navigation is spoken and not negated. Pack templates that need a
path, such as GitHub's owner/repository, are offered only on a page that has one.

On four real page snapshots from the live run, 8 of 12 link requests picked the right link, 3 abstained
and 1 was confidently wrong ("show the edit history" chose Edit). Asking in groups of 6 or 9 turned
abstentions into wrong links, and putting the pack's longer labels first was also worse, so neither is
used. **For links, verification proves the browser reached the link Laya chose, not that it was the one
meant**, so a wrong choice is reported as done. The destination is a navigation, never a submission.

After a search is verified, the numbered-result argument is bound to the observed URL. Only tools compatible
with remaining work are offered; Laya still chooses whether to act, wait or report a blocker. An early DONE
gets verifier feedback and bounded recovery, never a fabricated success. Known loading pages wait for DOM
evidence for up to eight seconds, within the overall goal deadline.

Evidence comes from the site pack's `browsing` probe (see [Writing site packs](SITE_PACKS.md)). This is a
pilot tested on Wikipedia, YouTube and GitHub. eBay search/listing observations are now implemented
but live Safari validation is pending; other site-search outcomes are refused rather than attempted
unverified. Generic observed links can be opened on other sites. A browser challenge never counts
as success.

### eBay milestone (development)

- The pack declares search/listing evidence and observed pagination links, not command regexes for
  the goal loop. Item IDs deduplicate thumbnail/title/tracking links; placeholder listings do not count.
- "Open the second listing" binds the current search and result URL before leaving that page. It
  does not ask Laya to extract a query that was never spoken. A requested new tab retains that URL.
- "Open vintage cameras in a new tab" cannot choose a blank-tab-only outcome that drops the
  destination. Laya must choose a link or decline. "Scroll back up" is a direct scroll, not history.
- Filters, price/condition/sort changes, purchases and account actions remain outside this milestone.
  Follow-up clarification replies such as "number one" are not implemented in the goal loop.
- Synthetic regression tests and DOM checks pass. Local-model synthetic probes still abstain on
  "click on the second item"; no real-site accuracy claim follows from these tests. Live Safari
  comparison reached eBay's browser challenge, so shopping-site reliability remains unverified.

After quitting Safari normally, run the private, signed-out acceptance journeys:

```bash
python scripts/exercise_goal_browser.py --scenario ebay-categories --scenario ebay-search --scenario ebay-followups
```

These replay the logged category/search/new-tab/scroll journey with expected destinations independent
of the model's chosen contract. Setup is not credited to Laya; unavailable controls block dependent
checks. Keep the resulting page traces under ignored `runs/`, not in the public repository.

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
python scripts/check_goal_milestone.py --output runs/milestone-check
```

Live checks navigate test sites. Traces in ignored `runs/` may contain speech/page content; do not publish
them without sanitizing. Historical experiments and design notes remain in Git history.

### Paired development comparison, 2026-09-24

Published `main` (`a85d294`, legacy controller, `aac6fef/laya-mlx`) versus this branch with goal mode
enabled (`cklxx/laya-browser/v10s`). This compares complete systems, not architecture alone: the
checkpoint differs too. Neither the installed default mode nor main was changed. These are typed
transcript tests, not microphone/ASR measurements, and not a held-out product-accuracy estimate.

`scripts/compare_branches.py` runs identical requests through each version's actual model/controller.
Browser effects are simulated. Twenty cases use previously captured public-page element inventories;
the other cases use synthetic observations for controlled multi-step transitions. Explicit expectations
score destination/query/tab/scroll effects, never the model's own chosen contract. The historical
Alison Frantz target label was corrected: her portrait is not her article.

| Paired replay group | Main passes | Goal-loop passes |
| --- | ---: | ---: |
| Links on saved real pages | 19/20 | 11/20 |
| Site searches | 7/12 | 7/12 |
| Separate open-site / search follow-ups | 7/12 | 8/12 |
| Search then open numbered result, one request | 0/9 | 6/9 |
| Numbered result on current search page | 2/9 | 9/9 |
| Destination in a new tab | 0/4 | 4/4 |
| Category / scroll / back journey | 2/5 | 4/5 |
| Basic browser controls | 5/6 | 4/6 |
| Tabs | 5/5 | 3/5 |
| Negated, side-talk or incomplete requests | 7/9 | 9/9 |
| Unfinished speech must not act | 5/5 | 5/5 |

Coverage is 59/96 for main and 70/96 for the loop, including dependent steps that could not run
(3 main, 2 loop). Do not relabel these coverage fractions as general accuracy. The loop's wrong
portrait selection reported `verified_done`; URL arrival still does not prove intended-link correctness.
The replay observed 22 wrong-action cases on main versus 1 on the loop; incomplete/abstaining cases
were 12 versus 23. A search containing "and open the first video" as query text is a wrong query,
not merely unfinished work. These counts apply only to this development suite.

`scripts/compare_live.py` also scheduled 25 steps per version in owned Safari sessions, with bounded
render waits and independent expected links. Main completed 5; the loop completed 15. Different
dependent steps became reachable, and Google/eBay challenges prevented a clean global percentage.
The loop completed Wikipedia compound/follow-up searches, the five-step YouTube search/result/back/
new-tab/close journey, and Talk-in-a-new-tab. It abstained on GitHub's second repository: interpretation
was correct, but operation scores split between DONE (0.4942) and CLICK (0.361). Main sent Wikipedia
and GitHub follow-up searches to a web search engine, lost the target after opening a blank tab,
and interpreted "scroll back up" as Back. A wrong Back landing on a challenge is still an agent error.

Next priorities: distinguish same-label destinations (article vs image); prevent premature DONE from
blocking known-unfinished work without forcing clicks; improve target/operation calibration on real
pages; restore relative tabs/reload and generic web search; then extend shopping controls after live
observation. Keep Laya selecting actions; do not turn failing phrases into automatic regex dispatch.

Reproduce with fresh private output directories (do not reuse an old trace directory):

```bash
python scripts/compare_branches.py --source /path/to/main-checkout --mode legacy --output runs/main-replay
python scripts/compare_branches.py --source . --mode goal --output runs/goal-replay
python scripts/compare_live.py --source /path/to/main-checkout --mode legacy --output runs/main-live
python scripts/compare_live.py --source . --mode goal --output runs/goal-live
```

Replay fixes browser/search-engine settings to Safari/Google in a private temporary config file;
live runs retain the user's settings. These tests do not publish traces, model weights or screenshots.

The three-site development smoke test passed in Safari on 2026-09-23: Wikipedia → Mercury (3 actions),
YouTube → ESP32 → first video page (2), GitHub → ESP32 repositories (1), with no extra actions after success.
These are typed requests, not a microphone accuracy benchmark; opening a video page does not verify playback
past ads. The smoke test checks fixed expected outcomes independently of the model-selected contract.

Architecture references: [Laya browser training](https://github.com/NandhaKishorM/laya/blob/main/docs/finetune_browser_agent.md),
[laya-mlx](https://github.com/mizorewww/laya-mlx), [Jev Ultrafast](https://github.com/browser-use/jev-ultrafast).
