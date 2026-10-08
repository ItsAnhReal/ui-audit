# ui-audit — Responsive UI Auditor

**Give your AI coding agent eyes.** `ui-audit` drives Chromium through every route and safe UI state of a running web app, sweeps the whole width range, measures layout defects, takes a bounded set of annotated screenshots, points at the likely source files, and verifies fixes against a baseline.

It is a local CLI plus one portable Agent Skill shared by Claude Code and Codex. No account, no cloud.

```
Discover → Sweep → Capture → Diagnose → Map to code → Patch → Targeted rerun → Verify → Full regression
```

## Why not just screenshot ten device sizes?

Responsive bugs live *between* presets: a grid that overflows from 800 to 946 px is invisible at 768 and 1366. `ui-audit` probes the full range cheaply (no screenshots), and wherever the set of defects changes between two sweep points it binary-searches the exact pixel. Screenshots go to a bounded, explainable set of widths:

1. the four presets (390, 768, 1366, 1920)
2. anomaly boundaries where defects appear or disappear
3. neighbours of every CSS breakpoint the page declares (N−1, N, N+1)

## Install

```bash
pip install -e ".[dev]"          # from a checkout; Python 3.11+
playwright install chromium      # or point --browser-path / UI_AUDIT_BROWSER_PATH at an existing Chromium
```

## Use

```bash
ui-audit init --base-url http://localhost:3000   # writes ui-audit.toml with routes found in your source
ui-audit doctor                                   # Python, Chromium, config, app reachable, skills installed
ui-audit audit --output .ui-audit/baseline        # full audit
ui-audit ui                                       # or do all of it in the local app (below)
```

Outputs in the output directory:

| File | What it is |
|---|---|
| `report.json` | Source of truth: routes, states, coverage, captures, issues with widths, selectors, evidence and source candidates, and `groups`: the issues folded by cause (one component broken on five routes is one group) |
| `index.html` | Report viewer: findings by cause or by page, a width chart showing where they sit, filters, a screenshot viewer with the measured boxes, and a fix prompt to copy. One self-contained file, no server, English and German |
| `shots/*.png` | Clean and annotated full-page screenshots (sideways overflow included) |
| `semantic-review.md`, `semantic-packet.json` | A bounded packet (≤12 screenshots) for the agent's visual judgement |

Look at a report with `ui-audit report .ui-audit/baseline` (rebuilds `index.html` from `report.json` and opens it), or pass `--open` to `audit`.

After a fix, rerun only what changed and compare:

```bash
ui-audit audit --route /pricing --width 767,768,769,834 --output .ui-audit/fix-1
ui-audit verify .ui-audit/baseline .ui-audit/fix-1 --pixel-diff
```

`verify` reports **fixed**, **introduced** and **persistent** issues. A baseline issue only counts as fixed if the new run probed its route, state and at least one of its widths; everything else is counted as out of scope. Agent findings only count as fixed after a new semantic review. Exit code 1 means a P1/P2 issue was introduced (`--strict` also fails on persistent ones).

### Agent skill

```bash
ui-audit install-skill                 # .claude/skills/ui-audit and .codex/skills/ui-audit in this project
ui-audit install-skill --scope user    # ~/.claude/skills and ~/.codex/skills
```

The skill (`src/ui_audit/skill/SKILL.md`) tells the agent how to run the loop: baseline, semantic review, triage, patch, targeted rerun, verify, full regression, and when to stop.

## The app

```bash
ui-audit ui                                   # http://127.0.0.1:8484, opens in your browser
ui-audit ui --config .ui-audit/shop.toml      # another settings file; --runs DIR, --port N, --no-open
```

A local web app for the whole loop, started in your project folder. It lists every run in the runs folder (the parent of `output`, usually `.ui-audit/`) and lets you:

- **start an audit**: quick (key widths), complete (every width) or just some pages and widths; pick the settings file, the app's language and a saved sign-in. *Sign in…* opens a browser window and saves the session next to the runs. Progress, time left and the log show while it runs; it can be cancelled.
- **work through findings**: grouped by cause, filtered by severity, page, kind or width (click the width chart), with the screenshot at every captured width and the measured element boxed. Keyboard: `↑` `↓` move, `←` `→` widths, `/` search.
- **hand a finding to your agent**: *Copy fix prompt* copies the problem, where it is, the likely source files, the screenshot path and the re-check commands.
- **re-check a fix**: measures just those pages at the edges of where the finding was seen (and one pixel outside them) and says whether it is gone, using the same rule as `verify`.
- **accept** a finding with a reason (written to `ui-audit.accepted.json`, so later runs keep it), **compare** two runs, open a run's folder, delete old runs.

The server listens on 127.0.0.1 only, answers only to `127.0.0.1` and `localhost` host names, and requires a per-start token for every API call, so other websites cannot reach it. Each audit runs in its own process (`python -m ui_audit.runner`), one at a time.

## Checks

| Check | Severity | Meaning |
|---|---|---|
| `horizontal-overflow` | P1 | The page scrolls sideways; reports the top-most element that sticks out |
| `offscreen-control` / `offscreen-content` | P1 / P2 | A control or text is cut off at the viewport edge |
| `clipped-content` | P2 | A box with hidden overflow cuts into the letters of its text (lost line spacing alone does not count; ellipsis and line-clamp are treated as intentional) |
| `text-spill` | P3 | Text visibly overflows its box |
| `overlapping-controls` | P2 | Two interactive controls overlap by ≥20% (menus and dialogs layered on purpose, fixed or sticky bars over scrolling content, buttons inside a text field, small actions laid over a larger row, and wrapped inline links are excluded) |
| `small-target` | P2 below 768px, else P3 | Pointer target smaller than 24×24px and closer than the WCAG 2.5.8 spacing exception allows to another target; inline text links excluded |
| `unnamed-control` | P2 | No accessible name |
| `console-error`, `failed-resource` | P2 | Runtime errors while loading or entering a state |
| `semantic-*` | agent-assigned | Findings merged from the agent's review, labelled `origin: agent` |

Deterministic findings are measurements. They can still be intentional; add those selectors to `[checks] ignore_selectors`.

## States

Besides each route's initial state, `ui-audit` discovers states by clicking disclosure controls only: `aria-expanded`, `aria-haspopup`, tabs, `<details>`, and anything marked `data-ui-audit-state`. Discovery runs at 390 and 1280px, skips anything inside a form, navigating links, submit buttons and controls whose name sounds destructive (delete, pay, logout, …), and keeps a candidate only if the click changes the DOM without changing the URL. Anything else goes in `[[states.custom]]`:

```toml
[[states.custom]]
name = "cart-open"
route = "/shop"
actions = [{ click = "#cart" }, { wait_for = ".cart-drawer" }]
```

Actions: `click`, `hover`, `fill` + `value`, `press`, `wait`, `wait_for`. For logged-in pages, save a Playwright storage state and set `storage_state`.

## Faster runs

A full audit sweeps every route and every opened menu, tab and dialog across the whole width range. Three ways to spend less:

- `--fast` (or `[states] sweep = "key"`) still sweeps each route's initial page fully, but probes opened states only at the presets, the breakpoints and the widths where the initial page changed.
- `--changed-since <git ref>` audits only the routes that render a file changed since that ref. It reads which components each route rendered from a previous full report (`--baseline`, default: the output directory), which a dev build of React, Vue or Svelte reveals. A changed stylesheet, helper or component that no audited page rendered could affect anything, so then every route is audited; the command says which case applied.
- `--no-annotate` saves each screenshot once instead of twice. The viewer draws the boxes itself; only the agent's review packet loses its annotated images.

## Languages

`--locale de` (or `locale = "de"`) sets the browser language. Apps that follow it render in that language, where longer labels overflow first. Run once per language into separate output directories.

## Accepting a finding

Some findings are intentional. `ui-audit accept <report folder> <issue or group id> --reason "…"` records them in `ui-audit.accepted.json` in the project root (commit it). Accepted findings stay in the report, flagged with the reason, but out of the counts, `--fail-on` and `verify`. The viewer hides them behind an "Accepted" filter and has a button on every finding that copies the command.

## In CI

[`examples/github-workflow.yml`](examples/github-workflow.yml) audits the routes a pull request touches and comments the comparison with the base branch. It is a starting point: starting your app and keeping a baseline report are yours to adapt.

## Pages behind a login

```bash
ui-audit login --path /auth          # opens a browser window; sign in, then press Enter in the terminal
ui-audit audit --storage-state .ui-audit/auth.json
```

`login` saves the browser's cookies and local storage to `.ui-audit/auth.json` (or `--save <file>`); set `storage_state` in `ui-audit.toml` to use it on every run. You type the password yourself, in the browser; `ui-audit` never sees or stores it. The saved file works like a password for that account, so keep `.ui-audit/` out of version control, and sign in again when the session expires.

## Pages that measure clean for the wrong reason

A page that is still loading, shows an error or "unavailable" message, or is almost empty has nothing to overflow. Each measured route gets `content.state` in `report.json` (`ok`, `loading`, `error-like` or `thin`); the summary and the viewer list every route that is not `ok`, because zero findings there says nothing about the real page. Give such a route its data or a sign-in and run it again.

## Consent banners and setup

A cookie banner sits on top of every page and hides what is under it. With `[states] dismiss_consent = true` (the default) `ui-audit` looks for the banner's button that turns optional cookies down ("Only necessary", "Reject", "Ablehnen", …), clicks it once, and audits the pages a returning visitor sees. It never clicks "Accept all". The label it clicked is recorded as `consent_dismissed` in `report.json`. Set it to `false` to audit the first-visit view with the banner open.

For anything else that has to be out of the way first, list actions in `setup`; they run once on `/` before anything is measured (a failure there is reported in `errors`), and again on every page that is loaded, so a dismissal the app does not remember stays dismissed. An action whose target is not on the page is skipped:

```toml
setup = [{ click = "#close-promo" }]
```

## Routes

Discovered from `[routes] include`, framework conventions in `project_root` (Next.js app and pages routers, Nuxt, Astro, SvelteKit, React Router route tables, static `*.html`), `sitemap.xml`, and a same-origin crawl. Dynamic routes are listed as skipped until you give a sample in `[routes] samples`.

In a project whose `package.json` names a client-side router (React Router, Vue Router, …) and no file-based one, `pages/` is a folder of components, so its file names are not treated as URLs; only the route table counts.

With `dedupe = true` (the default) a route is skipped, and marked in `routes[].status`, when it renders the app's not-found page, redirects to a route already audited, or renders the same page as one. `--route` reruns never skip. `max_routes` counts routes that are measured: a skipped route costs one page load, not a place in the budget. Configured and crawled routes go first, source guesses last, and whatever is left when the budget is used up is listed in `truncated_routes`.

## Source hints

For each issue, development builds give runtime hints (React `_debugSource` and component names, Vue `__file`, Svelte `__svelte_meta`). These, the element's id, classes, parent classes and text are used to rank up to three candidate files. They are search results for the agent to confirm, not conclusions.

## Demo

`demo/` is a small static site with deliberately planted defects (see `demo/README.md`):

```bash
python3 -m http.server 8765 -d demo &
ui-audit audit http://localhost:8765 --project-root demo
```

## Development

```bash
pip install -e ".[dev]"
pytest                 # unit tests + end-to-end tests against the demo (≈1 min)
pytest -m "not e2e"    # unit tests only
```

## Status

Version 0.1.0. Not yet validated on a real application — see the project's definition of done. Known limits: Chromium only; source mapping is weak in production builds; automatic state discovery is intentionally shallow.
