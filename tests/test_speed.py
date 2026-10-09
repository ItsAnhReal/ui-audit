"""What makes audits faster must not change what they find: fonts, blocked trackers, parallel routes."""

import http.server
import threading
import time

import pytest

from ui_audit import browser
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
