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


@pytest.mark.parametrize(("data", "message"), [
    ({"checks": {"overlap_threshold": 1.5}}, r"checks.overlap_threshold must be between 0 and 1, not 1.5"),
    ({"checks": {"overlap_threshold": "0.2"}}, r"checks.overlap_threshold must be a number"),
    ({"checks": {"max_issues_per_check": 0}}, r"checks.max_issues_per_check must be at least 1, not 0"),
    ({"checks": {"min_target_size": -1}}, r"checks.min_target_size must be at least 0"),
    ({"viewports": {"widths": [390, 0]}}, r"every width in viewports.widths must be at least 1"),
    ({"viewports": {"sweep_step": 0}}, r"viewports.sweep_step must be at least 1"),
    ({"viewports": {"min_width": 800, "max_width": 400}}, r"min_width must not exceed"),
    ({"viewports": {"max_captures": True}}, r"viewports.max_captures must be an integer"),
    ({"routes": {"max_routes": 0}}, r"routes.max_routes must be at least 1"),
])
def test_numbers_out_of_range_are_rejected(data, message):
    with pytest.raises(ConfigError, match=message):
        from_dict(data)


def test_zero_is_a_valid_setting():
    cfg = from_dict({"checks": {"overlap_threshold": 0, "min_target_size": 0}, "viewports": {"max_captures": 0}})
    assert cfg.checks.overlap_threshold == 0 and cfg.checks.min_target_size == 0
