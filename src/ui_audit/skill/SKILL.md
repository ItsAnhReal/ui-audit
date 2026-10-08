---
name: ui-audit
description: Audit a running web app for responsive and visual defects across routes, UI states and viewport widths, fix them in code, and prove each fix with a before/after verification. Use when the user asks to check, QA, audit or fix layout, responsiveness, mobile view, overflow, clipping or visual regressions, or before shipping frontend changes.
---

# ui-audit — responsive UI audit and verified fixes

`ui-audit` is a local CLI. It drives Chromium through every discovered route and safe UI state, sweeps the width range, records objective defects, takes a bounded set of screenshots, and points at likely source files. You add judgement, change the code, and prove the result with `ui-audit verify`.

## Loop

```
Discover → Sweep → Capture → Diagnose → Map to code → Patch → Targeted rerun → Verify → Full regression
```

### 1. Preconditions

- The app must be running. Find the dev command (`package.json` scripts, README) and start it in the background if needed. Note the URL.
- Run `ui-audit doctor --base-url <url>` once. If no `ui-audit.toml` exists, run `ui-audit init --base-url <url>` and review the routes it found.
- If pages need a login, ask the user to run `ui-audit login --path <sign-in page>` themselves: it opens a browser window, they sign in, and the session is saved to `.ui-audit/auth.json`. Then set `storage_state` in `ui-audit.toml` or pass `--storage-state`. Never type real credentials you were not given.

### 2. Baseline

```bash
ui-audit audit --base-url <url> --project-root . --output .ui-audit/baseline
```

Read `.ui-audit/baseline/report.json` (source of truth) and skim `index.html`. Each issue has `severity`, `check`, `route`, `state`, `widths`, `selector`, `message`, `evidence` (screenshots) and `source_candidates`.

### 3. Semantic review (your judgement)

Open `.ui-audit/baseline/semantic-review.md`. Look at every screenshot it lists — use your image-reading tool on the PNG files. Record only problems a user would notice, using the rubric in the file, into `.ui-audit/baseline/agent-findings.json`, then:

```bash
ui-audit merge-findings .ui-audit/baseline
```

Your findings are stored with `origin: agent`. Never present them as measured facts.

### 4. Triage before editing

- Deterministic P1/P2 findings are measurements, not opinions — but they can be intentional (a deliberately scrollable table, a decorative overlap). Check the screenshot before fixing. Add genuinely intentional cases to `[checks] ignore_selectors` and say so.
- `source_candidates` and `hints` are search results, not proof. Open the file and confirm the element lives there.
- Group issues by root cause: one fixed-width container often explains several overflow findings at many widths.
- Do not "fix" P3 or subjective findings without asking the user.

### 5. Patch and targeted rerun

Fix one root cause at a time. Rerun only what you touched, at the widths where it failed plus neighbours:

```bash
ui-audit audit --base-url <url> --project-root . \
  --route /pricing --width 767,768,769,834,1024 --output .ui-audit/fix-1
ui-audit verify .ui-audit/baseline .ui-audit/fix-1
```

`verify` reports **fixed**, **introduced** and **persistent** issues, and counts baseline issues outside the rerun's routes/widths separately instead of calling them fixed. Exit code 1 means a P1/P2 was introduced.

### 6. Full regression and stop condition

When the targeted reruns are clean, run a full audit into a new directory and `verify` it against the baseline. You are done when:

- no P1/P2 issue is persistent or introduced, except ones the user accepted as intentional, and
- the verify output is shown to the user with the before/after screenshot paths for each fix.

If the same issue survives three attempts, stop and report what you tried.

## Report to the user

List each fixed issue with route, widths, root cause, the file you changed, and the verify result. List accepted exceptions and anything left open. Link `index.html` of the final run.

## Useful flags

- `--route` (repeatable) and `--width 390,768` for targeted runs
- `--no-states` to skip automatic state discovery, `--max-captures N` to bound screenshots
- `--fail-on P1` for CI-style exit codes
- `ui-audit verify --pixel-diff` adds per-screenshot changed-pixel ratios (needs Pillow)
