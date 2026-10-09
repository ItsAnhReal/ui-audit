"""State discovery never clicks a control that sounds destructive, however much it looks like a disclosure."""

import functools
import http.server
import shutil
import threading
from pathlib import Path

import pytest

from ui_audit import audit
from ui_audit.config import from_dict

CASES = Path(__file__).parent / "cases"

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("chromium_available")]


class _Recorder(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, seen, **kwargs):
        self.seen = seen
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self.seen.append(self.path)
        super().do_GET()

    def log_message(self, *args):
        pass


@pytest.fixture
def recording_site(tmp_path):
    """A directory served on a free port that remembers every path asked for: (url, directory, paths)."""
    site, seen = tmp_path / "site", []
    site.mkdir()
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Recorder, directory=str(site), seen=seen))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", site, seen
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("case", [
    "never-click-destructive.html",
    pytest.param("never-click-split-label.html", marks=pytest.mark.xfail(
        strict=True, reason="probe.js matches unsafe words against the raw name, and <br> makes 'Log\\nout'")),
])
def test_destructive_disclosures_are_never_clicked(recording_site, tmp_path, case):
    url, site, seen = recording_site
    shutil.copy(CASES / case, site / case)
    route = f"/{case}"
    cfg = from_dict({
        "base_url": url, "project_root": str(site), "output": str(tmp_path / "run"), "settle_ms": 50,
        "routes": {"include": [route], "discover": ["config"]}, "viewports": {"widths": [390, 1366]},
    })
    report = audit.run(cfg, log=lambda _: None)
    assert not [p for p in seen if p.startswith("/clicked")]
    assert [i["check"] for i in report["issues"] if i["route"] == route] == []
    # The safe disclosure was found and opened, so discovery did run on this page.
    assert [s["label"] for s in report["states"] if s["route"] == route and s["kind"] == "auto"] == ["expand: More"]
