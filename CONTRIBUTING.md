# Contributing

Thanks for helping improve LayaBrowse. Small, well-tested pull requests are easiest to review.

## Development setup

Requirements are the same as the app: Apple silicon, macOS 14+, Python 3.11+ and Xcode Command Line Tools.

```bash
git clone https://github.com/aryanbhujade/laya-mlx-voice-browser.git
cd laya-mlx-voice-browser
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Run the standard checks:

```bash
pytest -q
ruff check .
./native/build.sh
```

The unit suite does not need a model download, browser, microphone or network. Native compilation requires the
Command Line Tools.

## Site packs

Site packs are the quickest way to add reliable controls for a website. Read
[docs/SITE_PACKS.md](docs/SITE_PACKS.md), add or edit one JSON file, and include:

- direct phrases,
- natural paraphrases,
- unrelated/side-speech negatives,
- confirmation tests for account or purchase actions,
- the browser and pages used for live verification.

Do not include screenshots, traces or fixtures containing accounts, email, orders, addresses, private URLs or
other personal data.

## Pull-request checklist

- [ ] The change has one clear purpose.
- [ ] `pytest -q` passes.
- [ ] `ruff check .` passes.
- [ ] `./native/build.sh` passes when Swift code changed.
- [ ] New behavior has tests or a benchmark fixture.
- [ ] Site actions fail safely when their control is absent.
- [ ] Consequential/account-changing actions require confirmation.
- [ ] No credentials, tokens, private paths, account data, logs or generated browser profiles are included.
- [ ] Documentation describes any untested or platform-specific limitation honestly.

## Reporting bugs

Include the macOS version, Mac chip, Python version, browser, exact command and a non-sensitive description of
the page. Before sharing `layabrowse logs`, remove transcripts, URLs and identifiers you do not want public.

For a security or privacy issue, do not open a public issue containing exploit details or personal data. Contact
the repository owner privately through the contact information on their GitHub profile.
