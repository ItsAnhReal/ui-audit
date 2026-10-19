"""What the probe can see: open shadow roots, same-origin iframes, right-to-left pages, vertical
defects, breakpoints in every kind of stylesheet and controls that open dialogs or hover menus.
The planted defects of the demo's widgets and RTL pages are asserted in test_e2e.py."""

import pytest

from ui_audit.browser import PROBE_JS, launch

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("chromium_available")]


@pytest.fixture(scope="module")
def browser_context():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch(playwright)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.add_init_script(PROBE_JS)
        yield context
        browser.close()


@pytest.fixture
def page(browser_context):
    page = browser_context.new_page()
    yield page
    page.close()


def probe(page, html, width=390):
    page.set_viewport_size({"width": width, "height": 844})
    page.set_content(html)
    page.wait_for_timeout(50)  # custom elements upgrade, iframes load
    return page.evaluate("() => window.__uiAudit.probe({})")


def by_check(result):
    found = {}
    for issue in result["issues"]:
        found.setdefault(issue["check"], []).append(issue)
    return found


COMPONENTS = """<!doctype html><html><body style="margin: 0; font: 16px/1.5 sans-serif">
<x-card class="pro"></x-card>
<x-box><span>A slotted label that is far too long</span></x-box>
<script>
customElements.define("x-card", class extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" }).innerHTML = `<style>.price { display: block; width: 60px; overflow: hidden; white-space: nowrap; }</style>
      <span class="price">$1,234,567.00 per month</span><button aria-expanded="false">Details</button><button class="icon"></button>`;
  }
});
customElements.define("x-box", class extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" }).innerHTML = `<div class="frame" style="width: 80px; overflow: hidden; white-space: nowrap"><slot></slot></div>`;
  }
});
</script></body></html>"""


def test_elements_in_open_shadow_roots_are_measured_and_named_through_their_host(page):
    found = by_check(probe(page, COMPONENTS))
    assert sorted(i["selector"] for i in found["clipped-content"]) == ["x-box >> div.frame", "x-card.pro >> span.price"]
    assert "A slotted label" in next(i["message"] for i in found["clipped-content"] if i["selector"].startswith("x-box"))
    assert [i["selector"] for i in found["unnamed-control"]] == ["x-card.pro >> button.icon"]
    # Playwright's own selectors look inside shadow roots too, so they find the same element.
    for selector in ("x-card.pro >> span.price", "x-box >> div.frame"):
        assert page.locator(selector).count() == 1
    assert page.evaluate("s => window.__uiAudit.isTriggerVisible(s)", "x-card.pro >> span.price")
    assert page.evaluate("items => window.__uiAudit.annotate(items)",
                         [{"selector": "x-card.pro >> span.price", "severity": "P2", "check": "clipped-content", "index": 1}]) == 1
    page.evaluate("() => window.__uiAudit.clearAnnotations()")
    # A disclosure inside a component is a state candidate that Playwright can click.
    [candidate] = page.evaluate("() => window.__uiAudit.stateCandidates({})")
    assert candidate["selector"] == "x-card.pro >> button:nth-of-type(1)" and candidate["kind"] == "expand"
    page.locator(candidate["selector"]).click()
    # The page's text, which tells pages apart, includes what the components show.
    shown = "A slotted label that is far too long" + "$1,234,567.00 per month"
    assert int(page.evaluate("() => window.__uiAudit.pageFingerprint()").split(":")[0]) >= len(shown)


FRAMED = """<!doctype html><html><body style="margin: 0">
<p style="height: 40px; margin: 0">Outer page</p>
<iframe class="embed" style="display: block; margin-left: 30px; width: 300px; height: 120px; border: 2px solid"
  srcdoc="<!doctype html><body style='margin: 10px'><div class=label style='width: 80px; overflow: hidden; white-space: nowrap'>A very long clipped label</div></body>"></iframe>
<iframe class="other" style="width: 200px; height: 60px" src="data:text/html,<div style='width:40px;overflow:hidden;white-space:nowrap'>Another origin, not measured</div>"></iframe>
</body></html>"""


def test_same_origin_iframes_are_measured_and_placed_on_the_page(page):
    page.set_content(FRAMED)
    page.frame_locator("iframe.embed").locator("div.label").wait_for()
    result = page.evaluate("() => window.__uiAudit.probe({})")
    [clipped] = result["issues"]
    assert clipped["check"] == "clipped-content"
    assert clipped["selector"] == "iframe.embed >> internal:control=enter-frame >> div.label"
    # The frame's content box starts 32px in (margin and border) and 42px down; the label 10px further.
    assert (clipped["rect"]["x"], clipped["rect"]["y"]) == (42, 52)
    assert page.locator(clipped["selector"]).count() == 1
    assert page.evaluate("items => window.__uiAudit.annotate(items)",
                         [{"selector": clipped["selector"], "severity": "P2", "check": "clipped-content", "index": 1}]) == 1


def test_a_right_to_left_page_overflows_to_the_left(page):
    rtl = '<!doctype html><html dir="rtl"><body style="margin: 0"><p>نص</p>{}</body></html>'
    found = by_check(probe(page, rtl.format('<div class="wide" style="width: 600px">عريض جدا</div>')))
    [overflow] = found["horizontal-overflow"]
    assert overflow["selector"] == "div.wide" and "210px past the left edge" in overflow["message"]
    assert "fixed width of 600px" in overflow["message"]
    # Past the right edge of a right-to-left page is out of reach, as past the left edge is on any other.
    found = by_check(probe(page, rtl.format('<div class="pushed" style="margin-right: -80px">مزاح</div>')))
    assert [i["selector"] for i in found["offscreen-content"]] == ["div.pushed"] and "horizontal-overflow" not in found


DIALOG = """<!doctype html><html><body style="margin: 0">
<div role="dialog" aria-modal="true" aria-label="Terms" style="position: fixed; top: 20px; left: 20px; right: 20px; background: #fff; {style}">
<div style="height: 1200px">Long terms</div><button>Accept terms</button></div>{after}
</body></html>"""


def test_a_fixed_dialog_taller_than_the_screen_is_reported_unless_something_scrolls_it(page):
    [tall] = by_check(probe(page, DIALOG.format(style="", after="")))["dialog-too-tall"]
    assert tall["severity"] == "P1" and '"Accept terms"' in tall["message"] and "844px high viewport" in tall["message"]
    assert "dialog-too-tall" not in by_check(probe(page, DIALOG.format(style="max-height: 90vh; overflow-y: auto", after="")))
    overlay = ('<div style="position: fixed; inset: 0; overflow-y: auto">'
               '<div role="dialog" style="margin: 20px; background: #fff"><div style="height: 1200px">Long</div><button>OK</button></div></div>')
    assert "dialog-too-tall" not in by_check(probe(page, overlay))


def test_breakpoints_come_from_every_kind_of_query_and_stylesheet(page):
    page.set_content("""<!doctype html><html><head><style>
@media (600px <= width) { p { color: red } }
@media (width < 40em) { p { color: blue } }
@media (400px < width < 900px) { p { color: green } }
@container (min-width: 500px) { p { color: gray } }
@container card (inline-size > 30rem) { p { color: gray } }
@import url("data:text/css,@media (min-width: 1100px) { p { color: red } }");
</style></head><body><p>Text</p><x-el></x-el><script>
customElements.define("x-el", class extends HTMLElement {
  constructor() {
    super();
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = "<style>@media (max-width: 700px) { b { color: red } }</style><b>x</b>";
    const sheet = new CSSStyleSheet();
    sheet.replaceSync("@media (min-width: 1300px) { b { color: blue } }");
    root.adoptedStyleSheets = [sheet];
  }
});
</script></body></html>""")
    assert page.evaluate("() => window.__uiAudit.breakpoints()") == [400, 480, 500, 600, 640, 700, 900, 1300]


CANDIDATES = """<!doctype html><html><body>
<nav><ul>
  <li class="plain"><a href="/">Home</a></li>
  <li class="menu"><a href="#r">Resources</a><ul class="sub" style="display: none"><li><a href="/docs">Docs</a></li></ul></li>
  <li class="open"><a href="#o">Open</a><ul><li><a href="/x">Always shown</a></li></ul></li>
</ul></nav>
<button class="terms" aria-controls="terms">View terms</button>
<button class="filters" aria-controls="filters">Filters</button>
<button class="tip" popovertarget="tip">Tip</button>
<a class="bs" href="#signup" data-bs-toggle="modal">Sign up</a>
<button class="danger" aria-controls="confirm">Delete project</button>
<div id="terms" role="dialog" hidden>Terms</div>
<div id="confirm" role="dialog" hidden>Sure?</div>
<div id="filters" hidden>Filters</div>
<div id="tip" popover>Tip text</div>
</body></html>"""


def test_dialog_openers_and_hover_menus_are_state_candidates(page):
    page.set_content(CANDIDATES)
    found = {c["selector"]: (c["kind"], c.get("action", "click")) for c in page.evaluate("() => window.__uiAudit.stateCandidates({})")}
    assert found == {"button.terms": ("dialog", "click"), "button.tip": ("dialog", "click"), "a.bs": ("dialog", "click"),
                     "li.menu": ("hover", "hover")}
