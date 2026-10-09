"""Report files: report.json (the source of truth) and index.html (the report viewer)."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

REPORT_JSON = "report.json"
REPORT_HTML = "index.html"


def write_json(report: dict, out_dir: Path) -> Path:
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
        counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
    return counts


def audited_routes(report: dict) -> list[dict]:
    """Routes that were measured; older reports have no status and audited everything they loaded."""
    return [r for r in report["routes"] if r.get("status", "audited") == "audited" and r.get("loaded", True)]


# Fields the viewer reads. Rects and DOM hints stay in report.json only.
_ISSUE_FIELDS = ("id", "check", "severity", "origin", "route", "state", "selector", "message", "widths", "evidence")
_REPORT_FIELDS = ("version", "created", "base_url", "project_root", "routes", "skipped_dynamic_routes",
                  "truncated_routes", "consent_dismissed", "states", "breakpoints", "captures", "errors", "stats")


def _viewer_data(report: dict) -> dict:
    data = {key: report[key] for key in _REPORT_FIELDS if key in report}
    data["config"] = {"viewports": (report.get("config") or {}).get("viewports", {})}
    data["issues"] = [
        {**{key: issue[key] for key in _ISSUE_FIELDS if key in issue},
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
