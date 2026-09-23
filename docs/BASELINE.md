# Initial raw-checkpoint smoke results

Measured locally on 2026-09-22 with `scripts/evaluate_commands.py` and the 20 rows in
`datasets/browser_commands.jsonl`. These are development smoke results, not a benchmark: the set is tiny,
English-only, manually authored and has no independent test split.

| Laya-MLX checkpoint | Intent | Command gate | Completeness | Site |
|---|---:|---:|---:|---:|
| `aac6fef/laya-multilingual-mlx` | 65% | 10% | 85% | 25% |
| `aac6fef/laya-typed-decisions-mlx` | 80% | 45% | 10% | 95% |
| `aac6fef/laya-mlx` | 65% | 80% | 75% | 90% |

The English checkpoint is the default because it had the strongest balance on this English smoke set. None
of the three is accurate enough to justify autonomous execution from raw probabilities alone. The runtime
therefore keeps deterministic grammar for explicit commands, exact site and payload extraction, confidence
gates, stale-page checks and destructive-action confirmation.

## Why these numbers look the way they do

Upstream says so plainly. The Laya README reports that **the base checkpoints are near chance on
typed-decisions zero-shot** — 0.362 against a 0.461 majority baseline — and that fine-tuning is what
produces strong performance; the fine-tuned checkpoint reaches 0.766, above TypeSafe Jev's published
0.727. This project runs a base checkpoint, zero-shot, on a domain it was never fine-tuned for, so
near-chance heads are the documented behaviour rather than a sign of misuse.

Two further upstream limitations apply directly here:

- **High-cardinality choice.** A 77-option question "allocates only ~3–4 tokens per label, causing
  accuracy to fall off sharply (0.425 vs Jev's 0.870)". This does **not** apply here, and it was
  worth measuring rather than assuming: the `intent` question uses 162 of its 192 prefix tokens, all
  15 options are rendered untruncated, and the longest is 14 tokens against a 48-token cap. Nothing
  is starved, so `laya_mlx.shortlist` is not a remedy for this project — see below.
- **Ordinal `score` is the weakest primitive** (SST-5 0.372), which is what `scroll_amount` uses.

laya-mlx adds: "confidence does not guarantee accuracy."

## Three fixes that were tried on the intent head and did not work

Recorded so they are not attempted again from scratch. Baseline is the single 15-option question at
18/26 = 0.692, with mean confidence 0.977 when right and 0.879 when wrong.

| Attempt | Result |
|---|---|
| Group the 15 options into 5 abstract families, then ask within the family | 0.385 — the family head sends "press enter", "open a new tab" and "switch to the next tab" all to `navigate` |
| `laya_mlx.shortlist` with `embed_fn_from_agent`, k = 10/8/6 | 0.577 / 0.538 / 0.462 ranking on the state; 0.654 / 0.654 / 0.385 ranking on the transcript alone |
| Prune options to the ten the page can actually support, reaching the calibrated 6-10 bucket | 0.692, unchanged, and confidence separation falls from +0.098 to +0.026 |

The shortlist result has a clear cause: retrieval drops the correct label before the model sees it.
At k = 6 the right answer survives in only 10 of 26 rows, which caps accuracy below the baseline
whatever the model then does. Mean-pooled encoder embeddings rank `search_web` above `go_back` for
"go back" and above `press_enter` for "press enter". Shortlisting is for option sets too large to
render; ours is not one.

The pruning result rules out the remaining prompt-shaped explanation: reaching the calibrated bucket
changes neither the accuracy nor, usefully, the confidence. What is left is the checkpoint itself,
which is what the upstream zero-shot warning above already said.

## `complete` measured on real speech

`scripts/extract_completeness.py` turns a service log into labelled data without hand annotation:
every partial transcript the final one goes on to extend was incomplete when it was seen, and the
final is complete. One development log produced 1,062 rows from 373 utterances — 763 incomplete, 299
complete, majority baseline 0.718.

The current `complete` question scores **AUC 0.560** on that set, where 0.5 is no signal. Its best
achievable accuracy is 0.718, exactly the majority baseline: nothing beats always answering
"incomplete" without running the model. Twelve formulations were tried — five wordings, `true`/`false`
criteria, a declarative statement, a `choice` recast, naming the state field in backticks as the
upstream presets do, a transcript-only state, and a bare string state — and every one of them sat on
the baseline.

The head is therefore not carrying the streaming gate, and no prompt change makes it. The two honest
options are to detect an unfinished command with grammar, which is a syntactic question that rules
answer well, or to fine-tune this head on data like the above. The extraction script exists so that
the second is cheap; its output stays outside the repository because transcripts contain whatever was
spoken near the microphone.

The next defensible milestone is a larger speaker/session-separated dataset followed by threshold calibration.
Browser-specific fine-tuning is justified if held-out intent or target selection remains inadequate after the
schema and candidate shortlisting stabilize.
