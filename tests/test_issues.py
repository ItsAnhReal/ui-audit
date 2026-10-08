from ui_audit.issues import IssueSet, sweep_signature


def raw(check="horizontal-overflow", severity="P1", selector=".hero"):
    return {"check": check, "severity": severity, "selector": selector, "message": "m", "rect": {"x": 0}, "hints": {}}


def test_observations_fold_into_one_issue():
    issues = IssueSet()
    issues.observe(raw(severity="P2"), "/", "default", 900)
    issues.observe(raw(severity="P1"), "/", "default", 800)
    issues.observe(raw(severity="P2"), "/", "default", 800)
    (issue,) = issues.all()
    assert issue["widths"] == [800, 900]
    assert issue["severity"] == "P1"
    assert set(issue["rects"]) == {"800", "900"}


def test_state_duplicates_collapse_into_default():
    issues = IssueSet()
    issues.observe(raw("small-target", "P2", ".icon"), "/", "default", 390)
    issues.observe(raw("small-target", "P2", ".icon"), "/", "menu-open", 390)
    issues.observe(raw("clipped-content", "P2", ".drawer"), "/", "menu-open", 390)
    result = issues.all()
    assert [(i["state"], i["check"]) for i in result] == [("default", "small-target"), ("menu-open", "clipped-content")]
    assert result[0]["also_in_states"] == ["menu-open"]
    # Calling all() twice must not duplicate state names.
    assert issues.all()[0]["also_in_states"] == ["menu-open"]


def test_sweep_signature_ignores_width_independent_checks():
    result = {"issues": [raw(), raw("unnamed-control", "P2", "button"), raw("small-target", "P2", "a")]}
    assert sweep_signature(result) == frozenset({"horizontal-overflow|.hero"})
