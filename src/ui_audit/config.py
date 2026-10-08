"""Configuration: defaults, `ui-audit.toml` loading, and CLI overrides."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "ui-audit.toml"

# The four presets every audit captures, in priority order.
STANDARD_VIEWPORTS: list[tuple[str, int, int]] = [
    ("mobile", 390, 844),
    ("tablet", 768, 1024),
    ("laptop", 1366, 768),
    ("desktop", 1920, 1080),
]

DISCOVERY_METHODS = ("config", "source", "sitemap", "crawl")


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
    # Explicit widths replace the sweep entirely (targeted reruns).
    widths: list[int] = field(default_factory=list)


@dataclass
class CheckConfig:
    min_target_size: int = 24
    overlap_threshold: float = 0.2
    max_issues_per_check: int = 15
    ignore_selectors: list[str] = field(default_factory=list)


@dataclass
class Config:
    base_url: str = "http://localhost:3000"
    project_root: str = "."
    output: str = ".ui-audit/latest"
    annotate: bool = True
    storage_state: str = ""
    browser_path: str = ""
    settle_ms: int = 150
    # Browser language, e.g. "de" or "fr-FR"; empty keeps Chromium's default (en-US).
    locale: str = ""
    # Findings accepted as intentional, relative to project_root; see `ui-audit accept`.
    accepted_file: str = "ui-audit.accepted.json"
    # Actions run once on "/" before anything is measured, e.g. [{click = "#close-promo"}].
    setup: list[dict[str, Any]] = field(default_factory=list)
    routes: RouteConfig = field(default_factory=RouteConfig)
    states: StateConfig = field(default_factory=StateConfig)
    viewports: ViewportConfig = field(default_factory=ViewportConfig)
    checks: CheckConfig = field(default_factory=CheckConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SECTIONS = {
    "routes": RouteConfig,
    "states": StateConfig,
    "viewports": ViewportConfig,
    "checks": CheckConfig,
}


class ConfigError(ValueError):
    pass


def _build(cls: type, data: dict[str, Any], where: str):
    known = cls.__dataclass_fields__
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}")
    return cls(**data)


def from_dict(data: dict[str, Any]) -> Config:
    data = dict(data)
    sections = {name: data.pop(name, {}) for name in _SECTIONS}
    cfg = _build(Config, data, "top level")
    for name, cls in _SECTIONS.items():
        if not isinstance(sections[name], dict):
            raise ConfigError(f"[{name}] must be a table")
        setattr(cfg, name, _build(cls, sections[name], f"[{name}]"))
    bad = set(cfg.routes.discover) - set(DISCOVERY_METHODS)
    if bad:
        raise ConfigError(f"unknown discovery method(s): {', '.join(sorted(bad))}")
    if cfg.states.sweep not in ("full", "key"):
        raise ConfigError('states.sweep must be "full" or "key"')
    if cfg.viewports.min_width > cfg.viewports.max_width:
        raise ConfigError("viewports.min_width must not exceed viewports.max_width")
    return cfg


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
base_url = "{base_url}"
project_root = "."
output = ".ui-audit/latest"
annotate = true
# Playwright storage state (cookies/localStorage) for authenticated audits.
storage_state = ""
# Chromium executable; leave empty to use Playwright's own browser.
browser_path = ""
# Actions run once on "/" before anything is measured.
# setup = [{{ click = "#close-promo" }}]

[routes]
include = {include}
exclude = ["/logout*", "/signout*", "/api/*"]
discover = ["config", "source", "sitemap", "crawl"]
max_routes = 25
dedupe = true
# samples = {{ "/blog/[slug]" = "/blog/hello-world" }}

[states]
auto = true
max_per_route = 4
dismiss_consent = true
# [[states.custom]]
# name = "cart-open"
# route = "/"
# actions = [{{ click = "#cart-button" }}]

[viewports]
min_width = 320
max_width = 1920
sweep_step = 80
breakpoint_neighbors = true
max_captures = 10

[checks]
min_target_size = 24
ignore_selectors = []
"""


def render_template(base_url: str, include: list[str]) -> str:
    rendered = "[" + ", ".join(f'"{route}"' for route in include) + "]"
    return TEMPLATE.format(base_url=base_url, include=rendered)
