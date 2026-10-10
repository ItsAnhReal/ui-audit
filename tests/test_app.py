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
        f'base_url = "{url}"\nproject_root = "{site.as_posix()}"\noutput = ".ui-audit/latest"\nsettle_ms = 50\n'
        '[routes]\ndiscover = ["config"]\ninclude = ["/pricing.html"]\n')
    server = AppServer(Workspace(project, project / "ui-audit.toml"), 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = launch(playwright)
            page = browser.new_page(locale="en-US", viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(server.launch_url)
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


PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e2c4c0d10000000049454e44ae426082")


def small_run(folder, base_url, project):
    """A finished run with one finding and one screenshot, written as `ui-audit audit` would."""
    (folder / "shots").mkdir(parents=True)
    (folder / "shots" / "home__default__390.png").write_bytes(PNG_1PX)
    issue = {"id": "i1", "signature": "text-spill|/|default|p", "check": "text-spill", "severity": "P2", "origin": "deterministic",
             "route": "/", "state": "default", "selector": "p", "message": "text spills", "widths": [390], "evidence": [], "rects": {}}
    data = {"version": "0.1.0", "created": "2026-01-01T00:00:00+00:00", "base_url": base_url, "project_root": str(project),
            "output_dir": str(folder), "routes": [{"path": "/", "discovered_by": ["config"], "loaded": True, "status": "audited"}],
            "states": [], "breakpoints": [], "errors": [], "stats": {"issues": report.summary_counts([issue]), "seconds": 1},
            "captures": [{"route": "/", "state": "default", "width": 390, "file": "shots/home__default__390.png", "reasons": ["standard"]}],
            "config": {"viewports": {"min_width": 320, "max_width": 1920}}, "coverage": {"/|default": [390]}, "issues": [issue]}
    report.write_json(data, folder)
    report.write_html(data, folder)
    return folder


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_static_report_is_safe_and_works_from_the_keyboard(tmp_path):
    from playwright.sync_api import sync_playwright

    from ui_audit.browser import launch

    out = small_run(tmp_path / "it's a run", "javascript:alert(1)//", tmp_path)
    errors = []
    with sync_playwright() as playwright:
        browser = launch(playwright)
        page = browser.new_page(locale="en-US", viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async (t) => { window.copied = t; }}})")
        page.goto((out / "index.html").as_uri())
        page.locator(".item").first.wait_for()
        assert page.locator('a[href^="javascript"]').count() == 0  # base_url is not a web address: no "open page" link
        page.get_by_role("button", name="Copy accept command").click()
        quoted = str(tmp_path / "it's a run").replace("'", "'\\''")  # the run folder as the OS writes it
        assert page.evaluate("window.copied").startswith(f"ui-audit accept '{quoted}' ")  # one shell word

        # the focus ring shows on a ghost button that sets box-shadow: none
        settings = page.get_by_role("button", name="Settings")
        page.locator("body").focus()
        for _ in range(40):
            page.keyboard.press("Tab")
            if settings.evaluate("el => el === document.activeElement"):
                break
        ring = settings.evaluate("el => { const s = getComputedStyle(el); return [s.outlineStyle, s.outlineWidth]; }")
        assert ring == ["solid", "2px"]
        page.screenshot(path=str(tmp_path / "focus.png"))

        # single-key shortcuts can be turned off, and stay off
        page.locator(".item").first.click()
        page.keyboard.press("/")
        assert page.evaluate("document.activeElement.type") == "search"
        page.keyboard.press("Escape")
        settings.click()
        toggle = page.get_by_role("menuitemcheckbox", name="Single-key shortcuts (j, k, /)")
        assert toggle.get_attribute("aria-checked") == "true"
        toggle.click()
        page.reload()
        page.locator(".item").first.click()
        page.keyboard.press("/")
        assert page.evaluate("document.activeElement.type") != "search"
        page.get_by_role("button", name="Settings").click()
        assert page.get_by_role("menuitemcheckbox", name="Single-key shortcuts (j, k, /)").get_attribute("aria-checked") == "false"
        page.keyboard.press("Escape")

        # dialogs have a name
        page.get_by_role("button", name="Full screen").click()
        assert page.get_by_role("dialog", name="Screenshot").is_visible()
        browser.close()
    assert errors == []


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_app_opens_only_with_its_key_and_announces_errors(tmp_path):
    from playwright.sync_api import sync_playwright

    from ui_audit.browser import launch

    project = tmp_path / "shop"
    small_run(project / ".ui-audit" / "shop-20260101-090000", "http://localhost:3000", project)
    server = AppServer(Workspace(project), 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = launch(playwright)
            page = browser.new_page(locale="en-US", viewport={"width": 1280, "height": 900})
            assert page.goto(server.url).status == 403
            assert "Open the address printed in the terminal" in page.content() and server.token not in page.content()
            page.goto(server.launch_url)
            page.wait_for_url(server.url)  # the key leaves the address bar
            page.get_by_role("heading", name="shop", exact=True).wait_for()
            page.get_by_role("button", name="New audit").click()
            assert page.get_by_role("dialog", name="New audit").is_visible()
            page.keyboard.press("Escape")
            page.route("**/api/state", lambda route: route.abort())
            page.locator('[role="alert"] .toast.bad').wait_for(timeout=15_000)
            assert page.locator('[role="status"] .toast.bad').count() == 0
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
