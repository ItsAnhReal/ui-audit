"""The audit pipeline: discover → sweep → capture → diagnose → map to code → report."""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import __version__, browser, report as report_mod, routes, semantic, states, viewports
from .config import STANDARD_VIEWPORTS, Config
from .issues import IssueSet, coverage_key, load_accepted, mark_accepted, sweep_signature
from .sources import SourceIndex

NOT_APPLICABLE = frozenset({"<state not applicable>"})
# The sweep waits for loading fonts and running transitions (browser.settle), and at least two
# animation frames after each resize, rather than for a fixed time.
SWEEP_SETTLE_MS = 0
CANDIDATE_FACTOR = 8
# Below this width a page is read as a phone layout, also when phone emulation is turned off.
MOBILE_WIDTH = 768


# Routes measured side by side when `workers = 0`: one per two CPUs, at most this many.
AUTO_WORKERS_MAX = 4


def worker_count(cfg: Config) -> int:
    """How many routes are measured at once, each in a browser of its own."""
    return cfg.workers or max(1, min(AUTO_WORKERS_MAX, (os.cpu_count() or 2) // 2))


@dataclass
class _RouteWork:
    """What measuring one route adds to the report. It is kept apart and merged in the order
    the routes were listed, so routes measured side by side report as if one after another."""
    route: routes.Route
    breakpoints: list[int]
    baseline_errors: set[str]
    issues: list[tuple[str, tuple, dict]] = field(default_factory=list)  # IssueSet calls, in order
    finished: list[tuple[dict, str]] = field(default_factory=list)  # (state record, status)
    captures: list[dict] = field(default_factory=list)
    coverage: dict[str, list[int]] = field(default_factory=dict)
    truncated: dict[str, dict[str, set[int]]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    logs: list[str] = field(default_factory=list)
    probes: int = 0
    failure: Exception | None = None

    def observe(self, *args, **kwargs) -> None:
        self.issues.append(("observe", args, kwargs))

    def runtime(self, *args, **kwargs) -> None:
        self.issues.append(("runtime", args, kwargs))


def _file_slug(route: str) -> str:
    # Hash-router routes ("/#/settings") get their own prefix so they don't share files with "/settings".
    path, hashed, fragment = route.partition("#")
    if hashed:
        return f"{_file_slug(path)}--hash-{_file_slug(fragment)}"
    return states.slug(route.strip("/")) if route.strip("/") else "root"


def _probe_opts(cfg: Config) -> dict:
    return {
        "minTarget": cfg.checks.min_target_size,
        "overlapThreshold": cfg.checks.overlap_threshold,
        "maxPerCheck": cfg.checks.max_issues_per_check,
        "ignoreSelectors": cfg.checks.ignore_selectors,
    }


def _not_a_page(response) -> str | None:
    """The content type of a route that is a feed, a data file or an image rather than a page."""
    if response is None:
        return None
    kind = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    return None if not kind or kind in {"text/html", "application/xhtml+xml"} else kind


def _landed(url: str, base_url: str) -> str:
    """Where a route ended up: its path, or the whole URL when it left the app's origin."""
    here, there = urlparse(url), urlparse(base_url)
    path, prefix = routes.normalize(url), routes.normalize(base_url)
    if (here.scheme, here.netloc) != (there.scheme, there.netloc):
        return f"{here.scheme}://{here.netloc}{path}"
    if prefix != "/" and (path == prefix or path.startswith(prefix + "/")):
        path = path[len(prefix):] or "/"  # routes are relative to a base URL with a path
    return path


def _skip_reason(page, response, path: str, missing: str | None, seen_pages: dict[str, str],
                 seen_paths: dict[str, str], loading: bool = False, base_url: str = "") -> str | None:
    """Why a freshly loaded route adds nothing to the audit, or None if it should be audited."""
    fingerprint = page.evaluate("() => window.__uiAudit.pageFingerprint()")
    # Routes are relative to the base path; a page outside it keeps its full URL and matches no route.
    landed = routes.route_of(base_url, page.url) or page.url
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


def run(cfg: Config, only_routes: list[str] | None = None, log: Callable[[str], None] = print,
        on_event: Callable[..., None] | None = None) -> dict:
    """Audit the app. `on_event(name, **data)` reports progress: "routes" once, then "route"
    as each route is measured, skipped or fails to load, and "state" as each state is done."""
    started = time.monotonic()
    lock = threading.Lock()  # routes measured side by side report progress one at a time

    def event(name: str, **data) -> None:
        if on_event:
            with lock:
                on_event(name, **data)

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
    # Per coverage key, the checks the probe capped and the widths where it did.
    truncated: dict[str, dict[str, set[int]]] = {}
    route_records: list[dict] = []
    errors: list[str] = []
    all_breakpoints: set[int] = set()
    probe_count = 0
    opts = _probe_opts(cfg)

    consent: str | None = None
    remote_sheets: dict[str, set[int]] = {}  # stylesheet URL → its breakpoints, fetched once per run
    index = SourceIndex(Path(cfg.project_root))
    route_sources: dict[str, set[str]] = {}

    def note_sources(page, into: set[str]) -> None:
        try:
            found = page.evaluate("() => window.__uiAudit.sourceFiles()")
        except Exception:  # noqa: BLE001 - a page that navigated away has nothing to add
            return
        into.update(index.relative(f) for f in found)

    # The first browser leads: it finds the routes, decides which repeat another, and finds
    # the states. The others audit exactly those routes and states, so their findings line up.
    lead = cfg.browsers[0]
    discovery = None
    planned: dict[str, list] = {}
    lead_records: dict[tuple[str, str], dict] = {}

    def audit_in(engine: str) -> None:
        nonlocal consent, discovery
        leading = engine == lead
        label = browser.LABELS[engine]
        where = (lambda path: path) if leading else (lambda path: f"{path} ({label})")

        def merge(work: _RouteWork) -> None:
            nonlocal probe_count
            if work.failure is not None:
                raise work.failure
            path = work.route.path
            for name, args, kwargs in work.issues:
                getattr(issue_set, name)(*args, **kwargs)
            for record, status in work.finished:
                if leading:
                    record["status"] = status
                    state_records.append(record)
                    lead_records[(path, record["id"])] = record
                elif (path, record["id"]) in lead_records:
                    lead_records[(path, record["id"])].setdefault("browsers", {})[engine] = status
            captures.extend(work.captures)
            coverage.update(work.coverage)
            for key, checks in work.truncated.items():
                for check, widths in checks.items():
                    truncated.setdefault(key, {}).setdefault(check, set()).update(widths)
            errors.extend(work.errors)
            route_sources.setdefault(path, set()).update(work.sources)
            probe_count += work.probes

        def measure(session: browser.Session, pending: list[_RouteWork], run_route) -> None:
            """Measure the routes kept, in `workers` browsers at once, this one included.
            Playwright's sync API belongs to the thread that started it, so each helper thread
            runs a browser of its own, signed in and past the consent banner like this one."""
            workers = min(worker_count(cfg), len(pending))
            if workers <= 1:
                for work in pending:
                    run_route(session, work, log)
                    merge(work)
                return
            todo: queue.SimpleQueue[_RouteWork] = queue.SimpleQueue()
            for work in pending:
                todo.put(work)
            signed_in = session[0].context.storage_state()

            def drain(session: browser.Session) -> None:
                while True:
                    try:
                        work = todo.get_nowait()
                    except queue.Empty:
                        return
                    try:
                        run_route(session, work, work.logs.append)
                    except Exception as exc:  # noqa: BLE001 - raised again when merged, as if sequential
                        work.failure = exc
                    with lock:  # each route's lines together, as it finishes
                        for line in work.logs:
                            log(line)

            def helper() -> None:
                try:
                    with browser.session(cfg, engine, storage_state=signed_in) as helper_session:
                        drain(helper_session)
                except Exception as exc:  # noqa: BLE001 - the routes are left to the other browsers
                    with lock:
                        log(f"{label}: a worker browser stopped ({str(exc).splitlines()[0][:160]})")

            threads = [threading.Thread(target=helper, daemon=True) for _ in range(workers - 1)]
            for thread in threads:
                thread.start()
            drain(session)
            for thread in threads:
                thread.join()
            for work in pending:
                merge(work)

        with browser.session(cfg, engine) as opened:
            page, runtime = opened
            if len(cfg.browsers) > 1:
                log(f"{label}:")
            errors.extend(states.run_setup(page, cfg) if leading else
                          [f"{label}: {e}" for e in states.run_setup(page, cfg)])
            engine_consent = None
            if cfg.states.dismiss_consent:
                try:
                    browser.load(page, cfg.base_url, "/", 1280, 900, cfg.settle_ms)
                    engine_consent = states.dismiss_consent(page, cfg)
                except Exception:  # noqa: BLE001 - the routes below report what cannot be loaded
                    pass
            if leading:
                consent = engine_consent
                discovery = routes.discover(cfg, page, only_routes)
                errors.extend(discovery.errors)
                log(f"routes: {', '.join(r.path for r in discovery.routes)}")
                if discovery.skipped_dynamic:
                    log(f"skipped dynamic routes (add [routes.samples]): {', '.join(discovery.skipped_dynamic)}")
                route_list = discovery.routes
            else:
                route_list = [r for r in discovery.routes if r.path in planned]
            if engine_consent:
                log(f"consent banner closed with \"{engine_consent}\"")
            event("routes", paths=[r.path for r in route_list],
                  limit=None if only_routes or not leading else cfg.routes.max_routes)

            # A targeted rerun audits exactly what was asked for, so verify can rely on its coverage.
            dedupe = cfg.routes.dedupe and not only_routes and leading
            missing = _missing_fingerprint(page, cfg) if dedupe else None
            seen_pages: dict[str, str] = {}
            seen_paths: dict[str, str] = {}

            measured = 0
            pending: list[_RouteWork] = []
            for position, route in enumerate(route_list):
                path = route.path
                # max_routes bounds what is measured; CANDIDATE_FACTOR bounds how many pages are
                # opened to find that many, so a long list of redirects cannot run forever.
                if leading and not only_routes and (measured >= cfg.routes.max_routes
                                        or position >= cfg.routes.max_routes * CANDIDATE_FACTOR):
                    discovery.truncated = [r.path for r in discovery.routes[position:]]
                    log(f"max_routes reached, not audited: {', '.join(discovery.truncated)}")
                    break
                runtime.clear()
                try:
                    response = states.open_page(page, cfg, path, 1280, 900)
                except Exception as exc:  # noqa: BLE001 - keep auditing the other routes
                    errors.append(f"{where(path)}: could not load ({exc.__class__.__name__}: {str(exc)[:120]})")
                    if leading:
                        reason = f"{exc.__class__.__name__}: {(str(exc).splitlines() or [''])[0][:160]}"
                        route_records.append({"path": path, "discovered_by": route.discovered_by, "loaded": False,
                                              "error": reason})
                    event("route", path=path, status="failed", detail=exc.__class__.__name__)
                    continue
                if cfg.states.dismiss_consent and engine_consent is None:
                    # The banner may only exist on some pages; once it is gone, start this route clean.
                    engine_consent = states.dismiss_consent(page, cfg)
                    if leading:
                        consent = engine_consent
                    if engine_consent:
                        opened.reset_mobile()  # the phone page starts again from the storage without the banner
                        runtime.clear()
                        response = states.open_page(page, cfg, path, 1280, 900)
                landed = _landed(page.url, cfg.base_url)
                moved = {"landed": landed} if landed != path else {}  # a redirect, e.g. to a sign-in page
                kind = _not_a_page(response)
                if kind:
                    if leading:
                        route_records.append({"path": path, "discovered_by": route.discovered_by, "loaded": True,
                                              "status": f"skipped: not a web page ({kind})", **moved})
                    log(f"{where(path)}: skipped (not a web page: {kind})")
                    event("route", path=path, status="skipped", detail=f"not a web page ({kind})")
                    continue
                content = page.evaluate("() => window.__uiAudit.contentState()")
                skip = (_skip_reason(page, response, path, missing, seen_pages, seen_paths, content["state"] == "loading",
                                     base_url=cfg.base_url)
                        if dedupe else None)
                if skip:
                    route_records.append({"path": path, "discovered_by": route.discovered_by, "loaded": True,
                                          "status": f"skipped: {skip}", **moved})
                    log(f"{path}: skipped ({skip})")
                    event("route", path=path, status="skipped", detail=skip)
                    continue
                if leading:
                    route_records.append({"path": path, "discovered_by": route.discovered_by, "loaded": True,
                                          "status": "audited", "content": content, **moved})
                note_sources(page, route_sources.setdefault(path, set()))
                if content["state"] != "ok":
                    log(f"{where(path)}: may not show its real content ({content['state']}: {content['detail']})")
                measured += 1
                breakpoints = sorted(set(page.evaluate("() => window.__uiAudit.breakpoints()"))
                                     | _remote_breakpoints(page, remote_sheets))
                all_breakpoints.update(breakpoints)
                work = _RouteWork(route, breakpoints, set(runtime.console_errors) | set(runtime.failed_resources))
                for message in runtime.console_errors:
                    work.runtime("console-error", path, "default", message, 1280, engine=engine)
                for message in runtime.failed_resources:
                    work.runtime("failed-resource", path, "default", message, 1280, engine=engine)
                pending.append(work)

            def run_route(session: browser.Session, work: _RouteWork, say: Callable[[str], None]) -> None:
                """Find the states of a route the lead browser kept (or take the lead's) and sweep
                each one. Everything it finds goes into `work`, merged into the report later."""
                page, runtime = session
                path, breakpoints, baseline_errors = work.route.path, work.breakpoints, work.baseline_errors
                initial_anomalies: set[int] = set()
                if leading:
                    state_list = [states.default_state(path), *states.custom_states(cfg, path)]
                    state_list += states.discover(page, cfg, path)
                    planned[path] = state_list
                else:
                    state_list = planned[path]
                say(f"{where(path)}: {len(state_list)} state(s), breakpoints {breakpoints or 'none'}")
                event("route", path=path, status="measuring", states=len(state_list))

                def finish(record: dict, status: str) -> None:
                    work.finished.append((record, status))
                    event("state", path=path, state=record["id"], status=status)

                for state in state_list:
                    record = state.to_dict()
                    lo, hi = state.width_range(vc.min_width, vc.max_width)
                    if lo > hi:
                        finish(record, "skipped: no widths in range")
                        continue
                    key_only = cfg.states.sweep == "key" and state.kind != "default" and not vc.widths
                    if vc.widths:
                        probe_widths = sorted({w for w in vc.widths if lo <= w <= hi})
                    elif key_only:
                        probe_widths = sorted(
                            {w for _, w, _ in STANDARD_VIEWPORTS if lo <= w <= hi}
                            | (set(viewports.breakpoint_neighbors(breakpoints, lo, hi)) if vc.breakpoint_neighbors else set())
                            | {w for w in initial_anomalies if lo <= w <= hi}
                        ) or sorted({lo, hi})  # a range with no preset still gets probed
                    else:
                        probe_widths = sorted(
                            set(viewports.sweep_widths(lo, hi, vc.sweep_step))
                            | {w for _, w, _ in STANDARD_VIEWPORTS if lo <= w <= hi}
                            | (set(viewports.breakpoint_neighbors(breakpoints, lo, hi)) if vc.breakpoint_neighbors else set())
                        )
                    if not probe_widths:
                        finish(record, "skipped: no widths in range")
                        continue

                    runtime.clear()
                    scout = session.page_for(probe_widths[0])
                    first, loaded = states.first_width(scout, cfg, state, probe_widths)
                    if first is None:
                        finish(record, "skipped: its control is not shown at any width")
                        continue
                    if not loaded:
                        runtime.clear()
                    # Narrow widths are measured on a phone page, the others on the desktop page. The
                    # state is replayed on each page the first time a width needs it.
                    applied: dict[int, bool] = {}

                    def page_at(width: int, _state=state, _applied=applied, _ready=scout if loaded else None):
                        target = session.page_for(width)
                        if id(target) not in _applied:
                            _applied[id(target)] = states.apply(target, cfg, _state, width, viewports.height_for(width),
                                                                target is _ready)
                        return target if _applied[id(target)] else None

                    first_page = page_at(first)
                    if first_page is None:
                        finish(record, "skipped: could not be applied")
                        continue
                    if state.kind != "default":
                        note_sources(first_page, work.sources)  # an opened dialog or menu brings its own components
                        new_errors = [m for m in runtime.console_errors if m not in baseline_errors]
                        # The error came with opening this state, so the component that opened is where to look.
                        layer = (first_page.evaluate("t => window.__uiAudit.layerInfo(t)", state.trigger)
                                 if new_errors else None)
                        for message in new_errors:
                            work.runtime("console-error", path, state.id, message, first, hints=layer, engine=engine)
                        for message in runtime.failed_resources:
                            if message not in baseline_errors:
                                work.runtime("failed-resource", path, state.id, message, first, engine=engine)

                    results: dict[int, dict] = {}
                    not_applicable: set[int] = set()

                    def probe(width: int, _state=state, _results=results, _na=not_applicable,
                              _page_at=page_at) -> frozenset[str]:
                        target = _page_at(width)
                        if target is None:
                            _na.add(width)
                            return NOT_APPLICABLE
                        browser.resize(target, width, viewports.height_for(width), min(cfg.settle_ms, SWEEP_SETTLE_MS))
                        states.rehover(target, _state, min(cfg.settle_ms, SWEEP_SETTLE_MS))
                        work.probes += 1
                        if _state.trigger and not target.evaluate("s => window.__uiAudit.isTriggerVisible(s)", _state.trigger):
                            _na.add(width)
                            return NOT_APPLICABLE
                        result = target.evaluate("o => window.__uiAudit.probe(o)", opts)
                        _results[width] = result
                        for raw in result["issues"]:
                            work.observe(raw, path, _state.id, width, engine)
                        for check in result.get("truncated") or {}:
                            work.truncated.setdefault(coverage_key(path, _state.id, engine), {}).setdefault(check, set()).add(width)
                        return sweep_signature(result)

                    try:
                        sweep = viewports.sweep(probe, probe_widths, refine=vc.refine and not vc.widths and not key_only,
                                                max_refinements=vc.max_refinements)
                        if state.kind == "default":
                            initial_anomalies.update(sweep.anomalies)
                    except Exception as exc:  # noqa: BLE001 - one broken state must not end the audit
                        work.coverage[coverage_key(path, state.id, engine)] = sorted(results)
                        work.errors.append(f"{where(path)} [{state.id}]: {str(exc)[:160]}")
                        finish(record, f"failed: {exc.__class__.__name__}")
                        continue
                    work.coverage[coverage_key(path, state.id, engine)] = sorted(results)

                    standard = [w for _, w, _ in STANDARD_VIEWPORTS if lo <= w <= hi]
                    if vc.widths:
                        plans = [viewports.CapturePlan(w, ["requested"]) for w in probe_widths]
                    else:
                        bp_widths = viewports.breakpoint_neighbors(breakpoints, lo, hi) if vc.breakpoint_neighbors else []
                        # Key-width mode does not refine, so its anomalies are the initial page's, where probed.
                        anomalies = sweep.anomalies + ([w for w in sorted(initial_anomalies)
                                                        if w in results and w not in sweep.anomalies] if key_only else [])
                        plans = viewports.select_captures(
                            standard, bp_widths, anomalies, {w for w, r in results.items() if r["issues"]},
                            vc.max_captures, lo, hi)
                    plans = [p for p in plans if p.width not in not_applicable]
                    if state.kind == "default":
                        _check_viewport_meta(first_page, work, path, engine, plans, results, vc.mobile_below or MOBILE_WIDTH)

                    for plan in plans:
                        try:
                            target = page_at(plan.width)
                            if target is None:
                                continue
                            work.captures.append(_capture(target, cfg, shots_dir, out_dir, path, state, plan, results, probe, engine))
                        except Exception as exc:  # noqa: BLE001 - keep the other screenshots
                            work.errors.append(f"{where(path)} [{state.id}] {plan.width}px: screenshot failed ({str(exc)[:120]})")
                    if leading:
                        record["probed_widths"] = len(results)
                        record["captures"] = len(plans)
                    finish(record, "audited")
                    say(f"  {state.id}: {len(results)} widths probed, {len(plans)} captured")

            measure(opened, pending, run_route)

    # Only browsers that finished count as audited: a finding is "only in" some browsers only
    # where the others were really measured.
    audited_browsers = []
    for engine in cfg.browsers:
        if engine == lead:
            audit_in(engine)
            audited_browsers.append(engine)
            continue
        try:
            audit_in(engine)
            audited_browsers.append(engine)
        except Exception as exc:  # noqa: BLE001 - the lead browser's findings still stand
            errors.append(f"{browser.LABELS[engine]}: {str(exc).splitlines()[0][:200]}")
            log(f"{browser.LABELS[engine]}: not audited ({str(exc).splitlines()[0][:200]})")

    issues = issue_set.all({(s["route"], s["id"]): s["parent"] for s in state_records if s.get("parent")})
    for record in route_records:
        if record.get("status") == "audited":
            record["sources"] = sorted(s for s in route_sources.get(record["path"], ()) if not s.startswith(("/", "..")))
    for issue in issues:
        issue["source_candidates"] = index.rank(issue.get("hints") or {}, check=issue["check"])
        issue["browsers"].sort(key=cfg.browsers.index)
    for capture in captures:
        for issue in issues:
            if (issue["route"] == capture["route"] and issue["state"] == capture["state"]
                    and capture["width"] in issue["widths"] and capture["browser"] in issue["browsers"]):
                issue["evidence"].append(capture.get("annotated") or capture["file"])

    mark_accepted(issues, load_accepted(Path(cfg.project_root) / cfg.accepted_file))

    result = {
        "tool": "ui-audit",
        "version": __version__,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": cfg.base_url,
        "locale": cfg.locale,
        "browsers": audited_browsers,
        "project_root": str(Path(cfg.project_root).resolve()),
        "output_dir": str(out_dir),
        "config": cfg.to_dict(),
        # A run limited to some routes; widths of a targeted run are in config.viewports.widths.
        "only_routes": only_routes or [],
        "routes": route_records,
        "skipped_dynamic_routes": discovery.skipped_dynamic,
        "truncated_routes": discovery.truncated,
        "consent_dismissed": consent,
        "states": state_records,
        "breakpoints": sorted(all_breakpoints),
        "coverage": coverage,
        # Same keys as coverage: check → widths where the probe did not report or look at everything.
        "coverage_truncated": {key: {check: sorted(widths) for check, widths in sorted(checks.items())}
                               for key, checks in truncated.items()},
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


# Stylesheets from other origins fetched in one run, at most; most apps load one or two from a CDN.
MAX_REMOTE_SHEETS = 10


def _remote_breakpoints(page, cache: dict[str, set[int]]) -> set[int]:
    """Breakpoints in the page's stylesheets from another origin that it may not read itself
    (a CDN without CORS headers). Each is fetched once per run, with the browser's cookies."""
    try:
        hrefs = page.evaluate("() => window.__uiAudit.unreadableSheets()")
    except Exception:  # noqa: BLE001 - a page that navigated away has no stylesheets to add
        return set()
    found: set[int] = set()
    for href in hrefs:
        if href not in cache:
            if len(cache) >= MAX_REMOTE_SHEETS:
                continue
            text = browser.fetch_text(page, href)
            cache[href] = set(viewports.css_breakpoints(text)) if text else set()
        found |= cache[href]
    return found


def _check_viewport_meta(page, issue_set: IssueSet | _RouteWork, path: str, engine: str, plans: list, results: dict,
                         narrow_below: int) -> None:
    """Report a missing or zoom-blocking meta viewport once per route, at the narrowest width
    captured (or probed) below `narrow_below`, so it comes with a phone screenshot."""
    narrow = sorted(p.width for p in plans if p.width < narrow_below) or sorted(w for w in results if w < narrow_below)
    if not narrow:
        return
    try:
        raw = page.evaluate("() => window.__uiAudit.viewportMeta()")
    except Exception:  # noqa: BLE001 - a page that navigated away is measured by its sweep only
        return
    if raw:
        issue_set.observe(raw, path, "default", narrow[0], engine)


def _capture(page, cfg: Config, shots_dir: Path, out_dir: Path, path: str, state, plan, results: dict, probe,
             engine: str = "chromium") -> dict:
    width, height = plan.width, viewports.height_for(plan.width)
    if width not in results:
        probe(width)
    browser.resize(page, width, height, cfg.settle_ms)
    states.rehover(page, state, cfg.settle_ms)
    if state.kind == "default":
        # A width the page was not scrolled at can still hold sections waiting to fade in.
        # An open menu or dialog is left alone: some close when the page scrolls.
        browser.reveal(page, cfg.settle_ms)
    scroll_width, scroll_height = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.scrollHeight]")
    # Include sideways overflow so the evidence shows what sticks out.
    clip = {"x": 0, "y": 0, "width": max(width, min(scroll_width, width * 2)),
            "height": max(min(scroll_height, 6000), height)}
    base = f"{_file_slug(path)}__{states.slug(state.id)}__{width}" + ("" if engine == "chromium" else f"__{engine}")
    clean = shots_dir / f"{base}.png"
    page.screenshot(path=str(clean), full_page=True, clip=clip)
    found = results.get(width, {}).get("issues", [])
    capture = {
        "route": path, "state": state.id, "width": width, "height": height, "browser": engine, "reasons": plan.reasons,
        "file": clean.relative_to(out_dir).as_posix(), "issue_count": len(found),
    }
    if cfg.annotate and found:
        items = [{"selector": i["selector"], "severity": i["severity"], "check": i["check"], "index": n}
                 for n, i in enumerate(found, 1)]
        page.evaluate("items => window.__uiAudit.annotate(items)", items)
        annotated = shots_dir / f"{base}__annotated.png"
        page.screenshot(path=str(annotated), full_page=True, clip=clip)
        page.evaluate("() => window.__uiAudit.clearAnnotations()")
        capture["annotated"] = annotated.relative_to(out_dir).as_posix()
    return capture
