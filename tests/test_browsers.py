"""Auditing in more than one browser: config, issue merging, verify scope, and end-to-end runs."""

import pytest

from ui_audit import audit
from ui_audit.config import ConfigError, from_dict, parse_browsers
from ui_audit.issues import IssueSet, coverage_key
from ui_audit.verify import compare


def test_browsers_default_to_chromium_and_accept_safari_as_webkit():
    assert from_dict({}).browsers == ["chromium"]
    assert parse_browsers("Chromium, safari,firefox,webkit") == ["chromium", "webkit", "firefox"]
    assert from_dict({"browsers": ["firefox"]}).browsers == ["firefox"]
    with pytest.raises(ConfigError, match="unknown browser"):
        parse_browsers("edge")
    with pytest.raises(ConfigError, match="at least one"):
        from_dict({"browsers": []})


def test_one_defect_seen_in_several_browsers_is_one_issue():
    raw = {"check": "horizontal-overflow", "severity": "P1", "selector": ".card", "message": "m",
           "rect": {"x": 0, "y": 0, "width": 500, "height": 20}}
    issues = IssueSet()
    issues.observe(raw, "/", "default", 390)
    issues.observe(raw, "/", "default", 390, "webkit")
    issues.observe(raw, "/", "default", 400, "webkit")
    issues.observe({**raw, "selector": ".nav"}, "/", "default", 390, "webkit")
    found = {i["selector"]: i for i in issues.all()}
    assert found[".card"]["browsers"] == ["chromium", "webkit"]
    assert found[".card"]["widths"] == [390, 400]
    assert found[".card"]["widths_by_browser"] == {"chromium": [390], "webkit": [390, 400]}
    assert set(found[".card"]["rects"]) == {"390", "390@webkit", "400@webkit"}
    assert found[".nav"]["browsers"] == ["webkit"]
    assert found[".card"]["signature"] == "horizontal-overflow|/|default|.card"  # unchanged by browsers


def _issue(selector, browsers=None):
    issue = {"id": selector, "signature": f"text-spill|/|default|{selector}", "check": "text-spill", "severity": "P2",
             "route": "/", "state": "default", "selector": selector, "message": "m", "widths": [390],
             "origin": "deterministic"}
    if browsers:
        issue["browsers"] = browsers
    return issue


def test_verify_counts_a_fix_only_where_every_affected_browser_was_looked_at():
    baseline = {"issues": [_issue(".both", ["chromium", "webkit"]), _issue(".safari", ["webkit"]), _issue(".old")],
                "captures": []}
    chromium_only = {"issues": [], "captures": [], "coverage": {coverage_key("/", "default"): [390]}}
    result = compare(baseline, chromium_only)
    assert [i["selector"] for i in result["fixed"]] == [".old"]
    assert result["out_of_scope"] == 2

    both = {"issues": [], "captures": [], "coverage": {coverage_key("/", "default"): [390],
                                                       coverage_key("/", "default", "webkit"): [390]}}
    assert {i["selector"] for i in compare(baseline, both)["fixed"]} == {".both", ".safari", ".old"}


# A box that is only too wide where the user agent says Firefox: the kind of browser-specific
# code path (UA sniffing, vendor CSS) that only shows up when the audit runs in that browser.
FIREFOX_ONLY = """<!doctype html>
<!-- An audit in Chromium and Firefox must report the overflow of .promo in Firefox only. -->
<html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<style>body { margin: 0; font: 16px sans-serif; } .promo { padding: 8px; } .ff .promo { width: 900px; }</style>
<script>if (navigator.userAgent.includes("Firefox")) document.documentElement.classList.add("ff");</script>
</head><body><main><h1>Offers</h1><p class="promo">Spring sale on every plan, this week only.</p></main></body></html>
"""


def _available(engine):
    try:
        from playwright.sync_api import sync_playwright

        from ui_audit.browser import launch

        with sync_playwright() as playwright:
            launch(playwright, engine=engine).close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"{engine} unavailable: {str(exc).splitlines()[0]}")


def _config(url, site, out, browsers, include):
    return from_dict({
        "base_url": url, "project_root": str(site), "output": str(out), "settle_ms": 50, "browsers": browsers,
        "routes": {"include": include, "discover": ["config"]},
        "viewports": {"sweep_step": 160, "max_captures": 6},
    })


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
@pytest.mark.parametrize("engine", ["webkit", "firefox"])
def test_demo_defects_show_up_in_the_other_browsers_too(demo_site, tmp_path, engine):
    _available(engine)
    url, site = demo_site
    report = audit.run(_config(url, site, tmp_path / "run", ["chromium", engine], ["/", "/pricing.html"]),
                       log=lambda _: None)
    assert report["browsers"] == ["chromium", engine]
    assert not [e for e in report["errors"] if engine in e.lower()], report["errors"]
    overflow = [i for i in report["issues"] if i["check"] == "horizontal-overflow" and i["route"] == "/"
                and i["state"] == "default"]
    assert overflow and overflow[0]["browsers"] == ["chromium", engine]
    assert len([i for i in report["issues"] if i["check"] == "clipped-content" and i["route"] == "/pricing.html"]) == 3
    assert coverage_key("/", "default", engine) in report["coverage"]
    shots = {c["browser"] for c in report["captures"]}
    assert shots == {"chromium", engine}
    assert all(c["file"].endswith(f"__{engine}.png") for c in report["captures"] if c["browser"] == engine)
    states = {(s["route"], s["id"]): s for s in report["states"]}
    assert states[("/", "expand-menu")]["browsers"] == {engine: "audited"}
    for issue in report["issues"]:
        assert issue["evidence"], issue["signature"]


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_a_defect_in_one_browser_is_marked_as_such(demo_site, tmp_path):
    _available("firefox")
    url, site = demo_site
    (site / "offers.html").write_text(FIREFOX_ONLY, encoding="utf-8")
    report = audit.run(_config(url, site, tmp_path / "run", ["chromium", "firefox"], ["/offers.html"]),
                       log=lambda _: None)
    promo = [i for i in report["issues"] if i["check"] in ("horizontal-overflow", "offscreen-content")]
    assert promo and all(i["browsers"] == ["firefox"] for i in promo)
    evidence = {e for i in promo for e in i["evidence"]}
    assert evidence and all("__firefox" in e for e in evidence)


def test_verify_looks_at_the_widths_each_browser_showed_the_issue_at():
    baseline = {"issues": [{**_issue(".x", ["chromium", "webkit"]), "widths": [390, 1280],
                            "widths_by_browser": {"chromium": [390], "webkit": [1280]}}], "captures": []}
    swapped = {"issues": [], "captures": [], "coverage": {coverage_key("/", "default"): [1280],
                                                          coverage_key("/", "default", "webkit"): [390]}}
    assert compare(baseline, swapped)["fixed"] == []
    matching = {"issues": [], "captures": [], "coverage": {coverage_key("/", "default"): [390],
                                                           coverage_key("/", "default", "webkit"): [1280]}}
    assert [i["selector"] for i in compare(baseline, matching)["fixed"]] == [".x"]


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_a_browser_that_did_not_start_is_not_counted_as_audited(demo_site, tmp_path, monkeypatch):
    from ui_audit import browser

    real = browser.launch

    def launch(playwright, executable_path="", headless=True, engine="chromium"):
        if engine != "chromium":
            raise RuntimeError("Firefox is not installed")
        return real(playwright, executable_path, headless)

    monkeypatch.setattr(browser, "launch", launch)
    url, site = demo_site
    report = audit.run(_config(url, site, tmp_path / "run", ["chromium", "firefox"], ["/pricing.html"]),
                       log=lambda _: None)
    assert report["browsers"] == ["chromium"]
    assert any(e.startswith("Firefox:") for e in report["errors"])
    assert report["issues"] and all(i["browsers"] == ["chromium"] for i in report["issues"])
