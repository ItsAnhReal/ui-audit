# CLAUDE.md

Guidance for Claude Code (and Codex via AGENTS.md) working on this repository.

## What this is

`ui-audit` — a Python Playwright CLI plus one portable Agent Skill that audits running web apps for responsive defects across routes, UI states and widths, and verifies fixes.

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
| `cli.py` | argparse commands: `init`, `doctor`, `audit`, `login`, `accept`, `report`, `ui`, `merge-findings`, `verify`, `install-skill` |
| `config.py` | dataclass config, `ui-audit.toml` loading (unknown keys are errors), template |
| `audit.py` | the pipeline: routes → states → sweep → captures → source hints → reports |
| `probe.js` | injected as an init script; all in-page measurement, state candidates, annotations |
| `viewports.py` | pure functions: sweep widths, breakpoint neighbours, boundary search, capture selection |
| `routes.py` | discovery from config, source conventions, sitemap, crawl |
| `states.py` | conservative state discovery and replay of custom actions |
| `issues.py` | issue signatures and aggregation across widths and states |
| `sources.py` | ranking candidate source files from runtime and DOM hints |
| `report.py`, `semantic.py`, `verify.py` | report.json/index.html, agent review packet + merge, baseline comparison |
| `ui/` | the viewer and app front end (`index.html`, `app.css`, `i18n.js`, `app.js`); `report.py` assembles them into one page, with report data inlined (static `index.html`) or an app token (`ui-audit ui`) |
| `server.py` | `ui-audit ui`: stdlib HTTP server on 127.0.0.1, run list, job queue, accept/re-check/compare API |
| `runner.py` | one audit in a subprocess for the app: JSON spec on stdin, JSON-line progress events on stdout |
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
- The app server only binds 127.0.0.1, checks the Host header and requires its token on every API call; screenshots need its SameSite=Strict cookie. Every text in `ui/app.js` goes through `t()` and exists in both languages of `ui/i18n.js` (`tests/test_i18n.py`).
- A check that reported something that is not a defect gets the smallest page reproducing it in `tests/cases/` before the check changes; the first line of each case states what an audit must report.

## Conventions

- Python 3.11+, standard library plus Playwright; Pillow only for optional pixel diffs.
- Keep `probe.js` dependency-free and side-effect-free except `annotate`/`clearAnnotations`.
- Tests: unit tests for pure logic, `@pytest.mark.e2e` for anything that needs Chromium.
