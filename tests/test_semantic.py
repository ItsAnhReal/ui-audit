import json

from ui_audit.semantic import MAX_PACKET_CAPTURES, build_packet, merge


def make_report(n_captures=3):
    captures = [{"route": "/", "state": "default", "width": 300 + i, "height": 844, "reasons": ["standard"],
                 "file": f"shots/root__default__{300 + i}.png", "issue_count": i % 2} for i in range(n_captures)]
    issues = [{"id": "x", "signature": "horizontal-overflow|/|default|.a", "check": "horizontal-overflow", "severity": "P1",
               "route": "/", "state": "default", "selector": ".a", "message": "m", "widths": [301], "origin": "deterministic"}]
    return {"captures": captures, "issues": issues}


def test_packet_is_bounded_and_prioritises_captures_with_issues(tmp_path):
    report = make_report(20)
    json_path, md_path = build_packet(report, tmp_path)
    packet = json.loads(json_path.read_text())
    assert len(packet["items"]) == MAX_PACKET_CAPTURES
    assert packet["omitted_captures"] == 20 - MAX_PACKET_CAPTURES
    assert packet["items"][0]["width"] == 301 and packet["items"][0]["deterministic_findings"]
    assert "agent-findings.json" in md_path.read_text()


def test_merge_validates_labels_and_dedupes():
    report = make_report()
    good = {"route": "/", "state": "default", "width": 301, "severity": "P2", "category": "layout",
            "description": "Cards collide.", "evidence": "shots/x.png"}
    bad_route = dict(good, route="/missing")
    bad_severity = dict(good, severity="high")
    added, errors = merge(report, [good, good, bad_route, bad_severity, {"route": "/"}])
    assert added == 1
    assert len(errors) == 3
    agent = [i for i in report["issues"] if i["origin"] == "agent"]
    assert agent[0]["check"] == "semantic-layout" and agent[0]["widths"] == [301]
