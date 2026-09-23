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
  accuracy to fall off sharply (0.425 vs Jev's 0.870)". Our `intent` question has 15 options and
  lands in the `choice:11+` temperature bucket that laya-mlx refuses to apply. `laya_mlx.shortlist`
  is the documented remedy: embed the state and the options, keep the top *k*, run one prediction on
  the reduced set. It keeps the options concrete, unlike grouping them into abstract families, which
  was measured here and was much worse (0.385 against 0.692 for the single question).
- **Ordinal `score` is the weakest primitive** (SST-5 0.372), which is what `scroll_amount` uses.

laya-mlx adds: "confidence does not guarantee accuracy."

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
