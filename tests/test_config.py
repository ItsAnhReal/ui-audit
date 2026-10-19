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
    ({"viewports": {"mobile_below": -1}}, r"viewports.mobile_below must be at least 0"),
])
def test_numbers_out_of_range_are_rejected(data, message):
    with pytest.raises(ConfigError, match=message):
        from_dict(data)


def test_zero_is_a_valid_setting():
    cfg = from_dict({"checks": {"overlap_threshold": 0, "min_target_size": 0},
                     "viewports": {"max_captures": 0, "mobile_below": 0}})
    assert cfg.checks.overlap_threshold == 0 and cfg.checks.min_target_size == 0
    assert cfg.viewports.mobile_below == 0


def test_checks_can_be_turned_off_and_rated_and_unknown_names_are_errors():
    cfg = from_dict({"checks": {"disable": ["tiny-text"], "severity": {"small-target": "P3", "rule:autoplay": "P1"},
                                "rules": ["rules/autoplay.js"]}})
    assert cfg.checks.disable == ["tiny-text"] and cfg.checks.severity["rule:autoplay"] == "P1"
    with pytest.raises(ConfigError, match="checks.disable: unknown check 'tiny-txt'"):
        from_dict({"checks": {"disable": ["tiny-txt"]}})
    with pytest.raises(ConfigError, match="checks.severity: unknown check 'rule:other'"):
        from_dict({"checks": {"severity": {"rule:other": "P1"}}})
    with pytest.raises(ConfigError, match="checks.severity.small-target must be P1, P2 or P3"):
        from_dict({"checks": {"severity": {"small-target": "high"}}})
    with pytest.raises(ConfigError, match="not a .js file"):
        from_dict({"checks": {"rules": ["rules/a.ts"]}})
    with pytest.raises(ConfigError, match="same name"):
        from_dict({"checks": {"rules": ["a/x.js", "b/x.js"]}})


def test_rule_files_are_read_from_the_project(tmp_path):
    from ui_audit.config import rule_sources

    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "autoplay.js").write_text("() => []", encoding="utf-8")
    cfg = from_dict({"project_root": str(tmp_path), "checks": {"rules": ["rules/autoplay.js"]}})
    assert rule_sources(cfg) == [("rule:autoplay", "() => []")]
    cfg.checks.rules.append("rules/missing.js")
    with pytest.raises(ConfigError, match="cannot read"):
        rule_sources(cfg)


def test_route_overrides_set_widths_and_add_ignored_selectors():
    cfg = from_dict({"viewports": {"widths": [390]}, "checks": {"ignore_selectors": [".chat"]},
                     "routes": {"overrides": [{"route": "/blog/*", "widths": [600, 900], "ignore_selectors": [".ad"]},
                                              {"route": "/blog/old", "widths": [320], "ignore_selectors": [".x"]}]}})
    assert cfg.route_settings("/blog/old") == ([600, 900], [".chat", ".ad", ".x"])
    assert cfg.route_settings("/") == ([390], [".chat"])
    with pytest.raises(ConfigError, match=r"unknown key\(s\) in routes.overrides #1: width"):
        from_dict({"routes": {"overrides": [{"route": "/", "width": [1]}]}})
    with pytest.raises(ConfigError, match="routes.overrides #1 needs route"):
        from_dict({"routes": {"overrides": [{"widths": [500]}]}})
    with pytest.raises(ConfigError, match="every width in routes.overrides #1 must be at least 1"):
        from_dict({"routes": {"overrides": [{"route": "/", "widths": [0]}]}})


def test_environment_variables_are_read_and_never_written_back(monkeypatch):
    monkeypatch.setenv("STAGING_URL", "https://staging.example")
    monkeypatch.setenv("PREVIEW_TOKEN", "tok-123")
    monkeypatch.delenv("UNSET_FOR_TEST", raising=False)
    cfg = from_dict({"base_url": "${STAGING_URL}/app/", "headers": {"X-Preview": "Bearer ${PREVIEW_TOKEN}",
                                                                   "X-Literal": "plain-secret"},
                     "http_credentials": {"username": "${UNSET_FOR_TEST:-preview}", "password": "${PREVIEW_TOKEN}"},
                     "states": {"custom": [{"name": "s", "actions": [{"fill": "#q", "value": "$${NOT_A_VAR}"}]}]}})
    assert cfg.base_url == "https://staging.example/app/"
    assert cfg.headers["X-Preview"] == "Bearer tok-123" and cfg.http_credentials["username"] == "preview"
    assert cfg.states.custom[0]["actions"][0]["value"] == "${NOT_A_VAR}"
    stored = cfg.to_dict()
    assert "tok-123" not in str(stored) and "plain-secret" not in str(stored)
    assert stored["base_url"] == "${STAGING_URL}/app/"
    assert stored["headers"] == {"X-Preview": "Bearer ${PREVIEW_TOKEN}", "X-Literal": "<redacted>"}
    assert stored["http_credentials"]["password"] == "${PREVIEW_TOKEN}"
    assert stored["states"]["custom"][0]["actions"][0]["value"] == "$${NOT_A_VAR}"
    # For another process on this machine only: literal secrets kept, ${VAR} left to resolve there.
    assert cfg.to_dict(redact=False)["headers"]["X-Literal"] == "plain-secret"
    # A value changed after loading (a CLI option) is stored as it is now.
    cfg.base_url = "http://localhost:3000"
    assert cfg.to_dict()["base_url"] == "http://localhost:3000"
    with pytest.raises(ConfigError, match="report does not keep secrets"):
        from_dict(stored)
    del stored["headers"]["X-Literal"]
    again = from_dict(stored)
    assert again.headers["X-Preview"] == "Bearer tok-123"
    with pytest.raises(ConfigError, match=r"environment variable UNSET_FOR_TEST is not set \(used in headers.A\)"):
        from_dict({"headers": {"A": "${UNSET_FOR_TEST}"}})


def test_basic_auth_becomes_a_header_for_sitemaps():
    cfg = from_dict({"headers": {"X-A": "1"}, "http_credentials": {"username": "u", "password": "p"}})
    assert cfg.request_headers() == {"X-A": "1", "Authorization": "Basic dTpw"}
    with pytest.raises(ConfigError, match="http_credentials needs password"):
        from_dict({"http_credentials": {"username": "u"}})
    with pytest.raises(ConfigError, match="headers must be a table of strings"):
        from_dict({"headers": {"X-A": 1}})


@pytest.mark.parametrize(("data", "message"), [
    ({"setup": [{"klick": "#a"}]}, r"setup, step 1 must name exactly one action"),
    ({"setup": [{"click": "#a", "hover": "#b"}]}, r"setup, step 1 must name exactly one action"),
    ({"setup": [{"click": "#a", "value": "x"}]}, r"unknown key\(s\) in setup, step 1 \(click\): value"),
    ({"states": {"custom": [{"name": "cart", "actions": [{"click": "#a"}, {"scroll": True}]}]}},
     r'state "cart", step 2 \(scroll\) must be a selector or a number'),
    ({"states": {"custom": [{"name": "cart", "actions": [{"wait": -1}]}]}}, r'state "cart", step 1 \(wait\) must be at least 0'),
    ({"states": {"custom": [{"name": "cart", "action": []}]}}, r"unknown key\(s\) in states.custom #1: action"),
    ({"states": {"custom": [{"name": "cart", "applies_to": "phone"}]}}, r'state "cart": applies_to must be'),
    ({"timeouts": {"navigation": 0}}, r"timeouts.navigation must be at least 1"),
    ({"timeouts": {"idle": 1}}, r"unknown key\(s\) in \[timeouts\]: idle"),
    ({"ignore_https_errors": "yes"}, r"ignore_https_errors must be true or false"),
])
def test_malformed_settings_name_their_place(data, message):
    with pytest.raises(ConfigError, match=message):
        from_dict(data)


def test_every_action_kind_is_accepted_and_described():
    from ui_audit.config import describe_action

    actions = [{"click": "#a"}, {"hover": "#a"}, {"fill": "#q", "value": "x"}, {"select": "#s", "value": ["a", "b"]},
               {"check": "#c"}, {"uncheck": "#c"}, {"press": "Escape"}, {"scroll": "#footer"}, {"scroll": 400},
               {"goto": "/cart"}, {"wait": 100}, {"wait_for": ".drawer"}, {"wait_for_url": "**/cart"}]
    assert from_dict({"setup": actions}).setup == actions
    assert describe_action({"select": "#s", "value": "m"}) == "select '#s' value 'm'"


def test_template_mentions_every_section():
    text = render_template("http://localhost:3000", ["/"])
    for key in ("headers", "http_credentials", "ignore_https_errors", "[timeouts]", "disable", "severity", "rules",
                "[[routes.overrides]]", "docs/configuration.md"):
        assert key in text, key
