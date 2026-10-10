---
name: ui-audit
description: Audit a running web app for responsive and visual defects across routes, UI states and viewport widths, fix them in code, and prove each fix with a before/after verification. Use when the user asks to check, QA, audit or fix layout, responsiveness, mobile view, overflow, clipping or visual regressions, or before shipping frontend changes.
---

# ui-audit — responsive UI audit and verified fixes

`ui-audit` is a local CLI. It drives Chromium through every discovered route and safe UI state, sweeps the width range, records objective defects, takes a bounded set of screenshots, and points at likely source files. You add judgement, change the code, and prove the result with `ui-audit verify`.

## Loop

```
Start app → Baseline → Read groups → Triage → Patch → Targeted rerun → Verify → Full regression
```

### 1. Preconditions

- The app must be running. Find the dev command (`package.json` scripts, README), start it **in the background** (it never exits on its own), and poll the URL until it answers (e.g. `curl -sf <url>` in a short loop) before auditing.
- Run `ui-audit doctor --base-url <url>` once. If no `ui-audit.toml` exists, run `ui-audit init --base-url <url>` and review the routes it found.
- If pages need a login, ask the user to run `ui-audit login --path <sign-in page>` themselves; it saves the session to `.ui-audit/auth.json`. Then set `storage_state` in `ui-audit.toml` or pass `--storage-state`. Never type real credentials you were not given.

### 2. Baseline

```bash
ui-audit audit <url> --project-root . --output .ui-audit/baseline --json
```

`--json` prints a compact summary on stdout (logs go to stderr): counts, **groups** (one per cause, with routes, width range, one example selector, the best source candidate and a screenshot path), routes to check by hand, errors. `--fast` probes opened menus and dialogs only at key widths; use it for quick passes. Add `--browsers chromium,webkit,firefox` if the user cares about Safari or Firefox.

**Read the summary, not report.json** (it is large). Drill into one cause at a time:

```bash
ui-audit show .ui-audit/baseline --json                 # the summary again
ui-audit show .ui-audit/baseline --group <id> --json    # every finding of a cause: widths, evidence, all source candidates, re-check command
ui-audit show .ui-audit/baseline --issue <id> --json    # one finding
```

### 3. Triage before editing

- Deterministic P1/P2 findings are measurements, not opinions — but they can be intentional (a deliberately scrollable table, a decorative overlap). Look at the screenshot before fixing.
- For an intentional finding, run `ui-audit accept <run> <issue-or-group-id> --reason "..."` and tell the user. Prefer this over `[checks] ignore_selectors`: it is recorded per finding with a reason in `ui-audit.accepted.json`, and later runs stop counting it.
- Source candidates are search results, not proof. Open the file and confirm the element lives there.
- A group is one root cause: fix it once, not per finding.
- Do not "fix" P3 or subjective findings without asking the user.

### 4. Semantic review (optional)

Screenshot review is expensive; do it when the deterministic results are clean, when a route is flagged "check by hand" (its `content.state` is not ok), or when the user asks for visual judgement. Then open `<run>/semantic-review.md`, look at the PNGs it lists with your image tool, write problems a user would notice to `<run>/agent-findings.json` (rubric in the file) and run `ui-audit merge-findings <run>`. These are stored with `origin: agent`; never present them as measured facts.

### 5. Patch and targeted rerun

Fix one cause at a time. `show --group <id>` gives the exact re-check command; it looks like:

```bash
ui-audit audit --like .ui-audit/baseline --route /pricing --width 767,768,769,1024 --output .ui-audit/baseline-recheck
ui-audit verify .ui-audit/baseline .ui-audit/baseline-recheck --json
```

`--like <run>` reuses that run's settings. `verify` reports **fixed**, **introduced** and **persistent** findings, and counts baseline findings outside the rerun's routes/widths as `out_of_scope` instead of calling them fixed. After editing only some components, `ui-audit audit --changed-since <git-ref> --baseline .ui-audit/baseline` audits just the routes that render changed files.

### 6. Full regression and stop condition

When the targeted reruns are clean, run a full audit into a new directory and `verify` it against the baseline. You are done when:

- no P1/P2 finding is persistent or introduced, except ones accepted as intentional, and
- the verify result is shown to the user with the before/after screenshot paths for each fix.

If the same finding survives three attempts, stop and report what you tried.

## Exit codes

`0` ok · `1` findings over the threshold (`audit --fail-on P1|P2|P3`; `verify`: a P1/P2 was introduced, or persists with `--strict`) · `2` usage or config error · `3` the app or browser failed (app not reachable, browser did not start). On `3`, fix the environment, not the code.

## Report to the user

List each fixed cause with route, widths, root cause, the file you changed, and the verify result. List accepted exceptions and anything left open. Link `index.html` of the final run.

## Useful flags

- `--route` (repeatable), `--width 390,768` for targeted runs; `--no-states` skips state discovery; `--max-captures N` bounds screenshots
- `--fail-on P1` for CI-style exit codes
- Exit codes: 0 ok, 1 findings over the threshold (`--fail-on`, `verify`), 2 usage or input error, 3 the app or the audit failed (a route did not load, or most routes ended on a sign-in page): never read 3 as "no findings"
- `ui-audit verify --pixel-diff` adds per-screenshot changed-pixel ratios (needs Pillow)
