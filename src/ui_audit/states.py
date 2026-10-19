"""UI state discovery and replay.

Automatic discovery is deliberately conservative: it only clicks disclosure
controls (menus, popups, tabs, <details>, controls that open a dialog), never
anything inside a form, never a navigating link, and never a control whose
name sounds destructive. Navigation items with a hidden menu inside are
hovered, not clicked. A candidate is kept only if clicking it changes the DOM
without changing the URL. Anything riskier belongs in `[[states.custom]]`.
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
    parent: str | None = None  # the state a nested one opens from

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
    response = browser.load(page, cfg.base_url, route, width, height, cfg.settle_ms)
    if cfg.setup:
        for action in cfg.setup:
            _run_action(page, action)
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
    if not loaded:
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
    """Find safe, reversible UI states on one route, and those nested one level inside another
    (a submenu in an opened menu, a tab in an opened dialog)."""
    found: list[State] = []
    if not cfg.states.auto:
        return found
    seen_triggers: dict[str, State] = {}
    opts = {"unsafeWords": cfg.states.unsafe_words, "ignoreSelectors": cfg.checks.ignore_selectors}
    # Disclosures seen inside an opened state, tried once every state of the page itself is found.
    nested: list[tuple[State, dict, str]] = []
    for applies_to, (width, height) in DISCOVERY_WIDTHS.items():
        try:
            open_page(page, cfg, route, width, height)
            candidates = page.evaluate("o => window.__uiAudit.stateCandidates(o)", opts)
        except Exception:  # noqa: BLE001 - an unloadable route yields no states
            continue
        known = {c["selector"] for c in candidates}
        clean = True  # the page is as it was loaded
        for candidate in candidates:
            if len(found) >= cfg.states.max_per_route:
                return found
            selector = candidate["selector"]
            if selector in seen_triggers:
                # Visible at both widths: the state applies everywhere.
                seen_triggers[selector].applies_to = "any"
                continue
            changes, clean, inside = _changes_dom(page, cfg, route, candidate, width, height, clean, opts, known)
            if changes:
                state = _found_state(found, route, candidate, applies_to)
                seen_triggers[selector] = state
                if candidate["kind"] in NESTING_KINDS:
                    nested += [(state, c, applies_to) for c in inside[:MAX_NESTED]]
    for parent, candidate, applies_to in nested:
        if len(found) >= cfg.states.max_per_route:
            return found
        key = f"{parent.id} {candidate['selector']}"
        if key in seen_triggers:
            seen_triggers[key].applies_to = "any"
            continue
        width, height = DISCOVERY_WIDTHS[applies_to]
        changes, _, _ = _changes_dom(page, cfg, route, candidate, width, height, False, opts, after=parent.actions)
        if changes:
            seen_triggers[key] = _found_state(found, route, candidate, parent.applies_to, parent)
    return found


# Kinds of state whose opened layer can hold more disclosures: a submenu, a tab in a dialog.
NESTING_KINDS = {"expand", "popup", "dialog", "hover"}
# Disclosures tried inside one opened state.
MAX_NESTED = 3


def _found_state(found: list[State], route: str, candidate: dict, applies_to: str, parent: State | None = None) -> State:
    """Add a discovered state to `found`, with an id no other state of the route has. A state
    nested in another replays the other's actions first and shows while its control does."""
    selector = candidate["selector"]
    action = {candidate.get("action", "click"): selector}
    label = f"{candidate['kind']}: {candidate['label']}"
    state = State(id=auto_state_id(candidate["kind"], candidate["label"]), route=route, kind="auto",
                  label=f"{parent.label} › {label}" if parent else label,
                  actions=[*parent.actions, action] if parent else [action],
                  trigger=parent.trigger if parent else selector, applies_to=applies_to,
                  parent=parent.id if parent else None)
    if any(s.id == state.id for s in found):
        state.id = auto_state_id(candidate["kind"], candidate["label"], selector)
    if any(s.id == state.id for s in found):
        state.id = f"{state.id}-{len(found) + 1}"
    found.append(state)
    return state


def _changes_dom(page, cfg, route: str, candidate: dict, width: int, height: int, clean: bool, opts: dict,
                 known: set[str] | None = None, after: list[dict] | None = None) -> tuple[bool, bool, list[dict]]:
    """Click (or hover) a candidate and report (it opened something, the page is back as
    loaded, the candidates it brought on screen that `known` does not list). With `after`,
    the page is loaded and those actions are replayed first; it is not put back.

    Reloading before every candidate made discovery the slowest part of an audit. A
    disclosure can be closed again, so the page is reloaded only when closing it (Escape,
    then a second click, or moving the pointer away) does not bring the page back to what it was.
    """
    selector, hover = candidate["selector"], candidate.get("action") == "hover"
    try:
        if not clean or after:
            open_page(page, cfg, route, width, height)
            if after:
                if not all(_run_action(page, action) for action in after):
                    return False, False, []
                browser.settle(page, cfg.settle_ms)
        before_url = page.url
        before = page.evaluate("() => window.__uiAudit.domFingerprint()")
        target = page.locator(selector).first
        if hover:
            target.hover(timeout=3000)
        else:
            target.click(timeout=3000)
        browser.settle(page, cfg.settle_ms)
        if page.url != before_url:
            return False, False, []
        after_fingerprint = page.evaluate("() => window.__uiAudit.domFingerprint()")
        if after_fingerprint == before:
            return False, not after, []
        inside = []
        if known is not None:
            inside = [c for c in page.evaluate("o => window.__uiAudit.stateCandidates(o)", opts)
                      if c["selector"] not in known and c["selector"] != selector]
    except Exception:  # noqa: BLE001 - unclickable trigger
        return False, False, []
    if after:
        return True, False, inside
    try:
        if hover:
            page.mouse.move(0, 0)
            browser.settle(page, cfg.settle_ms)
        else:
            page.keyboard.press("Escape")
            browser.settle(page, cfg.settle_ms)
            if page.evaluate("() => window.__uiAudit.domFingerprint()") != before:
                page.locator(selector).first.click(timeout=1500)
                browser.settle(page, cfg.settle_ms)
        restored = page.url == before_url and page.evaluate("() => window.__uiAudit.domFingerprint()") == before
    except Exception:  # noqa: BLE001 - whatever is open now, the next candidate starts from a reload
        restored = False
    return True, restored, inside


def rehover(page, state: State, settle_ms: int) -> None:
    """Hover again after a resize. The pointer stays where it was while the layout moves under
    it, so a menu that opens on hover would close."""
    hovers = [action for action in state.actions if "hover" in action]
    for action in hovers:
        _run_action(page, action)
    if hovers:
        browser.settle(page, settle_ms)
