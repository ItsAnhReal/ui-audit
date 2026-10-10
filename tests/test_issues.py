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
    result = {"issues": [raw(), raw("unnamed-control", "P2", "button"), raw("small-target", "P2", "a"),
                         raw("tiny-text", "P3", "p"), raw("small-input-font", "P3", "input"), raw("broken-image", "P2", "img")]}
    assert sweep_signature(result) == frozenset({"horizontal-overflow|.hero"})


def test_overflow_cause_is_kept_without_changing_the_signature():
    issues = IssueSet()
    issues.observe(raw(), "/", "default", 800)
    issues.observe({**raw(), "cause": "transform moves it 80px to the right"}, "/", "default", 900)
    (issue,) = issues.all()
    assert issue["cause"] == "transform moves it 80px to the right"
    assert issue["signature"] == "horizontal-overflow|/|default|.hero"


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


def test_an_overflow_only_below_common_phone_widths_is_rated_milder():
    issues = IssueSet()
    issues.observe(raw(severity="P1"), "/", "default", 320)
    issues.observe(raw(severity="P1", selector=".wide"), "/", "default", 320)
    issues.observe(raw(severity="P1", selector=".wide"), "/", "default", 390)
    issues.observe(raw("clipped-content", "P2", ".box"), "/", "default", 320)
    rated = {i["selector"]: i["severity"] for i in issues.all()}
    assert rated == {".hero": "P2", ".wide": "P1", ".box": "P2"}


def test_page_overflow_and_the_cut_off_edge_of_one_element_are_one_group():
    from ui_audit.issues import assign_groups

    source = [{"file": "src/Tile.tsx", "line": 41, "reasons": ["runtime source"]}]
    issues = [{"id": f"i{n}", "check": check, "severity": "P2", "route": "/demo", "state": "default",
               "selector": "div.tile", "message": "m", "widths": [320], "source_candidates": source}
              for n, check in enumerate(["horizontal-overflow", "offscreen-content", "offscreen-control"])]
    assert len(assign_groups(issues)) == 1


def test_runtime_signatures_leave_out_what_changes_between_runs():
    from ui_audit.issues import runtime_key

    first = IssueSet().runtime("console-error", "/", "default",
                               "TypeError: x is undefined at http://localhost:5173/assets/index-a1B2c3D4.js?v=17:1:23456", 390)
    second = IssueSet().runtime("console-error", "/", "default",
                                "TypeError: x is undefined at http://localhost:5173/assets/index-Zz9Yy8Xx.js?v=18:1:23999", 390)
    assert first["signature"] == second["signature"] == "console-error|/|default|TypeError: x is undefined at http://localhost:5173/assets/index.js"
    assert first["message"].endswith("index-a1B2c3D4.js?v=17:1:23456")  # the raw text stays readable
    assert runtime_key("http://localhost:3000/api/cart?ts=1696851234567#top (404)") == "http://localhost:3000/api/cart (404)"
    assert runtime_key("/static/js/main.3f2a1b9c.chunk.js (net::ERR_FAILED)") == "/static/js/main.chunk.js (net::ERR_FAILED)"
    assert runtime_key("Request 550e8400-e29b-41d4-a716-446655440000 at 2026-10-09T12:34:56.789Z, order 1234567") == \
        "Request <id> at <time>, order <n>"
    # Plain words, small numbers and status codes are what tells errors apart; they stay.
    assert runtime_key("Failed to load bootstrap.bundle.js: 404 at line 42") == "Failed to load bootstrap.bundle.js: 404 at line 42"


def test_auto_state_ids_leave_out_counts():
    from ui_audit.states import auto_state_id

    assert auto_state_id("expand", "Cart (3)") == auto_state_id("expand", "Cart (12)") == "expand-cart"
    assert auto_state_id("popup", "3 new  messages") == "popup-new-messages"
    assert auto_state_id("expand", "12") == "expand-expand"
    # Two triggers that read the same are told apart by their selector, not by discovery order.
    assert auto_state_id("expand", "More", "nav > button.more:nth-of-type(2)") == "expand-more-button-more"
