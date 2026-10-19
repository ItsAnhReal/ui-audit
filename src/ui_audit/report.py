"""Report files: report.json (the source of truth) and index.html (the report viewer)."""

from __future__ import annotations

import json
import re
import shlex
from datetime import date
from importlib import resources
from pathlib import Path

from .issues import assign_groups, mark_accepted, rect_key

REPORT_JSON = "report.json"
REPORT_HTML = "index.html"


def write_json(report: dict, out_dir: Path) -> Path:
    # Derived from the issues every time, so merged agent findings are grouped too.
    report["groups"] = assign_groups(report["issues"])
    path = out_dir / REPORT_JSON
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_json(path: Path) -> dict:
    if path.is_dir():
        path = path / REPORT_JSON
    return json.loads(path.read_text(encoding="utf-8"))


def summary_counts(issues: list[dict]) -> dict[str, int]:
    counts = {"P1": 0, "P2": 0, "P3": 0}
    for issue in issues:
        if issue.get("accepted"):
            continue
        counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
    return counts


def audited_routes(report: dict) -> list[dict]:
    """Routes that were measured; older reports have no status and audited everything they loaded."""
    return [r for r in report["routes"] if r.get("status", "audited") == "audited" and r.get("loaded", True)]


# Fields the viewer reads. Rects and DOM hints stay in report.json only.
_ISSUE_FIELDS = ("id", "group", "accepted", "check", "severity", "origin", "route", "state", "selector", "message",
                 "message_key", "message_params", "widths", "evidence", "also_in_states", "browsers")
_REPORT_FIELDS = ("version", "created", "base_url", "project_root", "output_dir", "locale", "browsers", "routes", "skipped_dynamic_routes",
                  "truncated_routes", "consent_dismissed", "states", "breakpoints", "captures", "errors", "stats", "only_routes")


def viewer_data(report: dict, run_dir: str | None = None) -> dict:
    """What the viewer reads about a run in the folder `run_dir` (default: the report's output_dir)."""
    from .summary import recheck_command

    data = {key: report[key] for key in _REPORT_FIELDS if key in report}
    groups = assign_groups(report["issues"])  # reports written before grouping existed get it here
    # The commands the viewer copies are worked out here, once, with the same quoting and
    # re-check widths as the CLI and the app's server.
    directory = (run_dir or report.get("output_dir") or ".").rstrip("/") or "."
    by_id = {i["id"]: i for i in report["issues"]}
    data["groups"] = [{**{key: g[key] for key in ("id", "check", "severity", "source", "count", "routes")},
                       "recheck": recheck_command(report, directory, [by_id[i] for i in g["issue_ids"]])} for g in groups]
    data["accept_command"] = f'ui-audit accept {shlex.quote(directory)} {{id}} --reason "why this is fine"'
    in_groups = {i: g["count"] for g in groups for i in g["issue_ids"]}
    config = report.get("config") or {}
    data["config"] = {"viewports": config.get("viewports", {}), "sweep": (config.get("states") or {}).get("sweep", "full"),
                      "signed_in": bool(config.get("storage_state"))}
    # Boxes for the screenshot viewer: only at widths that have a screenshot.
    shot_widths: dict[tuple[str, str], set[str]] = {}
    for capture in report.get("captures", []):
        shot_widths.setdefault((capture["route"], capture["state"]), set()).add(
            rect_key(capture["width"], capture.get("browser", "chromium")))
    data["issues"] = [
        {**{key: issue[key] for key in _ISSUE_FIELDS if key in issue},
         "rects": {w: r for w, r in (issue.get("rects") or {}).items()
                   if w in shot_widths.get((issue["route"], issue["state"]), ())},
         "source_candidates": [{"file": c["file"], "line": c.get("line"), "reasons": c.get("reasons", [])[:3]}
                               for c in issue.get("source_candidates", [])[:3]],
         # one finding of a larger group can be re-checked on its own; alone, its group's command is the same
         **({"recheck": recheck_command(report, directory, [issue])} if in_groups.get(issue["id"], 1) > 1 else {})}
        for issue in report["issues"]
    ]
    return data


# The viewer's script files in ui/app/, in the order they are joined. Each is a part of one
# function body: later files use what earlier ones define, and main.js starts the page.
APP_SCRIPTS = ("core.js", "text.js", "model.js", "dom.js", "state.js", "shell.js", "home.js", "new-audit.js",
               "run.js", "findings.js", "detail.js", "compare.js", "main.js")


def app_script(names: tuple[str, ...] = APP_SCRIPTS, tail: str = "") -> str:
    """The viewer's script: the files joined inside one function, so they share a scope
    without a module loader (the static report opens from file://). `tail` runs last, inside."""
    folder = resources.files("ui_audit").joinpath("ui", "app")
    body = "\n".join(f"// ---- {name}\n{folder.joinpath(name).read_text(encoding='utf-8')}" for name in names)
    return f'(() => {{\n"use strict";\n{body}\n{tail}\n}})();\n'


def page(report: dict | None = None, app: dict | None = None) -> str:
    """The viewer as one self-contained page. Given report data it is the static report a
    run leaves behind; given app settings it is `ui-audit ui`, which loads runs from its server."""
    ui = resources.files("ui_audit").joinpath("ui")

    def inline(value) -> str:
        # "</" would end the data block early; "<\\/" is the same string to JSON.
        return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")

    parts = {
        "/*__STYLE__*/": ui.joinpath("app.css").read_text(encoding="utf-8"),
        "/*__SCRIPT__*/": ui.joinpath("i18n.js").read_text(encoding="utf-8") + "\n" + app_script(),
        "__REPORT_DATA__": inline(report),
        "__APP_CONFIG__": inline(app),
    }
    # One pass, so a placeholder that appears inside the data or the code is left alone.
    pattern = "|".join(re.escape(key) for key in parts)
    return re.sub(pattern, lambda m: parts[m.group(0)], ui.joinpath("index.html").read_text(encoding="utf-8"))


def write_html(report: dict, out_dir: Path) -> Path:
    """Write the self-contained viewer: the page with this report's data inlined."""
    path = out_dir / REPORT_HTML
    path.write_text(page(viewer_data(report)), encoding="utf-8")
    return path


def _accepted_file(report: dict) -> Path:
    config = report.get("config") or {}
    return Path(report["project_root"]) / config.get("accepted_file", "ui-audit.accepted.json")


def _read_accepted(path: Path) -> list[dict]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _chosen(report: dict, ids: list[str], out_dir: Path) -> list[dict]:
    wanted = set(ids)
    for group in report.get("groups", []):
        if group["id"] in wanted:
            wanted |= set(group["issue_ids"])
    chosen = [i for i in report["issues"] if i["id"] in wanted]
    if not chosen:
        raise LookupError(f"no issue or group in {out_dir} has the id(s): {', '.join(ids)}")
    return chosen


def _save_decisions(report: dict, out_dir: Path, path: Path, entries: list[dict]) -> None:
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # The open report reflects the decision right away; later audits read the file.
    mark_accepted(report["issues"], {e["signature"]: e for e in entries if e.get("signature")})
    report["stats"]["issues"] = summary_counts(report["issues"])
    write_json(report, out_dir)
    write_html(report, out_dir)


def accept(out_dir: Path, ids: list[str], reason: str) -> tuple[int, int, Path]:
    """Record findings (or whole groups) as intentional in the project's accepted file.

    Returns how many were added, how many were accepted already, and the file."""
    report = read_json(out_dir)
    chosen = _chosen(report, ids, out_dir)
    path = _accepted_file(report)
    entries = _read_accepted(path)
    known = {e.get("signature") for e in entries}
    today = date.today().isoformat()
    added = [{"signature": i["signature"], "check": i["check"], "route": i["route"], "reason": reason, "date": today}
             for i in chosen if i["signature"] not in known]
    _save_decisions(report, out_dir, path, entries + added)
    return len(added), len(chosen) - len(added), path


def unaccept(out_dir: Path, ids: list[str]) -> tuple[int, Path]:
    """Take findings back out of the accepted file, so they count again. Returns (removed, file)."""
    report = read_json(out_dir)
    signatures = {i["signature"] for i in _chosen(report, ids, out_dir)}
    path = _accepted_file(report)
    entries = _read_accepted(path)
    kept = [e for e in entries if e.get("signature") not in signatures]
    _save_decisions(report, out_dir, path, kept)
    return len(entries) - len(kept), path
