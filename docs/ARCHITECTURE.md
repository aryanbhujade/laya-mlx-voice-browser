# How LayaBrowse works

```text
double-tap → Apple Speech final transcript → proposed outcomes → Laya selects a goal
                                                          ↓
SafariDriver or Chromium ← execute compatible action ← Laya selects next action
          ↓                                               ↑
   observe fresh page → verify goal / update action history ──┘
```

The default is the goal loop, not the older rules-first command pipeline. Laya is a local classifier:
each question presents fixed choices, such as a requested outcome, operation or observed target. It
does not write arbitrary code or browse without tools. The Python controller dispatches the selected
typed action only after scope, confidence, safety and stale-page checks.

## Processes

- The Swift `LayaBrowse.app` owns the global shortcut, microphone, Apple Speech recognition, menu-bar
  status and notch island. `layabrowse install` registers it as a user LaunchAgent.
- `backend.py` runs as the app's Python child and forwards transcripts and status. It opens the browser
  chosen in settings, lazily on the first listening session.
- `goal_controller.py` serializes browser access, invalidates stale decisions when new speech arrives,
  and runs the bounded observe–choose–act–observe loop. It starts paused after a backend restart until
  a fresh listening-on signal arrives.
- `goal_engine.py` presents Laya with available goal and action choices. `goal_contracts.py` proposes
  finite outcomes and verifies them; `goals.py` builds compatible actions from the current page.
- `page.py` extracts visible elements and site-pack evidence. `safari.py` uses SafariDriver's separate,
  signed-out automation session. `chromium.py` uses a persistent dedicated Chromium profile.

## What the model decides

The transcript can provide literal arguments—site, search text, a spoken result number—but it does not
dispatch an action. Laya selects the requested outcome or `unsupported`. For a chosen goal, the next
question offers only actions compatible with that goal and observed browser state. After execution,
the controller observes again, checks the requested outcome, and either stops or chooses another action.
For a YouTube Short, for example, the site pack exposes player state and controls; Laya can choose
pause or comments, while the verifier checks `paused` or visible comments afterward.

Exact back/forward/scroll commands have a narrow, zero-model fast path. They run only after a final
transcript. They are a deliberate latency exception, not the general decision architecture.

## Completion and boundaries

An action returning successfully does not prove the user's goal is done. Search requires rendered
results, an opened result requires the observed result destination, tabs require the intended tab
identity/count, and media actions require the observed player state or destination. An ambiguous choice,
browser challenge, stale page, unsupported goal or exhausted action budget stops without a success claim.
Verification can prove that a chosen outcome happened, but not that Laya interpreted the original
utterance correctly; link-choice errors and speech-recognition mistakes remain possible.

Goal mode intentionally omits consequential account and shopping actions, arbitrary form workflows,
filter/sort controls and much of the legacy site-pack command inventory. Those need explicit capabilities,
observations and end-state verification before they should be promoted. The older controller remains
available with `layabrowse install --legacy` for local fallback; it is not the default release path.

See [goal-loop design and test evidence](GOAL_LOOP.md) and [site-pack observations](SITE_PACKS.md).
