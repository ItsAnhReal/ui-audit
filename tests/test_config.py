import tomllib

import pytest

from ui_audit.config import Config, ConfigError, from_dict, load, render_template


def test_defaults():
    cfg = Config()
    assert cfg.viewports.min_width == 320 and cfg.viewports.max_captures == 10
    assert "crawl" in cfg.routes.discover


def test_unknown_keys_are_rejected():
    with pytest.raises(ConfigError, match="unknown key"):
        from_dict({"base_ur": "x"})
    with pytest.raises(ConfigError, match=r"\[viewports\]"):
        from_dict({"viewports": {"widths_typo": [1]}})
    with pytest.raises(ConfigError, match="discovery"):
        from_dict({"routes": {"discover": ["magic"]}})


def test_load_resolves_project_root_relative_to_file(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "ui-audit.toml").write_text('base_url = "http://localhost:5173"\nproject_root = "web"\n[viewports]\nmax_captures = 4\n')
    cfg, path = load(start=app / "sub" if False else app)
    assert path == app / "ui-audit.toml"
    assert cfg.project_root == str((app / "web").resolve())
    assert cfg.viewports.max_captures == 4


def test_template_round_trips():
    text = render_template("http://localhost:3000", ["/", "/pricing"])
    cfg = from_dict(tomllib.loads(text))
    assert cfg.routes.include == ["/", "/pricing"]
