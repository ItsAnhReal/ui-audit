import json

from ui_audit.verify import compare, render_markdown


def issue(sig_selector, route="/", state="default", widths=(800,), severity="P1", origin="deterministic"):
    sig = f"horizontal-overflow|{route}|{state}|{sig_selector}"
    return {"id": sig_selector, "signature": sig, "check": "horizontal-overflow", "severity": severity, "route": route,
            "state": state, "selector": sig_selector, "message": "m", "widths": list(widths), "origin": origin}


def test_fixed_introduced_persistent_and_scope():
    baseline = {"issues": [
        issue(".a", widths=(800, 900)),            # fixed: probed at 800 in the rerun
        issue(".b", widths=(800,)),                 # persistent
        issue(".c", widths=(1440,)),                # same route, width not probed -> out of scope
        issue(".d", route="/other"),                # route not rerun -> out of scope
    ], "captures": []}
    current = {"issues": [issue(".b"), issue(".new", severity="P2")], "captures": [],
               "coverage": {"/|default": [799, 800, 801]}}
    result = compare(baseline, current)
    assert [i["selector"] for i in result["fixed"]] == [".a"]
    assert [i["selector"] for i in result["persistent"]] == [".b"]
    assert [i["selector"] for i in result["introduced"]] == [".new"]
    assert result["out_of_scope"] == 2
    text = render_markdown(result)
    assert "Fixed: **1**" in text and "Introduced: **1**" in text


def test_agent_findings_need_a_new_review_before_counting_as_fixed():
    baseline = {"issues": [issue(".x", widths=(1440,), origin="agent")], "captures": []}
    rerun = {"issues": [], "captures": [], "coverage": {"/|default": [1440]}}
    result = compare(baseline, rerun)
    assert result["fixed"] == [] and [i["selector"] for i in result["needs_review"]] == [".x"]

    reviewed = {"issues": [issue(".other", origin="agent")], "captures": [], "coverage": {"/|default": [1440]}}
    result = compare(baseline, reviewed)
    assert [i["selector"] for i in result["fixed"]] == [".x"]


def test_accepted_findings_are_left_out_on_either_side():
    accepted = {**issue(".ok"), "accepted": {"reason": "intentional"}}
    baseline = {"issues": [accepted], "captures": []}
    rerun = {"issues": [], "captures": [], "coverage": {"/|default": [800]}}
    result = compare(baseline, rerun)
    assert result["fixed"] == [] and result["persistent"] == [] and result["introduced"] == []


def test_a_finding_its_check_was_capped_for_is_not_fixed():
    baseline = {"issues": [issue(".a", widths=(800,)), issue(".b", widths=(800, 900)), issue(".c", widths=(800,))],
                "captures": [], "coverage": {"/|default": [800, 900]}}
    current = {"issues": [], "captures": [], "coverage": {"/|default": [800, 900]},
               # 800px reported only the first findings of horizontal-overflow; 900px reported all of them.
               "coverage_truncated": {"/|default": {"horizontal-overflow": [800]}}}
    result = compare(baseline, current)
    assert [i["selector"] for i in result["fixed"]] == [".b"]
    assert result["out_of_scope"] == 2
    # Another check capped at the same width says nothing about this one.
    current["coverage_truncated"] = {"/|default": {"small-target": [800]}}
    assert len(compare(baseline, current)["fixed"]) == 3


def test_capped_checks_are_kept_per_browser():
    found = {**issue(".a"), "browsers": ["chromium", "webkit"], "widths_by_browser": {"chromium": [800], "webkit": [800]}}
    baseline = {"issues": [found], "captures": [], "coverage": {"/|default": [800], "/|default|webkit": [800]}}
    current = {"issues": [], "captures": [], "coverage": {"/|default": [800], "/|default|webkit": [800]},
               "coverage_truncated": {"/|default|webkit": {"horizontal-overflow": [800]}}}
    assert compare(baseline, current)["fixed"] == []
    current["coverage_truncated"] = {"/|default|firefox": {"horizontal-overflow": [800]}}
    assert len(compare(baseline, current)["fixed"]) == 1


def test_findings_on_routes_and_states_the_baseline_did_not_audit_are_new_scope():
    baseline = {"issues": [], "captures": [], "coverage": {"/|default": [800]}}
    current = {"issues": [issue(".new"), issue(".route", route="/added"), issue(".menu", state="menu-open")],
               "captures": [], "coverage": {"/|default": [800], "/added|default": [800], "/|menu-open": [800]}}
    result = compare(baseline, current)
    assert [i["selector"] for i in result["introduced"]] == [".new"]
    assert sorted(i["selector"] for i in result["new_scope"]) == [".menu", ".route"]
    text = render_markdown(result)
    assert "On routes/states the baseline did not audit: 2" in text and "## New scope (not in the baseline)" in text
    # A baseline that records no coverage cannot tell: everything new stays introduced.
    del baseline["coverage"]
    assert len(compare(baseline, current)["introduced"]) == 3


def test_verify_exits_on_introduced_but_not_on_new_scope(tmp_path):
    from ui_audit.cli import main

    def write(name, report):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "report.json").write_text(json.dumps(report))
        return str(folder)

    base = write("base", {"issues": [], "captures": [], "coverage": {"/|default": [800]}})
    added = write("added", {"issues": [issue(".x", route="/added")], "captures": [], "coverage": {"/added|default": [800]}})
    assert main(["verify", base, added]) == 0
    assert json.loads((tmp_path / "added" / "verify.json").read_text())["new_scope"][0]["selector"] == ".x"
    broke = write("broke", {"issues": [issue(".x")], "captures": [], "coverage": {"/|default": [800]}})
    assert main(["verify", base, broke]) == 1
