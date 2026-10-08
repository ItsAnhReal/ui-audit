import functools
import http.server
import shutil
import threading
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent / "demo"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def demo_site(tmp_path):
    """A private copy of the demo app served on a free port: (url, directory)."""
    site = tmp_path / "site"
    shutil.copytree(DEMO, site)
    handler = functools.partial(_QuietHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", site
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def chromium_available():
    try:
        from playwright.sync_api import sync_playwright

        from ui_audit.browser import launch

        with sync_playwright() as playwright:
            launch(playwright).close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Chromium unavailable: {str(exc).splitlines()[0]}")
