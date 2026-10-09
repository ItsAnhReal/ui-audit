import json
import socket
import subprocess
import sys

import pytest

from ui_audit import ci
from ui_audit.verify import compare


def issue(selector, severity="P1", route="/", state="default", widths=(800,), **extra):
    return {"id": selector, "signature": f"horizontal-overflow|{route}|{state}|{selector}", "check": "horizontal-overflow",
            "severity": severity, "route": route, "state": state, "selector": selector, "message": "m",
            "widths": list(widths), "origin": "deterministic", **extra}


def report(*issues):
    return {"issues": list(issues), "routes": [{"path": "/", "status": "audited", "content": {"state": "ok"}}],
            "groups": [], "errors": [], "captures": [], "coverage": {"/|default": [800]}}


def test_summary_of_a_comparison_leads_with_what_the_change_introduced():
    base, head = report(issue(".old"), issue(".gone")), report(issue(".old"), issue(".new", "P2"))
    result = compare(base, head)
    text = ci.render_summary(head, result, base=base, base_sha="abcdef123456", blocking=True,
                             run_url="https://github.com/o/r/actions/runs/1", artifact="ui-audit-report")
    assert text.startswith(ci.MARKER)
    assert "### ❌ ui-audit: 1 new responsive problem in this change" in text
    assert "base commit `abcdef1`: **1 new** · 1 fixed · 1 still open" in text
    assert text.index("New in this change") < text.index("Fixed (1)") < text.index("Still open (1)")
    assert "| This change | 1 | 1 | 0 |" in text and "| Base | 2 | 0 | 0 |" in text
    assert "`ui-audit-report` artifact of [this run](https://github.com/o/r/actions/runs/1)" in text


def test_summary_without_a_comparison_lists_one_finding_per_cause():
    head = report(issue(".a", group="g1"), issue(".b", group="g1"), issue(".c", "P2", group="g2"),
                  issue(".ok", group="g3", accepted={"reason": "fine"}))
    head["groups"] = [{"id": "g1", "issue_ids": [".a", ".b"]}, {"id": "g2", "issue_ids": [".c"]},
                      {"id": "g3", "issue_ids": [".ok"]}]
    text = ci.render_summary(head)
    assert "### ⚠️ ui-audit: 3 responsive problems from 2 causes" in text
    assert "2 P1 · 1 P2 · 0 P3 across 1 route." in text
    assert "`.a`" in text and "`.c`" in text and "`.b`" not in text and "`.ok`" not in text


def test_summary_names_routes_that_did_not_show_real_content_and_long_lists_are_cut():
    head = report(*[issue(f".x{n}") for n in range(ci.LIST_LIMIT + 3)])
    head["routes"][0]["content"] = {"state": "loading", "detail": "spinner"}
    text = ci.render_summary(head)
    assert "`/` may not show its real content (loading: spinner)" in text
    assert "… and 3 more in the report" in text


def test_summary_when_nothing_could_be_audited():
    text = ci.render_summary(None, notes=["http://localhost:3000 did not answer"])
    assert "could not audit" in text and "> http://localhost:3000 did not answer" in text


def test_blocking():
    head = report(issue(".a", "P2"))
    new = compare(report(), head)
    same = compare(head, head)
    assert ci.is_blocking("new", head, new) and not ci.is_blocking("new", head, same)
    assert not ci.is_blocking("new", head, None)  # nothing compared: nothing is new
    assert ci.is_blocking("P2", head, None) and not ci.is_blocking("P1", head, None)
    assert not ci.is_blocking("never", head, new) and not ci.is_blocking("P3", None, None)
    assert not ci.is_blocking("P3", report(issue(".a", accepted={"reason": "ok"})), None)


def test_comment_is_updated_instead_of_repeated(monkeypatch):
    calls = []

    def api(method, url, token, body=None):
        calls.append((method, url, body))
        if method == "GET":
            return [{"id": 1, "body": "unrelated"}, {"id": 7, "body": f"{ci.MARKER}\nold"}]
        return {"html_url": "https://github.com/o/r/pull/3#issuecomment-7"}

    monkeypatch.setattr(ci, "_api", api)
    ci.post_comment("new body", api="https://api", repo="o/r", pr=3, token="t")
    assert calls[-1] == ("PATCH", "https://api/repos/o/r/issues/comments/7", {"body": "new body"})

    calls.clear()
    monkeypatch.setattr(ci, "_api", lambda method, url, token, body=None: calls.append((method, url, body)) or
                        ([] if method == "GET" else {"html_url": "u"}))
    ci.post_comment("first", api="https://api", repo="o/r", pr=3, token="t")
    assert calls[-1] == ("POST", "https://api/repos/o/r/issues/3/comments", {"body": "first"})


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args], cwd=cwd, check=True,
                   capture_output=True)


def test_base_worktree_matches_the_working_directory(tmp_path):
    repo = tmp_path / "repo"
    (repo / "web").mkdir(parents=True)
    (repo / "web" / "index.html").write_text("base")
    git("init", "-q", cwd=repo)
    git("add", ".", cwd=repo)
    git("commit", "-qm", "base", cwd=repo)
    (repo / "web" / "index.html").write_text("head")
    path, sha = ci.base_worktree(repo / "web", "HEAD", tmp_path / "base")
    assert path == tmp_path / "base" / "web" and (path / "index.html").read_text() == "base" and len(sha) == 40
    ci.remove_worktree(repo, tmp_path / "base")
    assert not (tmp_path / "base").exists()


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_app_is_started_waited_for_and_stopped(tmp_path):
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    app = ci.App(f"{sys.executable} -m http.server {port} --bind 127.0.0.1", tmp_path, tmp_path / "app.log")
    app.start(url, timeout=20)
    assert ci._answers(url)
    app.stop(url)
    assert not ci._answers(url)


def test_a_start_command_that_dies_is_reported_with_its_output(tmp_path):
    app = ci.App("echo boom; exit 3", tmp_path, tmp_path / "app.log")
    with pytest.raises(ci.CIError, match="exited with code 3") as caught:
        app.start(f"http://127.0.0.1:{free_port()}/", timeout=10)
    assert "boom" in str(caught.value)


def test_run_reports_an_app_that_never_answers(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    from ui_audit.cli import main

    code = main(["ci", f"http://127.0.0.1:{free_port()}/", "--compare", "none", "--output", str(tmp_path / "out")])
    assert code == 2
    assert "could not audit" in (tmp_path / "out" / "summary.md").read_text()
