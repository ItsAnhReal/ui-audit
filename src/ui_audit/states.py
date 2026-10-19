"""UI state discovery and replay.

Automatic discovery is deliberately conservative: it only clicks disclosure
controls (menus, popups, tabs, <details>), never anything inside a form,
never a navigating link, and never a control whose name sounds destructive.
A candidate is kept only if clicking it changes the DOM without changing the
URL. Anything riskier belongs in `[[states.custom]]`.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import browser, viewports
from .config import describe_action

# Discovery runs once at a narrow and once at a wide viewport, because
# hamburger menus and desktop dropdowns only exist at one of them.
DISCOVERY_WIDTHS = {"narrow": (390, 844), "wide": (1280, 900)}
WIDTH_RANGES = {"narrow": (0, 1023), "wide": (768, 100000), "any": (0, 100000)}


@dataclass
class State:
    id: str
    route: str
    kind: str  # default | auto | custom
    label: str
    actions: list[dict] = field(default_factory=list)
    trigger: str | None = None
    applies_to: str = "any"  # narrow | wide | any

    def width_range(self, min_width: int, max_width: int) -> tuple[int, int]:
        low, high = WIDTH_RANGES[self.applies_to]
        return max(low, min_width), min(high, max_width)

    def to_dict(self) -> dict:
        return asdict(self)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "state"


def auto_state_id(kind: str, label: str, selector: str | None = None) -> str:
    """A discovered state's id, part of its issues' signatures. Counts in a label ("Cart (3)",
    "2 new messages") change between runs, so digits are left out; two triggers that read
    the same are told apart by the last step of their selector."""
    name = slug(re.sub(r"\d+", " ", label))
    if name == "state":
        name = kind
    if selector:
        tail = re.sub(r":nth-of-type\(\d+\)", "", selector.split(" > ")[-1])
        name = f"{name}-{slug(tail)}"
    return f"{kind}-{name}"


def default_state(route: str) -> State:
    return State(id="default", route=route, kind="default", label="Initial page")


def open_page(page, cfg, route: str, width: int, height: int):
    """Load a route and replay the setup actions on it; returns the document's response.

    Setup often only changes the current DOM (closing a promo that is not remembered), so it
    has to run again on every page that is measured, not just once. An action whose target
    is not there (a promo that stayed closed) is skipped. Then the page is scrolled through
    once, so sections that fade in on scroll are there when it is measured.
    """
    response = browser.load(page, cfg.base_url, route, width, height, cfg.settle_ms, cfg.timeouts.network_idle)
    if cfg.setup:
        for action in cfg.setup:
            _run_action(page, cfg, action)
        browser.settle(page, cfg.settle_ms)
    browser.reveal(page, cfg.settle_ms)
    return response


def first_width(page, cfg, state: State, widths: list[int]) -> tuple[int | None, bool]:
    """The narrowest of `widths` at which the state's trigger is on screen, and whether the
    page is now freshly loaded at that width, so apply() need not load it again.

    A state's width range is a guess from the two discovery widths: a menu found at 1280px
    is tried from 768px up, but its button may only show from 1024px. Starting the state at
    the first width where its button exists keeps it from being skipped altogether.
    """
    if not state.trigger or not widths:
        return (widths[0] if widths else None), False
    try:
        open_page(page, cfg, state.route, widths[0], viewports.height_for(widths[0]))
        for width in widths:
            browser.resize(page, width, viewports.height_for(width), 0)
            if page.evaluate("s => window.__uiAudit.isTriggerVisible(s)", state.trigger):
                # Loaded at a narrower width and resized is not the same as loaded here.
                return width, width == widths[0]
    except Exception:  # noqa: BLE001 - an unloadable page has no width where the state applies
        return None, False
    return None, False


def apply(page, cfg, state: State, width: int, height: int, loaded: bool = False) -> bool:
    """Load the route at `width` (unless it is `loaded` there already) and replay the state.
    False if not applicable."""
    return replay(page, cfg, state, width, height, loaded) is None


def replay(page, cfg, state: State, width: int, height: int, loaded: bool = False) -> str | None:
    """apply(), returning None when the state is open, else which step failed and why."""
    if not loaded:
        open_page(page, cfg, state.route, width, height)
    url_before = page.url
    for n, action in enumerate(state.actions, 1):
        failure = _run_action(page, cfg, action)
        if failure:
            return f"step {n} ({describe_action(action)}) failed: {failure}"
    browser.settle(page, cfg.settle_ms)
    if state.kind == "auto" and page.url != url_before:
        return "its control left the page"
    return None


def dismiss_consent(page, cfg) -> str | None:
    """Turn optional cookies down if a consent banner is showing; returns the button's label."""
    try:
        found = page.evaluate("() => window.__uiAudit.consentDecline()")
        if not found:
            return None
        page.locator(found["selector"]).first.click(timeout=3000)
        browser.settle(page, cfg.settle_ms)
    except Exception:  # noqa: BLE001 - a banner that cannot be closed is audited as it is
        return None
    return found["label"]


def run_setup(page, cfg) -> list[str]:
    """Run the configured setup actions on "/"; returns one message per action that failed."""
    if not cfg.setup:
        return []
    browser.load(page, cfg.base_url, "/", 1280, 900, cfg.settle_ms, cfg.timeouts.network_idle)
    failed = []
    for n, action in enumerate(cfg.setup, 1):
        failure = _run_action(page, cfg, action)
        if failure:
            failed.append(f"setup: step {n} ({describe_action(action)}) failed: {failure}")
    browser.settle(page, cfg.settle_ms)
    return failed


def _run_action(page, cfg, action: dict) -> str | None:
    """Run one setup or state action; None when it ran, else why it did not."""
    timeout, wait = cfg.timeouts.action, cfg.timeouts.wait_for
    try:
        if "click" in action:
            locator = page.locator(action["click"]).first
            if not locator.is_visible():
                return "not on the page or not visible"
            locator.click(timeout=timeout)
        elif "hover" in action:
            page.locator(action["hover"]).first.hover(timeout=timeout)
        elif "fill" in action:
            page.locator(action["fill"]).first.fill(str(action.get("value", "")), timeout=timeout)
        elif "select" in action:
            value = action.get("value", "")
            page.locator(action["select"]).first.select_option(
                [str(v) for v in value] if isinstance(value, list) else str(value), timeout=timeout)
        elif "check" in action:
            page.locator(action["check"]).first.check(timeout=timeout)
        elif "uncheck" in action:
            page.locator(action["uncheck"]).first.uncheck(timeout=timeout)
        elif "press" in action:
            page.keyboard.press(action["press"])
        elif "scroll" in action:
            if isinstance(action["scroll"], str):
                page.locator(action["scroll"]).first.scroll_into_view_if_needed(timeout=timeout)
            else:
                page.evaluate("y => window.scrollTo(0, y)", action["scroll"])
        elif "goto" in action:
            page.goto(browser.url_for(cfg.base_url, action["goto"]), wait_until="load")
        elif "wait" in action:
            page.wait_for_timeout(int(action["wait"]))
        elif "wait_for" in action:
            page.locator(action["wait_for"]).first.wait_for(timeout=wait)
        elif "wait_for_url" in action:
            target = action["wait_for_url"]
            # A route ("/cart") is a URL of the app; a pattern ("**/cart*") is used as it is.
            page.wait_for_url(browser.url_for(cfg.base_url, target) if target.startswith("/") else target,
                              timeout=wait)
        else:
            return "no known action"
    except Exception as exc:  # noqa: BLE001 - a failed action means the state does not apply
        return f"{exc.__class__.__name__}: {(str(exc).splitlines() or [''])[0][:160]}"
    return None


def custom_states(cfg, route: str) -> list[State]:
    states = []
    for entry in cfg.states.custom:
        if entry.get("route", "/") != route:
            continue
        name = entry.get("name") or "custom"
        states.append(State(id=f"custom-{slug(name)}", route=route, kind="custom", label=name,
                            actions=list(entry.get("actions", [])), applies_to=entry.get("applies_to", "any")))
    return states


def discover(page, cfg, route: str) -> list[State]:
    """Find safe, reversible UI states on one route."""
    found: list[State] = []
    if not cfg.states.auto:
        return found
    seen_triggers: dict[str, State] = {}
    opts = {"unsafeWords": cfg.states.unsafe_words, "ignoreSelectors": cfg.route_settings(route)[1]}
    for applies_to, (width, height) in DISCOVERY_WIDTHS.items():
        try:
            open_page(page, cfg, route, width, height)
            candidates = page.evaluate("o => window.__uiAudit.stateCandidates(o)", opts)
        except Exception:  # noqa: BLE001 - an unloadable route yields no states
            continue
        clean = True  # the page is as it was loaded
        for candidate in candidates:
            if len(found) >= cfg.states.max_per_route:
                return found
            selector = candidate["selector"]
            if selector in seen_triggers:
                # Visible at both widths: the state applies everywhere.
                seen_triggers[selector].applies_to = "any"
                continue
            changes, clean = _changes_dom(page, cfg, route, selector, width, height, clean)
            if changes:
                state = State(id=auto_state_id(candidate["kind"], candidate["label"]), route=route, kind="auto",
                              label=f"{candidate['kind']}: {candidate['label']}", actions=[{"click": selector}],
                              trigger=selector, applies_to=applies_to)
                if any(s.id == state.id for s in found):
                    state.id = auto_state_id(candidate["kind"], candidate["label"], selector)
                if any(s.id == state.id for s in found):
                    state.id = f"{state.id}-{len(found) + 1}"
                found.append(state)
                seen_triggers[selector] = state
    return found


def _changes_dom(page, cfg, route: str, selector: str, width: int, height: int, clean: bool) -> tuple[bool, bool]:
    """Click a candidate and report (it opened something, the page is back as loaded).

    Reloading before every candidate made discovery the slowest part of an audit. A
    disclosure can be closed again, so the page is reloaded only when closing it (Escape,
    then a second click) does not bring the page back to what it was.
    """
    try:
        if not clean:
            open_page(page, cfg, route, width, height)
        before_url = page.url
        before = page.evaluate("() => window.__uiAudit.domFingerprint()")
        page.locator(selector).first.click(timeout=3000)
        browser.settle(page, cfg.settle_ms)
        if page.url != before_url:
            return False, False
        after = page.evaluate("() => window.__uiAudit.domFingerprint()")
        if after == before:
            return False, True
    except Exception:  # noqa: BLE001 - unclickable trigger
        return False, False
    try:
        page.keyboard.press("Escape")
        browser.settle(page, cfg.settle_ms)
        if page.evaluate("() => window.__uiAudit.domFingerprint()") != before:
            page.locator(selector).first.click(timeout=1500)
            browser.settle(page, cfg.settle_ms)
        restored = page.url == before_url and page.evaluate("() => window.__uiAudit.domFingerprint()") == before
    except Exception:  # noqa: BLE001 - whatever is open now, the next candidate starts from a reload
        restored = False
    return True, restored
