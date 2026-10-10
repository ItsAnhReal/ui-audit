"""Browser lifecycle: launching Chromium, WebKit or Firefox, loading pages, collecting runtime errors."""

from __future__ import annotations

import glob
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from urllib.parse import urljoin, urlparse

from . import routes

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


LABELS = {"chromium": "Chromium", "webkit": "Safari (WebKit)", "firefox": "Firefox"}


def launch(playwright, executable_path: str = "", headless: bool = True, engine: str = "chromium"):
    """Launch a browser. Chromium falls back to any local Chromium build if needed;
    `executable_path` applies to Chromium only."""
    if engine != "chromium":
        try:
            return getattr(playwright, engine).launch(headless=headless)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(f"{LABELS[engine]} is not installed; run `playwright install {engine}`") from exc
            raise
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
        # The page cancelled the request itself (it navigated or unmounted); nothing failed.
        # Chromium, Firefox and WebKit each word that differently.
        if any(word in reason for word in ("ERR_ABORTED", "NS_BINDING_ABORTED", "cancelled")):
            return
        self.failed_resources.append(f"{url} ({reason})"[:300])

    def clear(self) -> None:
        self.console_errors.clear()
        self.failed_resources.clear()


@contextmanager
def session(cfg, engine: str = "chromium"):
    """Yield (page, runtime_log) with the probe script installed."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch(playwright, cfg.browser_path, engine=engine)
        context_args = {"viewport": {"width": 1280, "height": 900}}
        if cfg.storage_state:
            context_args["storage_state"] = cfg.storage_state
        if cfg.locale:
            context_args["locale"] = cfg.locale
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
            if cfg.storage_state:
                # Sign-in tokens rotate while the app runs; keep the newest ones so the next
                # audit does not start from a token that has already been exchanged.
                try:
                    context.storage_state(path=cfg.storage_state)
                    Path(cfg.storage_state).chmod(0o600)
                except Exception:  # noqa: BLE001 - a read-only session file still works for this run
                    pass
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
    """The URL of a route. Routes are relative to the base URL's path: /x under http://h/app/ is
    http://h/app/x, and a hash route /#/settings is http://h/app/#/settings."""
    # "./" keeps a first segment with a colon (/a:b) from reading as a URL scheme.
    return urljoin(base_url.rstrip("/") + "/", "./" + path.lstrip("/"))


def load(page, base_url: str, path: str, width: int, height: int, settle_ms: int):
    """Open a route and return the main document's response (None if there was none)."""
    page.set_viewport_size({"width": width, "height": height})
    url = url_for(base_url, path)
    if routes.same_document(page.url, url):
        page.goto("about:blank")  # changing only the fragment does not reload; a hash route starts fresh
    response = page.goto(url, wait_until="load", timeout=30000)
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


# Scrolls through the page once and back to the top. Sections that fade in when they scroll
# into view (IntersectionObserver, `whileInView`) stay invisible on a page nobody scrolled, and
# a full-page screenshot does not scroll, so without this they are measured and shown empty.
_REVEAL_JS = """async maxSteps => {
  const frame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const pause = () => new Promise(r => setTimeout(r, 60));
  const step = Math.max(Math.round(window.innerHeight * 0.8), 200);
  let steps = 0;
  for (let y = step; steps < maxSteps; y += step, steps++) {
    const bottom = document.documentElement.scrollHeight - window.innerHeight;
    if (y - step >= bottom) break;
    window.scrollTo(0, Math.min(y, bottom));
    await frame();
    await pause();
  }
  window.scrollTo(0, 0);
  await frame();
  return steps;
}"""
REVEAL_MAX_STEPS = 40


def reveal(page, settle_ms: int) -> None:
    """Bring in content that only appears once it has been scrolled into view."""
    try:
        if page.evaluate(_REVEAL_JS, REVEAL_MAX_STEPS):
            settle(page, settle_ms)
    except Exception:  # noqa: BLE001 - a page that navigates while scrolling is measured as it is
        pass


def resize(page, width: int, height: int, settle_ms: int) -> None:
    page.set_viewport_size({"width": width, "height": height})
    settle(page, settle_ms)
