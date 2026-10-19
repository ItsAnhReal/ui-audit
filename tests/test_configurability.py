"""End to end: per-check settings, rule files, route overrides, state actions, headers and basic auth."""

import base64
import http.server
import json
import secrets
import threading

import pytest

from ui_audit import audit
from ui_audit.config import from_dict

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("chromium_available")]

CONFIG_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Settings</title>
<style>body { margin: 0; font: 16px/1.5 sans-serif; } .wide { width: 900px; } .fine { font-size: 9px; }</style>
</head><body><main>
<h1>Order</h1>
<p class="fine">Fine print under 12px.</p>
<div class="wide" id="banner">A banner wider than a phone.</div>
<video id="promo" autoplay muted width="120" height="60"></video>
<label>Size <select id="size"><option value="s">Small</option><option value="m">Medium</option></select></label>
<label><input type="checkbox" id="agree"> I agree</label>
<div id="panel" hidden><div id="table" style="width: 1400px">A table that is too wide.</div></div>
</main>
<script>
const panel = document.getElementById("panel");
const update = () => {
  panel.hidden = !(location.search.includes("step=2")
    || (document.getElementById("size").value === "m" && document.getElementById("agree").checked));
};
document.getElementById("size").addEventListener("change", update);
document.getElementById("agree").addEventListener("change", update);
update();
</script></body></html>"""

AUTOPLAY_RULE = """// Videos that start playing on their own.
(context) => Array.from(document.querySelectorAll("video[autoplay]")).map((element) => ({
  element, severity: "P3", message: `Video plays on its own at ${context.width}px.`,
}));
"""

# Made up per run, so no credential-looking literal sits in the repository.
PASSWORD = secrets.token_hex(8)
TOKEN = secrets.token_hex(8)


def config(url, site, out, **data):
    base = {"base_url": url, "project_root": str(site), "output": str(out), "settle_ms": 50,
            "routes": {"discover": ["config"]}, "states": {"auto": False}}
    for key, value in data.items():
        base[key] = {**base[key], **value} if isinstance(value, dict) and key in base else value
    return from_dict(base)


def test_checks_rules_route_overrides_and_state_actions(demo_site, tmp_path):
    url, site = demo_site
    (site / "config.html").write_text(CONFIG_PAGE)
    (site / "rules").mkdir()
    (site / "rules" / "autoplay-video.js").write_text(AUTOPLAY_RULE)
    (site / "rules" / "broken.js").write_text("() => { throw new Error('rule went wrong'); }")
    cfg = config(
        url, site, tmp_path / "run",
        routes={"include": ["/config.html", "/pricing.html"],
                "overrides": [{"route": "/config*", "widths": [500], "ignore_selectors": ["#banner"]}]},
        viewports={"widths": [390]},
        checks={"disable": ["tiny-text"], "severity": {"clipped-content": "P1"},
                "rules": ["rules/autoplay-video.js", "rules/broken.js"]},
        states={"custom": [
            {"name": "panel", "route": "/config.html", "actions": [
                {"select": "#size", "value": "m"}, {"check": "#agree"}, {"wait_for": "#table"}, {"scroll": "#table"},
                {"scroll": 0}]},
            {"name": "step two", "route": "/config.html", "actions": [
                {"goto": "/config.html?step=2"}, {"wait_for_url": "**/config.html?step=2"}]},
            {"name": "missing", "route": "/config.html", "actions": [{"check": "#agree"}, {"click": "#nope"}]},
        ]})
    report = audit.run(cfg, log=lambda _: None)

    # The override's widths replace the sweep on its routes only.
    assert report["coverage"]["/config.html|default"] == [500]
    assert report["coverage"]["/pricing.html|default"] == [390]
    issues = report["issues"]
    assert not [i for i in issues if i["check"] == "tiny-text"]
    assert not [i for i in issues if "banner" in i["selector"]]  # ignored on that route
    clipped = [i for i in issues if i["check"] == "clipped-content" and i["route"] == "/pricing.html"]
    assert clipped and all(i["severity"] == "P1" for i in clipped)

    rule = [i for i in issues if i["check"] == "rule:autoplay-video"]
    assert len(rule) == 1 and rule[0]["origin"] == "rule" and rule[0]["severity"] == "P3"
    assert rule[0]["selector"] == "#promo" and rule[0]["widths"] == [500] and rule[0]["message"].endswith("500px.")
    assert all(i["origin"] == "deterministic" for i in issues if not i["check"].startswith("rule:"))
    assert any("rule rule:broken failed" in e and "rule went wrong" in e for e in report["errors"])

    status = {s["id"]: s["status"] for s in report["states"]}
    assert status["custom-panel"] == status["custom-step-two"] == "audited"
    for state in ("custom-panel", "custom-step-two"):
        assert [i for i in issues if i["state"] == state and i["check"] == "horizontal-overflow"
                and "table" in i["selector"]], state
    assert status["custom-missing"] == ("skipped: could not be applied (step 2 (click '#nope') failed: "
                                        "not on the page or not visible)")
    assert any("[custom-missing]: step 2 (click '#nope')" in e for e in report["errors"])


class _Recorder:
    def __init__(self):
        self.seen: list[tuple[str, str | None, str | None]] = []  # (path, X-Token, Authorization)


def _serve(handler_class):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_headers_and_basic_auth_reach_the_app_only(tmp_path, monkeypatch):
    app, other = _Recorder(), _Recorder()
    pixel = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")

    class Other(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            other.seen.append((self.path, self.headers.get("X-Token"), self.headers.get("Authorization")))
            self.send_response(200)
            self.send_header("Content-Type", "image/gif")
            self.end_headers()
            self.wfile.write(pixel)

        def log_message(self, *args):
            pass

    other_server = _serve(Other)
    # localhost and 127.0.0.1 are different origins.
    elsewhere = f"http://localhost:{other_server.server_address[1]}/pixel.gif"
    expected = "Basic " + base64.b64encode(f"preview:{PASSWORD}".encode()).decode()

    class App(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            app.seen.append((self.path, self.headers.get("X-Token"), self.headers.get("Authorization")))
            if self.headers.get("Authorization") != expected:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="staging"')
                self.end_headers()
                return
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            if self.path == "/sitemap.xml":
                body, kind = (f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{base}/about</loc>'
                              "</url></urlset>"), "application/xml"
            else:
                body, kind = ('<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width">'
                              f'<title>t</title></head><body><main><h1>Staging</h1><img alt="" src="{elsewhere}">'
                              "</main></body></html>"), "text/html"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    app_server = _serve(App)
    try:
        monkeypatch.setenv("UI_AUDIT_TEST_TOKEN", TOKEN)
        url = f"http://127.0.0.1:{app_server.server_address[1]}"
        cfg = config(url, tmp_path, tmp_path / "run", routes={"discover": ["sitemap"], "dedupe": False}, viewports={"widths": [800]},
                     headers={"X-Token": "${UI_AUDIT_TEST_TOKEN}"},
                     http_credentials={"username": "preview", "password": PASSWORD},
                     timeouts={"navigation": 10000, "network_idle": 500})
        report = audit.run(cfg, log=lambda _: None)
    finally:
        app_server.shutdown()
        other_server.shutdown()

    # The sitemap was fetched with the credentials and the header, so its route was found.
    assert [r["path"] for r in report["routes"] if r.get("status") == "audited"] == ["/about"]
    assert ("/sitemap.xml", TOKEN, expected) in app.seen
    assert any(path == "/about" and token == TOKEN and auth == expected for path, token, auth in app.seen)
    assert other.seen and all(token is None and auth is None for _, token, auth in other.seen)
    text = (tmp_path / "run" / "report.json").read_text(encoding="utf-8")
    assert TOKEN not in text and PASSWORD not in text
    stored = json.loads(text)["config"]
    assert stored["headers"] == {"X-Token": "${UI_AUDIT_TEST_TOKEN}"}
    assert stored["http_credentials"] == {"username": "preview", "password": "<redacted>"}
