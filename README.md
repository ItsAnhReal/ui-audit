# ui-audit — Responsive UI Auditor

**Give your AI coding agent eyes.** `ui-audit` drives Chromium through every route and safe UI state of a running web app, sweeps the whole width range, measures layout defects, takes a bounded set of annotated screenshots, points at the likely source files, and verifies fixes against a baseline.

It is a local CLI, a local app, and one portable Agent Skill shared by Claude Code and Codex. No account, no cloud, MIT licensed.

![The report viewer: a grid that only overflows between 800 and 946 px, found by the width sweep and boxed in the screenshot](https://raw.githubusercontent.com/ItsAnhReal/ui-audit/main/docs/report-viewer.png)

```
Discover → Sweep → Capture → Diagnose → Map to code → Patch → Targeted rerun → Verify → Full regression
```

## Try it in a minute

```bash
git clone https://github.com/ItsAnhReal/ui-audit && cd ui-audit
pip install -e .                 # Python 3.11+
playwright install chromium
python3 -m http.server 8765 -d demo &
ui-audit audit http://localhost:8765 --project-root demo --open
```

The demo is a small site with planted defects. The one in the screenshot above is the point: four fixed columns that overflow only between 800 and 946 px, invisible at every common device preset.

## Why not just screenshot ten device sizes?

Responsive bugs live *between* presets: a grid that overflows from 800 to 946 px is invisible at 768 and 1366. `ui-audit` probes the full range cheaply (no screenshots), and wherever the set of defects changes between two sweep points it binary-searches the exact pixel. Screenshots go to a bounded, explainable set of widths:

1. the four presets (390, 768, 1366, 1920)
2. anomaly boundaries where defects appear or disappear
3. neighbours of every CSS breakpoint the page declares (N−1, N, N+1)

## Install

```bash
pipx install git+https://github.com/ItsAnhReal/ui-audit   # or: pip install -e . in a checkout; Python 3.11+
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

To re-check with the settings an earlier run used (app address, sign-in, language, setup), add `--like .ui-audit/baseline`; options you pass override them, and without `--output` the run goes to `.ui-audit/baseline-again`. The re-check commands in fix prompts use it.

`verify` reports **fixed**, **introduced** and **persistent** issues. A baseline issue only counts as fixed if the new run probed its route, state and at least one of its widths; everything else is counted as out of scope. Agent findings only count as fixed after a new semantic review. Exit code 1 means a P1/P2 issue was introduced (`--strict` also fails on persistent ones).

### Agent skill

```bash
ui-audit install-skill                 # .claude/skills/ui-audit and .codex/skills/ui-audit in this project
ui-audit install-skill --scope user    # ~/.claude/skills and ~/.codex/skills
```

The skill (`src/ui_audit/skill/SKILL.md`) tells the agent how to run the loop: baseline, semantic review, triage, patch, targeted rerun, verify, full regression, and when to stop.

## The app

```bash
ui-audit ui                                   # http://127.0.0.1:8484/?k=…, opens in your browser
ui-audit ui --config .ui-audit/shop.toml      # another settings file; --runs DIR, --port N, --no-open
```

A local web app for the whole loop, started in your project folder. It lists every run in the runs folder (the parent of `output`, usually `.ui-audit/`) and lets you:

- **start an audit**: quick (key widths), complete (every width) or just some pages and widths; pick the settings file, the app's language and a saved sign-in. *Sign in…* opens a browser window and saves the session next to the runs. Progress, time left and the log show while it runs; it can be cancelled.
- **work through findings**: grouped by cause, filtered by severity, page, kind or width (click the width chart), with the screenshot at every captured width and the measured element boxed. Keyboard: `↑` `↓` move, `←` `→` widths, `/` search.
- **hand a finding to your agent**: *Copy fix prompt* copies the problem, where it is, the likely source files, the screenshot path and the re-check commands.
- **re-check a fix**: measures just those pages at the edges of where the finding was seen (and one pixel outside them) and says whether it is gone, using the same rule as `verify`.
- **accept** a finding with a reason (written to `ui-audit.accepted.json`, so later runs keep it), **compare** two runs, open a run's folder, delete old runs.

The server listens on 127.0.0.1 only, answers only to `127.0.0.1` and `localhost` host names, and requires a per-start token for every API call, so other websites cannot reach it. The page itself opens only from the address printed at start, which carries a secret key (`?k=…`), so other users on the same machine cannot use it either; reopening that address works for as long as the server runs. Each audit runs in its own process (`python -m ui_audit.runner`), one at a time.

## Checks

| Check | Severity | Meaning |
|---|---|---|
| `horizontal-overflow` | P1 | The page scrolls sideways; reports the top-most element that sticks out, or the grid whose columns are wider than the grid itself |
| `offscreen-control` / `offscreen-content` | P1 / P2 | A control or text is cut off at the viewport edge; not reported again when it is the same element (or grid) as a `horizontal-overflow` |
| `clipped-content` | P2 | A box with hidden overflow cuts into the letters of its text (lost line spacing alone does not count; ellipsis and line-clamp are treated as intentional, and so are whole slides or drawer panels parked beside the visible one) |
| `text-spill` | P3 | Text visibly overflows its box |
| `overlapping-controls` | P2 | Two interactive controls overlap by ≥20% (menus and dialogs layered on purpose, including an opened menu next to its expanded button, fixed or sticky bars over scrolling content, buttons inside a text field, small actions laid over a larger row, and wrapped inline links are excluded) |
| `small-target` | P2 below 768px, else P3 | Pointer target smaller than 24×24px and closer than the WCAG 2.5.8 spacing exception allows to another target; inline text links excluded |
| `unnamed-control` | P2 | No accessible name |
| `console-error`, `failed-resource` | P2 | Runtime errors while loading or entering a state; an error logged while a state opened points at the dialog or menu that opened |
| `semantic-*` | agent-assigned | Findings merged from the agent's review, labelled `origin: agent` |

The three overflow checks are rated one step lower when the overflow is 4px or less, and one more step when it only occurs below 360px, the narrowest width most phones in use have. They are grouped as one cause in the report.

Deterministic findings are measurements. They can still be intentional; add those selectors to `[checks] ignore_selectors`.

## States

Besides each route's initial state, `ui-audit` discovers states by clicking disclosure controls only: `aria-expanded`, `aria-haspopup`, tabs, `<details>`, and anything marked `data-ui-audit-state`. Discovery runs at 390 and 1280px, skips anything inside a form, navigating links, submit buttons and controls whose name sounds destructive (delete, pay, logout, …), and keeps a candidate only if the click changes the DOM without changing the URL. A state found at 1280px is opened from the narrowest swept width at which its control is shown. Anything else goes in `[[states.custom]]`:

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

## Browsers

Audits run in Chromium. `--browsers chromium,webkit,firefox` (or `browsers = [...]` in `ui-audit.toml`) also runs them in WebKit, the engine behind Safari, and Firefox; install those once with `playwright install webkit firefox`. The first browser finds the routes and states, the others audit the same ones. A defect seen in several browsers is one finding; each finding lists its `browsers`, and the viewer marks the ones that show up in some browsers only.

## Accepting a finding

Some findings are intentional. `ui-audit accept <report folder> <issue or group id> --reason "…"` records them in `ui-audit.accepted.json` in the project root (commit it). Accepted findings stay in the report, flagged with the reason, but out of the counts, `--fail-on` and `verify`. The viewer hides them behind an "Accepted" filter and has a button on every finding that copies the command.

## In CI

The repository is also a GitHub Action. On every pull request it starts your app twice, once from the base commit and once from the pull request, audits both, and comments what the change introduced and fixed. The job fails when a new P1 or P2 finding appears.

```yaml
# .github/workflows/ui-audit.yml
name: ui-audit
on: pull_request

jobs:
  ui-audit:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write   # for the comment
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - uses: ItsAnhReal/ui-audit@main
        with:
          url: http://localhost:3000
          install: npm ci
          start: npm run dev -- --port 3000
          args: --fast
```

`install` and `start` run in each checkout; `start` stays in the background and is stopped after each audit, so both runs use the same port. The token that posts the comment is kept away from `install`, `start` and the audit, which run the pull request's code. The comment is updated on later pushes rather than repeated, the job summary carries the same text, and both reports with their screenshots are uploaded as the `ui-audit-report` artifact (open `head/index.html`).

| Input | Default | |
|---|---|---|
| `url` | required | where the app answers once it runs |
| `start` | | command that starts the app; without it the app must already run and nothing is compared |
| `install` | | command run before `start` in each checkout, e.g. `npm ci` |
| `working-directory` | `.` | where the app lives in the repository |
| `compare` | `auto` | `base`, `none`, or a folder with a committed `report.json`; `auto` is `base` on pull requests with a `start` command |
| `changed-only` | `false` | audit only routes that render a changed file (with `compare: base`) |
| `fail-on` | `new` | `new` (a P1 or P2 introduced), `P1`/`P2`/`P3` (any open finding at that level), or `never`; unless `never`, a base commit that cannot be audited fails the job too |
| `args` | | more `ui-audit audit` options, e.g. `--fast --route / --route /pricing` |
| `comment` | `true` | comment on the pull request (pull requests from forks get a read-only token; the job summary still works) |

Outputs: `p1`, `p2`, `p3`, `introduced`, `fixed`, `blocking`, `report-dir`, `summary-file`. Pin the action to a commit SHA if you want the same checks on every run.

The action is a thin wrapper around `ui-audit ci`, which works the same way in any other CI system:

```bash
ui-audit ci http://localhost:3000 --install "npm ci" --start "npm run dev -- --port 3000" --base-ref origin/main --args "--fast"
```

It exits 1 when `--fail-on` is met and 2 when the app or the audit could not run, and writes both reports and `summary.md` to `.ui-audit/ci`.

## Pages behind a login

```bash
ui-audit login --path /auth          # opens a browser window; sign in, then press Enter in the terminal
ui-audit audit --storage-state .ui-audit/auth.json
```

`login` saves the browser's cookies and local storage to `.ui-audit/auth.json` (or `--save <file>`); set `storage_state` in `ui-audit.toml` to use it on every run. You type the password yourself, in the browser; `ui-audit` never sees or stores it. The saved file works like a password for that account, so keep `.ui-audit/` out of version control, and sign in again when the session expires.

## Pages that measure clean for the wrong reason

A page that is still loading, shows an error or "unavailable" message, or is almost empty has nothing to overflow. Every page is scrolled through once before it is measured, so sections that fade in on scroll are there; a section that still stays fully transparent marks the route `hidden`. Each measured route gets `content.state` in `report.json` (`ok`, `loading`, `error-like`, `hidden` or `thin`); the summary and the viewer list every route that is not `ok`, because zero findings there says nothing about the real page. Give such a route its data or a sign-in and run it again.

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

## How it compares

| Tool | What it does | What ui-audit adds |
|---|---|---|
| Percy, Chromatic, BackstopJS | Compare screenshots with an approved baseline | Finds defects without a baseline, measures them instead of diffing pixels, and covers widths between presets |
| Lighthouse, axe | Performance and accessibility rules on one viewport | Layout defects across the whole width range and in opened menus, tabs and dialogs |
| Polypane, Responsively | Show many viewports side by side for a person to look at | Runs unattended and tells an agent what is broken, where, and in which file |
| Playwright MCP, Chrome DevTools MCP | Give an agent a browser to drive | A systematic sweep, findings grouped by cause, and `verify` to prove a fix |

## Development

```bash
pip install -e ".[dev]"
pytest                 # unit tests + end-to-end tests against the demo (a few minutes)
pytest -m "not e2e"    # unit tests only
```

Guidance for contributors and coding agents is in [`CLAUDE.md`](CLAUDE.md). A finding that is not a defect gets the smallest page reproducing it in `tests/cases/` before the check changes; bug reports with such a page are the most useful kind.

## Status

Version 0.1.0, alpha. Tested on two of the author's own apps and on Docusaurus, the Astro blog starter and the Bootstrap examples; [`CHANGELOG.md`](CHANGELOG.md) lists what those runs changed. Known limits: Chromium only; source mapping is weak in production builds; automatic state discovery is intentionally shallow.

## License

[MIT](LICENSE)
