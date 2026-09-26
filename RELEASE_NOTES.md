# LayaBrowse 0.2.1 — YouTube player controls

This source-install alpha extends the default, local-Laya goal loop with two YouTube controls:

- **Theater mode** on a standard watch page. Laya chooses the supported outcome, the browser turns
  the mode on only if needed, and the controller verifies the observed player layout.
- **Skip the ad** only when YouTube shows an ad and a visible Skip button. Safari uses a native
  WebDriver click and the controller checks that the ad ends. Unskippable ads are not bypassed.

YouTube Shorts can now appear as distinct search results, so “open the first Short” does not silently
open an earlier standard video result. Existing play/pause, mute/unmute, next/previous video or Short,
and comments controls remain available.

Install from the [README](README.md) with `layabrowse install`. This is **not** a notarized `.app`;
the native menu-bar app is built locally. The release includes source archives, not a packaged binary.

Verification: 345 local tests and Ruff pass. These checks cover action selection, observed outcomes,
and skip-button gating; they are not a claim that every YouTube ad variant or live speech phrasing has
been tested. YouTube can change its player controls. SafariDriver still uses a separate signed-out
automation window; shopping, account changes, arbitrary forms and filters are outside verified goals.
