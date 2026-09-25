# LayaBrowse 0.2.0 — goal mode by default

`layabrowse install` now installs the local Laya goal loop without flags. The Swift menu-bar app,
LaunchAgent and foreground CLI use the same default. The previous rules-first engine remains
available with `layabrowse install --legacy` for comparison or rollback.

The loop asks Laya to choose a supported outcome and a compatible browser action, observes the page,
then checks that the outcome occurred before reporting success. It currently supports safe site
navigation, searches and numbered results on selected sites, visible links, tabs, basic scrolling,
and YouTube video/Short controls. New tabs open Google. Exact back, forward and scroll remain narrow
zero-model shortcuts. Search, link and media decisions still use Laya.

This is a **source-install alpha**, not a redistributable or notarized `.app`. The native app is built
and signed locally by `layabrowse install` because it depends on the local Python environment and
model cache. The GitHub release's automatically generated source archives are the release files;
follow the [README](README.md) to install. An MP4 setup/architecture explainer is attached separately.

Known limits: the SafariDriver session is separate from ordinary signed-in Safari tabs; Google and
eBay can present automation challenges; speech recognition can mishear commands; ambiguous links
can abstain or be chosen incorrectly; sorting/filter menus, purchases, messages and account changes
are not yet verified goal capabilities. A reported recovery after toggling listening off/on is still
under investigation. Do not treat this as a general computer-use agent.
