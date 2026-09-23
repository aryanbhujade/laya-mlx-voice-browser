# Three problems worth solving next

Where this comes from: a development session that measured what Laya currently contributes, why its
weakest head is weak, and how the experimental goal loop on `experiment/laya-goal-loop` compares.
Every number below was measured locally on small development sets; none is a benchmark claim.

The aim is unchanged: **Laya decides what the browser does next**, observes the result, and continues
until the spoken request is satisfied. These three pieces of work are what stands between that aim
and the code as it exists.

They are independent. Only the first is research; the other two are engineering, and the third
deletes more code than it adds.

---

## 1. Knowing when to stop

### Why this blocks everything else

A loop that cannot tell "finished" from "not finished" has two failure modes and no third option: it
stops while work remains, or it keeps acting after the work is done. Every other capability —
deeper goals, more sites, corrections — multiplies whichever one it has. Goal *depth* is capped by
stopping accuracy, so this decides how ambitious the loop is allowed to be.

### What was measured

The standard pipeline's `complete` head, which answers "has the speaker finished the command", was
measured on 1,062 rows extracted from a real service log:

| | |
|---|---|
| AUC | **0.560** (0.5 is no signal) |
| Best achievable accuracy | 0.718 |
| Majority baseline | 0.718 |

Nothing beats always answering "incomplete" without running the model. Twelve formulations were
tried before concluding this — five wordings, `true`/`false` criteria, a declarative statement, a
`choice` recast, naming the state field in backticks as upstream's presets do, a transcript-only
state, and a bare string state as the published examples use. All sat on the baseline. Details in
[BASELINE.md](BASELINE.md).

The goal loop's DONE decision, on the browser-tuned `cklxx/laya-browser` checkpoint, fails the same
way. On a Wikipedia article page:

| Goal | Truth | Result |
|---|---|---|
| "open wikipedia and search for Alan Turing" | satisfied | abstained |
| "open wikipedia and search for Mercury" | not satisfied | abstained |
| "open the talk page" | work remains | CLICK at 0.989 |

It cannot separate the satisfied case from the unsatisfied one, while ordinary next-step choices are
confident and correct. The branch's own probes agree and are starker: `noul` gave P(done) = 0.9939 to
Wikipedia's homepage *before* the search was submitted, and a DONE/CONTINUE choice picked CONTINUE on
the completed page. A five-site live run ended with YouTube choosing DONE on an empty page and eBay
choosing DONE on a bot-challenge page.

The important conclusion: **browser fine-tuning fixed operation and target selection but not
completion.** These are different abilities, and only one of them has been trained.

### The dataset, and why it is nearly free

Completeness data needs no annotation. Apple Speech already labels it: every partial transcript that
the final one goes on to extend was, at that moment, incomplete; the final is complete.
`scripts/extract_completeness.py` does this, and one development log produced 1,062 rows from 373
utterances (763 incomplete, 299 complete).

Stopping data is the same trick one level up. A goal trace in `runs/` records, for each decision, the
page state before, the action taken, and the page state after. A run that ended with the goal
satisfied gives one positive at the final state and one negative at *every* earlier state. A run that
ended without satisfying the goal gives negatives throughout. The labels come from the outcome check
the benchmark already performs — `outcome_matches` in `scripts/benchmark_goal_loop.py` verifies the
destination and query independently of what the model claimed.

What has to be built, and it is small:

1. An extractor over `runs/*.jsonl`, in the shape of `extract_completeness.py`, emitting
   `{goal, page_before, action, page_after, remaining_work: bool}`.
2. Deliberate negatives that a happy-path run will not produce: a challenge page, an empty page, a
   search box filled but not submitted, the right site but the wrong query, a results page when the
   goal asked to open a result.
3. A split by goal and by site, so the same run's states cannot appear on both sides.

The third point matters more than it sounds. States within one run are near-duplicates; splitting
randomly would let the model memorise a page rather than learn the judgement, and the measurement
would look far better than it is.

### Three candidate fixes, cheapest first

**a. Verify the outcome deterministically instead of asking.** For the goals we support — open a
site, search it, open a result — "did it work" is checkable: compare the URL, the query parameter and
the page title against the request. `outcome_matches` already does exactly this in the benchmark.
Promoting it into the runtime would let the loop stop on evidence rather than opinion.

Its limit is honest and should be stated: it only covers goals whose success is expressible as a URL
check. "Find me a cheap one" is not. But that covers most of what the loop attempts today, and it
costs nothing at inference.

**b. Calibrate a stopping threshold on the labelled set.** Keep the model's DONE answer but stop
trusting its raw probability. Fit a temperature on a calibration split and report a reliability
curve, not a single number. This is worth doing only if the head has signal to calibrate — which the
dataset will say, and which `complete` did not.

**c. Fine-tune a completion head.** Upstream's README reports base checkpoints near chance on
typed-decisions zero-shot (0.362 against a 0.461 majority baseline) and the fine-tuned checkpoint at
0.766, above TypeSafe Jev's published 0.727. The browser checkpoint shows the same pattern within
this project: trained abilities work, untrained ones do not. Completion was not trained, so training
it is the intervention with precedent.

Do (a) first because it is deterministic and immediate, and it makes the loop useful while (c) is
evaluated. They are complementary: a verified outcome is a free label for training.

### How we will know it worked

Report goal completion and extra actions, not target top-1. Specifically:

- completion rate on held-out goals, checked by `outcome_matches` rather than by DONE;
- **stopped early** and **kept going after done** as separate rates, because they have different costs;
- actions per completed goal, against the minimum the goal needs;
- AUC of whatever stopping signal is used, on the held-out split.

A DONE rate on its own is not evidence. The branch already keeps Laya's DONE and the independent
outcome check in separate columns, and that separation should survive.

---

## 2. Universal commands at 0 ms, everything else into the loop

### What the usage actually looks like

300 distinct utterances from a real log, classified by what the deterministic layer can do with them:

| Path | Share |
|---|---:|
| Universal — scroll, back, forward, reload, tabs, media | 9.0% |
| Single deterministic command | 49.7% |
| Multi-step chain | 4.0% |
| **Nothing deterministic applies** | **37.3%** |

That last row is the case for the loop. It is not exotic speech; it is ordinary speech that depends
on context:

```
'Little bit more'                     continues a previous scroll
'to the YouTube one'                  elliptical tab reference
'And can you do the freeze frame one' refers to a result on screen
'Actually can we do documentaries about terrorism'  refines the last search
'Fill the query bar with the word skateboard'
```

These need the previous action, the page, or both. No regex reaches them, because the missing
information is not in the words. A loop that carries goal text and executed history has exactly what
they require.

### The routing rule

Route on syntax, never on a model judgement:

- If the whole utterance is a bare universal command, execute it deterministically at 0 ms.
- Otherwise hand it to the loop.

`spans.universal_command` already implements the test and is already style- and courtesy-tolerant:
"scroll down", "scroll down please", "Could you scroll down please", "Can you scroll down even more"
all qualify, while "scroll down to the comments" and "forward this email" do not.

The reason to keep this syntactic is that the obvious alternative — asking the model whether this is a
simple command — is the `is_command` judgement, and that head admits 8 of 8 wrong answers at its
current threshold. Routing must not depend on the weakest part of the system.

### What this buys

Scrolling, history and tab movement mean the same thing on every website. There is nothing to
understand, so spending a model pass on them buys nothing and costs the one thing a voice interface
cannot spare: the feeling that it responded instantly. Meanwhile the 37% that genuinely needs
understanding stops being handled by regexes that were only ever approximating understanding.

It also reverses the ratchet. Every failure so far was answered by adding a rule, which shrank the
model's share each time. Fixed routing means new capability lands in the loop by default, and the
deterministic set stays small and stable.

### Risks

- **Latency for the 91%.** Everything that is not a bare universal command pays a model pass —
  roughly 30–60 ms measured on the browser checkpoint. That is acceptable for speech; the earlier
  concern about multi-second runs was page loading, which both paths pay.
- **Regression against today's behaviour.** The 49.7% single deterministic commands currently work
  and are fast. Moving them into the loop must be measured before it is adopted, using
  `scripts/measure_model_contribution.py`, which already reports rules-only against with-Laya per
  benchmark. Move them in stages, not all at once.
- **Cancellation.** The loop can have an action in flight when the speaker changes their mind. The
  branch invalidates pending work on every speech update and treats double-tap-off as cancellation;
  an action already dispatched cannot be recalled. That boundary should be stated in the UI, not
  just in a doc.

---

## 3. Site packs as capabilities, not matchers

### The problem being solved

A pack action already carries both halves of what the loop needs: a description
("switch theater mode on or off") and an implementation (`{"key": "t"}`). That is the same shape as
the loop's `Candidate` — a label plus an action.

But packs also carry a *matcher*. `sites.match_phrase` and `sites.lexical_match` decide by regex and
word overlap, and their answer then competes with grammar, with lexical element ranking, and with the
model. Several decision-makers, one decision.

Every site-pack bug found in that session was two of them disagreeing:

| Symptom | Cause |
|---|---|
| "go back" ran Google's *previous page of results* | pack matcher beat the grammar rule |
| "scroll down" jumped to YouTube's comments | pack term matched two of three words |
| "search for cats on YouTube" searched for "cats on YouTube" | payload rules and the model disagreed |

The fixes were referees: `universal_command` to stop packs redefining universal commands, `paths` to
stop controls being offered where they do not exist, `_GENERIC` to stop everyday words selecting a
control, a request-shape gate for model-chosen controls. All of that machinery exists to adjudicate a
fight.

### What changes

The pack stops deciding and only offers. On a YouTube watch page Laya would see one list:

```
Browser: go back
Browser: open a new tab
Browser: search youtube for the requested topic
YouTube: switch theater mode on or off
YouTube: scroll down to the comments
YouTube: open my watch later list
YouTube: like this video            [side effect]
YouTube: subscribe to this channel  [confirm]
Talk (link)
View history (link)
```

…and picks one. One ranked set, one decision, one vocabulary. The disagreements above are not
expressible, because there is nothing left to disagree with.

Mechanically this is small: `sites.SitePack.available(url)` already returns the actions that exist on
the current page, and `goals.action_space` already builds a `dict[str, Candidate]`. The work is to
map one into the other and delete the matchers.

### What it preserves

- `confirm` and `side_effect` still gate execution *after* Laya picks. Safety is applied to the
  chosen action, which is where it belongs.
- `paths` decides whether an option is offered at all — the same filtering the loop already does for
  page elements.
- `say` and `terms` do not disappear; they become the description text the model ranks against, and
  the seed corpus for evaluating whether the model finds a control from natural phrasing.

### What it deletes

`lexical_match` and its `_GENERIC` rule, the request-shape gate for model-chosen controls, and the
`universal_command` override for packs. Those are referees, and there is no fight to referee.
`match_phrase` may survive as an explicit fast path for exact spoken phrases, but only if it is
measured to be worth the divergence it reintroduces.

### Migration

Do it behind the goal-loop flag, where the standard mode is untouched. A pack contributes candidates
in the loop and continues to be matched in the standard mode until the loop is the default. The
regression test is the existing `datasets/site_controls.jsonl`, scored the same way: the executed
action must match, and rows labelled `expected: null` must execute nothing.

The wider benefit is what pack authors have to know. Today a pack is partly a matching problem — the
`_GENERIC` rule, the `terms` that must not collide, the `paths` that stop a control being chosen
where it does not exist. Merged, a pack is a description of what a site can do, and contributors stop
writing matching logic, which is the part they would get wrong.

---

## Order of work

1. **Stopping (1)** — it gates goal depth, and it is the only one that might not work. Start with
   deterministic outcome verification, which is immediate, then build the labelled set and decide
   between calibration and fine-tuning on evidence.
2. **Routing (2)** — independent of stopping, and it can ship for universal commands alone before
   the loop takes over anything else.
3. **Packs (3)** — do this once the loop is carrying real traffic, because the payoff is deleting
   referee code, and the referees are only unnecessary when there is a single decision-maker.

Nothing here requires the standard mode to be turned off, and none of it should be turned on by
default until goal completion, wrong actions, cancellation and the microphone flow have been measured
live rather than on fixtures.
