# Troubleshooting

Start with these three commands from the cloned repository:

```bash
source .venv/bin/activate
layabrowse status
layabrowse logs -n 100
```

The service log may contain recognized speech and visited/search URLs. Redact personal information before
sharing it in an issue.

## Installation

### `python3` is missing or too old

LayaBrowse requires Python 3.11 or newer:

```bash
python3 --version
```

Install a current Python from [python.org](https://www.python.org/downloads/macos/) or Homebrew, recreate
`.venv`, then repeat the installation.

### Xcode Command Line Tools are missing

Run:

```bash
xcode-select --install
```

Finish the macOS installer, then rerun `layabrowse install`.

### `layabrowse: command not found`

Activate the repository environment:

```bash
source .venv/bin/activate
```

Or call the executable directly:

```bash
.venv/bin/layabrowse status
```

### The model download stopped

The initial install downloads roughly 850 MB. Check the network connection and rerun:

```bash
layabrowse install
```

The Hugging Face cache resumes/reuses files that already downloaded.

## Menu-bar app and permissions

### The icon is missing

```bash
layabrowse status
layabrowse logs -n 100
```

If the service is installed but not running, rebuild and restart without rechecking the model:

```bash
layabrowse install --skip-model
```

### Microphone or Speech Recognition was denied

Open **System Settings → Privacy & Security**, allow **LayaBrowse** under **Microphone** and **Speech
Recognition**, then run:

```bash
layabrowse install --skip-model
```

LayaBrowse does not require Accessibility, Input Monitoring or Screen Recording.

### The shortcut does not respond

1. Click the Laya menu-bar icon and use **Start Listening** to confirm the app itself is working.
2. Choose a different shortcut such as **⌥ Space**.
3. If using a double-tap shortcut, select the relaxed double-tap speed.
4. Check whether another app already owns the same shortcut.
5. Inspect `layabrowse logs` for `shortcut ready` and `shortcut pressed`.

## Safari

### “Safari remote automation is disabled”

Enable **Safari → Settings → Advanced → Show features for web developers**, then enable
**Develop → Allow Remote Automation**.

### Safari times out after an automation window was closed

SafariDriver can keep a dead automation session after **Stop Session** or an unexpected close. Quit Safari
fully with **⌘Q**, reopen it, then start voice control again.

### Safari is signed out

SafariDriver uses a clean automation session and cannot share the ordinary signed-in Safari window. Choose a
Chromium browser for persistent accounts.

### Google shows an automated-traffic check in Safari

That check cannot be completed inside Safari's locked automation window. Default goal mode reports the
search as blocked; it does not switch engines silently, bypass the check, or claim success. You can
try Chromium's dedicated persistent profile or retry later.

## Chromium browsers

### Chrome/Edge/Brave opened a separate profile

Expected. Browser automation cannot attach to the ordinary profile safely, so LayaBrowse maintains a dedicated
persistent profile under its application-support folder. Sign into that profile once.

### Google shows an automated-traffic check

Solve it manually in the visible Chromium window. Signing into Google in the LayaBrowse profile usually makes
future checks less common. LayaBrowse does not solve CAPTCHAs.

### A Chromium browser is installed but not listed

Currently supported: Chrome, Edge, Brave, Chromium, Vivaldi, Opera and Opera GX in their standard macOS
locations. Open an issue with the browser name and application path if a standard installation is missed.

## Commands and pages

### LayaBrowse waits instead of acting

The phrase may be incomplete, unsupported in goal mode, misrecognized, blocked by the site, or ambiguous
among visible targets. Check `layabrowse logs -n 100` and look for the final transcript and `goal stopped`
reason. Rephrase with the visible link label if appropriate; redact page text and URLs before sharing logs.

Examples:

```text
“Click the Issues tab.”
“Open the first video.”
“Search Wikipedia for Alan Turing.”
```

### It chose the wrong visible element

Stop listening, undo/back if appropriate, and record:

- the site and page type (do not include a private URL),
- the exact command,
- the visible labels of the intended and selected controls,
- the browser.

Do not post passwords, private messages, account pages, full logs or browsing history.

### A site-pack command stopped working

Websites regularly change labels and markup. Check `src/laya_voice_browser/sites/` for the relevant pack and
follow [Writing site packs](SITE_PACKS.md). Prefer visible accessible labels over generated CSS class names.

## Removing LayaBrowse

```bash
layabrowse uninstall
```

This unloads the login service and removes its LaunchAgent. It intentionally leaves model weights, settings,
logs and the dedicated browser profile in place so they are not destroyed unexpectedly.
