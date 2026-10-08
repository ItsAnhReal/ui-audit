"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from importlib import resources
from pathlib import Path

from . import __version__
from .config import CONFIG_FILENAME, ConfigError, load, render_template

SKILL_TARGETS = {
    ("project", "claude"): Path(".claude/skills/ui-audit"),
    ("project", "codex"): Path(".codex/skills/ui-audit"),
    ("user", "claude"): Path("~/.claude/skills/ui-audit"),
    ("user", "codex"): Path("~/.codex/skills/ui-audit"),
}


def _widths(text: str) -> list[int]:
    try:
        return sorted({int(part) for part in text.split(",") if part.strip()})
    except ValueError as exc:
        raise argparse.ArgumentTypeError("widths must be comma-separated integers, e.g. 390,768") from exc


def _load_config(args):
    cfg, path = load(Path(args.config) if getattr(args, "config", None) else None)
    if getattr(args, "base_url", None):
        cfg.base_url = args.base_url
    if getattr(args, "project_root", None):
        cfg.project_root = args.project_root
    if getattr(args, "output", None):
        cfg.output = args.output
    if getattr(args, "browser_path", None):
        cfg.browser_path = args.browser_path
    return cfg, path


def cmd_init(args) -> int:
    from .routes import routes_from_source

    target = Path(args.project_root or ".") / CONFIG_FILENAME
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to overwrite)")
        return 1
    found, dynamic = routes_from_source(Path(args.project_root or "."), {})
    include = found[:15] or ["/"]
    target.write_text(render_template(args.base_url or "http://localhost:3000", include), encoding="utf-8")
    print(f"wrote {target} with {len(include)} route(s): {', '.join(include)}")
    if dynamic:
        print(f"dynamic routes need sample values in [routes] samples: {', '.join(dynamic[:10])}")
    gitignore = Path(args.project_root or ".") / ".gitignore"
    if gitignore.exists() and ".ui-audit/" not in gitignore.read_text(encoding="utf-8"):
        with gitignore.open("a", encoding="utf-8") as handle:
            handle.write("\n.ui-audit/\n")
        print("added .ui-audit/ to .gitignore")
    return 0


def cmd_doctor(args) -> int:
    ok = True

    def report(passed: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        ok &= passed
        print(f"  {'ok  ' if passed else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")

    print(f"ui-audit {__version__}")
    report(sys.version_info >= (3, 11), "python >= 3.11", sys.version.split()[0])
    try:
        cfg, path = _load_config(args)
        report(True, "config", str(path) if path else "none found, using defaults")
    except (ConfigError, OSError, ValueError) as exc:
        report(False, "config", str(exc))
        return 1
    try:
        from playwright.sync_api import sync_playwright

        from .browser import launch

        with sync_playwright() as playwright:
            browser = launch(playwright, cfg.browser_path)
            report(True, "chromium launches", browser.version)
            browser.close()
    except Exception as exc:  # noqa: BLE001 - report any launch failure
        report(False, "chromium launches", f"{str(exc).splitlines()[0]} (try `playwright install chromium` or --browser-path)")
    try:
        with urllib.request.urlopen(cfg.base_url, timeout=5) as response:  # noqa: S310 - local dev server
            report(response.status < 500, "app reachable", f"{cfg.base_url} ({response.status})")
    except Exception as exc:  # noqa: BLE001 - surface any network error
        report(False, "app reachable", f"{cfg.base_url} ({exc.__class__.__name__}); start the dev server first")
    for (scope, agent), target in SKILL_TARGETS.items():
        installed = (target.expanduser() / "SKILL.md").exists()
        print(f"  {'ok  ' if installed else '-   '}  skill for {agent} ({scope}) {'installed' if installed else 'not installed'}")
    return 0 if ok else 1


def cmd_audit(args) -> int:
    from .audit import run

    try:
        cfg, _ = _load_config(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if args.width:
        cfg.viewports.widths = args.width
    if args.no_states:
        cfg.states.auto = False
    if args.no_annotate:
        cfg.annotate = False
    if args.max_captures is not None:
        cfg.viewports.max_captures = args.max_captures
    if args.sweep_step:
        cfg.viewports.sweep_step = args.sweep_step
    log = (lambda _msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr))
    result = run(cfg, only_routes=args.route or None, log=log)

    counts = result["stats"]["issues"]
    out = Path(cfg.output)
    print(f"{counts['P1']} P1 · {counts['P2']} P2 · {counts['P3']} P3 across {len(result['routes'])} route(s), "
          f"{len(result['states'])} state(s), {len(result['captures'])} screenshot(s), {result['stats']['probes']} probes "
          f"in {result['stats']['seconds']}s")
    print(f"report: {out / 'report.json'}")
    print(f"contact sheet: {out / 'index.html'}")
    print(f"semantic review packet: {out / 'semantic-review.md'}")
    for error in result["errors"]:
        print(f"warning: {error}", file=sys.stderr)
    if args.fail_on:
        threshold = {"P1": ["P1"], "P2": ["P1", "P2"], "P3": ["P1", "P2", "P3"]}[args.fail_on]
        if any(counts[level] for level in threshold):
            return 2
    return 0


def cmd_merge(args) -> int:
    from . import report as report_mod
    from .semantic import merge

    out_dir = Path(args.report_dir)
    findings_path = Path(args.findings) if args.findings else out_dir / "agent-findings.json"
    report = report_mod.read_json(out_dir)
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    if isinstance(findings, dict):
        findings = findings.get("findings", [])
    added, errors = merge(report, findings)
    report["stats"]["issues"] = report_mod.summary_counts(report["issues"])
    report_mod.write_json(report, out_dir)
    report_mod.write_html(report, out_dir)
    print(f"merged {added} agent finding(s) into {out_dir / 'report.json'}")
    for error in errors:
        print(f"rejected {error}", file=sys.stderr)
    return 1 if errors else 0


def cmd_verify(args) -> int:
    from . import report as report_mod
    from . import verify

    base_dir, current_dir = Path(args.baseline), Path(args.current)
    baseline, current = report_mod.read_json(base_dir), report_mod.read_json(current_dir)
    result = verify.compare(baseline, current)
    out_dir = Path(args.output) if args.output else current_dir
    if args.pixel_diff:
        result["pixel_diffs"] = verify.pixel_diffs(baseline, current, base_dir, current_dir, out_dir)
    json_path, md_path = verify.write(result, out_dir)
    print(verify.render_markdown(result), end="")
    print(f"\nwritten: {json_path}, {md_path}")
    blocking = [i for i in result["introduced"] if i["severity"] in ("P1", "P2")]
    if args.strict:
        blocking += [i for i in result["persistent"] if i["severity"] in ("P1", "P2")]
    return 1 if blocking else 0


def cmd_install_skill(args) -> int:
    source = resources.files("ui_audit").joinpath("skill/SKILL.md")
    agents = ["claude", "codex"] if args.agent == "both" else [args.agent]
    for agent in agents:
        target = SKILL_TARGETS[(args.scope, agent)].expanduser()
        if args.scope == "project":
            target = Path(args.project_root or ".") / target
        target.mkdir(parents=True, exist_ok=True)
        with resources.as_file(source) as path:
            shutil.copyfile(path, target / "SKILL.md")
        print(f"installed {agent} skill: {target / 'SKILL.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ui-audit", description="Responsive UI Auditor")
    parser.add_argument("--version", action="version", version=f"ui-audit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, output=True):
        p.add_argument("--config", help=f"path to {CONFIG_FILENAME} (default: search upwards)")
        p.add_argument("--base-url", help="URL of the running app")
        p.add_argument("--project-root", help="source directory used for route discovery and source hints")
        p.add_argument("--browser-path", help="Chromium executable (or set UI_AUDIT_BROWSER_PATH)")
        if output:
            p.add_argument("--output", help="output directory (default .ui-audit/latest)")

    p = sub.add_parser("init", help=f"write a starter {CONFIG_FILENAME}")
    p.add_argument("--base-url")
    p.add_argument("--project-root")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("doctor", help="check Python, Chromium, config, app and installed skills")
    common(p, output=False)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("audit", help="discover, sweep, capture and report")
    common(p)
    p.add_argument("base_url_pos", nargs="?", metavar="URL", help="shorthand for --base-url")
    p.add_argument("--route", action="append", help="audit only this route (repeatable)")
    p.add_argument("--width", type=_widths, help="exact widths, e.g. 389,390,391 (disables the sweep)")
    p.add_argument("--sweep-step", type=int, help="sweep step in px (default 80)")
    p.add_argument("--max-captures", type=int, help="screenshot cap per route/state")
    p.add_argument("--no-states", action="store_true", help="skip automatic state discovery")
    p.add_argument("--no-annotate", action="store_true", help="skip annotated screenshots")
    p.add_argument("--fail-on", choices=["P1", "P2", "P3"], help="exit 2 if issues at or above this severity")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("merge-findings", help="merge agent findings into a report")
    p.add_argument("report_dir")
    p.add_argument("--findings", help="findings JSON (default <report_dir>/agent-findings.json)")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("verify", help="compare a baseline report with a new one")
    p.add_argument("baseline")
    p.add_argument("current")
    p.add_argument("--output", help="where to write verify.json/verify.md (default: current dir)")
    p.add_argument("--pixel-diff", action="store_true", help="also compute per-screenshot pixel diffs")
    p.add_argument("--strict", action="store_true", help="also fail on persistent P1/P2 issues")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("install-skill", help="install the shared agent skill")
    p.add_argument("--agent", choices=["claude", "codex", "both"], default="both")
    p.add_argument("--scope", choices=["project", "user"], default="project")
    p.add_argument("--project-root")
    p.set_defaults(func=cmd_install_skill)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "base_url_pos", None) and not args.base_url:
        args.base_url = args.base_url_pos
    return args.func(args)
