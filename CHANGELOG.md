# Changelog

## Unreleased

- One set of exit codes for every command: 0 ok, 1 findings over the threshold, 2 usage or input error, 3 the app or the audit failed. `audit --fail-on` now exits 1 (was 2), `ui-audit ci` exits 3 when it could not audit (was 2), `init` over an existing file and invalid agent findings exit 2, and a missing or broken `report.json` is a one-line error instead of a traceback.
- `audit` no longer reports an unreachable app as 0 findings: a route that did not load, a run that measured no route, or most routes ending on one sign-in page (an expired `storage_state`) is an `error:` line and exit 3. `doctor` says which copy of the skill each agent reads, and `--help` shows the four-step loop.

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
