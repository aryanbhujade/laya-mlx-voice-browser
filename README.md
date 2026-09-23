# LayaBrowse

**Browse the web by speaking to your Mac.** Double-tap a shortcut, say what you want, and LayaBrowse
operates Safari or a Chromium browser using a small local decision model.

[![CI](https://github.com/aryanbhujade/laya-mlx-voice-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/aryanbhujade/laya-mlx-voice-browser/actions/workflows/ci.yml)
![macOS 14+](https://img.shields.io/badge/macOS-14%2B-black)
![Apple silicon](https://img.shields.io/badge/Apple%20silicon-required-black)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)
[![MIT license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Setup and architecture video

A 2-minute walkthrough of installation, permissions, and how speech becomes browser actions.

https://github.com/user-attachments/assets/913a7be7-f81f-42c9-9b73-106c7b9871b5

> **Early alpha:** LayaBrowse is a source-installed macOS project, not a notarized downloadable app yet.
> Expect rough edges on websites that frequently change their interface.

```text
double-tap Left Control → “open YouTube and search for ESP32 projects”
                         → “open the first video”
                         → “make the video bigger”
```

Laya-MLX inference and action selection happen on your Mac. For locales supported by Apple's on-device
recognizer, speech recognition stays on the Mac too. Laya is a classifier rather than a chatbot: it chooses from
typed operations and visible page controls; it does not generate arbitrary code and execute it.

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

The final command builds and signs the local menu-bar app, downloads the Laya weights (about 850 MB, once),
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
2. Say: **“Open Wikipedia and search for Alan Turing.”**
3. Say: **“Open the first result.”**
4. Say: **“And in a new tab, open YouTube and search for Alan Turing documentaries.”**
5. Say: **“Open the first video.”**
6. Say: **“Make the video bigger.”**
7. Double-tap **Left Control** again to stop listening.

LayaBrowse stays in listening mode between commands. It does not stop after every sentence.

## What you can say

| Goal | Examples |
|---|---|
| Open a site | “open Wikipedia”, “go to github.com” |
| Search | “search for Alan Turing”, “search YouTube for lo-fi beats” |
| Chain actions | “open YouTube and search for bank robbery documentaries” |
| Work in a new tab | “in a new tab, search for ESP32 projects” |
| Click | “click View history”, “open the first result” |
| Type | “type hello world into the search box”, “press Return” |
| Scroll | “scroll down a little”, “scroll to the bottom” |
| Navigate | “go back”, “go forward”, “reload” |
| Manage tabs | “switch to the YouTube tab”, “tab three”, “close the other tabs” |
| Control media | “pause”, “skip ahead 30 seconds”, “play at 1.5x”, “turn on captions” |
| Resolve ambiguity | Say “one”, “two” or “the second one” when numbered badges appear |
| Approve a guarded action | Say “confirm” or “cancel” |

See the [command and workflow cookbook](docs/COMMANDS.md) for longer examples covering research, YouTube,
GitHub, Gmail, shopping and media.

## Site-aware controls

Site packs add fast, human phrasing for controls that are specific to a website. Current packs cover:

| Site | Examples |
|---|---|
| YouTube | Theater mode, mini player, comments, first video, subscriptions, history, Watch Later |
| Gmail | Compose, reply, reply all, forward, archive, delete, read/unread, inbox, sent, drafts, search mail |
| GitHub | Repository code, issues, pull requests, Actions, releases, README, starring |
| Google | First/second result, result pages, Images, Videos, News and Shopping |
| Wikipedia | References, article beginning and a random article |
| Spotify | Play/pause, next/previous, shuffle and repeat |
| Netflix | Skip intro/recap/credits and next episode |
| Amazon | First product, next page, cart, orders, deals, reviews, add to cart and Buy Now |
| eBay | First listing, next page, cart, watchlist, watch item, add to cart and Buy It Now |
| Etsy | First product, next page, cart, favorites, favorite item and add to cart |

Account-changing and purchase actions are confirmation-gated. Site packs use visible labels and conservative
selectors, but websites can redesign without notice. Contributors can add or repair packs without changing the
model; see [Writing site packs](docs/SITE_PACKS.md).

## How it behaves

- **Continuous session:** double-tap once to begin, speak multiple commands, double-tap again to stop.
- **Streaming decisions:** closed commands such as “go back” can run before speech ends; searches, typing,
  clicks and other payload-bearing commands wait for the phrase to finish.
- **Page-aware targets:** visible links, buttons and fields are ranked by how well their labels match your words.
- **Clarification instead of guessing:** ambiguous targets get numbered badges or a spoken clarification.
- **Confirmation before consequences:** purchases, deletion, sending, sign-in/out, voting and similar actions
  stop and ask for “confirm”.
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

Automatic search uses Google in Chromium and DuckDuckGo in Safari, because Google's automated-traffic check
cannot be completed inside Safari's locked automation window.

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
| Google shows “unusual traffic” | Solve it manually in Chromium. Safari automatically falls back to DuckDuckGo because its automation window cannot solve the check. |
| A site-specific command stopped working | The website likely changed its labels or markup. Open an issue with the site, command and visible control—but redact personal data. |
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

Choosing **Quit LayaBrowse** stops the current login session cleanly. Run `layabrowse install --skip-model` to
start it again without rechecking the model download.

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

## Performance

Measured on an Apple M4 Pro (24 GB):

| Measurement | Result |
|---|---:|
| Built-in command decision | 0 ms model time |
| Streaming decision | 18 ms median |
| Page-target decision | 50 ms median |
| Free-form request | 76 ms median |
| Click-target accuracy on 27 commands / 5 saved real pages | 96% |
| Site-control routing on the included 43-row suite | 100%, 0 executed false actions |

Those two accuracies are the whole pipeline's, not the model's. Grammar, site-pack rules and lexical
ranking settle most decisions before Laya is asked anything, so `scripts/measure_model_contribution.py`
reports each benchmark twice — rules alone, then with the model:

| Benchmark | Rules only | With Laya |
|---|---:|---:|
| Intent (26 spoken commands) | 92.3% | 84.6% |
| Site controls (43 rows) | 95.3% | 100% |
| Click targets (27 commands) | 96.3% | 96.3% |

Laya currently earns its place on loose site phrasings ("move this out of my inbox without erasing it"
→ archive) and on rejecting speech that is not a command. It does not pick click targets — lexical
ranking does, and the raw target head scores near chance on nine options. Treat these as small
development measurements on manually authored sets, not a benchmark; `docs/BASELINE.md` records the
raw per-head accuracies that led to this split of work.
| Startup after model download | About 1 second |
| Idle memory | About 0.9 GB, including 843 MB model weights |

These are small development measurements, not universal guarantees. Hardware, speech locale, page layout and
browser loading time all matter. Reproduce them with the scripts in `scripts/`.

## License and acknowledgements

MIT. LayaBrowse uses [Laya](https://github.com/NandhaKishorM/laya), a compact typed-decision model, through
[Laya-MLX](https://github.com/mizorewww/laya-mlx). Those are separate projects with their own licenses.
