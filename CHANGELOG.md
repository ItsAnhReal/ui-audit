# Changelog

## Unreleased

- **Changed issue signatures** — compare against a fresh baseline after upgrading. Selectors leave out generated class names and ids (CSS Modules, styled-components, emotion, Svelte, styled-jsx, React `useId`, Radix), prefer `data-testid`/`data-test`/`data-cy`, stable ids and a control's role and `aria-label`, and are as short as is unique on the page. Discovered state ids leave out counts ("Cart (3)" is `expand-cart`), and console errors and failed requests are identified without query strings, bundle hashes, timestamps and ids (the message keeps the raw text).
- `verify` no longer counts a finding as fixed where its check hit `max_issues_per_check` or the 400-control limit (recorded in report.json as `coverage_truncated`), and lists findings on routes or states the baseline did not audit as `new_scope` instead of introduced. Out-of-range numbers in `ui-audit.toml` are config errors, and a configured `0` (e.g. `min_target_size = 0`) is no longer replaced by the default.
- Widths below 768px are measured as a phone in Chromium and WebKit (meta viewport, touch, `hover: none`); Firefox stays a desktop browser. `[viewports] mobile_below = 0` turns it off. A page without `width=device-width` in its meta viewport now lays out 980px wide on narrow widths, as on a real phone, and is reported once as `viewport-meta`.
- New checks: `viewport-meta`, `sticky-covers-viewport`, `fixed-covers-end`, `small-input-font`, `tiny-text`, `distorted-image` and `broken-image`. A `horizontal-overflow` names its cause where it is clear (message and `cause`), and says when `overflow-x: hidden` on the page cuts the content off; existing signatures are unchanged.

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
