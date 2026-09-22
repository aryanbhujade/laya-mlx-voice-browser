# Laya-MLX Voice Browser

Control **Safari or any Chromium browser** by voice, using local, open-weight Laya typed decisions on
Apple silicon. Double-tap a key anywhere, say what you want, and it happens, often before you finish the
sentence. Everything runs on your Mac: speech recognition, the model and the browser control.

The model selects from bounded operations and visible page elements; deterministic Python policy authorizes
the choice, and SafariDriver or the Chrome DevTools Protocol executes it. Laya never writes code, CSS
selectors, URLs, or dictated text.

```text
Apple Speech partials -> Laya-MLX choices -> confidence/safety policy -> browser -> fresh observation
```

This is an independent Laya implementation inspired by the public, MIT-licensed designs of
[`browser-use/jev-ultrafast`](https://github.com/browser-use/jev-ultrafast) and
[`moritzkremb/jev-voice-browser`](https://github.com/moritzkremb/jev-voice-browser). It does not use Jev or
the TypeSafe API.

## What works

- Native `SFSpeechRecognizer` partial transcripts through a persistent Swift helper.
- Global double-tap **left Control** toggles continuous voice-control mode. A pause ends and submits one
  phrase, then recognition immediately resumes; double-tap again to leave voice-control mode.
- A notch island: pure black wings either side of the MacBook notch, never below it, with a subtle moving
  glint on its rim. The right wing shows voice-reactive level bars; the left shows what is happening
  (listening, thinking, opening, searching, clicking, done, “say confirm”, “say a number”). Preview it with
  `.build/Laya.app/Contents/MacOS/Laya --preview` (no permissions needed).
- On-device recognition is required when Apple's recognizer supports it for the selected locale.
- Local Laya-MLX inference, warmed once and reused.
- Real Safari control: navigate, search, click, type, select, Return, scroll, history, reload and tabs.
- Staged Laya decisions: only the questions a command still needs are asked (0–2 for most commands).
- Ordered command chains such as “go to YouTube and search for documentaries about bank robberies”. A chain
  splits only where both sides are complete commands, so “search for guitar tabs and back tracks” stays one
  search; `datasets/chains.jsonl` holds the labelled cases.
- Ambiguous targets become numbered badges on the page; say “two” or “the second one” to pick.
- Polite phrasing (“can you open…”) is understood by the rules while you are still speaking.
- Unqualified searches inherit supported sites: “search for…” on YouTube searches YouTube.
- Conversational plans such as “in a new tab, can you search for…” and “open GitHub to see repos for…”.
- Unscoped web searches use Google by default; DuckDuckGo remains available when explicitly requested.
- Free-text and URL values are extracted from the transcript and copied verbatim.
- Stale-page guard before execution.
- Spoken confirmation before potentially destructive page actions, including plain-looking links that change
  an account (vote, hide, follow, log out, unsubscribe).
- A lost browser session is reported once and ends the run instead of failing on every phrase.
- Typed and word-by-word replay modes for testing without a microphone.
- Optional JSONL decision/execution trace.
- Per-stage speech, snapshot, model, policy and execution timings.
- A labeled command-evaluation harness for Laya-specific threshold calibration.

## Requirements

- Apple silicon Mac
- macOS 14 or newer
- Python 3.11+
- Xcode Command Line Tools (to build the small Swift menu-bar app): `xcode-select --install`
- For Safari: **Develop > Allow Remote Automation** enabled. Chromium browsers need no setup.
- Microphone, Speech Recognition, Input Monitoring and Accessibility permissions (Laya asks on first start)

SafariDriver is included with Safari. The first time, macOS may require:

```bash
safaridriver --enable
```

That command changes a machine-level Safari automation setting, so this project never runs it automatically.
Safari may need to be restarted once after enabling Remote Automation. If a WebDriver session times out while
an existing Safari window is open, fully quit Safari before retrying so SafariDriver can create its isolated
automation window; save important tabs first.

## Install

```bash
git clone https://github.com/aryanbhujade/laya-mlx-voice-browser.git
cd laya-mlx-voice-browser
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
laya-voice-browser install
```

That last command sets Laya up as a background app (see below); you do not need the terminal after it.

The first run downloads the selected Laya checkpoint. Later decisions can run locally from the Hugging Face
cache. To download explicitly before going offline:

```bash
hf download aac6fef/laya-mlx
```

## Run in the background (recommended)

Set it up once; it then starts at login and waits in the background, with or without a browser open:

```bash
laya-voice-browser install
```

This builds the Laya app, downloads the model, and registers a per-user LaunchAgent that starts **Laya.app**
at login; the app runs the Python backend as its child, so macOS shows "Laya" in its background-activity
notice, Login Items and permission prompts. A waveform icon appears in the menu bar.

On first start Laya asks for Speech Recognition, Microphone, Input Monitoring and Accessibility in turn.
Accessibility can only be switched on by you in System Settings; until then the menu-bar icon shows a warning
and lists what is missing, and the shortcut starts working the moment it is allowed (no restart needed).

Double-tap **left Control** anywhere to talk; the browser opens on the first command and is reopened
automatically if you close its window. Everything else is in the menu-bar icon:

| Setting | Options |
|---|---|
| Shortcut | double-tap left/right Control, right Option or right Command; fast, normal or relaxed |
| Microphone Sensitivity | low (ignores background noise) · medium · high (quiet speech) |
| Browser | Automatic (your default browser) · Safari · any installed Chrome, Edge, Brave, Chromium, Vivaldi, Opera |
| Search Engine | Google · DuckDuckGo |
| Sounds, Show Notch Island | on / off |

There is no end-of-phrase setting: Laya learns how long to wait from the gaps between your words, waits
longer after words like "and" or "search for", ends sooner once it already understands a complete command,
and becomes more patient whenever it notices it cut you off. The learned profile is
`~/Library/Application Support/laya-voice-browser/speech-profile.json`.

Settings live in `~/Library/Application Support/laya-voice-browser/config.json`. Manage the service with:

```bash
laya-voice-browser status
```

```bash
laya-voice-browser logs
```

```bash
laya-voice-browser uninstall
```

The service restarts itself after a crash but not after **Quit Laya**. Logs are in
`~/Library/Logs/laya-voice-browser/service.log`.

### Browsers

- **Safari** uses Safari's automation window (logged out on every start; Google may show a CAPTCHA that
  cannot be solved in that window).
- **Chromium browsers** (Chrome, Edge, Brave, Chromium, Vivaldi, Opera, Opera GX) run in their own window with
  a dedicated Laya profile, next to your everyday browser: sign in there once and it stays signed in, and
  anything like a CAPTCHA can be solved by hand. Clicks and typing are sent as real input events through the
  Chrome DevTools Protocol. Chromium does not allow remote control of your everyday default profile, which is
  why Laya keeps its own.

## Run in the foreground

Voice mode:

```bash
laya-voice-browser --url https://example.com --trace runs/session.jsonl
```

Leave that process running, then double-tap the **left Control key** to enter voice-control mode. The native
helper stays resident between commands. A 1.1-second pause submits the current phrase and immediately starts
listening for the next one; the black listening island stays expanded throughout. Double-tap left Control
again to leave voice-control mode and collapse the island. On first use, macOS may ask for Microphone, Speech
Recognition, Accessibility and Input Monitoring permissions for `Laya`.

Typed command:

```bash
laya-voice-browser --command "go to wikipedia"
```

Word-by-word replay, which exercises early-action behavior:

```bash
laya-voice-browser --replay "open wikipedia and search for Alan Turing" --word-delay 0.3
```

Use another checkpoint or local directory:

```bash
laya-voice-browser --model aac6fef/laya-mlx --command "go back"
```

Environment options:

| Variable | Default | Purpose |
|---|---|---|
| `LAYA_MODEL` | `aac6fef/laya-mlx` | Hub id or local checkpoint |
| `LAYA_DTYPE` | `float16` | MLX inference precision |
| `LAYA_BATCH_SIZE` | `16` | Questions per model batch |
| `LAYA_COMPILE` | `0` | Enable MLX compilation after measuring the workload |
| `LAYA_SPEECH_LOCALE` | current locale | Apple Speech recognition locale |
| `LAYA_CONFIG` | Application Support path | Settings file shared by the app and backend |

## Safety boundary

Laya's answer is not authorization. Code applies completeness and confidence thresholds, refuses ambiguous
page targets, waits for final free-text payloads, checks that the page is unchanged, and asks for spoken
confirmation before destructive-looking actions. Confirmations expire after 10 seconds and retain the exact
page fingerprint they were created against; a changed page cancels execution. Model, Safari and confirmation
work is serialized through one worker. SafariDriver still has the authority of the controlled browser session:
use a dedicated Safari profile or logged-out test accounts during development.

Current thresholds are conservative starting values, **not calibrated production guarantees**. Before using
the project against accounts that matter, build a labeled command set, measure false activations, calibrate
the chosen checkpoint, and add site-specific verification.

See `docs/TRAINING.md` and run the starter raw-model evaluation with:

```bash
python scripts/evaluate_commands.py --predictions runs/predictions.jsonl
```

## Tests

```bash
pytest
ruff check .
python -m compileall -q src tests
./native/build.sh
```

Unit tests do not open Safari, request microphone access, download model weights, or make network calls.

## Architecture

- `native/Laya/` — the menu-bar app: speech, shortcut, notch island, settings menu, permissions, and the
  backend child process (`Backend.swift`).
- `backend.py` — the Python process the app runs: transcripts in on stdin, island statuses out on stdout.
- `browsers.py`, `safari.py`, `chromium.py` — browser choice and the Safari (WebDriver) and Chromium (DevTools
  Protocol) backends, sharing one page script in `page.py`.
- `laya.py` — warmed Laya-MLX model and typed question construction.
- `safari.py` — compact DOM observation, freshness checks and Safari execution.
- `policy.py` — confidence, completeness, payload and confirmation gates.
- `controller.py` — partial-transcript debounce, stale-result cancellation and traces.
- `spans.py` — deterministic verbatim text/URL candidate extraction.

### How a decision is made

Laya answers one multiple-choice question per model pass, over at most 512 tokens of
`[question + options] + state`, so latency grows with the number of questions (~20–60 ms each).

1. **Grammar first.** Explicit commands ("go to wikipedia", "go back", "scroll down a little") are settled by
   rules in `spans.py`; `go back`, `go forward`, `reload` and `new tab` run mid-speech with no model call.
2. **Stage 1 (gate):** only the unsettled questions among `is_command`, `intent` and `complete`.
3. **Stage 2 (details):** only what the resolved intent needs, and only once the policy would act:
   `target` + `destructive` for clicks, `text_span` for searches, `url_span`/`site` when no site was named.
4. **Targets:** elements are ranked by word overlap with the transcript. A unique best label match is used
   directly; ties go to Laya's `target` question over at most 9 `"label (role)"` options.

State is ordered by usefulness (transcript, page, 12 ranked elements, 2 recent actions, 300 characters of page
text) and trimmed from the end to fit each question's token budget instead of being cut silently.

Benchmarks against saved Safari snapshots (`tests/fixtures`):

```bash
python scripts/benchmark_pages.py      # target accuracy and model latency on real pages
python scripts/check_streaming.py      # unsafe early actions on partial speech
python scripts/evaluate_commands.py    # raw Laya head accuracy
```

## License and attribution

MIT. See `NOTICE` for the two reference projects. Laya/Laya-MLX model weights and packages retain their own
upstream licenses and provenance.
