"""Viewport selection: which widths to probe and which to capture.

The sweep probes cheaply (no screenshots) across the width range. Wherever
the set of objective issues changes between two sweep points, a binary search
finds the exact pixel where it changes. Screenshots are then taken at a
bounded, explainable set of widths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .config import STANDARD_VIEWPORTS

Signature = frozenset[str]


def height_for(width: int) -> int:
    for _, preset_width, preset_height in STANDARD_VIEWPORTS:
        if preset_width == width:
            return preset_height
    if width < 600:
        return 844
    if width < 1024:
        return 1024
    return 900


def sweep_widths(min_width: int, max_width: int, step: int) -> list[int]:
    if step <= 0:
        raise ValueError("sweep_step must be positive")
    widths = list(range(min_width, max_width + 1, step))
    if widths[-1] != max_width:
        widths.append(max_width)
    return widths


# What probe.js reads from the stylesheets the page can read: widths in @media and @container
# conditions, as min-/max-width or -inline-size or in range syntax either way round.
_QUERY_PRELUDE = re.compile(r"@(?:media|container)\b([^{;]*)\{", re.IGNORECASE)
_QUERY_WIDTHS = (
    re.compile(r"(?:min|max)-(?:width|inline-size)\s*:\s*([\d.]+)(px|em|rem)", re.IGNORECASE),
    re.compile(r"(?:width|inline-size)\s*[<>]=?\s*([\d.]+)(px|em|rem)", re.IGNORECASE),
    re.compile(r"([\d.]+)(px|em|rem)\s*[<>]=?\s*(?:width|inline-size)", re.IGNORECASE),
)


def css_breakpoints(css: str) -> list[int]:
    """The breakpoints a stylesheet's text declares, in px (an em or rem is 16px)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    found: set[int] = set()
    for prelude in _QUERY_PRELUDE.finditer(css):
        for pattern in _QUERY_WIDTHS:
            for value, unit in pattern.findall(prelude.group(1)):
                try:
                    px = round(float(value) * (1 if unit.lower() == "px" else 16))
                except ValueError:  # "1.2.3px"
                    continue
                if px > 0:
                    found.add(px)
    return sorted(found)


def breakpoint_neighbors(breakpoints: Iterable[int], min_width: int, max_width: int) -> list[int]:
    """Each declared breakpoint N contributes N-1, N and N+1."""
    widths: set[int] = set()
    for bp in breakpoints:
        for width in (bp - 1, bp, bp + 1):
            if min_width <= width <= max_width:
                widths.add(width)
    return sorted(widths)


def find_boundary(probe: Callable[[int], Signature], low: int, high: int,
                  low_sig: Signature, high_sig: Signature) -> tuple[int, int, int]:
    """Binary-search the last width that still looks like `low`.

    Returns (last_low_width, first_changed_width, probes_used). Assumes the
    signature changes at least once between `low` and `high`.
    """
    probes = 0
    while high - low > 1:
        mid = (low + high) // 2
        sig = probe(mid)
        probes += 1
        if sig == low_sig:
            low = mid
        else:
            high = mid
    return low, high, probes


@dataclass
class SweepResult:
    signatures: dict[int, Signature] = field(default_factory=dict)
    anomalies: list[int] = field(default_factory=list)
    probes: int = 0


def sweep(probe: Callable[[int], Signature], widths: list[int], refine: bool = True,
          max_refinements: int = 6) -> SweepResult:
    """Probe every width, then pin down each place the signature changes."""
    result = SweepResult()
    for width in widths:
        result.signatures[width] = probe(width)
        result.probes += 1
    if not refine:
        return result
    for low, high in refinement_order(widths, result.signatures, max_refinements):
        last_low, first_high, used = find_boundary(probe, low, high, result.signatures[low], result.signatures[high])
        result.probes += used
        for width in (last_low, first_high):
            if width not in result.anomalies:
                result.anomalies.append(width)
    return result


def refinement_order(widths: list[int], signatures: dict[int, Signature], budget: int) -> list[tuple[int, int]]:
    """The neighbouring sweep widths whose signature changes that the budget is spent on, narrowest first.

    A defect that flickers in and out at narrow widths must not use up the budget before a
    boundary at wide widths is pinned: first every change that brings in or ends a defect no
    earlier pick covers, then the remaining changes from narrow to wide."""
    changes = [(low, high) for low, high in zip(widths, widths[1:]) if signatures[low] != signatures[high]]
    covered: set[str] = set()
    first, rest = [], []
    for low, high in changes:
        changed = signatures[low] ^ signatures[high]
        if changed - covered:
            first.append((low, high))
            covered |= changed
        else:
            rest.append((low, high))
    return sorted((first + rest)[:max(budget, 0)])


@dataclass
class CapturePlan:
    width: int
    reasons: list[str]


def select_captures(standard: list[int], breakpoint_widths: list[int], anomalies: list[int],
                    with_issues: set[int], cap: int, min_width: int, max_width: int) -> list[CapturePlan]:
    """Bounded capture set, filled in priority order.

    1. standard presets (mobile, tablet, laptop, desktop)
    2. anomaly boundaries where issues are present
    3. declared breakpoint neighbours
    4. remaining anomaly boundaries
    """
    reasons: dict[int, list[str]] = {}
    order: list[int] = []

    def add(width: int, reason: str) -> None:
        if not min_width <= width <= max_width:
            return
        if width not in reasons:
            reasons[width] = []
            order.append(width)
        if reason not in reasons[width]:
            reasons[width].append(reason)

    for width in standard:
        add(width, "standard")
    for width in anomalies:
        if width in with_issues:
            add(width, "anomaly")
    for width in breakpoint_widths:
        add(width, "breakpoint")
    for width in anomalies:
        add(width, "anomaly")

    chosen = order[:cap] if cap > 0 else order
    return [CapturePlan(width, reasons[width]) for width in sorted(chosen)]
