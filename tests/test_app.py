"""`ui-audit ui`: the audit subprocess it starts, and the app driven in a real browser."""

import json
import subprocess
import sys
import threading
import time

import pytest

from ui_audit import report
from ui_audit.server import AppServer, Workspace


def run_runner(spec: dict, timeout: int = 120) -> tuple[int, list[dict]]:
    done = subprocess.run([sys.executable, "-m", "ui_audit.runner"], input=json.dumps(spec), capture_output=True,
                          text=True, timeout=timeout)
    events = []
    for line in done.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass  # a traceback line
    return done.returncode, events


def test_runner_reports_a_bad_config_as_an_event():
    code, events = run_runner({"config": {"no_such_key": 1}})
    assert code == 2
    assert events[-1]["event"] == "error" and "config error" in events[-1]["message"]


def test_runner_explains_when_it_cannot_tell_what_changed(tmp_path):
    spec = {"config": {"base_url": "http://127.0.0.1:9", "project_root": str(tmp_path)}, "changed_since": "main",
            "baseline": str(tmp_path / "missing")}
    code, events = run_runner(spec)
    assert code == 2
    assert events[-1]["event"] == "error" and "changed since main" in events[-1]["message"]


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_runner_streams_progress_while_it_audits(demo_site, tmp_path):
    url, site = demo_site
    config = {"base_url": url, "project_root": str(site), "output": str(tmp_path / "run"), "settle_ms": 50,
              "states": {"auto": False}, "viewports": {"widths": [390, 900]}}
    code, events = run_runner({"config": config, "routes": ["/pricing.html"]})
    assert code == 0, events
    kinds = [e["event"] for e in events if e["event"] != "log"]
    assert kinds == ["routes", "route", "state", "done"]
    assert events[[e["event"] for e in events].index("route")]["status"] == "measuring"
    done = events[-1]
    assert done["counts"]["P2"] >= 1 and done["errors"] == []
    assert report.read_json(tmp_path / "run")["only_routes"] == ["/pricing.html"]


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_app_runs_an_audit_and_accepts_a_finding(demo_site, tmp_path):
    from playwright.sync_api import sync_playwright

    from ui_audit.browser import launch

    url, site = demo_site
    project = tmp_path / "shop"
    project.mkdir()
    (project / "ui-audit.toml").write_text(
        f'base_url = "{url}"\nproject_root = "{site}"\noutput = ".ui-audit/latest"\nsettle_ms = 50\n'
        '[routes]\ndiscover = ["config"]\ninclude = ["/pricing.html"]\n')
    server = AppServer(Workspace(project, project / "ui-audit.toml"), 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = launch(playwright)
            page = browser.new_page(locale="en-US", viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(server.url)
            page.get_by_role("button", name="Start the first audit").click()
            page.get_by_role("button", name="Some pages").click()
            page.locator("#na-routes").fill("/pricing.html")
            page.locator("#na-widths").fill("390, 900")
            page.get_by_role("button", name="Start audit", exact=True).click()
            page.get_by_role("link", name="Show results").click(timeout=90_000)

            first = page.locator(".item").first
            first.wait_for()
            assert "Text clipped by its box" in page.locator(".detail h2").inner_text()
            page.locator(".stage-wrap:not(.loading-img) .stage img").wait_for()  # loaded, not replaced by an error
            assert page.locator(".stage img").evaluate("img => img.naturalWidth") > 0
            page.get_by_role("button", name="Accept", exact=True).click()
            page.locator(".accept-form textarea").fill("intentional teaser")
            page.locator(".accept-form button[type=submit]").click()
            page.get_by_text("Accepted. Later runs keep this decision.").wait_for()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    accepted = json.loads((site / "ui-audit.accepted.json").read_text())
    assert accepted and {e["reason"] for e in accepted} == {"intentional teaser"}
    run = next((project / ".ui-audit").glob("site-*"))  # named after the audited project
    saved = report.read_json(run)
    assert any(i.get("accepted") for i in saved["issues"]) and saved["config"]["viewports"]["widths"] == [390, 900]
    assert errors == []


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_static_report_opens_from_disk(demo_site, tmp_path):
    from playwright.sync_api import sync_playwright

    from ui_audit import audit
    from ui_audit.browser import launch
    from ui_audit.config import from_dict

    url, site = demo_site
    out = tmp_path / "run"
    audit.run(from_dict({"base_url": url, "project_root": str(site), "output": str(out), "settle_ms": 50,
                         "routes": {"include": ["/pricing.html"], "discover": ["config"]}, "states": {"auto": False},
                         "viewports": {"widths": [390, 900]}}), log=lambda _: None)
    errors = []
    with sync_playwright() as playwright:
        browser = launch(playwright)
        page = browser.new_page(locale="de-DE")
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto((out / "index.html").as_uri())
        page.locator(".item").first.wait_for()
        assert page.locator(".detail h2").inner_text() == "Text vom Container abgeschnitten"
        assert page.get_by_role("button", name="Befehl zum Nachprüfen kopieren").is_visible()
        started = time.monotonic()
        page.keyboard.press("ArrowDown")
        assert page.locator('.item[aria-selected="true"]').count() == 1 and time.monotonic() - started < 5
        browser.close()
    assert errors == []


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_cancelling_an_audit_stops_it_and_keeps_nothing(demo_site, tmp_path):
    import urllib.request

    url, site = demo_site
    project = tmp_path / "shop"
    project.mkdir()
    server = AppServer(Workspace(project), 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def api(path, body=None):
        request = urllib.request.Request(f"{server.url}api/{path}", data=None if body is None else json.dumps(body).encode(),
                                         headers={"X-UI-Audit-Token": server.token, "Host": f"127.0.0.1:{server.port}"})
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())

    try:
        job = api("runs", {"base_url": url, "mode": "complete"})
        assert job["name"].startswith("shop-")
        deadline = time.monotonic() + 60
        while not (api("state")["jobs"][0]["progress"].get("route")) and time.monotonic() < deadline:
            time.sleep(0.2)
        api(f"jobs/{job['id']}/cancel", {})
        while api("state")["jobs"][0]["status"] == "running" and time.monotonic() < deadline + 20:
            time.sleep(0.2)
        state = api("state")
    finally:
        server.shutdown()
        server.server_close()
    assert state["jobs"][0]["status"] == "cancelled"
    assert state["runs"] == [] and not (project / ".ui-audit" / job["name"]).exists()
