"""Configuration: defaults, `ui-audit.toml` loading, and CLI overrides."""

from __future__ import annotations

import base64
import fnmatch
import os
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .issues import DETERMINISTIC_CHECKS, SEVERITY_ORDER

CONFIG_FILENAME = "ui-audit.toml"

# The four presets every audit captures, in priority order.
STANDARD_VIEWPORTS: list[tuple[str, int, int]] = [
    ("mobile", 390, 844),
    ("tablet", 768, 1024),
    ("laptop", 1366, 768),
    ("desktop", 1920, 1080),
]

DISCOVERY_METHODS = ("config", "source", "sitemap", "crawl")

# Playwright's three engines. WebKit is the engine behind Safari.
BROWSERS = ("chromium", "webkit", "firefox")
BROWSER_ALIASES = {"chrome": "chromium", "safari": "webkit"}


def parse_browsers(value) -> list[str]:
    """`"chromium,safari"` or a list, as engine names in the given order without repeats."""
    items = value.split(",") if isinstance(value, str) else list(value)
    names: list[str] = []
    for item in items:
        name = str(item).strip().lower()
        name = BROWSER_ALIASES.get(name, name)
        if not name:
            continue
        if name not in BROWSERS:
            raise ConfigError(f"unknown browser {item!r}; use {', '.join(BROWSERS)} (or safari for webkit)")
        if name not in names:
            names.append(name)
    if not names:
        raise ConfigError("name at least one browser")
    return names


@dataclass
class RouteConfig:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=lambda: ["/logout*", "/signout*", "/api/*"])
    discover: list[str] = field(default_factory=lambda: list(DISCOVERY_METHODS))
    # Concrete values for dynamic segments, e.g. {"/blog/[slug]" = "/blog/hello-world"}.
    samples: dict[str, str] = field(default_factory=dict)
    max_routes: int = 25
    crawl_depth: int = 2
    # Skip routes that render the app's not-found page, redirect to, or repeat a route already audited.
    dedupe: bool = True
    # Per route pattern: {route = "/pricing*", widths = [...], ignore_selectors = [...]}.
    overrides: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StateConfig:
    auto: bool = True
    max_per_route: int = 4
    # Each entry: {name, route, actions = [{click = "..."}, {fill = "...", value = "..."}, ...]}
    custom: list[dict[str, Any]] = field(default_factory=list)
    # Extra words that mark a trigger as unsafe to click automatically.
    unsafe_words: list[str] = field(default_factory=list)
    # Turn optional cookies down once, so a consent banner does not cover every page.
    dismiss_consent: bool = True
    # Widths probed in states other than the initial page: "full" sweeps the whole range like
    # the initial page; "key" probes only the presets, the breakpoints and the widths where
    # the initial page changed, which is where an opened menu or dialog usually breaks too.
    sweep: str = "full"


@dataclass
class ViewportConfig:
    min_width: int = 320
    max_width: int = 1920
    sweep_step: int = 80
    breakpoint_neighbors: bool = True
    refine: bool = True
    max_refinements: int = 6
    max_captures: int = 10
    # Widths below this are measured as a phone (meta viewport, touch, `hover: none`); 0 turns it off.
    # Firefox cannot emulate a phone and stays a desktop browser at every width.
    mobile_below: int = 768
    # Explicit widths replace the sweep entirely (targeted reruns).
    widths: list[int] = field(default_factory=list)


@dataclass
class CheckConfig:
    min_target_size: int = 24
    overlap_threshold: float = 0.2
    max_issues_per_check: int = 15
    ignore_selectors: list[str] = field(default_factory=list)
    # Checks neither run nor reported, e.g. ["tiny-text"].
    disable: list[str] = field(default_factory=list)
    # Severity per check instead of the measured one, e.g. {"small-target" = "P3"}.
    severity: dict[str, str] = field(default_factory=dict)
    # Checks of your own: JavaScript files relative to project_root, each reported as rule:<file name>.
    rules: list[str] = field(default_factory=list)


@dataclass
class TimeoutConfig:
    # Milliseconds a page may take to load.
    navigation: int = 30000
    # Milliseconds to wait after loading for the network to go quiet; 0 does not wait.
    network_idle: int = 5000
    # Milliseconds a setup or state action waits for its element.
    action: int = 3000
    # Milliseconds `wait_for` and `wait_for_url` wait.
    wait_for: int = 5000


@dataclass
class Config:
    base_url: str = "http://localhost:3000"
    project_root: str = "."
    output: str = ".ui-audit/latest"
    annotate: bool = True
    storage_state: str = ""
    browser_path: str = ""
    # Engines to audit in, the first one leading: route discovery and deduplication happen there.
    browsers: list[str] = field(default_factory=lambda: ["chromium"])
    settle_ms: int = 150
    # Browser language, e.g. "de" or "fr-FR"; empty keeps Chromium's default (en-US).
    locale: str = ""
    # Findings accepted as intentional, relative to project_root; see `ui-audit accept`.
    accepted_file: str = "ui-audit.accepted.json"
    # Actions run once on "/" before anything is measured, e.g. [{click = "#close-promo"}].
    setup: list[dict[str, Any]] = field(default_factory=list)
    # Requests turned away: "trackers" (analytics that render nothing) or host names. [] blocks nothing.
    block_requests: list[str] = field(default_factory=lambda: ["trackers"])
    # Routes measured at the same time, each in a browser of its own; 0 picks from the CPU count.
    workers: int = 1
    # Sent with every request to the app's own origin, e.g. {"X-Preview-Token" = "${PREVIEW_TOKEN}"}.
    headers: dict[str, str] = field(default_factory=dict)
    # HTTP basic auth for a staging server: {username = "...", password = "${STAGING_PASSWORD}"}.
    http_credentials: dict[str, str] = field(default_factory=dict)
    # Accept self-signed and otherwise invalid certificates.
    ignore_https_errors: bool = False
    routes: RouteConfig = field(default_factory=RouteConfig)
    states: StateConfig = field(default_factory=StateConfig)
    viewports: ViewportConfig = field(default_factory=ViewportConfig)
    checks: CheckConfig = field(default_factory=CheckConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    # Values that came from ${VAR}: path -> (as written, as resolved). Not a setting.
    _env: dict[tuple, tuple[str, str]] = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self, redact: bool = True) -> dict[str, Any]:
        """The settings as stored in report.json: values read from the environment as their
        ${VAR}, and secrets written into the file left out. `redact=False` keeps those secrets,
        for handing to a process on this machine only, never for writing down."""
        data = asdict(self)
        data.pop("_env")
        for path, (raw, value) in self._env.items():
            *parents, last = path
            holder: Any = data
            try:
                for key in parents:
                    holder = holder[key]
                if holder[last] == value:
                    holder[last] = raw
            except (KeyError, IndexError, TypeError):
                continue  # changed since it was read
        for holder, key in _secret_places(data) if redact else []:
            if "${" not in str(holder[key]):
                holder[key] = REDACTED
        return data

    def route_settings(self, route: str) -> tuple[list[int], list[str]]:
        """(widths, ignore_selectors) for a route: the first matching override's widths, else
        `viewports.widths`; `checks.ignore_selectors` plus those of every matching override."""
        widths: list[int] = []
        ignore = list(self.checks.ignore_selectors)
        for override in self.routes.overrides:
            if fnmatch.fnmatch(route, override["route"]):
                widths = widths or list(override.get("widths") or [])
                ignore += [s for s in override.get("ignore_selectors") or [] if s not in ignore]
        return widths or list(self.viewports.widths), ignore

    def request_headers(self) -> dict[str, str]:
        """Headers for requests outside the browser (sitemaps): `headers` plus basic auth."""
        headers = dict(self.headers)
        if self.http_credentials:
            pair = f"{self.http_credentials['username']}:{self.http_credentials['password']}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        return headers


# Stands in for a secret that was written into ui-audit.toml instead of read from the environment.
REDACTED = "<redacted>"


def _secret_places(data: dict) -> list[tuple[dict, str]]:
    places: list[tuple[dict, str]] = [(data["headers"], name) for name in data.get("headers") or {}]
    if (data.get("http_credentials") or {}).get("password"):
        places.append((data["http_credentials"], "password"))
    return places


def rule_check(path: str) -> str:
    """The check name a rule file's findings carry: rule:<file name without .js>."""
    return "rule:" + Path(path).stem


def known_checks(cfg: Config) -> set[str]:
    return set(DETERMINISTIC_CHECKS) | {rule_check(path) for path in cfg.checks.rules}


def rule_sources(cfg: Config) -> list[tuple[str, str]]:
    """(check name, source) of every rule file; a file that cannot be read is a config error."""
    found = []
    for path in cfg.checks.rules:
        file = Path(path) if Path(path).is_absolute() else Path(cfg.project_root) / path
        try:
            source = file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"checks.rules: cannot read {file} ({exc.__class__.__name__})") from exc
        found.append((rule_check(path), source))
    return found


_SECTIONS = {
    "routes": RouteConfig,
    "states": StateConfig,
    "viewports": ViewportConfig,
    "checks": CheckConfig,
    "timeouts": TimeoutConfig,
}

# ${VAR}, ${VAR:-default}; $${VAR} is the literal text ${VAR}.
_ENV_REF = re.compile(r"\$(\$)?\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value: Any, path: tuple, found: dict[tuple, tuple[str, str]]) -> Any:
    """Replace ${VAR} in every string with the environment variable's value."""
    if isinstance(value, dict):
        return {key: _expand(item, (*path, key), found) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item, (*path, n), found) for n, item in enumerate(value)]
    if not isinstance(value, str) or "${" not in value:
        return value

    def substitute(match: re.Match) -> str:
        if match.group(1):
            return match.group(0)[1:]
        name, default = match.group(2), match.group(3)
        if os.environ.get(name):
            return os.environ[name]
        if default is not None:
            return default
        if name in os.environ:
            return ""
        where = ".".join(str(part) for part in path)
        raise ConfigError(f"environment variable {name} is not set (used in {where})")

    resolved = _ENV_REF.sub(substitute, value)
    found[path] = (value, resolved)
    return resolved


class ConfigError(ValueError):
    pass


def _build(cls: Any, data: dict[str, Any], where: str):
    known = {name for name in cls.__dataclass_fields__ if not name.startswith("_")}
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}")
    return cls(**data)


def from_dict(data: dict[str, Any]) -> Config:
    env: dict[tuple, tuple[str, str]] = {}
    data = _expand(dict(data), (), env)
    sections = {name: data.pop(name, {}) for name in _SECTIONS}
    cfg = _build(Config, data, "top level")
    cfg._env = env
    cfg.browsers = parse_browsers(cfg.browsers)
    for name, cls in _SECTIONS.items():
        if not isinstance(sections[name], dict):
            raise ConfigError(f"[{name}] must be a table")
        setattr(cfg, name, _build(cls, sections[name], f"[{name}]"))
    bad = set(cfg.routes.discover) - set(DISCOVERY_METHODS)
    if bad:
        raise ConfigError(f"unknown discovery method(s): {', '.join(sorted(bad))}")
    if cfg.states.sweep not in ("full", "key"):
        raise ConfigError('states.sweep must be "full" or "key"')
    validate(cfg)
    return cfg


def _number(value, where: str, low: float | None = None, high: float | None = None, integer: bool = True):
    kinds = (int,) if integer else (int, float)
    if isinstance(value, bool) or not isinstance(value, kinds):
        raise ConfigError(f"{where} must be {'an integer' if integer else 'a number'}, not {value!r}")
    if (low is not None and value < low) or (high is not None and value > high):
        if high is None:
            raise ConfigError(f"{where} must be at least {low}, not {value!r}")
        raise ConfigError(f"{where} must be between {low} and {high}, not {value!r}")


def _strings(value, where: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{where} must be a list of strings")


def _table(value, where: str, allowed: set[str], required: frozenset[str] = frozenset()) -> None:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a table")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}")
    missing = sorted(required - set(value))
    if missing:
        raise ConfigError(f"{where} needs {', '.join(missing)}")


# Actions for `setup` and `[[states.custom]]`: the key names the action, its value the target.
# `fill` and `select` also take a `value`.
ACTIONS = ("click", "hover", "fill", "select", "check", "uncheck", "press", "scroll", "goto",
           "wait", "wait_for", "wait_for_url")


def describe_action(action: dict) -> str:
    """`click '#cart'`, for messages about a step."""
    kind = next((key for key in ACTIONS if key in action), None)
    if kind is None:
        return str(action)
    return f"{kind} {action[kind]!r}" + (f" value {action['value']!r}" if "value" in action else "")


def _actions(actions, where: str) -> None:
    if not isinstance(actions, list):
        raise ConfigError(f"{where} must be a list of actions")
    for n, action in enumerate(actions, 1):
        step = f"{where}, step {n}"
        if not isinstance(action, dict):
            raise ConfigError(f'{step} must be a table such as {{ click = "#menu" }}')
        kinds = [key for key in action if key in ACTIONS]
        if len(kinds) != 1:
            raise ConfigError(f"{step} must name exactly one action ({', '.join(ACTIONS)}), not {action!r}")
        kind = kinds[0]
        extra = sorted(set(action) - {kind} - ({"value"} if kind in ("fill", "select") else set()))
        if extra:
            raise ConfigError(f"unknown key(s) in {step} ({kind}): {', '.join(extra)}")
        target = action[kind]
        if kind == "wait":
            _number(target, f"{step} (wait)", 0)
        elif kind == "scroll":
            if isinstance(target, bool) or not isinstance(target, (str, int)):
                raise ConfigError(f"{step} (scroll) must be a selector or a number of pixels from the top")
        elif not isinstance(target, str) or not target:
            raise ConfigError(f"{step} ({kind}) must be a non-empty string")
        if kind == "select" and not isinstance(action.get("value", ""), (str, list)):
            raise ConfigError(f"{step} (select): value must be a string or a list of strings")


def validate(cfg: Config) -> None:
    """Reject numbers out of range and malformed tables, with the key that holds them."""
    _number(cfg.settle_ms, "settle_ms", 0)
    _number(cfg.workers, "workers", 0, 16)
    if not isinstance(cfg.block_requests, list) or not all(isinstance(e, str) for e in cfg.block_requests):
        raise ConfigError('block_requests must be a list of host names or "trackers"')
    _actions(cfg.setup, "setup")
    if not isinstance(cfg.headers, dict) or not all(isinstance(v, str) for v in cfg.headers.values()):
        raise ConfigError('headers must be a table of strings, e.g. { "X-Preview-Token" = "${PREVIEW_TOKEN}" }')
    if cfg.http_credentials:
        _table(cfg.http_credentials, "http_credentials", {"username", "password"}, frozenset({"username", "password"}))
        if not all(isinstance(v, str) for v in cfg.http_credentials.values()):
            raise ConfigError("http_credentials: username and password must be strings")
    for holder, key in _secret_places({"headers": cfg.headers, "http_credentials": cfg.http_credentials}):
        if holder[key] == REDACTED:
            raise ConfigError("a report does not keep secrets that were written into ui-audit.toml; "
                              "write them as ${VAR} to run again with them")
    if not isinstance(cfg.ignore_https_errors, bool):
        raise ConfigError("ignore_https_errors must be true or false")
    _number(cfg.timeouts.navigation, "timeouts.navigation", 1)
    _number(cfg.timeouts.network_idle, "timeouts.network_idle", 0)
    _number(cfg.timeouts.action, "timeouts.action", 1)
    _number(cfg.timeouts.wait_for, "timeouts.wait_for", 1)
    _number(cfg.routes.max_routes, "routes.max_routes", 1)
    _number(cfg.routes.crawl_depth, "routes.crawl_depth", 0)
    if not isinstance(cfg.routes.overrides, list):
        raise ConfigError("routes.overrides must be a list of [[routes.overrides]] tables")
    for n, override in enumerate(cfg.routes.overrides, 1):
        where = f"routes.overrides #{n}"
        _table(override, where, {"route", "widths", "ignore_selectors"}, frozenset({"route"}))
        if not isinstance(override["route"], str) or not override["route"]:
            raise ConfigError(f'{where}: route must be a route or pattern such as "/blog/*"')
        if not isinstance(override.get("widths", []), list):
            raise ConfigError(f"{where}: widths must be a list of widths")
        for width in override.get("widths", []):
            _number(width, f"every width in {where}", 1)
        _strings(override.get("ignore_selectors", []), f"{where}: ignore_selectors")
    _number(cfg.states.max_per_route, "states.max_per_route", 0)
    if not isinstance(cfg.states.custom, list):
        raise ConfigError("states.custom must be a list of [[states.custom]] tables")
    for n, entry in enumerate(cfg.states.custom, 1):
        _table(entry, f"states.custom #{n}", {"name", "route", "actions", "applies_to"})
        where = f"state \"{entry.get('name') or 'custom'}\""
        if entry.get("applies_to", "any") not in ("narrow", "wide", "any"):
            raise ConfigError(f'{where}: applies_to must be "narrow", "wide" or "any"')
        _actions(entry.get("actions", []), where)
    vp = cfg.viewports
    _number(vp.min_width, "viewports.min_width", 1)
    _number(vp.max_width, "viewports.max_width", 1)
    _number(vp.sweep_step, "viewports.sweep_step", 1)
    _number(vp.max_refinements, "viewports.max_refinements", 0)
    _number(vp.max_captures, "viewports.max_captures", 0)
    _number(vp.mobile_below, "viewports.mobile_below", 0)
    if not isinstance(vp.widths, list):
        raise ConfigError("viewports.widths must be a list of widths")
    for width in vp.widths:
        _number(width, "every width in viewports.widths", 1)
    if vp.min_width > vp.max_width:
        raise ConfigError("viewports.min_width must not exceed viewports.max_width")
    _number(cfg.checks.min_target_size, "checks.min_target_size", 0)
    _number(cfg.checks.overlap_threshold, "checks.overlap_threshold", 0, 1, integer=False)
    _number(cfg.checks.max_issues_per_check, "checks.max_issues_per_check", 1)
    _strings(cfg.checks.ignore_selectors, "checks.ignore_selectors")
    _strings(cfg.checks.rules, "checks.rules")
    for path in cfg.checks.rules:
        if not path.endswith(".js"):
            raise ConfigError(f"checks.rules: {path!r} is not a .js file")
    names = [rule_check(path) for path in cfg.checks.rules]
    if len(set(names)) != len(names):
        raise ConfigError("checks.rules: two rule files have the same name")
    known = known_checks(cfg)
    _strings(cfg.checks.disable, "checks.disable")
    for check in cfg.checks.disable:
        if check not in known:
            raise ConfigError(f"checks.disable: unknown check {check!r}")
    if not isinstance(cfg.checks.severity, dict):
        raise ConfigError('checks.severity must be a table such as { "small-target" = "P3" }')
    for check, level in cfg.checks.severity.items():
        if check not in known:
            raise ConfigError(f"checks.severity: unknown check {check!r}")
        if level not in SEVERITY_ORDER:
            raise ConfigError(f"checks.severity.{check} must be P1, P2 or P3, not {level!r}")


def find_config(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load(path: Path | None = None, start: Path | None = None) -> tuple[Config, Path | None]:
    """Load a config file, or return defaults when none exists."""
    if path is None:
        path = find_config(start or Path.cwd())
    if path is None:
        return Config(), None
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    cfg = from_dict(data)
    # A relative project_root is relative to the config file, not the shell.
    root = Path(cfg.project_root)
    if not root.is_absolute():
        cfg.project_root = str((path.parent / root).resolve())
    return cfg, path


TEMPLATE = """\
# ui-audit configuration. Every key is optional; defaults are shown.
# Every setting is explained in docs/configuration.md. Strings may use ${{VAR}} for environment variables.
base_url = "{base_url}"
project_root = "."
output = ".ui-audit/latest"
annotate = true
# Playwright storage state (cookies/localStorage) for authenticated audits.
storage_state = ""
# Chromium executable; leave empty to use Playwright's own browser.
browser_path = ""
# Browsers to audit in: chromium, webkit (Safari's engine), firefox.
browsers = ["chromium"]
# Actions run on "/" before anything is measured and again on every page loaded.
# setup = [{{ click = "#close-promo" }}]
# Requests turned away: "trackers" (analytics that render nothing) or host names; [] for none.
block_requests = ["trackers"]
# Routes measured at the same time, each in its own browser; 0 picks from the CPU count.
workers = 1
# Sent with every request to the app's own origin; keep secrets in environment variables.
# headers = {{ "X-Preview-Token" = "${{PREVIEW_TOKEN}}" }}
# Basic auth for a staging server.
# http_credentials = {{ username = "preview", password = "${{STAGING_PASSWORD}}" }}
ignore_https_errors = false

[routes]
include = {include}
exclude = ["/logout*", "/signout*", "/api/*"]
discover = ["config", "source", "sitemap", "crawl"]
max_routes = 25
dedupe = true
# samples = {{ "/blog/[slug]" = "/blog/hello-world" }}
# [[routes.overrides]]
# route = "/admin/*"
# widths = [1280, 1920]
# ignore_selectors = [".chart"]

[states]
auto = true
max_per_route = 4
dismiss_consent = true
# [[states.custom]]
# name = "cart-open"
# route = "/"
# actions = [{{ click = "#cart-button" }}, {{ wait_for = ".cart-drawer" }}]

[viewports]
min_width = 320
max_width = 1920
sweep_step = 80
breakpoint_neighbors = true
max_captures = 10
# Widths below this are measured as a phone with touch; 0 measures every width as a desktop.
mobile_below = 768

[checks]
min_target_size = 24
ignore_selectors = []
# Checks neither run nor reported, and severities instead of the measured ones.
disable = []
# severity = {{ "small-target" = "P3" }}
# Checks of your own, one JavaScript function per file, reported as rule:<file name>.
rules = []

[timeouts]
navigation = 30000
network_idle = 5000
action = 3000
wait_for = 5000
"""


def render_template(base_url: str, include: list[str]) -> str:
    rendered = "[" + ", ".join(f'"{route}"' for route in include) + "]"
    return TEMPLATE.format(base_url=base_url, include=rendered)
