# LayaBrowse

**Browse the web by voice on your Mac.** Double-tap a key, say what you want — "go to YouTube and search for
lo-fi beats", "click the second result", "scroll down a little" — and it happens, often before you finish the
sentence. Speech recognition, the decision model and browser control all run locally on Apple silicon.

LayaBrowse is powered by [Laya](https://github.com/NandhaKishorM/laya), a small typed-decision model, running
natively through [Laya-MLX](https://github.com/mizorewww/laya-mlx). Laya never writes code or URLs: it picks
from a short list of safe operations and the elements visible on the page, and simple, predictable rules decide
whether to act.

## What it does

- **Works with Safari and Chromium browsers** — Chrome, Edge, Brave, Chromium, Vivaldi, Opera and Opera GX.
  "Automatic" follows your default browser.
- **Acts while you are still talking.** "Go back", "reload" and "open a new tab" run the instant you say them;
  searches and typing wait until you have finished dictating.
- **Understands the page.** "Click the talk page" finds the Talk link; "open the Wikipedia result" picks the
  right search result.
- **Chains commands.** "Go to YouTube and search for documentaries" runs as two steps; "search for rock and
  roll" stays one search.
- **Asks when it is unsure.** If two links match, numbered badges appear on the page — say "two".
- **Checks before anything risky.** Buying, deleting, sending, signing in or out, voting and similar actions
  wait for you to say "confirm".
- **Lives in the menu bar and the notch.** A small black island beside the notch shows what LayaBrowse is
  doing, with bars that follow your voice; it never covers the page.
- **Learns how you speak.** There is no "end of phrase" delay to tune: it learns your pace, waits longer after
  "and…" or "search for…", and ends quickly once your command is complete.

## Install

Requirements: an Apple silicon Mac, macOS 14 or newer, Python 3.11+, and Xcode Command Line Tools
(`xcode-select --install`).

```bash
git clone https://github.com/aryanbhujade/laya-mlx-voice-browser.git
```

```bash
cd laya-mlx-voice-browser
```

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
```

```bash
layabrowse install
```

`layabrowse install` builds the app, downloads the Laya weights (about 850 MB, once), and sets LayaBrowse to
start at login. After that you never need the terminal: LayaBrowse waits in the menu bar whether or not a
browser is open, and opens one when you give your first command.

**Using Safari?** Turn on **Safari ▸ Settings ▸ Advanced ▸ Show features for web developers**, then
**Develop ▸ Allow Remote Automation**. Chromium browsers need no setup.

## Permissions

LayaBrowse asks for two permissions the first time it starts, one prompt at a time:

| Permission | Why |
|---|---|
| **Microphone** | To hear your commands — only while listening is on. |
| **Speech Recognition** | To turn speech into text — on your Mac for languages Apple supports on-device, including English. |

That is all. The shortcut needs no permission: LayaBrowse only notices modifier keys going up and down (the
same way apps offer "double-tap Option"), never what you type. It does not need Accessibility, Input
Monitoring or Screen Recording. macOS also shows a one-time notice that LayaBrowse can run in the background;
you can manage it in **System Settings ▸ General ▸ Login Items**.

## Using it

1. **Double-tap left Control** (or your chosen shortcut). The island opens beside the notch and a soft chime
   plays.
2. **Speak.** A short pause ends each command; LayaBrowse keeps listening for the next one.
3. **Double-tap again** to stop listening.

| Say | What happens |
|---|---|
| "go to wikipedia", "open github dot com" | Opens the site |
| "search for alan turing", "search youtube for lo-fi beats" | Searches the web, or the named site |
| "click view history", "open the first result" | Clicks the matching link or button |
| "type hello world into the search box", "press enter" | Types exactly what you said |
| "scroll down a little", "scroll to the bottom" | Scrolls |
| "go back", "go forward", "reload" | History |
| "open a new tab", "next tab", "close this tab" | Tabs |
| "two", "the second one" | Picks a numbered badge |
| "confirm" / "cancel" | Answers a confirmation |

## Settings

Everything is in the menu-bar icon:

| Setting | Options |
|---|---|
| **Shortcut** | Double-tap left or right Control, left or right Option, or right Command; or press ⌥ Space or ⌃⌥ Space. Double-tap speed: fast, normal, relaxed. |
| **Speaking Style** | *Polite* understands "could you please open YouTube?" instantly. *Direct* treats only commands like "open YouTube" as instant commands, so conversation ("could you go back to what you said") is much less likely to trigger anything. |
| **Microphone Sensitivity** | *Low* ignores background noise and other voices; *High* picks up quiet speech. |
| **Browser** | Automatic (your default browser), Safari, or any installed Chromium browser. |
| **Search Engine** | Google or DuckDuckGo for plain "search for…" commands. |
| **Sounds** | The start/stop chime. |
| **Show Notch Island** | The island beside the notch. |

The menu also has Start/Stop Listening, Open Log and Quit LayaBrowse.

**Chromium browsers** open in their own window with a dedicated LayaBrowse profile, next to your everyday
browser (Chromium does not allow voice control of your main profile). Sign in there once and it stays signed
in. **Safari** uses its automation window, which starts signed out each time.

## Performance

Measured on an Apple M4 Pro (24 GB) with the benchmarks in `scripts/`.

| | |
|---|---|
| **Speech to text** (on-device) | First words appear ~20–30 ms into processing; a whole 1.4–2.2 s command is transcribed in 41–103 ms (5/5 exactly right) |
| **Decision, built-in phrasing** ("go back", "go to youtube", "search for …") | 0 ms — no model needed |
| **Decision, while you are still speaking** | 18 ms median |
| **Decision, clicking something on the page** | 50 ms median |
| **Decision, free-form request** ("I want to learn about enigma") | 76 ms median |
| **Right element clicked** | 96% of 27 commands on 5 real pages (Wikipedia, Hacker News, DuckDuckGo, GitHub); the one miss asked instead of guessing |
| **Unwanted actions** while you are mid-sentence or talking to someone else | 0 of 26 |
| **Browser actions** (Chrome) | Scroll, type, switch tab ~0.1–0.2 s; open a page ~0.7–1.1 s including loading |
| **Startup** | ~1 s to load the model at login |
| **Memory** | ~0.9 GB while idle (the model weights are 843 MB) |

## Privacy

Speech is recognised on your Mac (for languages Apple supports on-device, including English), and transcripts
and page contents are never sent anywhere; the only download is the model weights, once. Settings,
the learned speaking profile and logs are stored locally:

- `~/Library/Application Support/laya-voice-browser/` — `config.json`, `speech-profile.json`, browser profiles
- `~/Library/Logs/laya-voice-browser/service.log`

## Managing LayaBrowse

```bash
layabrowse status
```

```bash
layabrowse logs
```

```bash
layabrowse uninstall
```

LayaBrowse restarts itself if it crashes, but not after you choose **Quit LayaBrowse**.

## Development

```bash
pip install -e '.[dev]'
```

```bash
pytest && ruff check .
```

The unit tests need no model, browser, microphone or network. Benchmarks: `scripts/benchmark_pages.py`
(targets and latency on saved pages), `scripts/check_streaming.py` (no early actions mid-sentence),
`scripts/evaluate_commands.py` (raw model accuracy), and `LayaBrowse --benchmark-speech` (transcription).
`layabrowse --command "go to wikipedia"` runs a single typed command without the background app. How it works
inside is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT. Laya and Laya-MLX are separate projects with their own licenses:
[NandhaKishorM/laya](https://github.com/NandhaKishorM/laya) and
[mizorewww/laya-mlx](https://github.com/mizorewww/laya-mlx).
