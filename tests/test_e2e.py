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
