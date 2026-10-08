# CLAUDE.md

Guidance for Claude Code (and Codex via AGENTS.md) working on this repository.

## What this is

`ui-audit` — a Python Playwright CLI plus one portable Agent Skill that audits running web apps for responsive defects across routes, UI states and widths, and verifies fixes. Product thesis and roadmap live in the owner's PKM ("Responsive UI Auditor Project"); this file covers the code.

## Commands

```bash
pip install -e ".[dev]"      # Python ≥3.11
pytest                       # all tests; e2e tests launch Chromium against demo/ (~1 min)
pytest -m "not e2e"          # fast unit tests
python3 -m http.server 8765 -d demo &   # serve the demo app
ui-audit audit http://localhost:8765 --project-root demo --output /tmp/run
```

If Playwright's pinned Chromium is missing, `browser.launch()` falls back to any Chromium under `PLAYWRIGHT_BROWSERS_PATH`, `~/.cache/ms-playwright` or `/opt/pw-browsers`; `UI_AUDIT_BROWSER_PATH` overrides.

## Layout

| Module | Responsibility |
|---|---|
| `cli.py` | argparse commands: `init`, `doctor`, `audit`, `merge-findings`, `verify`, `install-skill` |
| `config.py` | dataclass config, `ui-audit.toml` loading (unknown keys are errors), template |
| `audit.py` | the pipeline: routes → states → sweep → captures → source hints → reports |
| `probe.js` | injected as an init script; all in-page measurement, state candidates, annotations |
| `viewports.py` | pure functions: sweep widths, breakpoint neighbours, boundary search, capture selection |
| `routes.py` | discovery from config, source conventions, sitemap, crawl |
| `states.py` | conservative state discovery and replay of custom actions |
| `issues.py` | issue signatures and aggregation across widths and states |
| `sources.py` | ranking candidate source files from runtime and DOM hints |
| `report.py`, `semantic.py`, `verify.py` | report.json/index.html, agent review packet + merge, baseline comparison |
| `skill/SKILL.md` | the shared agent skill shipped with the package |
| `demo/` | deliberately broken site; its README lists every planted defect |

## Invariants

- `report.json` is the source of truth; `index.html` is regenerated from it.
- An issue's identity is its signature `check|route|state|selector`. `verify` compares signatures, so changing selector generation or check names breaks comparisons with old baselines — call that out in the PR.
- Deterministic and agent findings are never mixed: agent findings carry `origin: agent`.
- `verify` must never count something as fixed that the new run did not look at.
- Automatic state discovery must stay conservative: no forms, no navigation, no destructive-sounding controls.
- The sweep stays bounded: `max_refinements` and `max_captures` caps are part of the product, not tuning knobs to remove.
- Every planted defect in `demo/` has an end-to-end assertion; add one when you add a check.

## Conventions

- Python 3.11+, standard library plus Playwright; Pillow only for optional pixel diffs.
- Keep `probe.js` dependency-free and side-effect-free except `annotate`/`clearAnnotations`.
- Tests: unit tests for pure logic, `@pytest.mark.e2e` for anything that needs Chromium.
