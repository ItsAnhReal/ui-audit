from ui_audit.cli import main


def test_install_skill_for_other_agents(tmp_path):
    assert main(["install-skill", "--target", "agents", "--project-root", str(tmp_path)]) == 0
    assert (tmp_path / ".agents/skills/ui-audit/SKILL.md").read_text().startswith("---\nname: ui-audit")
    assert not (tmp_path / ".claude").exists()
    assert main(["install-skill", "--agent", "all", "--project-root", str(tmp_path / "all")]) == 0
    for agent in ("claude", "codex", "agents"):
        assert (tmp_path / "all" / f".{agent}/skills/ui-audit/SKILL.md").is_file()
    # The default stays the two agents it always installed for.
    assert main(["install-skill", "--project-root", str(tmp_path / "default")]) == 0
    assert not (tmp_path / "default/.agents").exists()


def test_init_suggests_agents_md_lines(tmp_path, capsys):
    (tmp_path / "index.html").write_text("<h1>x</h1>")
    assert main(["init", "--project-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "AGENTS.md" in out and "ui-audit show" in out and "ui-audit verify" in out
