import http.server
import json
import socket
import threading

import pytest

from ui_audit.cli import audit_trustworthy, main, sign_in_wall, skill_status


def test_install_skill_project_scope(tmp_path):
    assert main(["install-skill", "--project-root", str(tmp_path)]) == 0
    for target in (".claude/skills/ui-audit/SKILL.md", ".codex/skills/ui-audit/SKILL.md"):
        text = (tmp_path / target).read_text()
        assert text.startswith("---\nname: ui-audit")


def test_init_writes_config_and_gitignore(tmp_path, capsys):
    (tmp_path / "index.html").write_text("<h1>x</h1>")
    (tmp_path / "about.html").write_text("<h1>y</h1>")
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    assert main(["init", "--project-root", str(tmp_path), "--base-url", "http://localhost:8000"]) == 0
    config = (tmp_path / "ui-audit.toml").read_text()
    assert 'base_url = "http://localhost:8000"' in config and '"/about.html"' in config
    assert ".ui-audit/" in (tmp_path / ".gitignore").read_text()
    assert main(["init", "--project-root", str(tmp_path)]) == 2  # a usage error, not a finding


def test_routes_for_changes_picks_what_a_change_can_affect():
    from ui_audit.cli import routes_for_changes

    baseline = {"routes": [
        {"path": "/", "status": "audited", "sources": ["src/Home.tsx", "src/Card.tsx"]},
        {"path": "/pricing", "status": "audited", "sources": ["src/Pricing.tsx", "src/Card.tsx"]},
        {"path": "/old", "status": "skipped: not found"},
    ]}
    assert routes_for_changes(baseline, ["README.md", "api/server.py"])[0] == []
    assert routes_for_changes(baseline, ["src/Pricing.tsx"])[0] == ["/pricing"]
    assert routes_for_changes(baseline, ["src/Card.tsx"])[0] == ["/", "/pricing"]
    # Every extension the source mapper reads counts as UI source, MDX included.
    assert routes_for_changes(baseline, ["src/Pricing.mdx"])[0] == ["/", "/pricing"]
    # A stylesheet or an unseen component could reach any page.
    assert routes_for_changes(baseline, ["src/Pricing.tsx", "src/index.css"])[0] == ["/", "/pricing"]
    for route in baseline["routes"]:
        route.pop("sources", None)
    assert routes_for_changes(baseline, ["src/Pricing.tsx"])[0] == ["/", "/pricing"]


def test_like_reuses_an_earlier_runs_settings(tmp_path):
    import argparse
    import json

    from ui_audit.cli import _load_config
    from ui_audit.config import Config

    cfg = Config()
    cfg.base_url, cfg.storage_state, cfg.locale = "http://localhost:8080", ".ui-audit/auth.json", "de"
    cfg.setup = [{"click": "button.accept"}]
    run = tmp_path / "shop-1"
    run.mkdir()
    (run / "report.json").write_text(json.dumps({"config": cfg.to_dict()}))
    again, path = _load_config(argparse.Namespace(like=str(run), output=None))
    assert path is None and again.storage_state == ".ui-audit/auth.json" and again.locale == "de" and again.setup == cfg.setup
    assert again.output == str(run) + "-again"  # never the run it copies
    override, _ = _load_config(argparse.Namespace(like=str(run), output=str(tmp_path / "x"), locale="fr"))
    assert override.output == str(tmp_path / "x") and override.locale == "fr"
    assert main(["audit", "--like", str(tmp_path / "missing")]) == 2


def test_missing_or_broken_inputs_are_one_line_usage_errors(tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    (run / "report.json").write_text(json.dumps({"routes": [], "issues": [], "stats": {"issues": {}}}))
    assert main(["verify", str(tmp_path / "missing"), str(run)]) == 2
    assert f"error: no report.json in {tmp_path / 'missing'}" in capsys.readouterr().err
    assert main(["merge-findings", str(run)]) == 2  # no agent-findings.json yet
    assert "agent-findings.json not found" in capsys.readouterr().err
    (run / "agent-findings.json").write_text("{not json")
    assert main(["merge-findings", str(run)]) == 2
    assert "is not valid JSON" in capsys.readouterr().err
    assert main(["accept", str(tmp_path / "missing"), "i1", "--reason", "x"]) == 2
    assert main(["report", str(tmp_path / "missing"), "--no-open"]) == 2
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "report.json").write_text("")
    assert main(["report", str(broken), "--no-open"]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_help_shows_the_loop_and_the_exit_codes(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "ui-audit init" in out and "ui-audit verify" in out and "3 the app or the audit failed" in out


def routes(*records):
    return {"routes": [dict(r) for r in records]}


def test_most_routes_landing_on_one_other_url_looks_like_an_expired_sign_in():
    login = [{"path": p, "landed": "/login", "status": "audited" if p == "/" else "skipped: redirects to /"}
             for p in ("/", "/a", "/b", "/c")]
    assert sign_in_wall(routes(*login)) == ("/login", 4, 4)
    assert sign_in_wall(routes(*login, {"path": "/login", "status": "skipped: redirects to /"})) == ("/login", 4, 5)
    # Two redirects are too few to tell; one route in four that stays put is no wall either.
    assert sign_in_wall(routes(*login[:2])) is None
    assert sign_in_wall(routes(*login[:3], {"path": "/x", "status": "audited"})) is None
    # A route that failed to load is not counted among the loaded ones.
    assert sign_in_wall(routes(*login, {"path": "/y", "loaded": False})) == ("/login", 4, 4)
    assert sign_in_wall(routes({"path": "/", "status": "audited"})) is None


def test_an_audit_that_measured_nothing_or_hit_a_sign_in_page_is_not_trusted(capsys):
    base = "http://localhost:3000"
    assert audit_trustworthy(routes({"path": "/", "status": "audited"},
                                    {"path": "/old", "status": "skipped: not found"}), base)
    assert not audit_trustworthy(routes({"path": "/", "status": "audited"},
                                        {"path": "/admin", "loaded": False, "error": "TimeoutError: 30000ms"}), base)
    err = capsys.readouterr().err
    assert "error: http://localhost:3000/admin did not load (TimeoutError: 30000ms)" in err
    assert "is the app running" not in err  # some routes did load
    assert not audit_trustworthy(routes({"path": "/old", "status": "skipped: not found"}), base)
    assert "no route was measured" in capsys.readouterr().err
    wall = [{"path": p, "landed": "https://sso.example.com/login", "status": "audited"} for p in ("/", "/a", "/b")]
    assert not audit_trustworthy(routes(*wall), base)
    err = capsys.readouterr().err
    assert "3 of 3 routes ended on https://sso.example.com/login" in err and "storage_state expired" in err


def test_doctor_names_the_skill_copy_each_agent_reads(tmp_path):
    project, home = tmp_path / "project", tmp_path / "home"
    project.mkdir()
    lines = skill_status(project, home)
    assert all("not installed" in line for line in lines) and "Claude Code" in lines[0] and "Codex" in lines[1]
    main(["install-skill", "--project-root", str(project), "--agent", "claude"])
    stale = home / ".codex/skills/ui-audit/SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("an older skill")
    claude, codex = skill_status(project, home)
    assert claude.startswith("ok") and "project (" in claude and "user (" not in claude
    assert codex.startswith("old") and "--agent codex --scope user" in codex


def test_an_audit_that_crashes_exits_3(monkeypatch, tmp_path, capsys):
    import ui_audit.audit

    def boom(*_args, **_kwargs):
        raise RuntimeError("browser closed")

    monkeypatch.setattr(ui_audit.audit, "run", boom)
    assert main(["audit", "http://127.0.0.1:1", "--output", str(tmp_path / "run"), "--quiet"]) == 3
    assert "error: the audit failed (RuntimeError: browser closed)" in capsys.readouterr().err


class _Handler(http.server.BaseHTTPRequestHandler):
    """Every page but /login redirects to /login, as an app does once the session has expired; /broken hangs up."""

    def do_GET(self):  # noqa: N802 - http.server's name
        if self.path.startswith("/broken"):
            self.close_connection = True
            return
        if self.path.startswith("/login") or not self.server.wall:
            body = (b"<!doctype html><title>t</title><main><h1>Page</h1><p>" + self.path.encode()
                    + b" has enough words to read as a real page and not as an empty one.</p></main>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(302)
        self.send_header("Location", "/login?next=" + self.path)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def app():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.wall = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def audit_args(url, tmp_path, *paths):
    (tmp_path / "ui-audit.toml").write_text(f'base_url = "{url}"\n[routes]\ndiscover = ["config"]\n'
                                            'include = ["/", "/a", "/b", "/c"]\n')
    return ["audit", "--config", str(tmp_path / "ui-audit.toml"), "--output", str(tmp_path / "run"), "--quiet",
            "--no-states", "--width", "390", "--project-root", str(tmp_path),
            *[arg for p in paths for arg in ("--route", p)]]


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_an_unreachable_app_is_a_failed_audit_not_a_clean_one(tmp_path, capsys):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    assert main(audit_args(url, tmp_path, "/") + ["--fail-on", "P3"]) == 3
    out, err = capsys.readouterr()
    assert f"error: {url}/ did not load" in err and "is the app running" in err
    assert "skipped" not in out  # a route that did not load is no duplicate
    assert (tmp_path / "run" / "report.json").is_file()


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_a_route_of_a_rerun_that_does_not_load_fails_the_audit(app, tmp_path, capsys):
    server, url = app
    server.wall = False
    assert main(audit_args(url, tmp_path, "/", "/broken")) == 3
    err = capsys.readouterr().err
    assert f"error: {url}/broken did not load" in err and "is the app running" not in err


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_every_route_sent_to_the_sign_in_page_fails_the_audit(app, tmp_path, capsys):
    _, url = app
    assert main(audit_args(url, tmp_path)) == 3
    err = capsys.readouterr().err
    assert f"4 of 4 routes ended on {url}/login" in err and "storage_state expired" in err
    report = json.loads((tmp_path / "run" / "report.json").read_text())
    assert {r["landed"] for r in report["routes"]} == {"/login"}
