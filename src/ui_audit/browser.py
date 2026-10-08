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
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""), str(Path.home() / ".cache/ms-playwright"), "/opt/pw-browsers"]
    patterns = ["chromium-*/chrome-linux*/chrome", "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
                "chromium-*/chrome-win*/chrome.exe"]
    found = []
    for root in filter(None, roots):
        for pattern in patterns:
            found.extend(sorted(glob.glob(str(Path(root) / pattern)), reverse=True))
    return found


def launch(playwright, executable_path: str = ""):
    """Launch Chromium, falling back to any local Chromium build if needed."""
    path = executable_path or os.environ.get("UI_AUDIT_BROWSER_PATH", "")
    if path:
        return playwright.chromium.launch(executable_path=path)
    try:
        return playwright.chromium.launch()
    except Exception as first_error:
        if "Executable doesn't exist" not in str(first_error):
            raise
        for candidate in _fallback_executables():
            try:
                return playwright.chromium.launch(executable_path=candidate)
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


def url_for(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def load(page, base_url: str, path: str, width: int, height: int, settle_ms: int) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url_for(base_url, path), wait_until="load", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:  # noqa: BLE001 - long-polling apps never go idle
        pass
    settle(page, settle_ms)


def settle(page, settle_ms: int) -> None:
    """Let layout, transitions and fonts finish after a change."""
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    if settle_ms:
        page.wait_for_timeout(settle_ms)


def resize(page, width: int, height: int, settle_ms: int) -> None:
    page.set_viewport_size({"width": width, "height": height})
    settle(page, settle_ms)
