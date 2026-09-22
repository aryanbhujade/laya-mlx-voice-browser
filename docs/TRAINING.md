# Training and calibration

Laya can run this project without additional training, but its general checkpoint is not automatically a
well-calibrated browser-command policy. The first real smoke test demonstrated this: the model correctly chose
`navigate_url` for “go to Wikipedia,” while its independent `is_command` probability was only `0.0964`.
Deterministic syntax and safety policy currently cover that failure, but they do not replace evaluation.

## Do this before fine-tuning

1. Collect real partial and final transcripts from consenting test sessions.
2. Remove private payloads and label intent, completeness, command/not-command, site and expected target.
3. Split by speaker, site and session so near-duplicate partials cannot leak into validation.
4. Measure each question head separately and plot false-activation versus missed-command rates.
5. Fit thresholds or calibration temperatures only on a calibration split; report a held-out test split once.

Run the starter evaluation:

```bash
python scripts/evaluate_commands.py \
  --predictions runs/browser-command-predictions.jsonl
```

The included 20 rows are smoke fixtures, not a credible benchmark. A useful calibration set should contain at
least hundreds of complete commands, incomplete prefixes, corrections, side speech, ambiguous targets and
destructive actions. Production-oriented fine-tuning should use thousands of diverse labeled decisions.

See `BASELINE.md` for the first measured comparison across the English, multilingual and typed-decisions
Laya-MLX checkpoints.

## When to fine-tune

Fine-tune after the action schema and questions stop changing and threshold calibration still leaves a material
accuracy gap. The upstream Laya repository provides an RLCD fine-tuning notebook using proper-scoring-rule
rewards. Convert or publish the resulting checkpoint for Laya-MLX only after evaluating it against the untouched
test split.

Useful training examples are typed decisions, not browser automation traces by themselves:

```json
{
  "state": {"transcript": "click the first result", "elements": ["e04 link ..."]},
  "question": "Which supported browser operation is intended?",
  "criteria": ["click_element", "navigate_url", "search_web", "none"],
  "answer": "click_element"
}
```

Do not train directly on passwords, private messages, browsing history or raw account pages. Prefer synthetic
pages and redacted transcript spans. Keep deterministic authorization and stale-page checks even after a model
is fine-tuned; higher model accuracy is not permission to perform an action.
