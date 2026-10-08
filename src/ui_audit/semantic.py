"""Semantic review: a bounded evidence packet for the coding agent, and the merge
step that brings the agent's judgement back into the report.

Deterministic checks catch geometry. They cannot tell whether hierarchy reads
well, whether a layout looks broken, or whether an overlap is intentional.
The packet hands the agent a small number of screenshots plus the
deterministic context; the agent's findings are merged back labelled
`origin: agent` so nobody mistakes them for measured facts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .issues import SEVERITY_ORDER, signature

PACKET_JSON = "semantic-packet.json"
PACKET_MD = "semantic-review.md"
MAX_PACKET_CAPTURES = 12
CATEGORIES = ["layout", "hierarchy", "readability", "consistency", "interaction", "content", "other"]

RUBRIC = """\
- **P1** — broken: content or controls unusable, unreadable or hidden; the page looks wrong to any user.
- **P2** — clearly degraded: awkward wrapping, cramped or colliding elements, weak hierarchy that hides the primary action.
- **P3** — polish: spacing, alignment or rhythm that a designer would flag but a user would not notice.
- Do not report personal taste. Do not report anything already listed as a deterministic finding unless you disagree with it.
"""


def _priority(capture: dict) -> tuple:
    return (-capture["issue_count"], "anomaly" not in capture["reasons"], capture["route"], capture["width"])


def build_packet(report: dict, out_dir: Path) -> tuple[Path, Path]:
    captures = sorted(report["captures"], key=_priority)[:MAX_PACKET_CAPTURES]
    items = []
    for capture in captures:
        related = [
            {"id": i["id"], "severity": i["severity"], "check": i["check"], "selector": i["selector"], "message": i["message"]}
            for i in report["issues"]
            if i["route"] == capture["route"] and i["state"] == capture["state"] and capture["width"] in (i.get("widths") or [])
        ]
        items.append({
            "route": capture["route"], "state": capture["state"], "width": capture["width"], "height": capture["height"],
            "screenshot": capture.get("annotated") or capture["file"], "clean_screenshot": capture["file"],
            "reasons": capture["reasons"], "deterministic_findings": related[:10],
        })
    packet = {
        "instructions": "Inspect each screenshot. Report only visual problems a user would notice. "
                        "Write findings to agent-findings.json, then run `ui-audit merge-findings`.",
        "rubric": RUBRIC,
        "categories": CATEGORIES,
        "finding_schema": {
            "route": "string, as listed", "state": "string, as listed", "width": "integer, as listed",
            "severity": "P1 | P2 | P3", "category": " | ".join(CATEGORIES),
            "description": "one sentence: what is wrong and where", "selector": "optional CSS selector",
            "evidence": "screenshot path you looked at",
        },
        "items": items,
        "omitted_captures": max(0, len(report["captures"]) - len(items)),
    }
    json_path = out_dir / PACKET_JSON
    json_path.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Semantic review packet", "",
        f"{len(items)} screenshot(s) selected from {len(report['captures'])}. "
        "Open each image, compare it with the deterministic findings, and record only what a user would notice.", "",
        "## Severity rubric", "", RUBRIC, "## Output", "",
        "Write a JSON array to `agent-findings.json` in this directory, one object per finding:", "",
        "```json",
        json.dumps([{"route": "/pricing", "state": "default", "width": 834, "severity": "P2", "category": "layout",
                     "description": "Plan cards squeeze to 120px and the price wraps onto three lines.",
                     "selector": ".plans", "evidence": "shots/pricing__default__834.png"}], indent=2),
        "```", "",
        "Then run `ui-audit merge-findings <this directory>`.", "",
        "## Screenshots", "",
    ]
    for item in items:
        lines.append(f"### {item['route']} · {item['state']} · {item['width']}px")
        lines.append(f"- Screenshot: `{item['screenshot']}` (clean: `{item['clean_screenshot']}`)")
        lines.append(f"- Selected because: {', '.join(item['reasons'])}")
        if item["deterministic_findings"]:
            lines.append("- Deterministic findings at this width:")
            for finding in item["deterministic_findings"]:
                lines.append(f"  - {finding['severity']} {finding['check']} `{finding['selector']}` — {finding['message']}")
        lines.append("")
    md_path = out_dir / PACKET_MD
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


class FindingError(ValueError):
    pass


def validate_finding(finding: dict, known: set[tuple[str, str]]) -> dict:
    missing = [key for key in ("route", "state", "width", "severity", "category", "description") if key not in finding]
    if missing:
        raise FindingError(f"missing {', '.join(missing)}")
    if finding["severity"] not in SEVERITY_ORDER:
        raise FindingError(f"severity must be P1, P2 or P3, not {finding['severity']!r}")
    if finding["category"] not in CATEGORIES:
        raise FindingError(f"category must be one of {', '.join(CATEGORIES)}")
    if (finding["route"], finding["state"]) not in known:
        raise FindingError(f"unknown route/state {finding['route']} / {finding['state']}")
    try:
        int(finding["width"])
    except (TypeError, ValueError) as exc:
        raise FindingError("width must be an integer") from exc
    return finding


def merge(report: dict, findings: list[dict]) -> tuple[int, list[str]]:
    """Add agent findings to the report in place. Returns (added, errors)."""
    known = {(c["route"], c["state"]) for c in report["captures"]}
    existing = {i["signature"] for i in report["issues"]}
    added, errors = 0, []
    for index, finding in enumerate(findings, 1):
        try:
            validate_finding(finding, known)
        except FindingError as exc:
            errors.append(f"finding {index}: {exc}")
            continue
        digest = hashlib.sha1(finding["description"].strip().lower().encode()).hexdigest()[:8]
        selector = finding.get("selector") or f"semantic:{finding['category']}:{digest}"
        sig = signature(f"semantic-{finding['category']}", finding["route"], finding["state"], selector)
        if sig in existing:
            continue
        existing.add(sig)
        report["issues"].append({
            "id": hashlib.sha1(sig.encode()).hexdigest()[:10],
            "signature": sig,
            "check": f"semantic-{finding['category']}",
            "severity": finding["severity"],
            "origin": "agent",
            "route": finding["route"],
            "state": finding["state"],
            "selector": selector,
            "message": finding["description"].strip(),
            "widths": [int(finding["width"])],
            "rects": {},
            "hints": {},
            "evidence": [finding["evidence"]] if finding.get("evidence") else [],
            "source_candidates": [],
        })
        added += 1
    report["issues"].sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), i["route"], i["state"], i["check"]))
    return added, errors
