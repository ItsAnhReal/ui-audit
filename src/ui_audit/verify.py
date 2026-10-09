"""Compare a baseline report with a fresh one: fixed, introduced, persistent.

A targeted rerun covers only some routes, states and widths. A baseline issue
counts as fixed only if the new run looked where the issue used to be: same
route and state, and at least one overlapping probed width. Everything else
is reported as out of scope rather than silently counted as fixed.
"""

from __future__ import annotations

import json
from pathlib import Path

from .issues import SEVERITY_ORDER, coverage_key


def _coverage(report: dict) -> dict[str, set[int]]:
    return {key: set(widths) for key, widths in report.get("coverage", {}).items()}


def _in_scope(issue: dict, coverage: dict[str, set[int]]) -> bool:
    """Whether the run looked where the issue was: in every browser it showed up in, at a width
    it showed up at in that browser."""
    by_browser = issue.get("widths_by_browser") or {}
    for engine in issue.get("browsers") or ["chromium"]:
        widths = set(by_browser.get(engine) or issue.get("widths") or [])
        probed = coverage.get(coverage_key(issue["route"], issue["state"], engine))
        if not probed or not probed & widths:
            return False
    return True


def compare(baseline: dict, current: dict) -> dict:
    coverage = _coverage(current)
    # A finding accepted as intentional is neither introduced nor still to fix.
    accepted = {i["signature"] for i in baseline["issues"] + current["issues"] if i.get("accepted")}
    base = {i["signature"]: i for i in baseline["issues"] if i["signature"] not in accepted}
    now = {i["signature"]: i for i in current["issues"] if i["signature"] not in accepted}

    # An agent finding can only be called fixed if the agent looked again.
    reviewed = {(i["route"], i["state"]) for i in current["issues"] if i.get("origin") == "agent"}

    fixed, persistent, needs_review, out_of_scope = [], [], [], []
    for sig, issue in base.items():
        if sig in now:
            persistent.append(now[sig])
        elif issue.get("origin") == "agent" and (issue["route"], issue["state"]) not in reviewed:
            (needs_review if f"{issue['route']}|{issue['state']}" in coverage else out_of_scope).append(issue)
        elif _in_scope(issue, coverage):
            fixed.append(issue)
        else:
            out_of_scope.append(issue)
    introduced = [issue for sig, issue in now.items() if sig not in base]

    def brief(issue: dict) -> dict:
        return {key: issue.get(key) for key in ("id", "severity", "check", "route", "state", "selector", "message", "widths", "origin",
                                                "browsers", "widths_by_browser")}

    by_severity = lambda items: sorted(items, key=lambda i: SEVERITY_ORDER.get(i["severity"], 9))  # noqa: E731
    return {
        "baseline": baseline.get("output_dir"),
        "current": current.get("output_dir"),
        "fixed": [brief(i) for i in by_severity(fixed)],
        "introduced": [brief(i) for i in by_severity(introduced)],
        "persistent": [brief(i) for i in by_severity(persistent)],
        "needs_review": [brief(i) for i in by_severity(needs_review)],
        "out_of_scope": len(out_of_scope),
        "pixel_diffs": [],
    }


def pixel_diffs(baseline: dict, current: dict, base_dir: Path, current_dir: Path, out_dir: Path) -> list[dict]:
    """Per-capture changed-pixel ratio for captures present in both runs."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return [{"error": "Pillow is not installed; pip install 'ui-audit[diff]'"}]
    key_of = lambda c: (c["route"], c["state"], c["width"], c.get("browser", "chromium"))  # noqa: E731
    base_caps = {key_of(c): c for c in baseline["captures"]}
    results = []
    diff_dir = out_dir / "diffs"
    for capture in current["captures"]:
        key = key_of(capture)
        if key not in base_caps:
            continue
        try:
            a = Image.open(base_dir / base_caps[key]["file"]).convert("RGB")
            b = Image.open(current_dir / capture["file"]).convert("RGB")
        except OSError:
            continue
        width, height = max(a.width, b.width), max(a.height, b.height)
        canvas_a = Image.new("RGB", (width, height), "white")
        canvas_b = Image.new("RGB", (width, height), "white")
        canvas_a.paste(a)
        canvas_b.paste(b)
        diff = ImageChops.difference(canvas_a, canvas_b).convert("L").point(lambda v: 255 if v > 24 else 0)
        changed = sum(diff.histogram()[255:]) / (width * height)
        entry = {"route": key[0], "state": key[1], "width": key[2], "browser": key[3], "changed_ratio": round(changed, 5)}
        if changed > 0:
            diff_dir.mkdir(parents=True, exist_ok=True)
            name = Path(capture["file"]).name
            diff.save(diff_dir / name)
            entry["diff"] = str((diff_dir / name).relative_to(out_dir))
        results.append(entry)
    return results


def render_markdown(result: dict) -> str:
    lines = ["# ui-audit verify", ""]
    lines.append(f"- Fixed: **{len(result['fixed'])}**")
    lines.append(f"- Introduced: **{len(result['introduced'])}**")
    lines.append(f"- Persistent: **{len(result['persistent'])}**")
    lines.append(f"- Agent findings to re-check (no semantic review in this run): {len(result['needs_review'])}")
    lines.append(f"- Baseline issues outside this run's routes/states/widths: {result['out_of_scope']}")
    for title, key in (("Introduced", "introduced"), ("Persistent", "persistent"),
                       ("Agent findings to re-check", "needs_review"), ("Fixed", "fixed")):
        if result[key]:
            lines += ["", f"## {title}", ""]
            for issue in result[key]:
                widths = issue.get("widths") or []
                where = f"{widths[0]}–{widths[-1]}px" if len(widths) > 1 else (f"{widths[0]}px" if widths else "")
                engines = issue.get("browsers") or ["chromium"]
                if engines != ["chromium"]:
                    where += f" ({', '.join(engines)})"
                lines.append(f"- {issue['severity']} `{issue['check']}` {issue['route']} [{issue['state']}] {where} `{issue['selector']}` — {issue['message']}")
    diffs = [d for d in result.get("pixel_diffs", []) if "changed_ratio" in d]
    if diffs:
        lines += ["", "## Pixel diffs", ""]
        for d in sorted(diffs, key=lambda d: -d["changed_ratio"]):
            lines.append(f"- {d['route']} [{d['state']}] {d['width']}px: {d['changed_ratio'] * 100:.2f}% changed")
    return "\n".join(lines) + "\n"


def write(result: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "verify.json"
    md_path = out_dir / "verify.md"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, md_path
