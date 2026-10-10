"""What makes audits faster must not change what they find: fonts, blocked trackers, parallel routes."""

import http.server
import threading
import time

import pytest

from ui_audit import audit, browser
from ui_audit.config import from_dict


@pytest.fixture
def slow_font_site():
    """A page whose web font takes 800ms to arrive."""
    page = b"""<!doctype html><html><head><style>
@font-face { font-family: Slow; src: url(/slow.woff2); }
p { font-family: Slow, monospace; }
</style></head><body><p>Hello</p></body></html>"""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/slow.woff2":
                time.sleep(0.8)
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_settle_waits_for_fonts_still_loading(slow_font_site, tmp_path):
    cfg = from_dict({"base_url": slow_font_site, "output": str(tmp_path)})
    with browser.session(cfg) as (page, _):
        page.goto(slow_font_site, wait_until="domcontentloaded")
        assert page.evaluate("document.fonts.status") == "loading"
        browser.settle(page, 0)
        assert page.evaluate("document.fonts.status") == "loaded"


TRACKED = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Tracked</title>
<script async src="https://www.google-analytics.com/analytics.js"></script></head>
<body><main><h1>Tracked page</h1><img alt="" src="http://pixel.tracker.test/p.gif"></main></body></html>"""


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_blocked_trackers_are_not_failed_resources(demo_site, tmp_path):
    url, site = demo_site
    (site / "tracked.html").write_text(TRACKED)

    def failed(block):
        cfg = from_dict({"base_url": url, "project_root": str(site), "output": str(tmp_path / str(len(block))),
                         "settle_ms": 0, "block_requests": block, "states": {"auto": False},
                         "routes": {"include": ["/tracked.html"], "discover": ["config"]},
                         "viewports": {"widths": [390]}})
        report = audit.run(cfg, log=lambda _: None)
        return [i["message"] for i in report["issues"] if i["check"] == "failed-resource"]

    assert failed(["trackers", "tracker.test"]) == []
    assert any("pixel.tracker.test" in m for m in failed([]))


def test_workers_default_to_one_and_follow_the_cli(monkeypatch, tmp_path):
    from ui_audit.cli import _load_config, build_parser

    assert from_dict({}).workers == 1 and audit.worker_count(from_dict({})) == 1
    monkeypatch.setattr(audit.os, "cpu_count", lambda: 32)
    assert audit.worker_count(from_dict({"workers": 0})) == audit.AUTO_WORKERS_MAX
    monkeypatch.setattr(audit.os, "cpu_count", lambda: 1)
    assert audit.worker_count(from_dict({"workers": 0})) == 1
    monkeypatch.chdir(tmp_path)  # no ui-audit.toml to find
    args = build_parser().parse_args(["audit", "http://localhost:1", "--workers", "3"])
    assert _load_config(args)[0].workers == 3


def test_a_state_found_at_the_narrowest_width_is_not_loaded_twice(monkeypatch):
    from ui_audit import states

    loads = []
    monkeypatch.setattr(states, "open_page", lambda page, cfg, route, width, height: loads.append(width))
    monkeypatch.setattr(states.browser, "settle", lambda *args: None)

    class Page:
        url = "http://x/"
        shown_from = 320

        def __init__(self):
            self.width = 0

        def evaluate(self, script, arg=None):
            return self.width >= self.shown_from

    def resize(page, width, height, settle_ms):
        page.width = width

    monkeypatch.setattr(states.browser, "resize", resize)
    cfg = from_dict({})
    state = states.State(id="menu", route="/", kind="auto", label="menu", trigger="#m", actions=[])
    page = Page()
    first, loaded = states.first_width(page, cfg, state, [320, 400, 480])
    assert (first, loaded) == (320, True)
    assert states.apply(page, cfg, state, first, 900, loaded) and loads == [320]
    # Shown only from a wider width: loaded at 320 and resized is not loaded there, so load again.
    page, loads[:] = Page(), []
    page.shown_from = 400
    first, loaded = states.first_width(page, cfg, state, [320, 400, 480])
    assert (first, loaded) == (400, False)
    assert states.apply(page, cfg, state, first, 900, loaded) and loads == [320, 400]
    # A state without a trigger is loaded by apply.
    assert states.first_width(page, cfg, states.default_state("/"), [320, 400]) == (320, False)


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_routes_measured_side_by_side_report_as_one_after_another(demo_site, tmp_path):
    url, site = demo_site

    def run(workers):
        cfg = from_dict({"base_url": url, "project_root": str(site), "output": str(tmp_path / str(workers)),
                         "settle_ms": 0, "workers": workers, "viewports": {"widths": [390, 768, 1280]}})
        lines = []
        return audit.run(cfg, log=lines.append), lines

    (one, _), (three, lines) = run(1), run(3)
    assert len(one["routes"]) >= 3
    for key in ("routes", "states", "coverage", "coverage_truncated", "breakpoints"):
        assert one[key] == three[key], key
    assert [i["signature"] for i in one["issues"]] == [i["signature"] for i in three["issues"]]
    assert [i["widths"] for i in one["issues"]] == [i["widths"] for i in three["issues"]]
    assert [(c["route"], c["state"], c["width"]) for c in one["captures"]] == \
           [(c["route"], c["state"], c["width"]) for c in three["captures"]]
    # Each route's lines stay together: a state line follows its route's line, never another route's.
    route_lines = [n for n, line in enumerate(lines) if "state(s), breakpoints" in line]
    assert len(route_lines) == len([r for r in one["routes"] if r.get("status") == "audited"])
    for start, end in zip(route_lines, route_lines[1:] + [len(lines)]):
        assert all(line.startswith("  ") for line in lines[start + 1:end])
