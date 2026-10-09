# Changelog

## Unreleased

- `ui-audit ci` starts and stops the app on Windows too (the whole process tree ends with `taskkill /T`).
- On Windows, file paths in `report.json`, the report and the app (source candidates, screenshots, settings and session files) use forward slashes like everywhere else.
- `ui-audit ci` asks an app on localhost directly whether it is up, never through a proxy from the environment or the macOS system settings.
- CI tests Python 3.11 to 3.14 on Linux plus macOS and Windows, and runs ruff, mypy and coverage. A test page asserts that state discovery never clicks a destructive-sounding control that looks like a disclosure.

## 0.1.0 — first public release

- `ui-audit audit`: route discovery (config, framework conventions, sitemap, crawl), conservative state discovery, a full width sweep with boundary refinement, bounded screenshots, findings grouped by cause, source hints, and a content check for pages that measure clean for the wrong reason.
- `ui-audit verify`: fixed, introduced and persistent findings against a baseline, never counting something as fixed that the new run did not look at.
- `ui-audit ui`: a local app to run audits, work through findings, hand them to an agent, re-check fixes and compare runs.
- `ui-audit login`, `accept`, `--fast`, `--changed-since`, `--locale`, consent-banner handling, setup actions.
- A GitHub Action (`uses: ItsAnhReal/ui-audit@…`) and `ui-audit ci`: audit a pull request and its base commit, comment what the change introduced and fixed, and fail on new P1/P2 findings.
- One Agent Skill shared by Claude Code and Codex (`ui-audit install-skill`).

Audits of Docusaurus, the Astro blog starter and the Bootstrap examples before release led to these fixes:

- Feeds and data endpoints (`rss.xml.js`, any non-HTML response) are skipped instead of audited as pages.
- Carousel slides and drawer menu panels parked beside the visible one no longer count as clipped content.
- An opened menu without `role=menu` floating over the page is no longer reported as overlapping controls, nor its items as crowding the targets under it.
- A visually hidden label that escapes its scrolling row and widens the page is named as the cause, instead of "the page is wider than the viewport".
- Text in a fixed bar, or clipped by its own box, is no longer named as what widens the page.
- Progress bars with a value no longer mark a page as still loading.
- Target sizes are compared as displayed: a 23.8px link is 24px.
