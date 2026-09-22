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

The next defensible milestone is a larger speaker/session-separated dataset followed by threshold calibration.
Browser-specific fine-tuning is justified if held-out intent or target selection remains inadequate after the
schema and candidate shortlisting stabilize.
