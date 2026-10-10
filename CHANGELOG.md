# Changelog

## Unreleased

- One set of exit codes for every command: 0 ok, 1 findings over the threshold, 2 usage or input error, 3 the app or the audit failed. `audit --fail-on` now exits 1 (was 2), `ui-audit ci` exits 3 when it could not audit (was 2), `init` over an existing file and invalid agent findings exit 2, and a missing or broken `report.json` is a one-line error instead of a traceback.
- `audit` no longer reports an unreachable app as 0 findings: a route that did not load, a run that measured no route, or most routes ending on one sign-in page (an expired `storage_state`) is an `error:` line and exit 3. `doctor` says which copy of the skill each agent reads, and `--help` shows the four-step loop.
- `ui-audit ci` starts and stops the app on Windows too (the whole process tree ends with `taskkill /T`).
- On Windows, file paths in `report.json`, the report and the app (source candidates, screenshots, settings and session files) use forward slashes like everywhere else.
- `ui-audit ci` asks an app on localhost directly whether it is up, never through a proxy from the environment or the macOS system settings.
- CI tests Python 3.11 to 3.14 on Linux plus macOS and Windows, and runs ruff, mypy and coverage. A test page asserts that state discovery never clicks a destructive-sounding control that looks like a disclosure.
- `ui-audit demo`: the demo site with planted defects now ships with the package; the command serves it, audits it and opens the report.
- Installable with `pipx install ui-audit` once 0.1.0 is on PyPI, and the Action gets a `v0` tag that follows every 0.x release.
- The GitHub Action posts the pull request comment from a separate step after the app has stopped; the step that runs `install`, `start` and the audit no longer gets the token. New `comment-file` input and `ui-audit ci --post-comment` for commenting from a `workflow_run` job, which also works for pull requests from forks. The README recommends `persist-credentials: false` and a `concurrency` group.
- The action installs only Chromium's system libraries when the browser comes from the cache, and caches pip downloads.
- `ui-audit ui` opens only from the address it prints at start (`http://127.0.0.1:8484/?k=…`, like Jupyter); without the key the page answers 403, so other users on the same machine cannot use the app. Sessions from the app's login are saved only as plain file names next to the runs.
- App and report: a visible keyboard focus outline everywhere (also in forced-colors mode), named dialogs, errors announced as alerts, a setting to turn off the single-key shortcuts `j`, `k` and `/`, no "open page" link for addresses that are not http(s), and a quoted path in the copied `accept` command.

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
