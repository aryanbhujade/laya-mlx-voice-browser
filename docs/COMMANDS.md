# Command and workflow cookbook

Double-tap your configured shortcut once to start a continuous voice session. Speak as many commands as you
want, then double-tap again to stop. A short pause separates commands; you do not need to toggle listening for
each sentence.

Commands below are examples, not exact magic phrases. Explicit commands are handled by deterministic rules;
site packs add natural examples; Laya handles the remaining short choice among relevant operations.

## Everyday browsing

```text
“Open Wikipedia.”
“Search for Alan Turing.”
“Open the first result.”
“Scroll down a little.”
“Open the references.”
“Go back.”
```

You can also combine complete steps:

```text
“Open YouTube and search for lo-fi beats.”
“Open GitHub to search for ESP32 repositories.”
“Open a new tab and search for restaurants near Durham.”
“In a new tab, can you search for information about post-quantum cryptography?”
```

Queries may contain ordinary conjunctions. “Search for rock and roll” remains one search; “search for ESP32
and then open the first result” becomes two actions.

## Research across tabs

```text
“Search for the history of public-key cryptography.”
“Open the Wikipedia result.”
“In a new tab, search for the original Diffie Hellman paper.”
“Switch to the Wikipedia tab.”
“Scroll to the references.”
“Switch to the next tab.”
```

Tab commands accept titles, positions and directions:

```text
“Switch to the YouTube tab.”
“Go to tab three.”
“The last tab.”
“Next tab.”
“Close the Wikipedia tab.”
“Close the other tabs.”
```

Closing all other tabs asks for confirmation.

## YouTube and media

```text
“Open YouTube and search for documentaries about bank robberies.”
“Open the first video.”
“Make the video bigger.”
“Show me the discussion under the video.”
“Pause.”
“Skip ahead thirty seconds.”
“Play at one point five x.”
“Turn on captions.”
“Full screen.”
```

Additional YouTube controls include the mini player, subscriptions, history, Watch Later, next video, Shorts
navigation and Skip Ad when YouTube exposes that button.

Generic media commands work on the main video or audio element on many sites:

```text
“Play.” / “Pause.”
“Mute.” / “Unmute.”
“Volume up.” / “Volume down.”
“Rewind ten seconds.” / “Skip ahead a minute.”
“Speed up.” / “Normal speed.”
“Exit full screen.”
```

## GitHub

Open a repository page first, then try:

```text
“Show me the bug reports.”
“Show changes waiting for code review.”
“Did the latest continuous integration build pass?”
“Where can I download the latest published version?”
“Show the project instructions.”
“Browse the source code.”
```

“Star this repository” and natural equivalents require confirmation.

## Gmail

Use a Chromium browser, sign into the dedicated LayaBrowse profile once, and open Gmail. Examples:

```text
“Compose a new email.”
“Reply to everyone.”
“Forward this email.”
“Get rid of this email but keep it.”
“Mark this as unread.”
“Show messages I have not sent yet.”
“Search my email for invoices from September.”
```

“Get rid of this email but keep it” means archive. Deleting requires confirmation. Site packs can open and
focus controls, but they do not yet extract a full recipient/subject/body structure from one long sentence.

## Shopping

Amazon, eBay and Etsy packs cover common discovery and navigation controls:

```text
“Open the first product.”
“Show more products.”
“What do people who bought this think?”
“Show my orders.”
“Open my watchlist.”
“Show my favorite items.”
```

Adding an item to a cart, watching/favoriting an item and Buy Now commands require confirmation. Checkout,
payment and final purchase steps should always be completed and reviewed manually.

## Numbered choices

When two or more page elements match, LayaBrowse places numbered badges next to the best candidates and says
which ones it found. Answer with:

```text
“One.”
“The second one.”
“Number three.”
“Cancel.”
```

## Confirmation

For guarded actions, the island says **Say confirm**. The next command must be:

```text
“Confirm.”
```

or:

```text
“Cancel.”
```

If the page or target changes while LayaBrowse is waiting, the pending action is discarded.
