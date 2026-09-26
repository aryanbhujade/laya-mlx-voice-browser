# Command and workflow cookbook

Double-tap the configured shortcut to start listening, speak multiple requests separated by a short
pause, then double-tap again to stop. Goal mode is the default after `layabrowse install`. These are
examples of supported outcomes, not a promise that every phrasing or changing website will work.

## Search and follow a result

```text
“Open YouTube and search for ESP32 tutorials.”
“Open the first video.”
“Pause the video.”
“Mute the video.”
“Open the comments.”
“Next short.”                  # while a Short is open
“Theater mode.”                # on a standard YouTube watch page
“Skip the ad.”                 # only when YouTube shows a Skip button
```

Search goals are grounded to the requested site. A search must render its results before it counts
as complete; opening the first/second/third result is a separate outcome. Google, YouTube, Wikipedia,
GitHub and eBay have search-result observations. On eBay or Google, an automation challenge may block
the journey. LayaBrowse does not solve or bypass it.
Theater mode is verified from the player layout. An ad skip is attempted only when an ad and visible
Skip button are observed; unskippable ads are left alone.

## Navigate links and tabs

```text
“Open Wikipedia.”
“Search for Ada Lovelace.”
“Open the Talk page.”
“Go back.”
“Scroll down.”
“Open a new tab.”
“In a new tab, search GitHub for ESP32.”
“Switch to the Wikipedia tab.”
“Go to the other tab.”
“Close all other tabs.”
```

New tabs start at Google. Exact back, forward and scroll commands are the only zero-model controls;
they still wait for a final transcript. Other outcomes go through Laya. Tab selection uses observed
titles, domains and positions. Closing other tabs is a distinct outcome that keeps the current one.

## Current limits

The default goal loop cannot yet work through sort/filter menus such as “sort by lowest price,” type
arbitrary multi-field forms, send messages, buy items, or invoke every action in the older site packs.
It will generally clarify or stop rather than silently fall back to those actions. A link can still
be chosen incorrectly: verification proves that the selected link opened, not that it matched your
meaning. Speech recognition can also mishear product names or “lowest price.”

The old rules-first engine remains available for comparison with `layabrowse install --legacy`, but
it is not the documented default and has different safety/accuracy characteristics. See
[architecture](ARCHITECTURE.md), [goal-loop evidence](GOAL_LOOP.md) and [troubleshooting](TROUBLESHOOTING.md).
