# LayaBrowse

**Browse the web by speaking to your Mac.** Double-tap a shortcut, say what you want, and LayaBrowse
uses a small local Laya model to choose browser actions, observe their results, and continue toward your goal.

[![CI](https://github.com/aryanbhujade/laya-mlx-voice-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/aryanbhujade/laya-mlx-voice-browser/actions/workflows/ci.yml)
![macOS 14+](https://img.shields.io/badge/macOS-14%2B-black)
![Apple silicon](https://img.shields.io/badge/Apple%20silicon-required-black)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)
[![MIT license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Setup and architecture video

[Watch the 1:35 setup and architecture walkthrough](https://github.com/aryanbhujade/laya-mlx-voice-browser/releases/download/v0.2.0/layabrowse-setup-goal-loop.mp4).
This narrated, source-backed explainer shows the install steps and the default goal loop. Its code
and architecture panels are rendered illustrations, not a filmed fresh installation or live voice demo.

> **Early alpha:** LayaBrowse is a source-installed macOS project, not a notarized downloadable app yet.
> Expect rough edges on websites that frequently change their interface.

**Default engine:** Laya chooses a goal from supported outcomes, chooses an available browser action,
observes the page, and stops only when the result is verified. `layabrowse install` installs this mode
without flags. The older rules-first engine remains available with `layabrowse install --legacy`.
See [goal-loop design and limits](docs/GOAL_LOOP.md).

```text
double-tap Left Control → “open YouTube and search for ESP32 projects”
                         → “open the first video”
                         → “pause the video”
```

Laya-MLX inference and action selection happen on your Mac. For locales supported by Apple's on-device
recognizer, speech recognition stays on the Mac too. Laya is a classifier rather than a chatbot: it chooses from
typed goals and available browser controls; it does not generate arbitrary code and execute it.

## What you need

| Requirement | Details |
|---|---|
| Mac | Apple silicon (M1 or newer) |
| macOS | 14 Sonoma or newer |
| Python | 3.11 or newer (`python3 --version`) |
| Build tools | Xcode Command Line Tools (`xcode-select --install`) |
| Disk | Allow about 1.5 GB for the environment and Laya weights |
| Browser | Safari, Chrome, Edge, Brave, Chromium, Vivaldi, Opera or Opera GX |

Intel Macs, Windows and Linux are not currently supported. The native menu-bar app, Apple Speech and MLX
runtime are macOS/Apple-silicon specific.

## Install in five minutes

Open **Terminal** and run:

```bash
git clone https://github.com/aryanbhujade/laya-mlx-voice-browser.git
cd laya-mlx-voice-browser
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
layabrowse install
```

The final command builds and signs the local menu-bar app, downloads the browser-trained Laya weights,
starts LayaBrowse and adds it to your login items. Rerunning `layabrowse install` safely rebuilds and restarts it.

When macOS asks, allow:

1. **Microphone** — used only while voice control is on.
2. **Speech Recognition** — converts speech to text using Apple's on-device recognizer when available for your
   language.

The global shortcut uses macOS hotkey/modifier APIs and does not need Accessibility, Input Monitoring or Screen
Recording permission.

### Safari setup

Safari needs one additional setting:

1. Open **Safari → Settings → Advanced**.
2. Enable **Show features for web developers**.
3. Open **Develop → Allow Remote Automation**.

Chromium browsers need no equivalent setting.

### Confirm it is running

```bash
layabrowse status
```

You should see `Installed: yes` and `Running: yes`. The L-with-a-spark icon appears in the menu bar.

## Your first workflow

1. Double-tap **Left Control**. The notch island opens and says **Listening**.
2. Say: **“Open YouTube and search for Alan Turing documentaries.”**
3. Say: **“Open the first video.”**
4. Say: **“Pause the video.”**
5. Say: **“Open the comments.”**
6. Say: **“In a new tab, search GitHub for ESP32.”**
7. Double-tap **Left Control** again to stop listening.

LayaBrowse stays in listening mode between commands. It does not stop after every sentence.

## What you can say

| Goal | Examples |
|---|---|
| Open a site | “open Wikipedia”, “go to github.com” |
| Search | “search for Alan Turing”, “search YouTube for lo-fi beats” |
| Chain actions | “open YouTube and search for bank robbery documentaries” |
| Work in a new tab | “in a new tab, search for ESP32 projects” |
| Click/open | “open the first result”, “click the visible Electronics link” |
| Scroll | “scroll down a little”, “scroll up” |
| Navigate | “go back”, “go forward” |
| Manage tabs | “open a new tab”, “switch to the YouTube tab”, “close the other tabs” |
| YouTube Shorts | “pause”, “mute”, “open the comments”, “next short” |

See the [command and workflow cookbook](docs/COMMANDS.md) for supported examples and current limits.

## Site-aware capabilities

Goal mode uses site packs to expose observable search results, article/video/item detail pages, and
safe navigation links. Its verified site-search goals currently cover Google, Wikipedia, YouTube,
GitHub and eBay. eBay may show an automation challenge. YouTube's basic player and Shorts controls
are available; site-specific controls from the older rules-first engine are **not** all available in
goal mode yet. Sorting/filter menus, purchases, email composition and account changes are not supported
goal outcomes. See [Writing site packs](docs/SITE_PACKS.md) to expand this safely.

## How it behaves

- **Continuous session:** double-tap once to begin, speak multiple commands, double-tap again to stop.
- **Goal loop:** after a final phrase, Laya chooses an outcome and a compatible next action; the browser
  result is observed before the loop continues or claims completion.
- **Fast universal controls:** exact back, forward and scroll commands skip the model, after the phrase ends.
- **Clarification instead of guessing:** uncertain or unsupported requests stop without an action.
- **Consequential actions:** purchases, deletion, sending and account changes are unavailable in goal mode.
- **Stale-page protection:** an action is discarded if the page changes before it can be executed.

## Browser sessions and accounts

LayaBrowse cannot control an arbitrary existing browser tab through normal browser automation APIs:

- **Chromium** opens a dedicated LayaBrowse profile. It is separate from your everyday profile, but persistent:
  sign in once and your sessions remain available next time. This is the best option for Gmail, YouTube,
  shopping and other signed-in workflows.
- **Safari** uses SafariDriver's automation window. It starts as a clean signed-out session each time. Use it for
  general browsing, or choose a Chromium browser when account state matters.

Choose the browser from the Laya menu-bar icon. **Automatic** follows your default browser.

## Settings

Everything is available from the menu-bar icon:

| Setting | Options |
|---|---|
| Shortcut | Double-tap left/right Control, left/right Option or right Command; or press ⌥ Space / ⌃⌥ Space |
| Double-tap speed | Fast, normal or relaxed |
| Speaking style | Polite or direct |
| Microphone sensitivity | Low, medium or high |
| Browser | Automatic, Safari or an installed Chromium browser |
| Search engine | Automatic, Google, DuckDuckGo, Bing or Brave Search |
| Sounds | Start/stop chime |
| Show Notch Island | Visual listening/action status |

Goal-mode web search uses Google, including from a new tab. Google's automated-traffic check can block
Safari automation; LayaBrowse reports the block rather than bypassing it.

## Common problems

| Symptom | Fix |
|---|---|
| `layabrowse: command not found` | Run `source .venv/bin/activate`, or use `.venv/bin/layabrowse install`. |
| No menu-bar icon | Run `layabrowse status`, then `layabrowse logs`. Rerun `layabrowse install` if it is not running. |
| Shortcut does nothing | Try a slower double tap, or choose ⌥ Space from the menu. Check whether another app owns that shortcut. |
| Microphone or speech prompt was denied | Enable LayaBrowse under **System Settings → Privacy & Security → Microphone / Speech Recognition**, then reinstall/restart it. |
| Safari will not open or timeouts | Enable **Develop → Allow Remote Automation**. If an automation session was stopped, quit Safari fully and try again. |
| Safari is signed out | This is a SafariDriver limitation. Choose Chrome/Edge/Brave and sign into the persistent LayaBrowse profile once. |
| Chromium opened a new profile | Expected. LayaBrowse uses its own persistent automation profile rather than your personal profile. |
| Google shows “unusual traffic” | Solve it manually in Chromium, or try later. Safari goal mode does not bypass the check or claim the search succeeded. |
| It responds again only after toggling listening | Capture `layabrowse logs -n 100` and note the time. Re-toggling can recreate a stopped browser session; this recovery path is being investigated. |
| A site-specific command stopped working | The website may have changed or the goal may be unsupported. Check the log's `goal stopped` reason; redact personal data before opening an issue. |
| First installation is slow | The Laya weights are downloading once. Rerun `layabrowse install` if the download was interrupted. |

More detail and recovery commands are in [Troubleshooting](docs/TROUBLESHOOTING.md).

## Privacy and safety

- Microphone audio is handled by Apple Speech and is never sent to Laya. When the selected locale supports
  on-device recognition, LayaBrowse requires it; otherwise the Apple Speech framework may use Apple's service.
- Laya inference and policy evaluation run locally through MLX.
- Page snapshots and transcripts are not sent to an external AI service.
- Websites still receive normal browser traffic, searches and form submissions when you instruct LayaBrowse to
  perform them.
- The local service log contains recognized speech, action summaries and visited/search URLs. **Redact it before
  posting or attaching it to an issue.**
- LayaBrowse never attempts to solve CAPTCHAs or bypass browser security warnings.

Local data lives in:

```text
~/Library/Application Support/laya-voice-browser/   settings, speech profile, Chromium profiles
~/Library/Logs/laya-voice-browser/service.log       local diagnostic log
```

## What it does not do

- It is not a general macOS computer-use agent; this repository controls supported web browsers.
- It does not understand every possible sentence or website control.
- It cannot reuse your normal Safari session or personal Chromium profile.
- It does not remove the need to review purchases, messages, account changes or other consequential actions.
- It does not need browser-command fine-tuning to run. Fine-tuning is an optional later step after collecting a
  properly split and redacted evaluation dataset; see [Training and calibration](docs/TRAINING.md).

## Managing LayaBrowse

```bash
layabrowse status
layabrowse logs
layabrowse logs -n 100
layabrowse uninstall
```

Choosing **Quit LayaBrowse** stops the current login session cleanly. Run `layabrowse install` to
start it again; cached model weights are reused.

## Development and contributing

```bash
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
ruff check .
./native/build.sh
```

The unit tests require no model, browser, microphone or network. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
site-pack workflow, test expectations and pull-request checklist. Architecture details are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Performance and evidence

Exact back/forward/scroll requests take **zero model passes**. In a development Safari Shorts session,
Laya's decision passes for pause, mute, comments and next Short took 45–54 ms each; page execution and
loading take additional time. The local model is not the speech recognizer, and these figures are not
speech-to-visible-result latency. The full test suite and reproducible development journeys are in
`tests/` and `scripts/`; [goal-loop measurements and limitations](docs/GOAL_LOOP.md) distinguish
typed-command checks from microphone-driven use. Browser challenges, misheard speech and ambiguous
links still cause real failures.

## License and acknowledgements

MIT. LayaBrowse uses [Laya](https://github.com/NandhaKishorM/laya), a compact typed-decision model, through
[Laya-MLX](https://github.com/mizorewww/laya-mlx). Those are separate projects with their own licenses.
