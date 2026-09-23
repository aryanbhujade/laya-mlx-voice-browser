# Writing site packs

Site packs describe small, stable controls that are meaningful only on a particular website. They are plain
JSON files in `src/laya_voice_browser/sites/`; no model training is required.

## How matching works

1. `say` patterns are anchored regular expressions for explicit phrases.
2. `terms` are natural examples used for exact and clear lexical matches.
3. If no rule is clear, the most relevant controls become a short multiple-choice question for Laya.
4. If the evidence remains ambiguous, the site action is not run.

This makes site packs fast for familiar phrases while retaining a conservative fallback for looser language.

### What Laya's fallback will and will not do

A control Laya picks itself (rather than one a phrase named) is only run when the speech is also addressed to
the browser **and** shaped like a request. Both are needed: on a Gmail page, "my inbox is a complete disaster
honestly" matches the *inbox* control with 0.90 confidence, and the model's own "is this a command?" score does
not catch it. Requiring request shape does, and it costs nothing at runtime.

The cost of that conservatism is that question-shaped requests such as "has the build passed" are ignored, even
though Laya picks the right control: this model scores those lower on "is this a command?" than actual
small talk, so the two cannot be separated reliably (a targeted "do they mean this now?" question was measured
and overlapped just as badly).

Rephrasing as an imperative is not enough on its own: "show the CI runs" is ignored just like the question,
because neither shares a word with the control. What works is naming the control the way the site does —
"open Actions", "show me Actions". Adding the phrase to the pack's `terms` is the fix that always works,
because rule and lexical matches skip this gate entirely.

## Minimal example

```json
{
  "name": "Example",
  "hosts": ["example.com"],
  "actions": [
    {
      "id": "comments",
      "description": "scroll to the comments",
      "say": ["(show|open|scroll to) (the )?comments"],
      "terms": ["what are people saying", "show the discussion"],
      "do": {"scroll_to": ["#comments", "[aria-label='Comments']"]}
    }
  ]
}
```

## Action fields

| Field | Meaning |
|---|---|
| `id` | Stable unique identifier inside the pack |
| `description` | Short operation label shown to Laya and in status text |
| `say` | Full-match case-insensitive regular expressions |
| `terms` | Natural phrasings for lexical ranking and exact matching |
| `do` | Exactly one browser operation, described below |
| `confirm` | Always require spoken confirmation |
| `side_effect` | Require confirmation when an inferred/model match selects it |
| `instant` | May run before the speech recognizer marks the phrase final |
| `paths` | URL path prefixes this control exists on; omit when it exists site-wide |

Supported `do` operations:

```json
{"key": "t"}
{"click": ["visible label", "alternative label"]}
{"click_css": ["#stable-id", "[aria-label='Stable label']"]}
{"fill": ["input[name='q']"], "submit": true}
{"open": "https://example.com/search?q={text}"}
{"scroll_to": ["#comments", "[aria-label='Comments']"]}
{"media": "next"}
```

Open templates support:

- `{text}` — URL-encoded captured speech from `(?P<text>...)`.
- `{host}` — the current hostname without a leading `www.`.
- `{1}` through `{5}` — current URL path segments. GitHub uses `{1}/{2}` for owner/repository.

## Safety rules

- Set `confirm: true` for purchases, deletion, subscriptions, stars/favorites, watchlists and other account
  changes.
- Use `side_effect: true` for reversible preference actions such as like/dislike when explicit phrases may act
  directly but inferred matches should confirm.
- Never encode CAPTCHA solving, security-warning bypasses, payment submission or password handling.
- Keep `instant` for closed, harmless controls whose meaning cannot change with more words.
- Prefer doing nothing over selecting a weak match.
- A bare universal command ("go back", "forward", "reload", "new tab", "close tab", "scroll down")
  always belongs to the browser, whatever trailing politeness or "a bit more" follows it, so a `say`
  pattern or `term` that matches one on its own is ignored. Qualify it — "forward this email",
  "scroll down to the comments" — and it works.
- Scope a control that only exists on some pages with `paths`, so it cannot be chosen where it does
  not exist. YouTube's comments and theater mode are `["^/watch", "^/shorts/"]`; on a list of search
  results the control is absent and "scroll down" is an ordinary scroll. Entries are plain prefixes
  anchored with `^`, so a pack can be read without evaluating a regular expression.

## Durable selectors

Prefer, in order:

1. Accessible labels and visible text through `click`.
2. Stable semantic attributes such as `aria-label`, `name`, `data-testid` or documented IDs.
3. Short structural selectors scoped to a stable component.

Avoid hashed/generated class names, positional selectors over an entire page, text that includes a username or
account data, and locale-specific labels when alternatives exist.

## Tests and benchmark

Add representative rule, lexical, negative and confirmation cases to `tests/test_sites.py` and
`datasets/site_controls.jsonl`.

```bash
pytest -q tests/test_sites.py tests/test_engine.py tests/test_policy.py
ruff check .
PYTHONPATH=src python scripts/benchmark_site_packs.py --verbose
```

The benchmark loads Laya-MLX and requires an Apple-silicon Mac. Unit tests do not load the model.

Before submitting a pack, test its actual controls in a logged-out/non-sensitive page where possible. Clearly
state which selectors were live-tested and which are best-effort; a passing unit test does not prove that a live
site still exposes a selector.
