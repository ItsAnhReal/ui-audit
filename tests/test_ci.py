import json
import socket
import subprocess
import sys
from types import SimpleNamespace

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


def test_a_base_that_cannot_be_audited_fails_the_run_and_the_audit_posts_nothing(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("x")
    git("init", "-q", cwd=repo)
    git("add", ".", cwd=repo)
    git("commit", "-qm", "base", cwd=repo)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("UI_AUDIT_GITHUB_TOKEN", "secret")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "temp"))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file(tmp_path, {"pull_request": {"number": 5}})))
    monkeypatch.setattr(ci, "_api", lambda *a, **k: pytest.fail("the audit must not call the GitHub API"))

    def fake_audit(*, label, output, **_):
        if label == "base":
            raise ci.CIError("the start command exited with code 1")
        output.mkdir(parents=True, exist_ok=True)
        (output / "report.json").write_text(json.dumps(report()))

    monkeypatch.setattr(ci, "audit_checkout", fake_audit)
    from ui_audit.cli import main

    out = tmp_path / "out"
    assert main(["ci", "http://127.0.0.1:1/", "--start", "x", "--base-ref", "HEAD", "--working-directory", str(repo),
                 "--output", str(out)]) == 2
    assert "The base commit could not be audited" in (out / "summary.md").read_text()
    assert json.loads((out / "pull-request.json").read_text()) == {"number": 5}  # for a later --post-comment
    assert main(["ci", "http://127.0.0.1:1/", "--start", "x", "--base-ref", "HEAD", "--working-directory", str(repo),
                 "--output", str(out), "--fail-on", "never"]) == 0


def test_install_start_and_audit_get_no_token(tmp_path, monkeypatch):
    for name in ci.TOKEN_VARS:
        monkeypatch.setenv(name, "secret")
    dump = f"{sys.executable} -c \"import os, sys; open(sys.argv[1], 'w').write(repr(dict(os.environ)))\""
    ci._run(f"{dump} install.txt", tmp_path, "install")
    with pytest.raises(ci.CIError):
        ci.App(f"{dump} start.txt", tmp_path, tmp_path / "app.log").start(f"http://127.0.0.1:{free_port()}/", timeout=10)
    for name in ("install.txt", "start.txt"):
        text = (tmp_path / name).read_text()
        assert "secret" not in text and "PATH" in text
    assert ci.os.environ["UI_AUDIT_GITHUB_TOKEN"] == "secret"  # only the children lose it


def test_the_comment_step_needs_no_playwright():
    # The action's comment step runs ui-audit from its source with a bare Python.
    code = "import sys, ui_audit.cli, ui_audit.ci; ui_audit.cli.build_parser(); print('playwright' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          check=True).stdout.strip() == "False"


def event_file(tmp_path, event):
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    return path


@pytest.fixture
def github(tmp_path, monkeypatch):
    """A GitHub environment for --post-comment; returns the API calls made and lets a test set the event."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_API_URL", "https://api")
    for name in ci.TOKEN_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UI_AUDIT_GITHUB_TOKEN", "t")
    calls = []
    heads = {}

    def api(method, url, token, body=None):
        calls.append((method, url, body))
        if "/pulls/" in url:
            return {"head": {"sha": heads.get(url.rsplit("/", 1)[1])}}
        return [] if method == "GET" else {"html_url": "u"}

    monkeypatch.setattr(ci, "_api", api)
    summary = tmp_path / "artifact" / "summary.md"
    summary.parent.mkdir()
    summary.write_text(f"{ci.MARKER}\nbody\n")

    return SimpleNamespace(calls=calls, heads=heads, summary=summary, event=lambda event: monkeypatch.setenv(
        "GITHUB_EVENT_PATH", str(event_file(tmp_path, event))))


def test_post_comment_only_posts(github):
    from ui_audit.cli import main

    github.event({"pull_request": {"number": 3}})
    assert main(["ci", "--post-comment", str(github.summary)]) == 0
    assert github.calls[-1] == ("POST", "https://api/repos/o/r/issues/3/comments", {"body": f"{ci.MARKER}\nbody\n"})


def test_post_comment_from_a_fork_or_without_a_token_is_a_notice(github, monkeypatch, capsys):
    from ui_audit.cli import main

    github.event({"pull_request": {"number": 3}})

    def forbidden(method, url, token, body=None):
        raise ci.urllib.error.HTTPError(url, 403, "Resource not accessible by integration", {}, None)

    monkeypatch.setattr(ci, "_api", forbidden)
    assert main(["ci", "--post-comment", str(github.summary)]) == 0
    assert "::notice::could not comment on the pull request (403)" in capsys.readouterr().err
    monkeypatch.delenv("UI_AUDIT_GITHUB_TOKEN")
    assert main(["ci", "--post-comment", str(github.summary)]) == 0
    assert "no GitHub token" in capsys.readouterr().err
    github.event({})  # a push: nothing to comment on
    assert main(["ci", "--post-comment", str(github.summary)]) == 0


def test_post_comment_in_a_workflow_run_trusts_the_artifact_only_for_the_audited_commit(github):
    from ui_audit.cli import main

    (github.summary.parent / "pull-request.json").write_text(json.dumps({"number": 9}))
    github.heads["9"] = "abc"
    github.event({"workflow_run": {"head_sha": "abc"}})
    assert main(["ci", "--post-comment", str(github.summary)]) == 0
    assert github.calls[0][:2] == ("GET", "https://api/repos/o/r/pulls/9")
    assert github.calls[-1][:2] == ("POST", "https://api/repos/o/r/issues/9/comments")

    github.calls.clear()
    github.event({"workflow_run": {"head_sha": "other"}})  # the artifact names a pull request it did not audit
    assert main(["ci", "--post-comment", str(github.summary)]) == 0
    assert [c[0] for c in github.calls] == ["GET"]


def test_the_base_commit_is_fetched_without_credentials(tmp_path):
    # actions/checkout with persist-credentials: false leaves a shallow clone and a plain origin URL.
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "index.html").write_text("base")
    git("init", "-q", cwd=upstream)
    git("add", ".", cwd=upstream)
    git("commit", "-qm", "base", cwd=upstream)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=upstream, capture_output=True, text=True).stdout.strip()
    (upstream / "index.html").write_text("head")
    git("commit", "-qam", "head", cwd=upstream)
    git("clone", "-q", "--depth=1", f"file://{upstream}", str(tmp_path / "clone"), cwd=tmp_path)
    path, sha = ci.base_worktree(tmp_path / "clone", base, tmp_path / "base")
    assert sha == base and (path / "index.html").read_text() == "base"
