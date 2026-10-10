"""What the probe clicks on its own: the consent banner's decline button and safe state controls.

Each page in tests/cases/consent and tests/cases/unsafe says on its first line what the probe
must pick there."""

from pathlib import Path

import pytest

from ui_audit.browser import PROBE_JS, launch

CASES = Path(__file__).parent / "cases"

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("chromium_available")]


def first_line(path: Path, key: str) -> str:
    return path.read_text().splitlines()[0].removeprefix(f"<!-- {key}:").removesuffix("-->").strip()


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch(playwright)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.add_init_script(PROBE_JS)
        yield context.new_page()
        browser.close()


@pytest.mark.parametrize("case", sorted((CASES / "consent").glob("*.html")), ids=lambda p: p.stem)
def test_consent_decline_only_inside_a_banner(page, case):
    page.goto(case.as_uri())
    found = page.evaluate("() => window.__uiAudit.consentDecline()")
    expected = first_line(case, "consent")
    assert (found["label"] if found else "none") == expected


def test_unsafe_words_match_whole_words(page):
    case = CASES / "unsafe" / "state-controls.html"
    page.goto(case.as_uri())
    found = page.evaluate("opts => window.__uiAudit.stateCandidates(opts)", {"unsafeWords": ["export"]})
    assert [c["label"] for c in found] == first_line(case, "candidates").split(", ")
