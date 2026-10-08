"""The audit pipeline: discover → sweep → capture → diagnose → map to code → report."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import __version__, browser, report as report_mod, routes, semantic, states, viewports
from .config import STANDARD_VIEWPORTS, Config
from .issues import IssueSet, sweep_signature
from .sources import SourceIndex

NOT_APPLICABLE = frozenset({"<state not applicable>"})
# The sweep waits for running transitions (browser.settle) rather than for a fixed time.
SWEEP_SETTLE_MS = 0
CANDIDATE_FACTOR = 8


def _file_slug(route: str) -> str:
    return states.slug(route.strip("/")) if route.strip("/") else "root"


def _probe_opts(cfg: Config) -> dict:
    return {
        "minTarget": cfg.checks.min_target_size,
        "overlapThreshold": cfg.checks.overlap_threshold,
        "maxPerCheck": cfg.checks.max_issues_per_check,
        "ignoreSelectors": cfg.checks.ignore_selectors,
    }


def _skip_reason(page, response, path: str, missing: str | None, seen_pages: dict[str, str],
                 seen_paths: dict[str, str], loading: bool = False) -> str | None:
    """Why a freshly loaded route adds nothing to the audit, or None if it should be audited."""
    fingerprint = page.evaluate("() => window.__uiAudit.pageFingerprint()")
    landed = routes.normalize(page.url)
    if path != "/" and (fingerprint == missing or (response is not None and response.status == 404)):
        return "not found"
    if landed != path and landed in seen_paths:
        return f"redirects to {seen_paths[landed]}"
    # A blank page or a loading skeleton identifies nothing: two different pages look alike.
    if loading or fingerprint.startswith("0:"):
        seen_paths.setdefault(landed, path)
        seen_paths.setdefault(path, path)
        return None
    if fingerprint in seen_pages:
        return f"same page as {seen_pages[fingerprint]}"
    seen_pages.setdefault(fingerprint, path)
    seen_paths.setdefault(landed, path)
    seen_paths.setdefault(path, path)
    return None


def _missing_fingerprint(page, cfg: Config) -> str | None:
    """What the app renders for a URL it does not know (single-page apps answer 200)."""
    try:
        browser.load(page, cfg.base_url, "/__ui-audit-missing-route__", 1280, 900, cfg.settle_ms)
        return page.evaluate("() => window.__uiAudit.pageFingerprint()")
    except Exception:  # noqa: BLE001 - without a reference, nothing is treated as not found
        return None


def run(cfg: Config, only_routes: list[str] | None = None, log: Callable[[str], None] = print) -> dict:
    started = time.monotonic()
    out_dir = Path(cfg.output)
    shots_dir = out_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    for stale in shots_dir.glob("*.png"):
        stale.unlink()

    vc = cfg.viewports
    issue_set = IssueSet()
    captures: list[dict] = []
    state_records: list[dict] = []
    coverage: dict[str, list[int]] = {}
    route_records: list[dict] = []
    errors: list[str] = []
    all_breakpoints: set[int] = set()
    probe_count = 0
    opts = _probe_opts(cfg)

    consent: str | None = None
    with browser.session(cfg) as (page, runtime):
        errors.extend(states.run_setup(page, cfg))
        if cfg.states.dismiss_consent:
            try:
                browser.load(page, cfg.base_url, "/", 1280, 900, cfg.settle_ms)
                consent = states.dismiss_consent(page, cfg)
            except Exception:  # noqa: BLE001 - the routes below report what cannot be loaded
                pass
        discovery = routes.discover(cfg, page, only_routes)
        errors.extend(discovery.errors)
        log(f"routes: {', '.join(r.path for r in discovery.routes)}")
        if discovery.skipped_dynamic:
            log(f"skipped dynamic routes (add [routes.samples]): {', '.join(discovery.skipped_dynamic)}")
        if consent:
            log(f"consent banner closed with \"{consent}\"")

        # A targeted rerun audits exactly what was asked for, so verify can rely on its coverage.
        dedupe = cfg.routes.dedupe and not only_routes
        missing = _missing_fingerprint(page, cfg) if dedupe else None
        seen_pages: dict[str, str] = {}
        seen_paths: dict[str, str] = {}

        measured = 0
        for position, route in enumerate(discovery.routes):
            path = route.path
            # max_routes bounds what is measured; CANDIDATE_FACTOR bounds how many pages are
            # opened to find that many, so a long list of redirects cannot run forever.
            if not only_routes and (measured >= cfg.routes.max_routes
                                    or position >= cfg.routes.max_routes * CANDIDATE_FACTOR):
                discovery.truncated = [r.path for r in discovery.routes[position:]]
                log(f"max_routes reached, not audited: {', '.join(discovery.truncated)}")
                break
            runtime.clear()
            try:
                response = browser.load(page, cfg.base_url, path, 1280, 900, cfg.settle_ms)
            except Exception as exc:  # noqa: BLE001 - keep auditing the other routes
                errors.append(f"{path}: could not load ({exc.__class__.__name__}: {str(exc)[:120]})")
                route_records.append({"path": path, "discovered_by": route.discovered_by, "loaded": False})
                continue
            if cfg.states.dismiss_consent and consent is None:
                # The banner may only exist on some pages; once it is gone, start this route clean.
                consent = states.dismiss_consent(page, cfg)
                if consent:
                    runtime.clear()
                    response = browser.load(page, cfg.base_url, path, 1280, 900, cfg.settle_ms)
            content = page.evaluate("() => window.__uiAudit.contentState()")
            skip = (_skip_reason(page, response, path, missing, seen_pages, seen_paths, content["state"] == "loading")
                    if dedupe else None)
            if skip:
                route_records.append({"path": path, "discovered_by": route.discovered_by, "loaded": True,
                                      "status": f"skipped: {skip}"})
                log(f"{path}: skipped ({skip})")
                continue
            route_records.append({"path": path, "discovered_by": route.discovered_by, "loaded": True,
                                  "status": "audited", "content": content})
            if content["state"] != "ok":
                log(f"{path}: may not show its real content ({content['state']}: {content['detail']})")
            measured += 1
            breakpoints = page.evaluate("() => window.__uiAudit.breakpoints()")
            all_breakpoints.update(breakpoints)
            baseline_errors = set(runtime.console_errors) | set(runtime.failed_resources)
            for message in runtime.console_errors:
                issue_set.runtime("console-error", path, "default", message, 1280)
            for message in runtime.failed_resources:
                issue_set.runtime("failed-resource", path, "default", message, 1280)

            state_list = [states.default_state(path), *states.custom_states(cfg, path)]
            state_list += states.discover(page, cfg, path)
            log(f"{path}: {len(state_list)} state(s), breakpoints {breakpoints or 'none'}")

            for state in state_list:
                record = state.to_dict()
                lo, hi = state.width_range(vc.min_width, vc.max_width)
                if lo > hi:
                    record["status"] = "skipped: no widths in range"
                    state_records.append(record)
                    continue
                if vc.widths:
                    probe_widths = sorted({w for w in vc.widths if lo <= w <= hi})
                else:
                    probe_widths = sorted(
                        set(viewports.sweep_widths(lo, hi, vc.sweep_step))
                        | {w for _, w, _ in STANDARD_VIEWPORTS if lo <= w <= hi}
                        | (set(viewports.breakpoint_neighbors(breakpoints, lo, hi)) if vc.breakpoint_neighbors else set())
                    )
                if not probe_widths:
                    record["status"] = "skipped: no widths in range"
                    state_records.append(record)
                    continue

                first = probe_widths[0]
                runtime.clear()
                if not states.apply(page, cfg, state, first, viewports.height_for(first)):
                    record["status"] = "skipped: could not be applied"
                    state_records.append(record)
                    continue
                if state.kind != "default":
                    for message in runtime.console_errors:
                        if message not in baseline_errors:
                            issue_set.runtime("console-error", path, state.id, message, first)
                    for message in runtime.failed_resources:
                        if message not in baseline_errors:
                            issue_set.runtime("failed-resource", path, state.id, message, first)

                results: dict[int, dict] = {}
                not_applicable: set[int] = set()

                def probe(width: int, _state=state, _results=results, _na=not_applicable) -> frozenset[str]:
                    nonlocal probe_count
                    browser.resize(page, width, viewports.height_for(width), min(cfg.settle_ms, SWEEP_SETTLE_MS))
                    probe_count += 1
                    if _state.trigger and not page.evaluate("s => window.__uiAudit.isTriggerVisible(s)", _state.trigger):
                        _na.add(width)
                        return NOT_APPLICABLE
                    result = page.evaluate("o => window.__uiAudit.probe(o)", opts)
                    _results[width] = result
                    for raw in result["issues"]:
                        issue_set.observe(raw, path, _state.id, width)
                    return sweep_signature(result)

                try:
                    sweep = viewports.sweep(probe, probe_widths, refine=vc.refine and not vc.widths,
                                            max_refinements=vc.max_refinements)
                except Exception as exc:  # noqa: BLE001 - one broken state must not end the audit
                    coverage[f"{path}|{state.id}"] = sorted(results)
                    record["status"] = f"failed: {exc.__class__.__name__}"
                    state_records.append(record)
                    errors.append(f"{path} [{state.id}]: {str(exc)[:160]}")
                    continue
                coverage[f"{path}|{state.id}"] = sorted(results)

                standard = [w for _, w, _ in STANDARD_VIEWPORTS if lo <= w <= hi]
                if vc.widths:
                    plans = [viewports.CapturePlan(w, ["requested"]) for w in probe_widths]
                else:
                    bp_widths = viewports.breakpoint_neighbors(breakpoints, lo, hi) if vc.breakpoint_neighbors else []
                    plans = viewports.select_captures(
                        standard, bp_widths, sweep.anomalies, {w for w, r in results.items() if r["issues"]},
                        vc.max_captures, lo, hi)
                plans = [p for p in plans if p.width not in not_applicable]

                for plan in plans:
                    try:
                        captures.append(_capture(page, cfg, shots_dir, out_dir, path, state, plan, results, probe))
                    except Exception as exc:  # noqa: BLE001 - keep the other screenshots
                        errors.append(f"{path} [{state.id}] {plan.width}px: screenshot failed ({str(exc)[:120]})")
                record["status"] = "audited"
                record["probed_widths"] = len(coverage[f"{path}|{state.id}"])
                record["captures"] = len(plans)
                state_records.append(record)
                log(f"  {state.id}: {len(coverage[f'{path}|{state.id}'])} widths probed, {len(plans)} captured")

    issues = issue_set.all()
    index = SourceIndex(Path(cfg.project_root))
    for issue in issues:
        if issue["check"] not in ("console-error", "failed-resource"):
            issue["source_candidates"] = index.rank(issue.get("hints") or {})
    for capture in captures:
        for issue in issues:
            if issue["route"] == capture["route"] and issue["state"] == capture["state"] and capture["width"] in issue["widths"]:
                issue["evidence"].append(capture.get("annotated") or capture["file"])

    result = {
        "tool": "ui-audit",
        "version": __version__,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": cfg.base_url,
        "project_root": str(Path(cfg.project_root).resolve()),
        "output_dir": str(out_dir),
        "config": cfg.to_dict(),
        "routes": route_records,
        "skipped_dynamic_routes": discovery.skipped_dynamic,
        "truncated_routes": discovery.truncated,
        "consent_dismissed": consent,
        "states": state_records,
        "breakpoints": sorted(all_breakpoints),
        "coverage": coverage,
        "captures": captures,
        "issues": issues,
        "errors": errors,
        "stats": {
            "probes": probe_count,
            "captures": len(captures),
            "screenshot_bytes": sum(f.stat().st_size for f in shots_dir.glob("*.png")),
            "issues": report_mod.summary_counts(issues),
            "seconds": round(time.monotonic() - started, 1),
        },
    }
    report_mod.write_json(result, out_dir)
    report_mod.write_html(result, out_dir)
    semantic.build_packet(result, out_dir)
    return result


def _capture(page, cfg: Config, shots_dir: Path, out_dir: Path, path: str, state, plan, results: dict, probe) -> dict:
    width, height = plan.width, viewports.height_for(plan.width)
    if width not in results:
        probe(width)
    browser.resize(page, width, height, cfg.settle_ms)
    scroll_width, scroll_height = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.scrollHeight]")
    # Include sideways overflow so the evidence shows what sticks out.
    clip = {"x": 0, "y": 0, "width": max(width, min(scroll_width, width * 2)),
            "height": max(min(scroll_height, 6000), height)}
    base = f"{_file_slug(path)}__{states.slug(state.id)}__{width}"
    clean = shots_dir / f"{base}.png"
    page.screenshot(path=str(clean), full_page=True, clip=clip)
    found = results.get(width, {}).get("issues", [])
    capture = {
        "route": path, "state": state.id, "width": width, "height": height, "reasons": plan.reasons,
        "file": str(clean.relative_to(out_dir)), "issue_count": len(found),
    }
    if cfg.annotate and found:
        items = [{"selector": i["selector"], "severity": i["severity"], "check": i["check"], "index": n}
                 for n, i in enumerate(found, 1)]
        page.evaluate("items => window.__uiAudit.annotate(items)", items)
        annotated = shots_dir / f"{base}__annotated.png"
        page.screenshot(path=str(annotated), full_page=True, clip=clip)
        page.evaluate("() => window.__uiAudit.clearAnnotations()")
        capture["annotated"] = str(annotated.relative_to(out_dir))
    return capture
