"""Issue identity and aggregation.

A probe reports observations at one width. The same defect usually shows up
across a range of widths, so observations are folded into one issue per
signature: (check, route, state, selector). The signature is what `verify`
compares between runs.
"""

from __future__ import annotations

import hashlib

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
}


def signature(check: str, route: str, state: str, selector: str) -> str:
    return f"{check}|{route}|{state}|{selector}"


def short_id(sig: str) -> str:
    return hashlib.sha1(sig.encode()).hexdigest()[:10]


def worst(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.get(a, 9) <= SEVERITY_ORDER.get(b, 9) else b


class IssueSet:
    """Accumulates observations into aggregated issues."""

    def __init__(self) -> None:
        self._issues: dict[str, dict] = {}

    def observe(self, raw: dict, route: str, state: str, width: int) -> dict:
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
            }
            self._issues[sig] = issue
        issue["severity"] = worst(issue["severity"], raw["severity"])
        if width not in issue["widths"]:
            issue["widths"].append(width)
            issue["widths"].sort()
        if raw.get("rect") and str(width) not in issue["rects"]:
            issue["rects"][str(width)] = raw["rect"]
        return issue

    def runtime(self, check: str, route: str, state: str, detail: str, width: int) -> dict:
        severity = "P2"
        raw = {"check": check, "severity": severity, "selector": detail[:120], "message": detail}
        return self.observe(raw, route, state, width)

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


def sweep_signature(probe_result: dict) -> frozenset[str]:
    """What the sweep compares between widths: which defects exist where."""
    return frozenset(f"{i['check']}|{i['selector']}" for i in probe_result["issues"]
                     if i["check"] not in {"small-target", "unnamed-control"})
