"""Browser lifecycle: launching Chromium, loading pages, collecting runtime errors."""

from __future__ import annotations

import glob
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from urllib.parse import urljoin, urlparse

PROBE_JS = resources.files("ui_audit").joinpath("probe.js").read_text(encoding="utf-8")


def _fallback_executables() -> list[str]:
    """Chromium builds already on disk, for when Playwright's pinned build is absent."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""), str(Path.home() / ".cache/ms-playwright"),
             str(Path.home() / "Library/Caches/ms-playwright"),
             str(Path(local_app_data) / "ms-playwright") if local_app_data else "", "/opt/pw-browsers"]
    patterns = ["chromium-*/chrome-linux*/chrome", "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
                "chromium-*/chrome-win*/chrome.exe",
                "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"]
    found = []
    for root in filter(None, roots):
        for pattern in patterns:
            found.extend(sorted(glob.glob(str(Path(root) / pattern)), reverse=True))
    return found


def launch(playwright, executable_path: str = "", headless: bool = True):
    """Launch Chromium, falling back to any local Chromium build if needed."""
    path = executable_path or os.environ.get("UI_AUDIT_BROWSER_PATH", "")
    if path:
        return playwright.chromium.launch(executable_path=path, headless=headless)
    try:
        return playwright.chromium.launch(headless=headless)
    except Exception as first_error:
        if "Executable doesn't exist" not in str(first_error):
            raise
        for candidate in _fallback_executables():
            try:
                return playwright.chromium.launch(executable_path=candidate, headless=headless)
            except Exception:  # noqa: BLE001 - try the next candidate
                continue
        raise


@dataclass
class RuntimeLog:
    console_errors: list[str] = field(default_factory=list)
    failed_resources: list[str] = field(default_factory=list)

    def on_console(self, message) -> None:
        # "Failed to load resource" repeats a failed request, which is
        # reported with its URL instead.
        if message.type == "error" and not message.text.startswith("Failed to load resource"):
            self.console_errors.append(message.text[:300])

    def on_failure(self, url: str, reason: str) -> None:
        # Browsers request /favicon.ico on their own; its absence is noise.
        if urlparse(url).path == "/favicon.ico":
            return
        self.failed_resources.append(f"{url} ({reason})"[:300])

    def clear(self) -> None:
        self.console_errors.clear()
        self.failed_resources.clear()


@contextmanager
def session(cfg):
    """Yield (page, runtime_log) with the probe script installed."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch(playwright, cfg.browser_path)
        context_args = {"viewport": {"width": 1280, "height": 900}}
        if cfg.storage_state:
            context_args["storage_state"] = cfg.storage_state
        context = browser.new_context(**context_args)
        context.add_init_script(PROBE_JS)
        page = context.new_page()
        log = RuntimeLog()
        page.on("console", log.on_console)
        page.on("pageerror", lambda exc: log.console_errors.append(str(exc)[:300]))
        page.on("requestfailed", lambda req: log.on_failure(req.url, str(req.failure)))
        page.on("response", lambda res: res.status >= 400 and log.on_failure(res.url, str(res.status)))
        try:
            yield page, log
        finally:
            context.close()
            browser.close()


def save_session(cfg, target: Path, path: str, wait, headless: bool = False) -> Path:
    """Open the app in a window, let `wait()` return once the person has signed in, and save
    the browser's cookies and local storage for `storage_state`."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch(playwright, cfg.browser_path, headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        try:
            context.new_page().goto(url_for(cfg.base_url, path), wait_until="load", timeout=30000)
            wait()
            target.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(target))
        finally:
            context.close()
            browser.close()
    target.chmod(0o600)  # it holds a signed-in session
    return target


def url_for(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def load(page, base_url: str, path: str, width: int, height: int, settle_ms: int):
    """Open a route and return the main document's response (None if there was none)."""
    page.set_viewport_size({"width": width, "height": height})
    response = page.goto(url_for(base_url, path), wait_until="load", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:  # noqa: BLE001 - long-polling apps never go idle
        pass
    try:  # a page that says it is still loading is not measured, or mistaken for another, as a skeleton
        page.wait_for_function("() => !document.querySelector('[aria-busy=\"true\"]')", timeout=4000)
    except Exception:  # noqa: BLE001 - some pages keep a busy region for good
        pass
    settle(page, settle_ms)
    return response


# Waits for CSS transitions and animations that are about to end, so nothing is measured
# mid-flight. Endless ones (spinners, marquees) and anything longer than the cap are not waited for.
_QUIESCE_JS = """cap => new Promise(resolve => {
  const deadline = performance.now() + cap;
  const moving = () => document.getAnimations().some(a => {
    if (a.playState !== "running" || !a.effect) return false;
    const end = a.effect.getComputedTiming().endTime;
    return Number.isFinite(end) && end - (a.currentTime || 0) <= cap;
  });
  const tick = () => (!moving() || performance.now() >= deadline) ? resolve() : requestAnimationFrame(tick);
  requestAnimationFrame(() => requestAnimationFrame(tick));
})"""
QUIESCE_CAP_MS = 600


def settle(page, settle_ms: int) -> None:
    """Let layout, transitions and fonts finish after a change."""
    page.evaluate(_QUIESCE_JS, QUIESCE_CAP_MS)
    if settle_ms:
        page.wait_for_timeout(settle_ms)


def resize(page, width: int, height: int, settle_ms: int) -> None:
    page.set_viewport_size({"width": width, "height": height})
    settle(page, settle_ms)
