"""Compact views of a run for coding agents.

report.json holds every box, hint and capture; a few pages of a demo already make it about
25k tokens. An agent needs far less to decide what to fix first: the counts, one entry per
cause with one example, and the pages whose result means little. `ui-audit audit --json`,
`ui-audit show` and the MCP server all print these views; the details of one cause come
on request.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from .issues import DETERMINISTIC_CHECKS, SEVERITY_ORDER, assign_groups, rect_key
from .report import REPORT_HTML, REPORT_JSON, audited_routes, summary_counts

MAX_GROUPS = 30
MAX_ERRORS = 20
MAX_VERIFY_ITEMS = 50
RUNTIME_CHECKS = {"console-error", "failed-resource"}


def _span(widths: list[int]) -> list[int]:
    return [min(widths), max(widths)] if widths else []


def _clip(text: str, limit: int = 240) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _source(candidate: dict | None) -> str | None:
    if not candidate:
        return None
    return f"{candidate['file']}:{candidate['line']}" if candidate.get("line") else candidate["file"]


def _width_limits(report: dict) -> tuple[int, int]:
    viewports = (report.get("config") or {}).get("viewports") or {}
    low = viewports.get("min_width") or 320
    return low, max(viewports.get("max_width") or 1920, low + 1)


def _groups(report: dict) -> list[dict]:
    # Reports written before grouping existed get it here; assign_groups also tags the issues.
    return assign_groups(report["issues"])


def best_capture(report: dict, issue: dict, width: int | None = None) -> dict | None:
    """The screenshot that shows an issue best, as the viewer picks it: one with the element's
    box, else the one nearest the middle of its widths (or nearest `width` when given)."""
    if issue.get("check") in RUNTIME_CHECKS:
        return None
    seen = issue.get("browsers") or ["chromium"]
    caps = [c for c in report.get("captures", []) if c["route"] == issue["route"] and c["state"] == issue["state"]
            and c.get("browser", "chromium") in seen]
    if not caps:
        return None
    if width is not None:
        return min(caps, key=lambda c: abs(c["width"] - width))
    rects = issue.get("rects") or {}
    boxed = [c for c in caps if rect_key(c["width"], c.get("browser", "chromium")) in rects]
    if boxed:
        return boxed[(len(boxed) - 1) // 2]
    widths = issue.get("widths") or []
    if not widths:
        return caps[0]
    middle = (widths[0] + widths[-1]) / 2
    return min(caps, key=lambda c: abs(c["width"] - middle))


def _shot(report: dict, run_dir: Path, issue: dict) -> str | None:
    capture = best_capture(report, issue)
    if not capture:
        return None
    return str(run_dir / (capture.get("annotated") or capture["file"]))


def representative(group: dict, issues: dict[str, dict]) -> dict:
    members = [issues[i] for i in group["issue_ids"] if i in issues]
    open_ = [i for i in members if not i.get("accepted")] or members
    return next((i for i in open_ if i["severity"] == group["severity"]), open_[0])


def compact_group(report: dict, run_dir: Path, group: dict, issues: dict[str, dict]) -> dict:
    members = [issues[i] for i in group["issue_ids"] if i in issues]
    example = representative(group, issues)
    browsers = sorted({b for i in members for b in (i.get("browsers") or ["chromium"])})
    entry = {
        "id": group["id"], "check": group["check"], "severity": group["severity"], "count": len(members),
        "message": _clip(example["message"]), "routes": group["routes"], "widths": group.get("widths") or [],
        "states": sorted({i["state"] for i in members}),
        "example": {"id": example["id"], "route": example["route"], "state": example["state"],
                    "selector": _clip(example["selector"], 160), "widths": _span(example.get("widths") or [])},
        "source": _source(group.get("source")) or _source((example.get("source_candidates") or [None])[0]),
        "screenshot": _shot(report, run_dir, example),
    }
    if browsers != ["chromium"]:
        entry["browsers"] = browsers
    accepted = sum(1 for i in members if i.get("accepted"))
    if accepted:
        entry["accepted"] = accepted
    return entry


def summary(report: dict, run_dir: Path, max_groups: int = MAX_GROUPS) -> dict:
    """Counts, causes (one example each), pages to check by hand, errors and paths."""
    run_dir = Path(run_dir)
    groups = _groups(report)
    issues = {i["id"]: i for i in report["issues"]}
    # A cause whose findings were all accepted is decided; it stays in report.json only.
    open_groups = [g for g in groups if any(not issues[i].get("accepted") for i in g["issue_ids"] if i in issues)]
    audited = audited_routes(report)
    hand = [{"route": r["path"], "state": r["content"].get("state"), "detail": _clip(r["content"].get("detail", ""))}
            for r in audited if (r.get("content") or {}).get("state", "ok") != "ok"]
    out = {
        "run_dir": str(run_dir),
        "report": str(run_dir / REPORT_JSON),
        "viewer": str(run_dir / REPORT_HTML),
        "base_url": report.get("base_url"),
        "counts": summary_counts(report["issues"]),
        "accepted": sum(1 for i in report["issues"] if i.get("accepted")),
        "routes": {"audited": len(audited), "skipped": len(report.get("routes", [])) - len(audited)},
        "groups": [compact_group(report, run_dir, g, issues) for g in open_groups[:max_groups]],
        "more_groups": max(0, len(open_groups) - max_groups),
        "check_by_hand": hand,
        "truncated_routes": report.get("truncated_routes") or [],
        "errors": [_clip(str(e)) for e in report.get("errors", [])[:MAX_ERRORS]],
    }
    if len(report.get("errors", [])) > MAX_ERRORS:
        out["more_errors"] = len(report["errors"]) - MAX_ERRORS
    if open_groups:
        out["next"] = f"ui-audit show {shlex.quote(str(run_dir))} --group {open_groups[0]['id']} --json"
    return out


def find(report: dict, ident: str) -> tuple[dict | None, list[dict]]:
    """The group with this id and its issues, or (None, [issue]) for an issue id."""
    groups = _groups(report)
    by_id = {i["id"]: i for i in report["issues"]}
    for group in groups:
        if group["id"] == ident:
            return group, [by_id[i] for i in group["issue_ids"] if i in by_id]
    if ident in by_id:
        return None, [by_id[ident]]
    raise LookupError(f"no group or issue with the id {ident} in this run")


def recheck_command(report: dict, run_dir: Path, issues: list[dict]) -> str:
    """A targeted rerun of these findings plus the comparison; the same command the viewer copies."""
    from .server import recheck_widths

    directory = str(run_dir).rstrip("/") or "."
    out = f"{directory}-recheck"
    q = shlex.quote
    routes = " ".join(f"--route {q(r)}" for r in dict.fromkeys(i["route"] for i in issues))
    widths = ",".join(str(w) for w in recheck_widths(issues, *_width_limits(report)))
    states = " --no-states" if all(i["state"] == "default" for i in issues) else ""
    return (f"ui-audit audit --like {q(directory)} {routes} --width {widths}{states} --output {q(out)}\n"
            f"ui-audit verify {q(directory)} {q(out)}")


def _detail_issue(report: dict, run_dir: Path, issue: dict) -> dict:
    entry = {key: issue[key] for key in ("id", "severity", "check", "origin", "route", "state", "selector", "message",
                                         "widths", "browsers", "also_in_states", "accepted") if issue.get(key)}
    if len(issue.get("browsers") or []) > 1:
        entry["widths_by_browser"] = issue.get("widths_by_browser")
    entry["evidence"] = [str(run_dir / e) for e in issue.get("evidence", [])]
    entry["source_candidates"] = [{"file": c["file"], "line": c.get("line"), "reasons": c.get("reasons", [])}
                                  for c in issue.get("source_candidates", [])]
    entry["screenshot"] = _shot(report, run_dir, issue)
    return entry


def detail(report: dict, run_dir: Path, ident: str, offset: int = 0, limit: int | None = None) -> dict:
    """One cause (or one issue) in full: every finding, its widths, evidence, every source
    candidate, screenshots, and the commands to re-check or accept it."""
    run_dir = Path(run_dir)
    group, members = find(report, ident)
    first = members[0]
    chosen = members[offset: offset + limit if limit else None]
    out = {
        "id": ident,
        "kind": "group" if group else "issue",
        "check": first["check"],
        "severity": group["severity"] if group else first["severity"],
        "about": DETERMINISTIC_CHECKS.get(first["check"], ""),
        "count": len(members),
        "issues": [_detail_issue(report, run_dir, i) for i in chosen],
        "recheck": recheck_command(report, run_dir, members) if any(i.get("widths") for i in members) else None,
        "accept": f'ui-audit accept {shlex.quote(str(run_dir))} {ident} --reason "why this is fine"',
    }
    if group:
        out["routes"], out["widths"], out["source"] = group["routes"], group.get("widths") or [], _source(group.get("source"))
    if offset or len(chosen) < len(members):
        out["offset"], out["more"] = offset, max(0, len(members) - offset - len(chosen))
    return out


def render_summary(data: dict) -> str:
    counts = data["counts"]
    lines = [f"{counts['P1']} P1 · {counts['P2']} P2 · {counts['P3']} P3 in {data['routes']['audited']} route(s)"
             + (f", {data['accepted']} accepted" if data["accepted"] else "") + f" — {data['report']}"]
    for g in data["groups"]:
        widths = "–".join(str(w) for w in g["widths"]) + "px" if g["widths"] else ""
        states = [s for s in g["states"] if s != "default"]
        state_note = f" [{', '.join(states)}]" if states else ""
        lines.append(f"{g['id']}  {g['severity']} {g['check']} ×{g['count']} {', '.join(g['routes'])}{state_note} {widths}".rstrip())
        lines.append(f"    {g['message']}")
        if g.get("source"):
            lines.append(f"    source: {g['source']}")
    if data["more_groups"]:
        lines.append(f"... and {data['more_groups']} more cause(s); see report.json")
    for r in data["check_by_hand"]:
        lines.append(f"check by hand: {r['route']} ({r['state']}: {r['detail']})")
    if data["truncated_routes"]:
        lines.append(f"not audited (max_routes): {', '.join(data['truncated_routes'])}")
    lines += [f"error: {e}" for e in data["errors"]]
    if data.get("next"):
        lines.append(f"details: {data['next'].removesuffix(' --json')}")
    return "\n".join(lines) + "\n"


def render_detail(data: dict) -> str:
    """The detail as text an agent can act on, laid out like the viewer's fix prompt."""
    lines = [f"{data['severity']} {data['check']} ({data['kind']} {data['id']}, {data['count']} finding(s))"]
    if data["about"]:
        lines.append(data["about"])
    for i in data["issues"]:
        widths = i.get("widths") or []
        where = f"{widths[0]}–{widths[-1]}px" if len(widths) > 1 else (f"{widths[0]}px" if widths else "")
        state = f" [{i['state']}]" if i["state"] != "default" else ""
        lines += ["", f"- {i['id']} {i['severity']} {i['route']}{state} {where}" + (" (accepted)" if i.get("accepted") else "")]
        if i["check"] not in RUNTIME_CHECKS:
            lines.append(f"  element: {i['selector']}")
        lines.append(f"  measured: {i['message']}")
        if i.get("browsers") and i["browsers"] != ["chromium"]:
            lines.append(f"  browsers: {', '.join(i['browsers'])}")
        sources = [f"{c['file']}:{c['line']}" if c.get("line") else c["file"] for c in i["source_candidates"]]
        if sources:
            lines.append(f"  likely source (search hints, confirm before editing): {', '.join(sources)}")
        if i.get("screenshot"):
            lines.append(f"  screenshot: {i['screenshot']}")
    if data.get("more"):
        lines.append(f"\n... and {data['more']} more finding(s)")
    if data["recheck"]:
        lines += ["", "When the fix is in, prove it with a targeted rerun and compare:", data["recheck"]]
    lines += ["", "If it is intentional:", data["accept"]]
    return "\n".join(lines) + "\n"


def verify_summary(result: dict, limit: int = MAX_VERIFY_ITEMS) -> dict:
    """verify's result without the noise: each finding on one short record, lists capped."""
    def brief(issue: dict) -> dict:
        entry = {"id": issue.get("id"), "severity": issue["severity"], "check": issue["check"], "route": issue["route"],
                 "state": issue["state"], "selector": _clip(issue.get("selector") or "", 160),
                 "widths": _span(issue.get("widths") or [])}
        if issue.get("origin") == "agent":
            entry["origin"] = "agent"
        if (issue.get("browsers") or ["chromium"]) != ["chromium"]:
            entry["browsers"] = issue["browsers"]
        return entry

    out = {"baseline": result.get("baseline"), "current": result.get("current")}
    for key in ("fixed", "introduced", "persistent", "needs_review"):
        items = sorted(result.get(key, []), key=lambda i: SEVERITY_ORDER.get(i["severity"], 9))
        out[key] = [brief(i) for i in items[:limit]]
        if len(items) > limit:
            out[f"more_{key}"] = len(items) - limit
    out["out_of_scope"] = result.get("out_of_scope", 0)
    diffs = [d for d in result.get("pixel_diffs", []) if "changed_ratio" in d and d["changed_ratio"] > 0]
    if diffs:
        out["pixel_diffs_changed"] = len(diffs)
    return out
