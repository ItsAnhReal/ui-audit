"""The local app's server: what it serves, to whom, and what the API does with runs."""

import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from ui_audit import report
from ui_audit.server import ApiError, AppServer, Workspace, recheck_widths

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def issue(n, route="/", check="text-spill", severity="P3", widths=(390, 400), state="default"):
    selector = f"p:nth-of-type({n})"
    return {"id": f"i{n}", "signature": f"{check}|{route}|{state}|{selector}", "check": check, "severity": severity,
            "origin": "deterministic", "route": route, "state": state, "selector": selector, "message": f"issue {n}",
            "widths": list(widths), "evidence": [], "rects": {}}


def make_run(runs, name, project, issues, created="2026-01-01T00:00:00+00:00", coverage=None):
    folder = runs / name
    (folder / "shots").mkdir(parents=True)
    (folder / "shots" / "home__default__390.png").write_bytes(PNG)
    data = {
        "version": "0.1.0", "created": created, "base_url": "http://app.test", "project_root": str(project),
        "output_dir": str(folder), "routes": [{"path": "/", "discovered_by": ["config"], "loaded": True, "status": "audited"}],
        "states": [], "breakpoints": [], "errors": [], "stats": {"issues": report.summary_counts(issues), "seconds": 12},
        "captures": [{"route": "/", "state": "default", "width": 390, "file": "shots/home__default__390.png", "reasons": ["standard"]}],
        "config": {"viewports": {"min_width": 320, "max_width": 1920}}, "coverage": coverage or {"|/|default": []},
        "issues": issues,
    }
    report.write_json(data, folder)
    return folder


@pytest.fixture
def app(tmp_path):
    project = tmp_path / "shop"
    runs = project / ".ui-audit"
    runs.mkdir(parents=True)
    (project / "ui-audit.toml").write_text('base_url = "http://localhost:3000"\noutput = ".ui-audit/latest"\n')
    make_run(runs, "shop-20260101-090000", project, [issue(1), issue(2, route="/cart", severity="P2")],
             coverage={"/|default": [390, 400], "/cart|default": [390, 400]})
    make_run(runs, "shop-20260102-090000", project, [issue(2, route="/cart", severity="P2"), issue(3)],
             created="2026-01-02T00:00:00+00:00", coverage={"/|default": [390, 400], "/cart|default": [390, 400]})
    server = AppServer(Workspace(project, project / "ui-audit.toml"), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, project
    server.shutdown()
    server.server_close()


def call(server, path, body=None, token=True, host=None, cookie=None):
    headers = {"Host": host or f"127.0.0.1:{server.port}"}
    if token:
        headers["X-UI-Audit-Token"] = server.token
    if cookie:
        headers["Cookie"] = cookie
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", data=data, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            kind = response.headers.get("Content-Type", "")
            return response.status, (json.loads(raw) if "json" in kind else raw), response.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, (json.loads(raw or b"{}") if "json" in exc.headers.get("Content-Type", "") else raw), exc.headers


def test_recheck_looks_at_both_edges_just_outside_them_and_the_middle():
    assert recheck_widths([{"widths": [400, 480, 560]}], 320, 1920) == [399, 400, 480, 560, 561]
    assert recheck_widths([{"widths": [320, 330]}], 320, 1920) == [320, 330, 331]  # never below the range
    many = [{"widths": [w, w + 10]} for w in range(400, 1600, 100)]
    widths = recheck_widths(many, 320, 1920)
    assert len(widths) == 14 and widths == sorted(widths)


def test_page_carries_a_token_and_a_strict_policy(app):
    server, _ = app
    status, page, headers = call(server, f"/?k={server.key}", token=False)
    assert status == 200 and server.token not in page.decode()
    assert 'http-equiv="refresh" content="0;url=/"' in page.decode()  # on to the page, without the key
    cookie = headers["Set-Cookie"]
    assert "SameSite=Strict" in cookie and "HttpOnly" in cookie and "Path=/;" in cookie
    status, page, headers = call(server, "/", token=False, cookie=cookie.split(";")[0])
    assert status == 200
    assert server.token in page.decode()
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store"


def test_the_page_needs_the_key_from_the_terminal(app):
    server, _ = app
    assert server.launch_url == f"{server.url}?k={server.key}"
    status, page, headers = call(server, "/", token=False)
    assert status == 403 and server.token not in page.decode() and "Set-Cookie" not in headers
    assert "printed in the terminal" in page.decode() and "Terminal" in page.decode()  # both languages
    status, page, headers = call(server, "/?k=guess", token=False)
    assert status == 403 and "Set-Cookie" not in headers
    assert call(server, "/", token=False, cookie=f"{server.cookie}=guess")[0] == 403
    # reopening the printed address keeps working while the server runs
    assert call(server, f"/?k={server.key}", token=False)[0] == 200
    assert call(server, f"/?k={server.key}", token=False)[0] == 200


def test_bad_request_lengths_are_refused_or_read_as_empty(app):
    import http.client

    server, _ = app
    for length, expected in (("-5", 400), ("nonsense", 400), (str(2_000_000), 413)):  # 400: read as {}, no run named
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        conn.putrequest("POST", "/api/compare", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{server.port}")
        conn.putheader("X-UI-Audit-Token", server.token)
        conn.putheader("Content-Length", length)
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == expected, (length, response.status)  # never a crash or a hang
        conn.close()


def test_other_hosts_and_missing_tokens_are_refused(app):
    server, _ = app
    assert call(server, "/", host="evil.example:80")[0] == 403  # DNS rebinding
    assert call(server, "/api/state", token=False)[0] == 403
    assert call(server, f"/?k={server.key}", host="evil.example:80")[0] == 403
    status, data, _ = call(server, "/api/state")
    assert status == 200 and data["project"] == "shop"
    assert [r["name"] for r in data["runs"]] == ["shop-20260102-090000", "shop-20260101-090000"]
    assert data["runs"][0]["counts"] == {"P1": 0, "P2": 1, "P3": 1}
    assert data["config"]["base_url"] == "http://localhost:3000"


def test_screenshots_need_the_cookie_and_nothing_else_is_served(app):
    server, project = app
    path = "/files/shop-20260101-090000/shots/home__default__390.png"
    assert call(server, path, token=False)[0] == 403
    cookie = f"{server.cookie}={server.token}"
    status, body, headers = call(server, path, token=False, cookie=cookie)
    assert status == 200 and body == PNG and headers["Content-Type"] == "image/png"
    assert call(server, "/files/shop-20260101-090000/report.json", cookie=cookie)[0] == 404  # images only
    (project / "secret.png").write_bytes(PNG)
    assert call(server, "/files/shop-20260101-090000/..%2F..%2Fsecret.png", cookie=cookie)[0] == 404
    assert call(server, "/files/..%2F/etc/passwd", cookie=cookie)[0] in (400, 404)


def test_accepting_from_the_app_writes_the_projects_file_and_can_be_undone(app):
    server, project = app
    name = "shop-20260101-090000"
    assert call(server, f"/api/runs/{name}/accept", {"ids": ["i1"], "reason": ""})[0] == 400
    assert call(server, f"/api/runs/{name}/accept", {"ids": ["nope"], "reason": "x"})[0] == 404
    status, data, _ = call(server, f"/api/runs/{name}/accept", {"ids": ["i1"], "reason": "decorative"})
    assert status == 200 and data["added"] == 1
    saved = json.loads((project / "ui-audit.accepted.json").read_text())
    assert saved[0]["reason"] == "decorative" and saved[0]["signature"].startswith("text-spill|/|")
    run = call(server, f"/api/runs/{name}")[1]
    assert next(i for i in run["issues"] if i["id"] == "i1")["accepted"]["reason"] == "decorative"
    assert call(server, "/api/state")[1]["runs"][1]["counts"]["P3"] == 0

    assert call(server, f"/api/runs/{name}/unaccept", {"ids": ["i1"]})[1]["removed"] == 1
    assert json.loads((project / "ui-audit.accepted.json").read_text()) == []
    assert call(server, "/api/state")[1]["runs"][1]["counts"]["P3"] == 1


def test_compare_counts_what_changed_between_two_runs(app):
    server, _ = app
    status, data, _ = call(server, "/api/compare", {"baseline": "shop-20260101-090000", "current": "shop-20260102-090000"})
    assert status == 200
    assert [i["id"] for i in data["fixed"]] == ["i1"]
    assert [i["id"] for i in data["introduced"]] == ["i3"]
    assert [i["id"] for i in data["persistent"]] == ["i2"]


def test_run_names_are_checked_and_deleting_removes_only_that_folder(app, tmp_path):
    server, project = app
    assert call(server, "/api/runs/..%2F..%2Fetc")[0] == 400
    assert call(server, "/api/runs/missing-run")[0] == 404
    outside = make_run(tmp_path / "elsewhere", "other", project, [issue(9)])
    (project / ".ui-audit" / "linked").symlink_to(outside)
    assert call(server, "/api/runs/linked/delete", {})[0] == 400
    assert outside.is_dir()
    status, data, _ = call(server, "/api/runs/shop-20260101-090000/delete", {})
    assert status == 200 and data["bytes"] > 0
    assert not (project / ".ui-audit" / "shop-20260101-090000").exists()
    assert (project / ".ui-audit" / "shop-20260102-090000").is_dir()


def test_bad_audit_requests_are_explained(app):
    server, _ = app
    assert call(server, "/api/runs", {"mode": "everything"})[1]["error"].startswith("mode must be")
    assert "http" in call(server, "/api/runs", {"base_url": "file:///etc/passwd"})[1]["error"]
    assert call(server, "/api/runs", {"mode": "pages", "routes": ["pricing"]})[0] == 400
    assert call(server, "/api/runs", {"mode": "pages", "routes": ["/"], "widths": ["wide"]})[0] == 400
    assert call(server, "/api/runs", {"config": "../secrets.toml"})[1]["error"].startswith("unknown settings file")
    assert call(server, "/api/runs", {"storage_state": "/etc/passwd"})[1]["error"].startswith("unknown session file")
    assert call(server, "/api/runs", {"changed_since": "main; rm -rf /"})[0] == 400
    assert call(server, "/api/state")[1]["jobs"] == []  # nothing was started


def test_sessions_are_saved_only_next_to_the_runs(app):
    server, project = app
    for save in ("../package.json", "../../x.json", "/tmp/x.json", "sub/auth.json", "auth.txt", ".hidden.json"):
        status, data, _ = call(server, "/api/login", {"base_url": "http://localhost:3000", "save": save})
        assert status == 400 and "plain .json file name" in data["error"], save
    assert call(server, "/api/state")[1]["jobs"] == []


def test_recheck_of_unknown_findings_is_refused(app):
    server, _ = app
    assert call(server, "/api/runs/shop-20260101-090000/recheck", {"ids": ["nope"]})[0] == 404


def test_sessions_are_listed_without_their_contents(tmp_path):
    project = tmp_path / "shop"
    (project / ".ui-audit").mkdir(parents=True)
    secret = {"cookies": [{"name": "sid", "value": "s3cr3t"}], "origins": [{"origin": "http://localhost:3000", "localStorage": []}]}
    (project / ".ui-audit" / "auth.json").write_text(json.dumps(secret))
    (project / ".ui-audit" / "notes.json").write_text("[]")
    sessions = Workspace(project).sessions()
    assert sessions == [{"path": ".ui-audit/auth.json", "modified": sessions[0]["modified"], "origins": ["http://localhost:3000"]}]
    assert "s3cr3t" not in json.dumps(sessions)
    with pytest.raises(ApiError):
        Workspace(project).session_file("../auth.json")


def test_the_page_has_no_unfilled_placeholders():
    page = report.page(app={"token": "t", "version": "0"})
    assert not re.search(r"/\*__\w+__\*/|__REPORT_DATA__|__APP_CONFIG__", page)
    assert page.count("<script") == 3  # report data, app config, code
