# How LayaBrowse works

```text
LayaBrowse.app (Swift)                       Python backend (child process)               browser
shortcut → mic → Apple Speech partials ─────▶ rules + Laya decisions → policy ──────────▶ Safari (WebDriver)
notch island, menu, settings  ◀── status ──── controller, safety checks                    or Chromium (DevTools)
```

## Processes

- **`native/Laya/`** — the menu-bar app. launchd starts it at login (`layabrowse install` writes the
  LaunchAgent); it runs `python -m laya_voice_browser backend` as its child, so macOS attributes permissions
  and background activity to LayaBrowse. Transcripts go to the backend's stdin as JSON lines; the backend
  writes island statuses (`{"state": ...}`) and end-of-phrase hints (`{"endpoint": ...}`) to stdout.
- **`backend.py`** — reads transcripts, runs the controller, and opens the browser chosen in settings.
- **`controller.py`** — debounces partial transcripts, discards stale results, runs command chains, handles
  "confirm"/"cancel" and numbered choices, and records traces.

## Deciding what to do

Laya answers one multiple-choice question per model pass, over at most 512 tokens of
`[question + options] + state`, so latency grows with the number of questions (~20–60 ms each).

1. **Grammar first** (`spans.py`). Explicit commands are settled by rules; "go back", "go forward", "reload" and
   "new tab" run mid-speech with no model call. The speaking style decides whether polite requests ("could you
   please…") count as explicit.
2. **Stage 1** asks only the unsettled of `is_command`, `intent` and `complete`, over a slim state (transcript,
   page, four most relevant elements, recent actions).
3. **Stage 2** asks only what the intent needs, and only once the policy would act: `target` and
   `destructive` for clicks, `text_span` for searches, `url_span`/`site` when no site was named.
4. **Targets.** Elements are ranked by word overlap with the transcript; a unique best label match is used
   directly, and ties go to Laya's `target` question over at most nine `"label (role)"` options. If it is
   still unclear, numbered badges appear on the page.
5. **Policy** (`policy.py`, `safety.py`) applies confidence, completeness and payload gates, and requires a
   spoken "confirm" for destructive or account-changing actions.

State is ordered by usefulness and trimmed to fit each question's token budget instead of being cut silently.

## Browsers

- **`safari.py`** — SafariDriver automation windows.
- **`chromium.py`** — the Chrome DevTools Protocol, on a dedicated profile, with trusted mouse and keyboard
  input.
- **`page.py`** — the page snapshot script shared by both, and the rule that an action stays valid while the URL
  and its target element are unchanged.
- **`browsers.py`** — resolves "Automatic" to the macOS default browser.

## End of phrase

`native/Laya/Endpointer.swift` learns the speaker's gaps between words (a running mean and spread), waits
longer after connecting words, shortens once the backend reports the command complete, and becomes more
patient when the speaker resumes right after a phrase was ended.
