"""Issue identity and aggregation.

A probe reports observations at one width. The same defect usually shows up
across a range of widths, so observations are folded into one issue per
signature: (check, route, state, selector). The signature is what `verify`
compares between runs.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SEVERITY_ORDER = {"P1": 1, "P2": 2, "P3": 3}

DETERMINISTIC_CHECKS = {
    "horizontal-overflow": "Page scrolls sideways; the element extends past the viewport.",
    "offscreen-control": "An interactive control is partly outside the viewport.",
    "offscreen-content": "Text or content is partly outside the viewport.",
    "clipped-content": "A box with hidden overflow cuts off its content.",
    "text-spill": "Text overflows its box visibly.",
    "overlapping-controls": "Two interactive controls overlap.",
    "small-target": "A pointer target is smaller than the minimum size.",
    "unnamed-control": "A control has no accessible name.",
    "console-error": "The page logged a JavaScript error.",
    "failed-resource": "A request failed or returned an HTTP error.",
    "viewport-meta": "The page has no usable meta viewport for phones, or it blocks zooming.",
    "sticky-covers-viewport": "Fixed and sticky bars cover too much of a phone screen.",
    "fixed-covers-end": "A fixed bottom bar covers the end of the page.",
    "small-input-font": "A text field's font is under 16px, so iOS zooms in on focus.",
    "tiny-text": "Text is smaller than 12px.",
    "distorted-image": "An image is drawn in another aspect ratio than its picture.",
    "broken-image": "An image did not load.",
}

# Findings that do not depend on the layout at a width; the sweep does not refine on them.
NOT_LAYOUT_CHECKS = {"small-target", "unnamed-control", "small-input-font", "tiny-text", "broken-image"}


# One overflow shows up as the page scrolling sideways and as content cut off at an edge.
OVERFLOW_CHECKS = {"horizontal-overflow", "offscreen-content", "offscreen-control"}
# The narrowest width most phones in use have. An overflow that only exists below it hits few
# people and is rated one step lower.
COMMON_MIN_WIDTH = 360


def signature(check: str, route: str, state: str, selector: str) -> str:
    return f"{check}|{route}|{state}|{selector}"


def coverage_key(route: str, state: str, engine: str = "chromium") -> str:
    """Where report.json's `coverage` keeps the widths probed for a route, state and browser.
    Chromium keeps the plain key, so reports from before other browsers read the same."""
    return f"{route}|{state}" if engine == "chromium" else f"{route}|{state}|{engine}"


def rect_key(width: int, engine: str = "chromium") -> str:
    """Key of an issue's box at a width in `rects`; boxes from other browsers than Chromium carry its name."""
    return str(width) if engine == "chromium" else f"{width}@{engine}"


def short_id(sig: str) -> str:
    return hashlib.sha1(sig.encode()).hexdigest()[:10]


def worst(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.get(a, 9) <= SEVERITY_ORDER.get(b, 9) else b


def milder(severity: str) -> str:
    return {"P1": "P2", "P2": "P3"}.get(severity, severity)


def rated(check: str, measured: str, widths: list[int]) -> str:
    """The severity to report for what the probe measured across `widths`."""
    if check in OVERFLOW_CHECKS and widths and max(widths) < COMMON_MIN_WIDTH:
        return milder(measured)
    return measured


# What changes between two runs of the same console error or failed request: query strings and
# fragments (cache busters), content hashes in bundle names (index-a1b2c3.js, main.3f2a1b9c.css),
# timestamps, UUIDs and long numbers (ids, columns in a minified bundle).
_URL_TAIL = re.compile(r"((?:https?|wss?|file)://[^\s?#'\"()<>]*)[?#][^\s'\"()<>]*")
_BUNDLE_HASH = re.compile(r"([\w.-]*?)[.-]([A-Za-z0-9_]{6,})(?=(?:\.chunk)?\.(?:m?js|cjs|css|map|wasm|woff2?|png|jpe?g|webp|avif|svg)\b)")
_VOLATILE = [
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"), "<time>"),
    (re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b"), "<time>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<id>"),
    (re.compile(r"\b(?=[0-9a-fA-F]*\d)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{12,}\b"), "<id>"),
    (re.compile(r"\d{5,}"), "<n>"),
]


def _hash_like(token: str) -> bool:
    return bool(re.search(r"\d", token) or (re.search(r"[A-Z]", token) and re.search(r"[a-z]", token)))


def runtime_key(detail: str) -> str:
    """The part of a console error or failed request that identifies it across runs; the raw
    text stays in the issue's message."""
    text = _URL_TAIL.sub(r"\1", detail)
    text = _BUNDLE_HASH.sub(lambda m: m.group(1) if _hash_like(m.group(2)) else m.group(0), text)
    for pattern, placeholder in _VOLATILE:
        text = pattern.sub(placeholder, text)
    return text


class IssueSet:
    """Accumulates observations into aggregated issues."""

    def __init__(self) -> None:
        self._issues: dict[str, dict] = {}
        self._measured: dict[str, str] = {}

    def observe(self, raw: dict, route: str, state: str, width: int, engine: str = "chromium") -> dict:
        sig = signature(raw["check"], route, state, raw["selector"])
        issue = self._issues.get(sig)
        if issue is None:
            issue = {
                "id": short_id(sig),
                "signature": sig,
                "check": raw["check"],
                "severity": raw["severity"],
                "origin": "deterministic",
                "route": route,
                "state": state,
                "selector": raw["selector"],
                "message": raw["message"],
                "widths": [],
                "rects": {},
                "hints": raw.get("hints") or {},
                "evidence": [],
                "source_candidates": [],
                "also_in_states": [],
                # The browsers it showed up in; the signature leaves the browser out, so one
                # defect seen in several browsers stays one issue.
                "browsers": [],
                "widths_by_browser": {},
            }
            self._issues[sig] = issue
        measured = self._measured[sig] = worst(self._measured.get(sig, raw["severity"]), raw["severity"])
        if width not in issue["widths"]:
            issue["widths"].append(width)
            issue["widths"].sort()
        issue["severity"] = rated(issue["check"], measured, issue["widths"])
        if engine not in issue["browsers"]:
            issue["browsers"].append(engine)
        seen_at = issue["widths_by_browser"].setdefault(engine, [])
        if width not in seen_at:
            seen_at.append(width)
            seen_at.sort()
        if raw.get("cause") and not issue.get("cause"):
            issue["cause"] = raw["cause"]  # what makes an overflowing element stick out
        key = rect_key(width, engine)
        if raw.get("rect") and key not in issue["rects"]:
            issue["rects"][key] = raw["rect"]
        return issue

    def runtime(self, check: str, route: str, state: str, detail: str, width: int, hints: dict | None = None,
                engine: str = "chromium") -> dict:
        severity = "P2"
        raw = {"check": check, "severity": severity, "selector": runtime_key(detail)[:120], "message": detail, "hints": hints}
        return self.observe(raw, route, state, width, engine)

    def all(self) -> list[dict]:
        """Aggregated issues. A defect that already shows in the default state is
        reported once there, with the other states it appears in listed."""
        defaults = {(i["check"], i["route"], i["selector"]): i for i in self._issues.values() if i["state"] == "default"}
        for issue in defaults.values():
            issue["also_in_states"] = []
        kept = []
        for issue in self._issues.values():
            twin = defaults.get((issue["check"], issue["route"], issue["selector"]))
            if issue["state"] != "default" and twin is not None:
                twin["also_in_states"].append(issue["state"])
                continue
            kept.append(issue)
        return sorted(kept, key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), i["route"], i["state"], i["check"], i["selector"]))


def _group_key(issue: dict) -> tuple[str, dict | None]:
    """What makes two findings the same defect: the component that renders the element.

    One overflowing card is one thing to fix however many routes and states show it. The
    line a framework's dev build reports for the element identifies that card; without it,
    the element's own tag and classes are the next best thing.
    """
    check = issue["check"]
    if check in OVERFLOW_CHECKS:
        check = "overflow"
    if check in ("console-error", "failed-resource"):
        return f"{check}|{runtime_key(issue['message'])[:160]}", None
    top = (issue.get("source_candidates") or [None])[0]
    if top and top.get("line") and "runtime source" in top.get("reasons", []):
        return f"{check}|{top['file']}:{top['line']}", {"file": top["file"], "line": top["line"]}
    tail = re.sub(r":nth-of-type\(\d+\)", "", issue.get("selector", "").split(" > ")[-1])
    return f"{check}|{tail}", None


def assign_groups(issues: list[dict]) -> list[dict]:
    """Tag every issue with the id of its group and return the groups, worst first."""
    groups: dict[str, dict] = {}
    for issue in issues:
        key, source = _group_key(issue)
        group = groups.get(key)
        if group is None:
            group = groups[key] = {"id": short_id(key), "check": issue["check"], "severity": issue["severity"],
                                   "source": source, "message": issue["message"], "count": 0, "routes": [],
                                   "widths": [], "issue_ids": []}
        issue["group"] = group["id"]
        group["severity"] = worst(group["severity"], issue["severity"])
        group["count"] += 1
        group["issue_ids"].append(issue["id"])
        if issue["route"] not in group["routes"]:
            group["routes"].append(issue["route"])
        widths = issue.get("widths") or []
        if widths:
            group["widths"] = [min(widths + group["widths"]), max(widths + group["widths"])]
    return sorted(groups.values(), key=lambda g: (SEVERITY_ORDER.get(g["severity"], 9), -len(g["routes"]), -g["count"]))


def load_accepted(path: Path) -> dict[str, dict]:
    """Findings someone looked at and accepted as intentional, by signature."""
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {e["signature"]: e for e in entries if isinstance(e, dict) and e.get("signature")}


def mark_accepted(issues: list[dict], accepted: dict[str, dict]) -> int:
    """Flag accepted issues; they stay in the report but out of the counts."""
    count = 0
    for issue in issues:
        entry = accepted.get(issue["signature"])
        if entry:
            issue["accepted"] = {"reason": entry.get("reason", ""), "date": entry.get("date", "")}
            count += 1
        else:
            issue.pop("accepted", None)
    return count


def sweep_signature(probe_result: dict) -> frozenset[str]:
    """What the sweep compares between widths: which defects exist where."""
    return frozenset(f"{i['check']}|{i['selector']}" for i in probe_result["issues"]
                     if i["check"] not in NOT_LAYOUT_CHECKS)
