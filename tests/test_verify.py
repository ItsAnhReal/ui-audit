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
