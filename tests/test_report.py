import json

from ui_audit import report
from ui_audit.cli import main

REPORT = {
    "version": "0.1.0", "created": "2026-01-01T00:00:00+00:00", "base_url": "http://app.test", "project_root": "/app",
    "routes": [{"path": "/", "discovered_by": ["config"], "loaded": True, "status": "audited"}],
    "states": [], "breakpoints": [768], "captures": [], "errors": [], "stats": {"probes": 1},
    "config": {"viewports": {"min_width": 320, "max_width": 1920}, "routes": {"include": ["/"]}},
    "issues": [{
        "id": "a1", "check": "text-spill", "severity": "P3", "origin": "deterministic", "route": "/", "state": "default",
        "selector": "p", "message": 'Text spills: "</script><b>"', "widths": [390], "evidence": [],
        "rects": {"390": {"x": 0}}, "hints": {"classes": ["x"]},
        "source_candidates": [{"file": "src/a.tsx", "line": 3, "score": 9, "reasons": ["class x"]}],
    }],
}


def embedded(page: str) -> dict:
    start = page.index('id="report-data">') + len('id="report-data">')
    return json.loads(page[start:page.index("</script>", start)])


def test_viewer_inlines_only_what_it_reads(tmp_path):
    page = report.write_html(REPORT, tmp_path).read_text()
    data = embedded(page)  # the "</script>" inside a message must not end the data block
    issue = data["issues"][0]
    assert issue["message"] == 'Text spills: "</script><b>"'
    assert issue["source_candidates"] == [{"file": "src/a.tsx", "line": 3, "reasons": ["class x"]}]
    assert issue["rects"] == {} and "hints" not in issue  # boxes only for widths that have a screenshot
    assert data["config"] == {"viewports": {"min_width": 320, "max_width": 1920}, "sweep": "full", "signed_in": False}
    assert data["groups"][0]["count"] == 1
    assert '"token"' not in page  # a static report carries no app token


def test_viewer_page_is_one_self_contained_file(tmp_path):
    page = report.write_html(REPORT, tmp_path).read_text()
    assert "/*__" not in page and "__REPORT_DATA__" not in page and "__APP_CONFIG__" not in page
    assert "window.uiAuditI18n" in page and "Content-Security-Policy" not in page
    assert "<script src" not in page and "<link rel=\"stylesheet\"" not in page


def test_report_command_rebuilds_the_viewer(tmp_path, capsys):
    assert main(["report", str(tmp_path), "--no-open"]) == 2
    report.write_json(REPORT, tmp_path)
    assert main(["report", str(tmp_path), "--no-open"]) == 0
    assert embedded((tmp_path / "index.html").read_text())["base_url"] == "http://app.test"


def test_accepting_a_finding_takes_it_out_of_the_counts(tmp_path, capsys):
    from ui_audit.issues import load_accepted, mark_accepted

    project = tmp_path / "app"
    project.mkdir()
    report_dir = tmp_path / "run"
    report_dir.mkdir()
    data = json.loads(json.dumps(REPORT))
    data["project_root"] = str(project)
    data["issues"][0]["signature"] = "text-spill|/|default|p"
    report.write_json(data, report_dir)
    group = report.read_json(report_dir)["groups"][0]["id"]

    assert main(["accept", str(report_dir), "nope", "--reason", "x"]) == 2
    assert main(["accept", str(report_dir), group, "--reason", "decorative overflow"]) == 0
    saved = report.read_json(report_dir)
    assert saved["issues"][0]["accepted"]["reason"] == "decorative overflow"
    assert saved["stats"]["issues"] == {"P1": 0, "P2": 0, "P3": 0}

    # The next audit of the same app reads the decision from the project.
    fresh = [{"signature": "text-spill|/|default|p"}, {"signature": "text-spill|/|default|h1"}]
    assert mark_accepted(fresh, load_accepted(project / "ui-audit.accepted.json")) == 1
    assert "accepted" in fresh[0] and "accepted" not in fresh[1]
