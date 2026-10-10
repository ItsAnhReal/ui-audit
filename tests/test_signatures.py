"""Selectors stay the same across builds and name one element; capped checks are recorded."""

import pytest

from ui_audit import audit
from ui_audit.config import from_dict

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("chromium_available")]

HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>t</title><style>
body { margin: 0; padding: 24px; font: 16px/1.5 sans-serif; }
p { width: 200px; height: 30px; overflow: hidden; }
.tools { display: flex; gap: 4px; } .tools button { width: 18px; height: 18px; padding: 0; }"""

# Class names and ids as CSS Modules, styled-components, emotion, Svelte, styled-jsx and React's
# useId write them: every build renames them. Each <p> clips its text.
HASHED = HEAD + """
</style></head><body><main class="Page_main__nLjiQ">
<ul class="Cards_list__x7Yz2 sc-bdVaJa kCQjZg">
  <li class="Card_card__3kd9A css-1x2y3z card"><p class="_3kd9A blurb">This paragraph needs three lines of room but shows one.</p></li>
  <li class="Card_card__3kd9A css-1x2y3z card"><p class="_3kd9A blurb">This paragraph needs three lines of room but shows one.</p></li>
</ul>
<div class="tools svelte-1abc23"><button class="jsx-123456" aria-label="Bold">b</button><button aria-label="Italic">i</button></div>
<div data-testid="promo"><p class="e1x2y3z0">This paragraph needs three lines of room but shows one.</p></div>
<section id=":r1:"><p>This paragraph needs three lines of room but its box only shows one of them.</p></section>
</main></body></html>"""

# More controls than the pairwise checks look at, all of them too small and too close.
CROWDED = HEAD + "</style></head><body><div class=\"tools\" style=\"flex-wrap: wrap\">" + \
    "<button aria-label=\"Tool\"></button>" * 420 + "</div></body></html>"


def run(site, url, tmp_path, pages, widths, checks=None):
    for name, html in pages.items():
        (site / name).write_text(html)
    cfg = from_dict({
        "base_url": url, "project_root": str(site), "output": str(tmp_path / "run"), "settle_ms": 50,
        "routes": {"include": [f"/{name}" for name in pages], "discover": ["config"], "dedupe": False},
        "states": {"auto": False}, "viewports": {"widths": widths}, "checks": checks or {},
    })
    return audit.run(cfg, log=lambda _: None)


def test_selectors_leave_out_generated_names_and_are_unique(demo_site, tmp_path):
    url, site = demo_site
    report = run(site, url, tmp_path, {"hashed.html": HASHED, "crowded.html": CROWDED}, [390])
    selectors = sorted(i["selector"] for i in report["issues"] if i["route"] == "/hashed.html")
    assert selectors == sorted([
        "li.card:nth-of-type(1) > p.blurb", "li.card:nth-of-type(2) > p.blurb",
        '[data-testid="promo"] > p', "section > p",
        'button[aria-label="Bold"]', 'button[aria-label="Italic"]',
    ])
    from playwright.sync_api import sync_playwright

    from ui_audit.browser import launch

    with sync_playwright() as playwright:
        chromium = launch(playwright)
        page = chromium.new_page()
        page.goto(f"{url}/hashed.html")
        assert [page.evaluate("s => document.querySelectorAll(s).length", s) for s in selectors] == [1] * len(selectors)
        chromium.close()

    # The 400-control cut and the per-check cap are both recorded where they happened.
    assert report["coverage_truncated"] == {"/crowded.html|default": {
        "overlapping-controls": [390], "small-target": [390], "unnamed-control": [390]}}


def test_a_configured_zero_is_respected(demo_site, tmp_path):
    url, site = demo_site
    tools = HEAD + "</style></head><body><div class=\"tools\"><button aria-label=\"Bold\">b</button>" \
        "<button aria-label=\"Italic\">i</button></div></body></html>"
    report = run(site, url, tmp_path, {"tools.html": tools}, [390], checks={"min_target_size": 0})
    assert [i for i in report["issues"] if i["check"] == "small-target"] == []
