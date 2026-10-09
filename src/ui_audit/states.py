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


def default_state(route: str) -> State:
    return State(id="default", route=route, kind="default", label="Initial page")


def open_page(page, cfg, route: str, width: int, height: int):
    """Load a route and replay the setup actions on it; returns the document's response.

    Setup often only changes the current DOM (closing a promo that is not remembered), so it
    has to run again on every page that is measured, not just once. An action whose target
    is not there (a promo that stayed closed) is skipped. Then the page is scrolled through
    once, so sections that fade in on scroll are there when it is measured.
    """
    response = browser.load(page, cfg.base_url, route, width, height, cfg.settle_ms)
    if cfg.setup:
        for action in cfg.setup:
            _run_action(page, action)
        browser.settle(page, cfg.settle_ms)
    browser.reveal(page, cfg.settle_ms)
    return response


def first_width(page, cfg, state: State, widths: list[int]) -> int | None:
    """The narrowest of `widths` at which the state's trigger is on screen.

    A state's width range is a guess from the two discovery widths: a menu found at 1280px
    is tried from 768px up, but its button may only show from 1024px. Starting the state at
    the first width where its button exists keeps it from being skipped altogether.
    """
    if not state.trigger or not widths:
        return widths[0] if widths else None
    try:
        open_page(page, cfg, state.route, widths[0], viewports.height_for(widths[0]))
        for width in widths:
            browser.resize(page, width, viewports.height_for(width), 0)
            if page.evaluate("s => window.__uiAudit.isTriggerVisible(s)", state.trigger):
                return width
    except Exception:  # noqa: BLE001 - an unloadable page has no width where the state applies
        return None
    return None


def apply(page, cfg, state: State, width: int, height: int) -> bool:
    """Load the route at `width` and replay the state. False if not applicable."""
    open_page(page, cfg, state.route, width, height)
    url_before = page.url
    for action in state.actions:
        if not _run_action(page, action):
            return False
    browser.settle(page, cfg.settle_ms)
    if state.kind == "auto" and page.url != url_before:
        return False
    return True


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
    browser.load(page, cfg.base_url, "/", 1280, 900, cfg.settle_ms)
    failed = [f"setup: action {n} could not run ({action})" for n, action in enumerate(cfg.setup, 1)
              if not _run_action(page, action)]
    browser.settle(page, cfg.settle_ms)
    return failed


def _run_action(page, action: dict) -> bool:
    try:
        if "click" in action:
            locator = page.locator(action["click"]).first
            if not locator.is_visible():
                return False
            locator.click(timeout=3000)
        elif "hover" in action:
            page.locator(action["hover"]).first.hover(timeout=3000)
        elif "fill" in action:
            page.locator(action["fill"]).first.fill(str(action.get("value", "")), timeout=3000)
        elif "press" in action:
            page.keyboard.press(action["press"])
        elif "wait" in action:
            page.wait_for_timeout(int(action["wait"]))
        elif "wait_for" in action:
            page.locator(action["wait_for"]).first.wait_for(timeout=5000)
        else:
            return False
    except Exception:  # noqa: BLE001 - a failed action means the state does not apply
        return False
    return True


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
    opts = {"unsafeWords": cfg.states.unsafe_words, "ignoreSelectors": cfg.checks.ignore_selectors}
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
                state = State(id=f"{candidate['kind']}-{slug(candidate['label'])}", route=route, kind="auto",
                              label=f"{candidate['kind']}: {candidate['label']}", actions=[{"click": selector}],
                              trigger=selector, applies_to=applies_to)
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
