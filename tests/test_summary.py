import json

from agent_fixtures import make_run

from ui_audit import summary
from ui_audit.cli import main


def test_summary_is_compact_and_groups_by_cause(tmp_path):
    run, data = make_run(tmp_path)
    s = summary.summary(data, run)
    assert s["counts"] == {"P1": 2, "P2": 2, "P3": 0}
    assert s["report"] == str(run / "report.json") and s["routes"] == {"audited": 3, "skipped": 1}
    # The two overflowing cards render from one component: one cause, worst first.
    first = s["groups"][0]
    assert first["check"] == "horizontal-overflow" and first["count"] == 2 and first["routes"] == ["/pricing", "/"]
    assert first["widths"] == [320, 480] and first["source"] == "src/Card.tsx:12"
    assert first["example"]["selector"] == "main > div.card" and first["example"]["route"] == "/pricing"
    # The screenshot that boxes the element, annotated.
    assert first["screenshot"] == str(run / "shots/pricing__default__390__annotated.png")
    runtime = next(g for g in s["groups"] if g["check"] == "console-error")
    assert runtime["screenshot"] is None
    assert s["check_by_hand"] == [{"route": "/account", "state": "login", "detail": "looks like a sign-in page"}]
    assert s["truncated_routes"] == ["/extra"] and s["errors"] == ["/account: timed out"]
    assert s["next"].endswith(f"--group {first['id']} --json")
    assert len(json.dumps(s)) < 4000


def test_summary_caps_groups_and_leaves_out_accepted_causes(tmp_path):
    run, data = make_run(tmp_path, extra_groups=40)
    s = summary.summary(data, run, max_groups=30)
    assert len(s["groups"]) == 30 and s["more_groups"] == 43 - 30
    clipped = next(i for i in data["issues"] if i["check"] == "clipped-content")
    clipped["accepted"] = {"reason": "decorative"}
    s = summary.summary(data, run, max_groups=100)
    assert all(g["check"] != "clipped-content" for g in s["groups"]) and s["accepted"] == 1


def test_detail_lists_every_finding_with_sources_and_commands(tmp_path):
    run, data = make_run(tmp_path)
    group = summary.summary(data, run)["groups"][0]["id"]
    d = summary.detail(data, run, group)
    assert d["kind"] == "group" and d["count"] == 2 and len(d["issues"]) == 2
    assert d["issues"][0]["source_candidates"][0] == {"file": "src/Card.tsx", "line": 12, "reasons": ["runtime source"]}
    assert d["issues"][0]["evidence"] == [str(run / "shots/pricing__default__390__annotated.png")]
    # The viewer's re-check: edges, one pixel outside, the middle; default state only so no state discovery.
    assert d["recheck"] == (f"ui-audit audit --like {run} --route /pricing --route / --width 320,360,361,390,480,481 "
                            f"--no-states --output {run}-recheck\nui-audit verify {run} {run}-recheck")
    assert d["accept"].startswith(f"ui-audit accept {run} {group} ")
    issue = summary.detail(data, run, d["issues"][1]["id"])
    assert issue["kind"] == "issue" and issue["count"] == 1
    paged = summary.detail(data, run, group, offset=1, limit=1)
    assert len(paged["issues"]) == 1 and paged["more"] == 0 and paged["offset"] == 1
    text = summary.render_detail(d)
    assert "src/Card.tsx:12" in text and "ui-audit verify" in text


def test_verify_summary_is_brief():
    issue = {"id": "a", "severity": "P2", "check": "text-spill", "route": "/", "state": "default", "selector": "p",
             "message": "long text " * 50, "widths": [400, 500, 600], "origin": "deterministic", "browsers": ["chromium"]}
    result = {"baseline": "b", "current": "c", "fixed": [issue] * 60, "introduced": [], "persistent": [issue],
              "needs_review": [], "out_of_scope": 3, "pixel_diffs": []}
    v = summary.verify_summary(result)
    assert len(v["fixed"]) == 50 and v["more_fixed"] == 10 and v["out_of_scope"] == 3
    assert v["persistent"] == [{"id": "a", "severity": "P2", "check": "text-spill", "route": "/", "state": "default",
                                "selector": "p", "widths": [400, 600]}]


def test_show_prints_the_summary_or_one_cause(tmp_path, capsys):
    run, data = make_run(tmp_path)
    assert main(["show", str(run), "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    group = s["groups"][0]["id"]
    assert main(["show", str(run)]) == 0
    assert group in capsys.readouterr().out
    assert main(["show", str(run), "--group", group, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 2
    assert main(["show", str(run), "--issue", "nope"]) == 2
    assert main(["show", str(tmp_path / "missing")]) == 2


def test_verify_json_keeps_stdout_for_the_json(tmp_path, capsys):
    run, data = make_run(tmp_path)
    assert main(["verify", str(run), str(run), "--output", str(tmp_path / "v"), "--json"]) == 0
    captured = capsys.readouterr()
    v = json.loads(captured.out)
    assert len(v["persistent"]) == 4 and v["fixed"] == [] and v["exit_code"] == 0
    assert "ui-audit verify" in captured.err  # the Markdown still shows, on stderr


def test_audit_json_without_a_run_says_so(tmp_path, capsys):
    assert main(["audit", "--like", str(tmp_path / "missing"), "--json"]) == 2
    assert json.loads(capsys.readouterr().out) == {"report": None, "exit_code": 2}
