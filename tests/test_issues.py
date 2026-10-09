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


def test_groups_fold_one_component_across_routes():
    from ui_audit.issues import assign_groups

    def issue(n, route, check="horizontal-overflow", line=376, selector="div.card", reasons=("runtime source",)):
        return {"id": f"i{n}", "check": check, "severity": "P1" if n == 2 else "P2", "route": route, "state": "default",
                "selector": selector, "message": "m", "widths": [320 + n, 400],
                "source_candidates": [{"file": "src/Card.tsx", "line": line, "reasons": list(reasons)}]}

    issues = [issue(1, "/orders"), issue(2, "/website"), issue(3, "/orders", line=341),
              issue(4, "/a", check="small-target", selector="nav > a.link:nth-of-type(2)", reasons=("class link",)),
              issue(5, "/b", check="small-target", selector="footer > a.link:nth-of-type(7)", reasons=("class link",))]
    groups = assign_groups(issues)
    assert [(g["count"], g["routes"], g["severity"]) for g in groups] == [
        (2, ["/orders", "/website"], "P1"), (2, ["/a", "/b"], "P2"), (1, ["/orders"], "P2")]
    assert groups[0]["source"] == {"file": "src/Card.tsx", "line": 376} and groups[0]["widths"] == [321, 400]
    assert groups[1]["source"] is None  # a guessed file is not an identity; the element's own classes are
    assert issues[0]["group"] == issues[1]["group"] != issues[2]["group"]
