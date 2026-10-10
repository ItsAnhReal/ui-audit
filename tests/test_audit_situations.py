"""Situations real apps (VibeSpace, Docusaurus, Astro, the Bootstrap examples) showed the audit
getting wrong, each on its own small page."""

from pathlib import Path

import pytest

from ui_audit import audit
from ui_audit.config import from_dict

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("chromium_available")]

HEAD = '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title><style>body { margin: 0; font: 16px/1.5 sans-serif; }'

# A menu button that only shows from 1024px, found at 1280px. Opening its sheet logs an error.
DESKTOP_SHEET = HEAD + """
.desktop-bar { display: none; } @media (min-width: 1024px) { .desktop-bar { display: block; } }
</style></head><body>
<p>Profile page with enough text to read as a real page, not an empty one, for the content check.</p>
<div class="desktop-bar"><button id="join" aria-expanded="false" aria-label="Join Example">Join</button></div>
<div id="sheet" class="join-sheet" role="dialog" hidden><h2>Claim your space on Example</h2></div>
<script>
document.getElementById("join").addEventListener("click", () => {
  document.getElementById("sheet").hidden = false;
  document.getElementById("join").setAttribute("aria-expanded", "true");
  console.error("DialogContent requires a DialogTitle");
});
</script></body></html>"""

# Two fixed 156px columns and a 12px gap: 324px, 2px wider than a 320px phone on each side.
NARROW_GRID = HEAD + """
.tiles { display: grid; grid-template-columns: repeat(2, 156px); gap: 12px; justify-content: center; }
.tiles > div { height: 156px; background: #eee; }
</style></head><body><div class="tiles"><div>One</div><div>Two</div></div></body></html>"""

# One section never fades in; the stacked slides of a fading carousel are hidden on purpose.
NEVER_SHOWN = HEAD + """
.ghost { opacity: 0; } .slides { position: relative; height: 80px; }
.slide { position: absolute; inset: 0; opacity: 0; } .slide.on { opacity: 1; }
</style></head><body>
<section><h1>Welcome</h1><p>Everything above the fold shows up as it should on this page.</p></section>
<section class="ghost"><h2>Benefits</h2><p>This whole section waits for an animation that never runs.</p></section>
<div class="slides"><div class="slide on">First slide with a quote in it</div><div class="slide">Second slide with a quote in it</div></div>
</body></html>"""


def run(site, url, tmp_path, pages, widths, auto_states=False):
    for name, html in pages.items():
        (site / name).write_text(html)
    cfg = from_dict({
        "base_url": url, "project_root": str(site), "output": str(tmp_path / "run"), "settle_ms": 50,
        "routes": {"include": [f"/{name}" for name in pages], "discover": ["config"], "dedupe": False},
        "states": {"auto": auto_states}, "viewports": {"widths": widths},
    })
    return audit.run(cfg, log=lambda _: None)


def test_a_desktop_only_state_is_opened_where_its_button_shows(demo_site, tmp_path):
    url, site = demo_site
    report = run(site, url, tmp_path, {"sheet.html": DESKTOP_SHEET}, [390, 800, 1100, 1366], auto_states=True)
    state = next(s for s in report["states"] if s["kind"] == "auto")
    assert state["applies_to"] == "wide" and state["status"] == "audited"
    assert report["coverage"][f"/sheet.html|{state['id']}"] == [1100, 1366]
    error = next(i for i in report["issues"] if i["check"] == "console-error")
    assert error["state"] == state["id"]
    # The opened sheet is in this file; before, a console error had no file hint at all.
    assert error["source_candidates"] and error["source_candidates"][0]["file"] == "sheet.html"


def test_a_two_pixel_overflow_only_on_the_narrowest_phones_is_minor(demo_site, tmp_path):
    url, site = demo_site
    report = run(site, url, tmp_path, {"grid.html": NARROW_GRID}, [320, 390])
    issues = [i for i in report["issues"] if i["route"] == "/grid.html"]
    assert [(i["check"], i["severity"], i["widths"]) for i in issues] == [("horizontal-overflow", "P3", [320])]
    assert issues[0]["selector"].endswith("div.tiles")  # the grid, not each tile in it
    assert issues[0]["message"].startswith("Grid columns need 324px but the grid is 320px wide")


def test_a_section_that_never_fades_in_makes_the_page_doubtful(demo_site, tmp_path):
    url, site = demo_site
    report = run(site, url, tmp_path, {"ghost.html": NEVER_SHOWN}, [1366])
    route = next(r for r in report["routes"] if r["path"] == "/ghost.html")
    assert route["content"] == {"state": "hidden", "detail": "1 section stays invisible"}


FEED = '<?xml version="1.0"?><rss version="2.0"><channel><title>Blog</title><link>https://example.com/</link></channel></rss>'

# Static progress bars, as a skills list or a cheatsheet shows them: content, not a page still loading.
METERS = HEAD + """</style></head><body><h1>Skills</h1>
<p>Profile page with enough text to read as a real page, not an empty one, for the content check.</p>
<p>Below are the skills this person rated themselves on, each as a bar from zero to one hundred.
The bars are drawn once and stay as they are; nothing on this page is still loading.</p>
<div role="progressbar" aria-valuenow="70" aria-valuemin="0" aria-valuemax="100" style="height:8px;background:#ddd">
<div style="width:70%;height:8px;background:#36c"></div></div></body></html>"""


def test_a_feed_is_skipped_and_a_progress_meter_is_content(demo_site, tmp_path):
    url, site = demo_site
    report = run(site, url, tmp_path, {"rss.xml": FEED, "meters.html": METERS}, [390])
    routes = {r["path"]: r for r in report["routes"]}
    # The test server takes the type from the platform's registry: application/xml, text/xml on Windows.
    assert routes["/rss.xml"]["status"] in ("skipped: not a web page (application/xml)",
                                            "skipped: not a web page (text/xml)")
    assert routes["/meters.html"]["content"]["state"] == "ok"
    assert not [i for i in report["issues"] if i["route"] == "/rss.xml"]


def test_a_screen_reader_label_that_escapes_its_row_is_named(demo_site, tmp_path):
    url, site = demo_site
    page = (Path(__file__).parent / "cases" / "escaped-sr-only.html").read_text()
    report = run(site, url, tmp_path, {"sr.html": page}, [390])
    issue = next(i for i in report["issues"] if i["route"] == "/sr.html")
    assert issue["selector"].endswith("span.sr-only")
    assert issue["message"].startswith('Screen-reader-only text "opens the third card"')
