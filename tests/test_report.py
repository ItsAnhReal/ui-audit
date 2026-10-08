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
    assert issue["source_candidates"] == [{"file": "src/a.tsx", "line": 3}]
    assert "rects" not in issue and "hints" not in issue
    assert data["config"] == {"viewports": {"min_width": 320, "max_width": 1920}}


def test_report_command_rebuilds_the_viewer(tmp_path, capsys):
    assert main(["report", str(tmp_path), "--no-open"]) == 2
    report.write_json(REPORT, tmp_path)
    assert main(["report", str(tmp_path), "--no-open"]) == 0
    assert embedded((tmp_path / "index.html").read_text())["base_url"] == "http://app.test"
