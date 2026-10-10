"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from collections import Counter
from importlib import resources
from pathlib import Path

from . import __version__
from .config import CONFIG_FILENAME, ConfigError, from_dict, load, parse_browsers, render_template
from .sources import SOURCE_EXTS

# Exit codes, the same for every command (README "Exit codes").
OK, FINDINGS, USAGE, FAILED = 0, 1, 2, 3

SKILL_TARGETS = {
    ("project", "claude"): Path(".claude/skills/ui-audit"),
    ("project", "codex"): Path(".codex/skills/ui-audit"),
    ("user", "claude"): Path("~/.claude/skills/ui-audit"),
    ("user", "codex"): Path("~/.codex/skills/ui-audit"),
}


class InputError(Exception):
    """A file the command was pointed at is missing or unreadable: a usage error, not a finding."""


def _read_input(path: Path, report: bool = True):
    """report.json in a run folder (or a JSON file when report=False), with a one-line error if it cannot be read."""
    target = path / "report.json" if report and (path.is_dir() or path.suffix != ".json") else path
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InputError(f"no report.json in {path}" if target != path else f"{path} not found") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"{target} is not valid JSON ({exc.msg}, line {exc.lineno})") from None
    except OSError as exc:
        raise InputError(f"cannot read {target}: {exc.strerror or exc}") from None


def _widths(text: str) -> list[int]:
    try:
        return sorted({int(part) for part in text.split(",") if part.strip()})
    except ValueError as exc:
        raise argparse.ArgumentTypeError("widths must be comma-separated integers, e.g. 390,768") from exc


def _browsers(text: str) -> list[str]:
    try:
        return parse_browsers(text)
    except ConfigError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _load_config(args):
    like = getattr(args, "like", None)
    if like:  # the settings an earlier run was made with, as its report.json recorded them
        report = Path(like) / "report.json"
        if not report.is_file():
            raise ConfigError(f"no report.json in {like}")
        cfg, path = from_dict(json.loads(report.read_text(encoding="utf-8"))["config"]), None
        if not getattr(args, "output", None):
            cfg.output = str(Path(like)) + "-again"  # never write over the run it copies
    elif getattr(args, "defaults_only", False):  # `ui-audit demo` ignores the ui-audit.toml of the folder it runs in
        cfg, path = from_dict({}), None
    else:
        cfg, path = load(Path(args.config) if getattr(args, "config", None) else None)
    if getattr(args, "base_url", None):
        cfg.base_url = args.base_url
    if getattr(args, "project_root", None):
        cfg.project_root = args.project_root
    if getattr(args, "output", None):
        cfg.output = args.output
    if getattr(args, "browser_path", None):
        cfg.browser_path = args.browser_path
    if getattr(args, "storage_state", None):
        cfg.storage_state = args.storage_state
    if getattr(args, "locale", None):
        cfg.locale = args.locale
    if getattr(args, "browsers", None):
        cfg.browsers = args.browsers
    if getattr(args, "fast", False):
        cfg.states.sweep = "key"
    return cfg, path


def cmd_init(args) -> int:
    from .routes import routes_from_source

    target = Path(args.project_root or ".") / CONFIG_FILENAME
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to overwrite)", file=sys.stderr)
        return USAGE
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
        return USAGE
    try:
        from playwright.sync_api import sync_playwright

        from .browser import launch

        with sync_playwright() as playwright:
            for engine in cfg.browsers:
                try:
                    browser = launch(playwright, cfg.browser_path, engine=engine)
                    report(True, f"{engine} launches", browser.version)
                    browser.close()
                except Exception as exc:  # noqa: BLE001 - report any launch failure
                    hint = f"try `playwright install {engine}`" + (" or --browser-path" if engine == "chromium" else "")
                    report(False, f"{engine} launches", f"{str(exc).splitlines()[0]} ({hint})")
    except Exception as exc:  # noqa: BLE001 - Playwright itself is missing or broken
        report(False, "playwright starts", str(exc).splitlines()[0])
    try:
        with urllib.request.urlopen(cfg.base_url, timeout=5) as response:  # noqa: S310 - local dev server
            report(response.status < 500, "app reachable", f"{cfg.base_url} ({response.status})")
    except Exception as exc:  # noqa: BLE001 - surface any network error
        report(False, "app reachable", f"{cfg.base_url} ({exc.__class__.__name__}); start the dev server first")
    for line in skill_status(Path(args.project_root or ".")):
        print(f"  {line}")
    return OK if ok else FAILED


def skill_status(project_root: Path, home: Path | None = None) -> list[str]:
    """One line per agent: which installed copy of the skill it reads, and whether that copy is current."""
    shipped = resources.files("ui_audit").joinpath("skill/SKILL.md").read_text(encoding="utf-8")
    lines = []
    for agent, name in (("claude", "Claude Code"), ("codex", "Codex")):
        found = []
        for scope in ("project", "user"):
            target = SKILL_TARGETS[(scope, agent)]
            path = project_root / target if scope == "project" else (home or Path.home()) / target.relative_to("~")
            if (path / "SKILL.md").is_file():
                found.append((scope, path / "SKILL.md"))
        if not found:
            lines.append(f"-     skill for {name}: not installed; only needed if you use {name} "
                         f"(`ui-audit install-skill --agent {agent}` puts it in this project)")
            continue
        old = [scope for scope, path in found if path.read_text(encoding="utf-8") != shipped]
        where = " and ".join(f"{scope} ({path})" for scope, path in found)
        note = ("; the project copy travels with the repository, the user copy is only on this machine"
                if len(found) > 1 else "")
        if old:
            note = f"; the {' and '.join(old)} copy is from another version, rerun " + " and ".join(
                f"`ui-audit install-skill --agent {agent} --scope {scope}`" for scope in old)
        lines.append(f"{'ok  ' if not old else 'old '}  skill for {name}: {where}{note}")
    return lines


def _open_viewer(path: Path) -> None:
    import webbrowser

    webbrowser.open(path.resolve().as_uri())


def cmd_accept(args) -> int:
    from . import report as report_mod

    _read_input(Path(args.report_dir))  # a wrong folder is a one-line error, not a traceback
    try:
        added, already, path = report_mod.accept(Path(args.report_dir), args.ids, args.reason)
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return USAGE
    print(f"accepted {added} finding(s) in {path}" + (f" ({already} were already accepted)" if already else ""))
    return 0


def cmd_login(args) -> int:
    from . import browser

    try:
        cfg, _ = _load_config(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    target = Path(args.save)
    print(f"A browser window opens at {browser.url_for(cfg.base_url, args.path)}. Sign in there.")
    try:
        browser.save_session(cfg, target, args.path,
                             wait=lambda: input("Press Enter here once you are signed in... "))
    except (EOFError, KeyboardInterrupt):
        print("\ncancelled; nothing saved", file=sys.stderr)
        return 1
    print(f"saved the signed-in session to {target}")
    # Forward slashes keep the TOML snippet valid on Windows, where "\U..." would be an escape.
    print(f'Use it with `storage_state = "{target.as_posix()}"` in ui-audit.toml or `ui-audit audit --storage-state {target}`.')
    print("The file works like a password for that account: keep it out of version control.")
    return 0


def cmd_report(args) -> int:
    from . import report as report_mod

    out_dir = Path(args.report_dir)
    if not (out_dir / report_mod.REPORT_JSON).is_file():
        print(f"no report.json in {out_dir}; run `ui-audit audit --output {out_dir}` first", file=sys.stderr)
        return 2
    path = report_mod.write_html(_read_input(out_dir), out_dir)
    print(f"report viewer: {path}")
    if not args.no_open:
        _open_viewer(path)
    return 0


def cmd_ui(args) -> int:
    from .server import Workspace, serve

    try:
        _, path = load(Path(args.config) if args.config else None)
        if path is None:  # no ui-audit.toml: settings kept next to the runs, newest first
            for candidate in sorted(Path(".ui-audit").glob("*.toml"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    load(candidate)
                except (ConfigError, OSError, ValueError):
                    continue
                path = candidate.resolve()
                break
        workspace = Workspace(Path.cwd(), path, Path(args.runs) if args.runs else None)
    except (ConfigError, OSError, ValueError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    serve(workspace, args.port, open_browser=not args.no_open)
    return 0


DEMO_DIR = Path(__file__).resolve().parent / "demo"


def _serve_demo(port: int):
    """Serve the bundled demo site on 127.0.0.1 in a thread; any free port if `port` is taken."""
    import functools
    import http.server
    import threading

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(DEMO_DIR))
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def cmd_demo(args) -> int:
    import shlex
    import threading

    server, url = _serve_demo(args.port)
    try:
        if args.serve_only:
            print(f"demo site: {url} (press Ctrl+C to stop)")
            print(f"audit it:  ui-audit audit {url} --project-root {shlex.quote(str(DEMO_DIR))} --output {shlex.quote(args.output)} --open")
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                print("\nstopping")
            return 0
        print(f"auditing the demo site at {url}; it has planted defects, listed in {DEMO_DIR / 'README.md'}")
        audit_args = build_parser().parse_args(["audit", "--base-url", url, "--project-root", str(DEMO_DIR),
                                                "--output", args.output, "--fast"] + ([] if args.no_open else ["--open"]))
        audit_args.defaults_only = True
        return cmd_audit(audit_args)
    finally:
        server.shutdown()
        server.server_close()


def _git_changed(project_root: str, ref: str) -> list[str]:
    """Files that differ from `ref`, plus new untracked ones, relative to project_root."""
    import subprocess

    def lines(*command: str) -> list[str]:
        done = subprocess.run(["git", "-C", project_root, *command], capture_output=True, text=True, check=True)
        return [line for line in done.stdout.splitlines() if line]

    return sorted(set(lines("diff", "--name-only", "--relative", ref)) | set(lines("ls-files", "--others", "--exclude-standard")))


def routes_for_changes(baseline: dict, changed: list[str]) -> tuple[list[str], str]:
    """Which routes of a previous full audit a set of changed files can affect, and why."""
    audited = [r for r in baseline["routes"] if r.get("status", "audited") == "audited" and r.get("loaded", True)]
    every = [r["path"] for r in audited]
    touched = [f for f in changed if Path(f).suffix in SOURCE_EXTS]
    if not touched:
        return [], "no UI source file changed"
    known = set().union(*(set(r.get("sources") or []) for r in audited)) if audited else set()
    if not known:
        return every, "the baseline has no component sources (not a dev build of React, Vue or Svelte), so every route is audited"
    unmapped = [f for f in touched if f not in known]
    if unmapped:
        # A stylesheet, a helper or a component no audited page rendered: its reach is unknown.
        return every, f"{unmapped[0]}{' and others' if len(unmapped) > 1 else ''} could affect any page, so every route is audited"
    hit = [r["path"] for r in audited if set(r.get("sources") or []) & set(touched)]
    return hit, f"{len(hit)} of {len(every)} routes render a changed file"


def cmd_audit(args) -> int:
    from . import report as report_mod
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
    only_routes = args.route or None
    if args.changed_since:
        baseline_dir = Path(args.baseline or cfg.output)
        if not (baseline_dir / report_mod.REPORT_JSON).is_file():
            print(f"--changed-since needs a previous full audit to map files to routes; none in {baseline_dir} "
                  "(run a full audit first, or pass --baseline)", file=sys.stderr)
            return 2
        try:
            changed = _git_changed(cfg.project_root, args.changed_since)
        except Exception as exc:  # noqa: BLE001 - not a git checkout, unknown ref, git missing
            print(f"could not list changes since {args.changed_since}: {str(exc).splitlines()[0]}", file=sys.stderr)
            return 2
        only_routes, why = routes_for_changes(_read_input(baseline_dir), changed)
        print(f"changed since {args.changed_since}: {why}")
        if not only_routes:
            return 0
        if Path(cfg.output).resolve() == baseline_dir.resolve():
            cfg.output = str(baseline_dir.with_name(baseline_dir.name + "-changed"))  # keep the full report
    try:
        result = run(cfg, only_routes=only_routes, log=log)
    except Exception as exc:  # noqa: BLE001 - one honest line instead of a traceback an agent reads as findings
        print(f"error: the audit failed ({exc.__class__.__name__}: {str(exc).splitlines()[0] if str(exc) else ''})",
              file=sys.stderr)
        return FAILED

    counts = result["stats"]["issues"]
    out = Path(cfg.output)
    audited = report_mod.audited_routes(result)
    megabytes = result["stats"]["screenshot_bytes"] / 1_000_000
    print(f"{counts['P1']} P1 · {counts['P2']} P2 · {counts['P3']} P3 across {len(audited)} route(s), "
          f"{len(result['states'])} state(s), {len(result['captures'])} screenshot(s) ({megabytes:.1f} MB), "
          f"{result['stats']['probes']} probes in {result['stats']['seconds']}s")
    if len(result["browsers"]) > 1:
        only = [i for i in result["issues"] if not i.get("accepted") and not set(result["browsers"]) <= set(i["browsers"])]
        if only:
            print(f"{len(only)} finding(s) show up in some browsers only; see browsers[] on each issue")
    groups = len(result.get("groups", []))
    if groups and groups < sum(counts.values()):
        print(f"{sum(counts.values())} findings come from {groups} distinct causes; see groups[] in report.json")
    for route in audited:
        content = route.get("content") or {}
        if content.get("state", "ok") != "ok":
            print(f"check by hand: {route['path']} may not show its real content "
                  f"({content['state']}: {content['detail']}), so a clean result there means little")
    failed = [r for r in result["routes"] if not r.get("loaded", True)]
    skipped = len(result["routes"]) - len(audited) - len(failed)
    if skipped:
        print(f"{skipped} route(s) skipped as not found, duplicate or not a web page; "
              "see routes[].status in report.json")
    print(f"report: {out / 'report.json'}")
    print(f"report viewer: {out / 'index.html'}")
    print(f"semantic review packet: {out / 'semantic-review.md'}")
    for error in result["errors"]:
        print(f"warning: {error.splitlines()[0]}", file=sys.stderr)
    if args.open:
        _open_viewer(out / report_mod.REPORT_HTML)
    if not audit_trustworthy(result, cfg.base_url):
        return FAILED
    if args.fail_on:
        threshold = {"P1": ["P1"], "P2": ["P1", "P2"], "P3": ["P1", "P2", "P3"]}[args.fail_on]
        if any(counts[level] for level in threshold):
            return FINDINGS
    return OK


def sign_in_wall(report: dict) -> tuple[str, int, int] | None:
    """The URL most routes were sent to instead of their own page (an expired sign-in, usually):
    (landed, how many, of how many loaded), or None. A handful of routes is too few to tell."""
    loaded = [r for r in report["routes"] if r.get("loaded", True)]
    moved = Counter(r["landed"] for r in loaded if r.get("landed"))
    if not moved:
        return None
    landed, count = moved.most_common(1)[0]
    return (landed, count, len(loaded)) if count >= 3 and count >= 0.8 * len(loaded) else None


def audit_trustworthy(report: dict, base_url: str) -> bool:
    """Print why a finished audit says little about the app (exit 3), or return True if it measured what it should."""
    from . import report as report_mod
    from .browser import url_for

    audited = report_mod.audited_routes(report)
    failed = [r for r in report["routes"] if not r.get("loaded", True)]
    for route in failed:
        print(f"error: {url_for(base_url, route['path'])} did not load ({route.get('error') or 'see errors[]'})",
              file=sys.stderr)
    if failed and len(failed) == len(report["routes"]):
        print(f"error: nothing loaded; is the app running at {base_url}?", file=sys.stderr)
    wall = sign_in_wall(report)
    if wall:
        landed, count, total = wall
        where = landed if "://" in landed else url_for(base_url, landed)
        print(f"error: {count} of {total} routes ended on {where} instead of their own page; that looks like a "
              "sign-in page: is storage_state expired? (`ui-audit login` saves a new session)", file=sys.stderr)
    if not audited and not failed:
        print("error: no route was measured; see routes[].status in report.json", file=sys.stderr)
    if failed or wall or not audited:
        print("the audit is incomplete, so 0 findings would not mean the app is fine", file=sys.stderr)
        return False
    return True


def cmd_merge(args) -> int:
    from . import report as report_mod
    from .semantic import merge

    out_dir = Path(args.report_dir)
    findings_path = Path(args.findings) if args.findings else out_dir / "agent-findings.json"
    report = _read_input(out_dir)
    findings = _read_input(findings_path, report=False)
    if isinstance(findings, dict):
        findings = findings.get("findings", [])
    added, errors = merge(report, findings)
    report["stats"]["issues"] = report_mod.summary_counts(report["issues"])
    report_mod.write_json(report, out_dir)
    report_mod.write_html(report, out_dir)
    print(f"merged {added} agent finding(s) into {out_dir / 'report.json'}")
    for error in errors:
        print(f"rejected {error}", file=sys.stderr)
    return USAGE if errors else OK  # rejected entries are invalid input: fix them and merge again


def cmd_verify(args) -> int:
    from . import verify

    base_dir, current_dir = Path(args.baseline), Path(args.current)
    baseline, current = _read_input(base_dir), _read_input(current_dir)
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
    return FINDINGS if blocking else OK


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


EPILOG = """the loop:
  1. ui-audit init                            write ui-audit.toml with the routes found in the source
  2. ui-audit audit --output .ui-audit/a      find layout bugs: report.json, index.html
  3. fix the code, then audit again into .ui-audit/b
  4. ui-audit verify .ui-audit/a .ui-audit/b  what is fixed, introduced or persistent

exit codes: 0 ok, 1 findings over the threshold (audit --fail-on, verify),
2 usage, config or input file error, 3 the app or the audit failed"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ui-audit", description="Responsive UI Auditor", epilog=EPILOG,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
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

    p = sub.add_parser("doctor", help="check Python, the browsers, config, app and installed skills")
    common(p, output=False)
    p.add_argument("--browsers", type=_browsers, metavar="LIST", help="browsers to check (default: those in the config)")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("audit", help="discover, sweep, capture and report")
    common(p)
    p.add_argument("base_url_pos", nargs="?", metavar="URL", help="shorthand for --base-url")
    p.add_argument("--like", metavar="RUN_DIR", help="reuse the settings an earlier run was made with (other options override them)")
    p.add_argument("--route", action="append", help="audit only this route (repeatable)")
    p.add_argument("--width", type=_widths, help="exact widths, e.g. 389,390,391 (disables the sweep)")
    p.add_argument("--sweep-step", type=int, help="sweep step in px (default 80)")
    p.add_argument("--max-captures", type=int, help="screenshot cap per route/state")
    p.add_argument("--no-states", action="store_true", help="skip automatic state discovery")
    p.add_argument("--no-annotate", action="store_true", help="skip annotated screenshots")
    p.add_argument("--fail-on", choices=["P1", "P2", "P3"], help="exit 1 if issues at or above this severity")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--open", action="store_true", help="open the report viewer in the browser when done")
    p.add_argument("--storage-state", help="signed-in session saved by `ui-audit login`")
    p.add_argument("--changed-since", metavar="REF",
                   help="audit only routes that render a file changed since this git ref (needs a previous full audit)")
    p.add_argument("--baseline", help="the full audit --changed-since maps files with (default: the output directory)")
    p.add_argument("--locale", help='browser language for this run, e.g. "de"')
    p.add_argument("--browsers", type=_browsers, metavar="LIST",
                   help="browsers to audit in, e.g. chromium,webkit,firefox (webkit is Safari's engine; default chromium)")
    p.add_argument("--fast", action="store_true",
                   help="probe opened menus, tabs and dialogs only at key widths (same as [states] sweep = \"key\")")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("accept", help="mark findings as intentional so later audits stop counting them")
    p.add_argument("report_dir")
    p.add_argument("ids", nargs="+", help="issue ids or group ids from the report")
    p.add_argument("--reason", required=True, help="why this is fine; kept next to the finding")
    p.set_defaults(func=cmd_accept)

    p = sub.add_parser("login", help="sign in once in a browser window and save the session for audits")
    p.add_argument("--config", help="path to ui-audit.toml (default: search upwards)")
    p.add_argument("--base-url", help="URL of the running app")
    p.add_argument("--browser-path", help="Chromium executable (or set UI_AUDIT_BROWSER_PATH)")
    p.add_argument("--path", default="/", help="page to open, e.g. /login (default /)")
    p.add_argument("--save", default=".ui-audit/auth.json", help="where to save the session (default .ui-audit/auth.json)")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("report", help="rebuild the report viewer from report.json and open it")
    p.add_argument("report_dir", nargs="?", default=".ui-audit/latest")
    p.add_argument("--no-open", action="store_true", help="only rebuild index.html")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("demo", help="audit the bundled demo site, which has planted defects, and open the report")
    p.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 to serve the demo on (default 8765, or any free one)")
    p.add_argument("--output", default=".ui-audit/demo", help="output directory (default .ui-audit/demo)")
    p.add_argument("--no-open", action="store_true", help="do not open the report when done")
    p.add_argument("--serve-only", action="store_true", help="only serve the demo site and print the audit command")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("ui", help="open the app: start audits, work through findings and compare runs in the browser")
    p.add_argument("--config", help=f"path to {CONFIG_FILENAME} (default: search upwards)")
    p.add_argument("--runs", help="folder the runs are kept in (default: where the configured output goes, .ui-audit)")
    p.add_argument("--port", type=int, default=8484, help="port on 127.0.0.1 (default 8484, or any free one)")
    p.add_argument("--no-open", action="store_true", help="do not open the browser")
    p.set_defaults(func=cmd_ui)

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

    from .ci import add_parser as add_ci_parser

    add_ci_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "base_url_pos", None) and not args.base_url:
        args.base_url = args.base_url_pos
    try:
        return args.func(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return USAGE
