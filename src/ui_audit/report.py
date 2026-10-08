"""Report files: report.json (the source of truth) and index.html (the report viewer)."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from .issues import assign_groups

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
_ISSUE_FIELDS = ("id", "group", "accepted", "check", "severity", "origin", "route", "state", "selector", "message", "widths", "evidence")
_REPORT_FIELDS = ("version", "created", "base_url", "project_root", "output_dir", "locale", "routes", "skipped_dynamic_routes",
                  "truncated_routes", "consent_dismissed", "states", "breakpoints", "captures", "errors", "stats")


def _viewer_data(report: dict) -> dict:
    data = {key: report[key] for key in _REPORT_FIELDS if key in report}
    assign_groups(report["issues"])  # reports written before grouping existed get it here
    data["config"] = {"viewports": (report.get("config") or {}).get("viewports", {})}
    # Boxes for the screenshot viewer: only at widths that have a screenshot.
    shot_widths: dict[tuple[str, str], set[str]] = {}
    for capture in report.get("captures", []):
        shot_widths.setdefault((capture["route"], capture["state"]), set()).add(str(capture["width"]))
    data["issues"] = [
        {**{key: issue[key] for key in _ISSUE_FIELDS if key in issue},
         "rects": {w: r for w, r in (issue.get("rects") or {}).items()
                   if w in shot_widths.get((issue["route"], issue["state"]), ())},
         "source_candidates": [{"file": c["file"], "line": c.get("line")} for c in issue.get("source_candidates", [])[:2]]}
        for issue in report["issues"]
    ]
    return data


def write_html(report: dict, out_dir: Path) -> Path:
    """Write the self-contained viewer: the template with this report's data inlined."""
    template = resources.files("ui_audit").joinpath("report_template.html").read_text(encoding="utf-8")
    # "</" would end the data block early; "<\\/" is the same string to JSON.
    payload = json.dumps(_viewer_data(report), ensure_ascii=False).replace("</", "<\\/")
    path = out_dir / REPORT_HTML
    path.write_text(template.replace("__REPORT_DATA__", payload), encoding="utf-8")
    return path
