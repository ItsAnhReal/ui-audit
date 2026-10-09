import pytest

from ui_audit.cli import main


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
    assert main(["init", "--project-root", str(tmp_path)]) == 1


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


def test_demo_audits_the_bundled_site_and_ignores_the_folders_config(tmp_path, monkeypatch):
    import socket
    import tomllib
    import urllib.request
    from pathlib import Path

    from ui_audit import cli

    seen = {}

    def fake_audit(args):
        cfg, path = cli._load_config(args)
        with urllib.request.urlopen(cfg.base_url + "/pricing.html") as response:  # served while the audit runs
            seen.update(status=response.status, cfg=cfg, path=path, args=args)
        return 0

    monkeypatch.chdir(tmp_path)
    (tmp_path / "ui-audit.toml").write_text('base_url = "http://localhost:3000"\nproject_root = "app"\n')
    monkeypatch.setattr(cli, "cmd_audit", fake_audit)
    with socket.socket() as taken:  # the default port in use: the demo moves to a free one
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        assert main(["demo", "--port", str(taken.getsockname()[1]), "--no-open"]) == 0
    assert seen["status"] == 200 and seen["path"] is None
    assert seen["cfg"].project_root == str(cli.DEMO_DIR) and seen["cfg"].output == ".ui-audit/demo"
    assert seen["args"].open is False and seen["cfg"].states.sweep == "key"
    with pytest.raises(OSError):  # stopped once the audit is done
        urllib.request.urlopen(seen["cfg"].base_url, timeout=2)

    # Every demo file ships in the wheel.
    pyproject = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text())
    globs = pyproject["tool"]["setuptools"]["package-data"]["ui_audit"]
    files = [p for p in cli.DEMO_DIR.iterdir()]
    assert files and all(any(p.match(g.split("/")[-1]) for g in globs if g.startswith("demo/")) for p in files)


def test_version_comes_from_the_installed_package():
    from importlib.metadata import version

    from ui_audit import __version__

    assert __version__ == version("ui-audit")
