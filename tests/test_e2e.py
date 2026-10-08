"""End-to-end runs against the deliberately broken demo app (see demo/README.md)."""

import pytest

from ui_audit import audit, verify
from ui_audit.config import from_dict

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("chromium_available")]


def config(url, site, out, **overrides):
    data = {
        "base_url": url, "project_root": str(site), "output": str(out), "settle_ms": 50,
        "routes": {"include": ["/", "/pricing.html", "/dashboard.html"], "discover": ["config"]},
        "viewports": {"sweep_step": 160, "max_captures": 12},
    }
    for key, value in overrides.items():
        if isinstance(value, dict):
            data.setdefault(key, {}).update(value)
        else:
            data[key] = value
    return from_dict(data)


def found(report, check, route, state="default"):
    return [i for i in report["issues"] if i["check"] == check and i["route"] == route and i["state"] == state]


def test_route_state_matrix_finds_every_planted_defect(demo_site, tmp_path):
    url, site = demo_site
    report = audit.run(config(url, site, tmp_path / "run"), log=lambda _: None)

    states = {(s["route"], s["id"]): s["status"] for s in report["states"]}
    assert states[("/", "expand-menu")] == "audited"
    assert states[("/dashboard.html", "tab-reports")] == "audited"
    assert states[("/dashboard.html", "details-advanced-filters")] == "audited"

    features = found(report, "horizontal-overflow", "/")
    assert features and min(features[0]["widths"]) == 800 and max(features[0]["widths"]) == 946
    assert found(report, "horizontal-overflow", "/", "expand-menu")
    assert found(report, "horizontal-overflow", "/dashboard.html", "details-advanced-filters")
    assert found(report, "clipped-content", "/dashboard.html", "tab-reports")
    assert len(found(report, "clipped-content", "/pricing.html")) == 3
    overlaps = found(report, "overlapping-controls", "/pricing.html")
    assert overlaps and all(768 <= w <= 1023 for i in overlaps for w in i["widths"])
    assert found(report, "small-target", "/") and found(report, "unnamed-control", "/")
    # The icon button shows in the menu state too, but is reported once.
    assert not found(report, "small-target", "/", "expand-menu")

    assert (tmp_path / "run" / "index.html").exists()
    assert (tmp_path / "run" / "semantic-review.md").exists()
    assert not found(report, "failed-resource", "/")  # favicon.ico 404 is ignored
    for issue in report["issues"]:
        assert issue["evidence"], issue["signature"]


def test_viewport_selection_keeps_breakpoints_and_anomalies_within_cap(demo_site, tmp_path):
    url, site = demo_site
    cfg = config(url, site, tmp_path / "run", routes={"include": ["/"]}, states={"auto": False},
                 viewports={"max_captures": 14})
    report = audit.run(cfg, log=lambda _: None)
    widths = sorted(c["width"] for c in report["captures"])
    assert len(widths) == 14  # the demo declares six breakpoints; the cap binds
    assert {389, 390, 391, 767, 768, 769} <= set(widths)
    assert {946, 947} & set(widths)  # the overflow's upper edge, found by refinement
    reasons = {c["width"]: c["reasons"] for c in report["captures"]}
    assert "anomaly" in reasons[946] or "anomaly" in reasons[947]


def test_fix_is_verified_by_targeted_rerun(demo_site, tmp_path):
    url, site = demo_site
    targeted = {"routes": {"include": ["/"]}, "states": {"auto": False}, "viewports": {"widths": [790, 800, 880, 946, 960]}}
    baseline = audit.run(config(url, site, tmp_path / "baseline", **targeted), log=lambda _: None)
    assert found(baseline, "horizontal-overflow", "/")

    css = site / "styles.css"
    css.write_text(css.read_text().replace("repeat(4, 220px)", "repeat(4, minmax(0, 1fr))"))
    current = audit.run(config(url, site, tmp_path / "fix", **targeted), log=lambda _: None)

    result = verify.compare(baseline, current)
    assert [i["check"] for i in result["fixed"]] == ["horizontal-overflow"]
    assert result["introduced"] == []
    diffs = verify.pixel_diffs(baseline, current, tmp_path / "baseline", tmp_path / "fix", tmp_path / "fix")
    changed = {d["width"]: d["changed_ratio"] for d in diffs}
    assert changed[880] > 0 and changed[790] == 0


LAYERED = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Layered</title><style>
body { margin: 0; font: 16px/1.5 sans-serif; }
.field { position: relative; width: 280px; margin: 24px; }
.field input { width: 100%; height: 44px; box-sizing: border-box; }
.field button { position: absolute; right: 6px; top: 8px; width: 32px; height: 40px; }
.legal { width: 170px; margin: 24px; }
.tight { margin: 24px; width: 200px; height: 20px; line-height: 28px; font-size: 14px; overflow: hidden; }
.row { position: relative; width: 240px; margin: 24px; }
.row a { display: block; height: 40px; line-height: 40px; }
.row button { position: absolute; right: 4px; top: 8px; width: 24px; height: 24px; }
main a { display: block; width: 200px; height: 44px; margin: 720px 24px 0; }
.bar { position: fixed; left: 0; right: 0; bottom: 0; padding: 16px; background: #eee; }
.bar button { width: 100%; height: 48px; }
</style></head><body>
<div class="field"><input aria-label="Password" type="password"><button aria-label="Show password">o</button></div>
<p class="legal">By continuing you accept the <a href="/pricing.html">terms of service agreement</a> and the
<a href="/dashboard.html">privacy and data policy</a>.</p>
<p class="tight">Leading only</p>
<div class="row"><a href="/dashboard.html">Menu</a><button aria-label="Show sub-items">v</button></div>
<main><a href="/pricing.html">See pricing</a></main>
<div class="bar"><button>Accept cookies</button></div>
</body></html>"""


def test_adornments_and_pinned_bars_are_not_overlaps(demo_site, tmp_path):
    url, site = demo_site
    (site / "layered.html").write_text(LAYERED)
    cfg = config(url, site, tmp_path / "run", routes={"include": ["/layered.html"]}, states={"auto": False},
                 viewports={"widths": [390, 1366]})
    report = audit.run(cfg, log=lambda _: None)
    assert report["coverage"]["/layered.html|default"] == [390, 1366]
    assert not found(report, "overlapping-controls", "/layered.html")
    # A line box taller than its clipping box loses leading, not letters.
    assert not found(report, "clipped-content", "/layered.html")


def test_not_found_and_repeated_routes_are_skipped(demo_site, tmp_path):
    url, site = demo_site
    (site / "plans.html").write_text((site / "pricing.html").read_text())
    included = ["/pricing.html", "/plans.html", "/missing.html"]
    cfg = config(url, site, tmp_path / "run", routes={"include": included}, states={"auto": False},
                 viewports={"widths": [390]})
    report = audit.run(cfg, log=lambda _: None)
    status = {r["path"]: r["status"] for r in report["routes"]}
    assert status == {"/pricing.html": "audited", "/plans.html": "skipped: same page as /pricing.html",
                      "/missing.html": "skipped: not found"}
    assert {i["route"] for i in report["issues"]} == {"/pricing.html"}
    assert report["stats"]["screenshot_bytes"] > 0

    # A targeted rerun audits what it is told to, so verify can trust its coverage.
    rerun = audit.run(cfg, only_routes=["/plans.html"], log=lambda _: None)
    assert [r["status"] for r in rerun["routes"]] == ["audited"]


CONSENT = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Consent</title><style>
body { margin: 0; font: 16px/1.5 sans-serif; }
main a { display: block; width: 220px; height: 44px; margin: 700px 24px 0; }
#banner { position: fixed; left: 0; right: 0; bottom: 0; padding: 16px; background: #eee; }
#banner button { height: 44px; }
</style></head><body>
<main><a href="/pricing.html">See pricing</a></main>
<div id="banner"><p>We use cookies to measure visits.</p>
<button id="all">Accept all</button> <button id="few">Only necessary</button></div>
<script>
const banner = document.getElementById("banner");
if (localStorage.getItem("consent")) banner.remove();
for (const id of ["all", "few"]) document.getElementById(id).onclick = () => { localStorage.setItem("consent", id); banner.remove(); };
</script></body></html>"""


def test_consent_banner_is_declined_once_and_setup_actions_run(demo_site, tmp_path):
    url, site = demo_site
    (site / "consent.html").write_text(CONSENT)
    cfg = config(url, site, tmp_path / "run", routes={"include": ["/pricing.html", "/consent.html"]},
                 states={"auto": False}, viewports={"widths": [390]}, setup=[{"click": "#no-such-button"}])
    report = audit.run(cfg, log=lambda _: None)
    # The banner only exists on the second route; the optional cookies are turned down, never accepted.
    assert report["consent_dismissed"] == "Only necessary"
    assert report["coverage"]["/consent.html|default"] == [390]
    assert report["errors"] == ["setup: action 1 could not run ({'click': '#no-such-button'})"]

    kept = audit.run(config(url, site, tmp_path / "kept", routes={"include": ["/consent.html"]},
                            states={"auto": False, "dismiss_consent": False}, viewports={"widths": [390]}),
                     log=lambda _: None)
    assert kept["consent_dismissed"] is None


def test_max_routes_counts_measured_routes_only(demo_site, tmp_path):
    url, site = demo_site
    included = ["/missing.html", "/pricing.html", "/dashboard.html"]
    cfg = config(url, site, tmp_path / "run", routes={"include": included, "max_routes": 1},
                 states={"auto": False}, viewports={"widths": [390]})
    report = audit.run(cfg, log=lambda _: None)
    assert {r["path"]: r["status"] for r in report["routes"]} == {
        "/missing.html": "skipped: not found", "/pricing.html": "audited"}
    assert report["truncated_routes"] == ["/dashboard.html"]


def test_saved_session_is_reused_by_the_audit(demo_site, tmp_path):
    from ui_audit import browser

    url, site = demo_site
    cfg = config(url, site, tmp_path / "run", routes={"include": ["/pricing.html"]}, states={"auto": False},
                 viewports={"widths": [390]})
    saved = browser.save_session(cfg, tmp_path / "auth" / "session.json", "/", wait=lambda: None, headless=True)
    assert saved.stat().st_mode & 0o777 == 0o600
    cfg.storage_state = str(saved)
    assert audit.run(cfg, log=lambda _: None)["coverage"]["/pricing.html|default"] == [390]


def test_pages_without_real_content_are_called_out(demo_site, tmp_path):
    url, site = demo_site
    page = "<!doctype html><html lang=en><head><meta charset=utf-8><title>t</title></head><body>{}</body></html>"
    (site / "gone.html").write_text(page.format("<h1>This menu is temporarily unavailable.</h1><p>" + "Try later. " * 30 + "</p>"))
    (site / "thin.html").write_text(page.format("<p>Coming soon.</p>"))
    (site / "busy.html").write_text(page.format('<main aria-busy="true"><p>' + "Loading the dashboard. " * 20 + "</p></main>"))
    (site / "busy-too.html").write_text((site / "busy.html").read_text())
    included = ["/pricing.html", "/gone.html", "/thin.html", "/busy.html", "/busy-too.html"]
    cfg = config(url, site, tmp_path / "run", routes={"include": included}, states={"auto": False},
                 viewports={"widths": [390]})
    report = audit.run(cfg, log=lambda _: None)
    content = {r["path"]: r["content"]["state"] for r in report["routes"]}
    # Two pages that are both still loading look alike; neither is skipped as a copy of the other.
    assert content == {"/pricing.html": "ok", "/gone.html": "error-like", "/thin.html": "thin",
                       "/busy.html": "loading", "/busy-too.html": "loading"}
    assert report["groups"] == [] or all(g["issue_ids"] for g in report["groups"])
