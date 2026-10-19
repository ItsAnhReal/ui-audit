# Contributing

Thanks for helping. Bug reports, false positives and pull requests are all welcome.

## Development setup

```bash
git clone https://github.com/ItsAnhReal/ui-audit && cd ui-audit
python3 -m venv .venv && . .venv/bin/activate   # Python 3.11+
pip install -e ".[dev]"
playwright install chromium                      # webkit firefox too, for the tests of other browsers
```

`ui-audit demo` serves the bundled demo site (`src/ui_audit/demo/`, every planted defect is listed in its README) and audits it.

## Tests

```bash
pytest -m "not e2e"    # unit tests, seconds
pytest                 # everything; e2e tests launch real browsers against the demo site (a few minutes)
```

Unit tests cover pure logic; anything that needs a browser is marked `@pytest.mark.e2e`. WebKit and Firefox tests skip where those browsers are not installed. CI runs the full suite.

## False positives: the `tests/cases` rule

When a check reports something that is not a defect, first add the smallest page that reproduces it to `tests/cases/`, then change the check. The first line of each case states what an audit must report (often nothing). That keeps every fix from quietly coming back. A bug report that already has such a page is the most useful kind.

## Pull requests

- One topic per pull request; keep the diff focused.
- Add tests for every change in behaviour, and a line under `## Unreleased` in `CHANGELOG.md` for anything users notice.
- Follow the invariants in [`CLAUDE.md`](CLAUDE.md), the guidance shared by people and coding agents. In particular: an issue's identity is its signature `check|route|state|selector`, so a change to selector generation or check names breaks comparisons with old baselines. Say so in the pull request.
- Every planted defect in the demo site has an end-to-end assertion; add one when you add a check.
- Texts in the app (`src/ui_audit/ui/app/*.js`) go through `t()` and exist in English and German.

## Releasing

Releases are published by [`.github/workflows/release.yml`](.github/workflows/release.yml) when a version tag is pushed. It builds the sdist and wheel, checks that the tag matches the version in `pyproject.toml`, publishes to PyPI with Trusted Publishing, creates a GitHub Release with the version's `CHANGELOG.md` section as notes, and moves the major tag (`v0`) to the release commit so `uses: ItsAnhReal/ui-audit@v0` picks it up.

One-time setup:

1. On PyPI, add a trusted publisher (for a project that does not exist yet: *Your account → Publishing → Add a new pending publisher*): project `ui-audit`, owner `ItsAnhReal`, repository `ui-audit`, workflow `release.yml`, environment `pypi`.
2. On GitHub, create the environment `pypi` (*Settings → Environments*); requiring a reviewer there makes every upload wait for an approval.

Each release:

1. Set `version` in `pyproject.toml` (the only place it is written; `ui_audit.__version__` reads it from the installed package).
2. In `CHANGELOG.md`, rename `## Unreleased` to `## <version>` (anything may follow on that line, e.g. `## 0.2.0 — short title`).
3. Merge that to `main`, then tag the merge commit and push the tag:

   ```bash
   git tag v0.2.0 && git push origin v0.2.0
   ```

If the tag and the version differ, or the changelog has no section for the version, the workflow stops before anything is published.
