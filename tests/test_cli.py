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
