// Injected into every page as an init script. Defines window.__uiAudit.
// Everything here is read-only except annotate()/clearAnnotations(), which
// add and remove an overlay that every probe ignores.
(() => {
  if (window.__uiAudit) return;

  const OVERLAY_ATTR = "data-ui-audit-overlay";
  const INTERACTIVE = [
    "a[href]", "button", "input:not([type=hidden])", "select", "textarea", "summary",
    "[role=button]", "[role=link]", "[role=tab]", "[role=menuitem]", "[role=checkbox]",
    "[role=switch]", "[tabindex]:not([tabindex='-1'])",
  ].join(",");
  const LAYER = "[role=menu],[role=dialog],[role=listbox],[role=tooltip],[popover],dialog,[aria-modal=true]";
  const TEXT_FIELD = "textarea,select,input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit]):not([type=reset]):not([type=image]):not([type=range]):not([type=color]):not([type=file])";
  const CONSENT_DECLINE = /only (the )?(necessary|essential|required)|(necessary|essential|required)( cookies)? only|reject|decline|deny|refuse|nur (notwendige|erforderliche|essenzielle)|ablehnen|refuser|rechazar|rifiuta/i;
  const CONSENT_TOPIC = /cookie|consent|einwilligung|zustimm|datenschutz|privacy|confidentialité|vie privée|privacidad|rgpd|gdpr|dsgvo/i;
  const PROBLEM_HEADING = /not found|unavailable|went wrong|\berror\b|access denied|forbidden|no longer exists|nicht gefunden|nicht verfügbar|\bfehler\b|kein zugriff|introuvable|indisponible|no encontrad|no disponible/i;
  // Whole words or phrases, matched case-insensitively: "order" alone would also stop "Order history".
  const DEFAULT_UNSAFE = [
    "delete", "remove", "logout", "log out", "sign out", "signout", "pay", "buy", "purchase",
    "checkout", "place order", "order now", "submit", "send", "publish", "unsubscribe", "cancel subscription",
    "reset", "archive", "disable", "deactivate", "approve", "reject", "save", "transfer", "refund",
    "löschen", "entfernen", "abmelden", "kaufen", "bestellen", "bezahlen", "senden", "absenden",
    "zurücksetzen", "archivieren", "deaktivieren", "genehmigen", "ablehnen", "speichern", "überweisen",
    "erstatten", "kündigen", "veröffentlichen",
  ];

  // probe() keeps every element's computed style for the length of one measurement: the
  // helpers below ask for the same ancestors' styles over and over. The page does not change
  // while it is measured, and outside probe() every call goes to the browser.
  const browserStyle = window.getComputedStyle.bind(window);
  let styleCache = null;
  function getComputedStyle(el, pseudo) {
    if (!styleCache || pseudo) return browserStyle(el, pseudo);
    let style = styleCache.get(el);
    if (!style) styleCache.set(el, style = browserStyle(el));
    return style;
  }

  // Open shadow roots are measured like the rest of the page: web components (Lit, Shoelace,
  // Ionic) render everything inside them. Closed ones cannot be read.
  //
  // Every element under root, the contents of open shadow roots right after their host.
  function deepElements(root) {
    const out = [];
    for (const el of root.querySelectorAll("*")) {
      out.push(el);
      if (el.shadowRoot) for (const inner of deepElements(el.shadowRoot)) out.push(inner);
    }
    return out;
  }

  // The box el is laid out in: a slotted element's slot, a shadow root's host, else the parent.
  function parentOf(node) {
    if (node.assignedSlot) return node.assignedSlot;
    if (node.parentElement) return node.parentElement;
    const up = node.parentNode;
    return up && up.host ? up.host : null;
  }

  // The document or shadow root el belongs to; probe() caches it per element.
  let rootCache = null;
  function rootOf(el) {
    if (!rootCache) return el.getRootNode();
    let root = rootCache.get(el);
    if (!root) rootCache.set(el, root = el.getRootNode());
    return root;
  }

  // closest() and contains() that look past shadow roots to their hosts.
  function closestDeep(el, selector) {
    for (let node = el; node; node = rootOf(node).host || null) {
      const found = node.closest(selector);
      if (found) return found;
    }
    return null;
  }

  function containsDeep(a, b) {
    if (a.contains(b)) return true;
    for (let root = rootOf(b); root.host; root = rootOf(root.host)) {
      if (a.contains(root.host)) return true;
    }
    return false;
  }

  // The element on top at a point, inside shadow roots too (the document only names the host).
  function elementAt(x, y) {
    let el = document.elementFromPoint(x, y);
    while (el && el.shadowRoot) {
      const inner = el.shadowRoot.elementFromPoint(x, y);
      if (!inner || inner === el) break;
      el = inner;
    }
    return el;
  }

  function queryAllDeep(selector, root = document) {
    const found = Array.from(root.querySelectorAll(selector));
    for (const el of root.querySelectorAll("*")) {
      if (el.shadowRoot) found.push(...queryAllDeep(selector, el.shadowRoot));
    }
    return found;
  }

  // A selector's steps: ` >> ` enters the shadow root of what the step before matched (as in
  // Playwright, whose CSS also looks inside shadow roots), and FRAME_STEP enters an iframe.
  const FRAME_STEP = "internal:control=enter-frame";
  function selectorSteps(selector) {
    const steps = [];
    let quote = null, start = 0;
    for (let i = 0; i < selector.length; i++) {
      const c = selector[i];
      if (quote) {
        if (c === "\\") i++;
        else if (c === quote) quote = null;
      } else if (c === "\"" || c === "'") {
        quote = c;
      } else if (selector.startsWith(" >> ", i)) {
        steps.push(selector.slice(start, i));
        start = i + 4;
        i += 3;
      }
    }
    steps.push(selector.slice(start));
    return steps;
  }

  // Where an iframe's content starts, in the viewport of the document holding the iframe.
  function frameOffset(frame) {
    const r = frame.getBoundingClientRect();
    const style = getComputedStyle(frame);
    return {
      x: r.left + frame.clientLeft + (parseFloat(style.paddingLeft) || 0),
      y: r.top + frame.clientTop + (parseFloat(style.paddingTop) || 0),
    };
  }

  // The element a selector of cssPath() names, with the offset of the iframes it is in.
  function queryDeep(selector) {
    let scope = document, el = null, dx = 0, dy = 0;
    for (const step of selectorSteps(selector)) {
      if (step === FRAME_STEP) {
        if (!el || el.tagName !== "IFRAME") return null;
        let doc = null;
        try { doc = el.contentDocument; } catch (e) { doc = null; }
        if (!doc) return null;
        const offset = frameOffset(el);
        dx += offset.x;
        dy += offset.y;
        scope = doc;
        el = null;
        continue;
      }
      if (el) scope = el.shadowRoot || el;
      try { el = scope.querySelector(step); } catch (e) { return null; }
      if (!el) return null;
    }
    return el ? { el, dx, dy } : null;
  }

  // One pattern for a list of words: each matches as a whole word (letters and digits of any
  // script count as word characters), any run of spaces matches the space in a phrase.
  function wordPattern(words) {
    const parts = words.map((w) => String(w).trim()).filter(Boolean)
      .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+"));
    return parts.length ? new RegExp(`(?<![\\p{L}\\p{N}])(?:${parts.join("|")})(?![\\p{L}\\p{N}])`, "iu") : null;
  }

  function isIgnored(el, ignore) {
    if (closestDeep(el, `[${OVERLAY_ATTR}]`)) return true;
    for (const selector of ignore || []) {
      try { if (closestDeep(el, selector)) return true; } catch (e) { /* invalid selector */ }
    }
    return false;
  }

  function isVisible(el) {
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) {
      return false;
    }
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function isScreenReaderOnly(el) {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 2 || rect.height <= 2) return true;
    const style = getComputedStyle(el);
    return style.clip === "rect(0px, 0px, 0px, 0px)" || style.clipPath === "inset(50%)";
  }

  // Build tools add classes and ids that change with every build or render: CSS Modules
  // (card_x7Yz2, Home_main__nLjiQ, _3kd9A), styled-components (sc-…, kCQjZg), emotion (css-1x2y3z),
  // Svelte (svelte-1abc), styled-jsx (jsx-123), React's useId (:r1:). A selector built from them
  // changes the issue's signature on every build.
  const GENERATED_CLASS = /^(sc-|css-|svelte-|jsx-\d|ng-tns-)/;
  const GENERATED_ID = /^(radix-|headlessui-|react-aria|mui-|ember\d|yui_|uid-)|:|^\d|\d{4,}/;
  const TEST_ATTRS = ["data-testid", "data-test", "data-cy"];
  const MAX_DEPTH = 8;

  function looksRandom(token) {
    if (token.length < 5) return false;
    // Letters and digits alternating three times or more: x7Yz2, a1b2c3, 3kd9A.
    if (/^[A-Za-z0-9]+$/.test(token) && (token.match(/[A-Za-z](?=\d)|\d(?=[A-Za-z])/g) || []).length >= 3) return true;
    // Mixed case that is not camelCase: kCQjZg, nLjiQ (navBar and myButton are camelCase).
    return token.length <= 8 && /^[A-Za-z]+$/.test(token) && /[A-Z]/.test(token) && /[a-z]/.test(token)
      && !/^[A-Za-z][a-z]*([A-Z][a-z]+)*$/.test(token);
  }

  function isGeneratedClass(c) {
    return GENERATED_CLASS.test(c) || c.startsWith("_") || c.split(/_+|-+/).some(looksRandom);
  }

  function stableClasses(el) {
    return Array.from(el.classList)
      .filter((c) => c.length <= 30 && !/[:\[\]\/.@%]/.test(c) && !isGeneratedClass(c))
      .slice(0, 2);
  }

  function stableId(el) {
    const id = el.id;
    return id && id.length <= 40 && !GENERATED_ID.test(id) && !id.split(/[-_]+/).some(looksRandom) ? id : null;
  }

  const attr = (name, value) => `[${name}="${value.replace(/["\\]/g, "\\$&")}"]`;

  // Unique in el's own document or shadow root, where a step of a selector looks.
  function unique(selector, el) {
    try {
      const found = rootOf(el).querySelectorAll(selector);
      return found.length === 1 && found[0] === el;
    } catch (e) {
      return false;
    }
  }

  // One step of a path: a test id or id that is unique by itself, or the tag with role and
  // label (controls only, labels without counts in them), stable classes, and nth-of-type
  // when a sibling would match too.
  function pathPart(node) {
    for (const name of TEST_ATTRS) {
      const value = node.getAttribute(name);
      if (value && unique(attr(name, value), node)) return { part: attr(name, value), anchor: true };
    }
    const id = stableId(node);
    if (id && unique(`#${CSS.escape(id)}`, node)) return { part: `#${CSS.escape(id)}`, anchor: true };
    let part = node.tagName.toLowerCase();
    if (node.matches(INTERACTIVE)) {
      const role = node.getAttribute("role");
      const label = node.getAttribute("aria-label") || "";
      if (role && /^[a-z]+$/.test(role)) part += `[role=${role}]`;
      if (label.trim() && label.length <= 60 && !/[\d\n]/.test(label)) part += attr("aria-label", label);
    }
    part += stableClasses(node).map((c) => `.${CSS.escape(c)}`).join("");
    const parent = node.parentNode;  // a shadow root has children too
    if (parent && parent.children) {
      const same = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      if (same.some((c) => c !== node && c.matches(part))) part += `:nth-of-type(${same.indexOf(node) + 1})`;
    }
    return { part, anchor: false };
  }

  // The shortest path up from el that is unique on the page, so it stays the same across
  // builds and annotate() marks the right element. probe() caches it per element.
  let pathCache = null;
  function cssPath(el) {
    if (pathCache && pathCache.has(el)) return pathCache.get(el);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < MAX_DEPTH) {
      if (node === document.body || node === document.documentElement) {
        parts.unshift(node.tagName.toLowerCase());
        break;
      }
      const { part, anchor } = pathPart(node);
      parts.unshift(part);
      if (anchor || unique(parts.join(" > "), el)) break;
      node = node.parentElement;
    }
    let path = parts.join(" > ");
    const host = rootOf(el).host;
    if (host) path = `${cssPath(host)} >> ${path}`;
    if (pathCache) pathCache.set(el, path);
    return path;
  }

  // The first visible text in `elements` that runs past the viewport's right edge (the left
  // edge on a right-to-left page) with nothing clipping it.
  function overflowingText(elements, vw, rtl) {
    const range = document.createRange();
    for (const parent of elements) {
      for (const node of parent.childNodes) {
        if (node.nodeType !== 3 || !node.nodeValue.trim()) continue;
        if (!isVisible(parent) || clippingAncestor(parent)) break;
        if (insideFixed(parent)) break;  // a fixed box never widens the page
        range.selectNodeContents(node);
        // Text its own box clips (a visually hidden label) reaches only as far as that box.
        const clipsOwn = getComputedStyle(parent).overflowX !== "visible";
        const box = clipsOwn ? parent.getBoundingClientRect() : range.getBoundingClientRect();
        const edge = (rtl ? box.left : box.right) + window.scrollX;
        if (rtl ? edge < -1 : edge > vw + 1) return { el: parent, text: node.nodeValue.trim().slice(0, 60), edge: Math.round(edge) };
      }
    }
    return null;
  }

  function insideFixed(el) {
    for (let node = el; node && node !== document.documentElement; node = parentOf(node)) {
      if (getComputedStyle(node).position === "fixed") return true;
    }
    return false;
  }

  // The nearest ancestor whose overflow clips el sideways. An absolutely positioned box is
  // clipped only from its containing block upwards, and a fixed one by none of them: a
  // visually hidden label inside a scrolling row still widens the page when the row is static.
  function clippingAncestor(el) {
    let position = getComputedStyle(el).position;
    for (let node = parentOf(el); node && node !== document.body && node !== document.documentElement; node = parentOf(node)) {
      const style = getComputedStyle(node);
      const transformed = style.transform !== "none" || style.filter !== "none" || /paint|layout|strict|content/.test(style.contain);
      const containing = transformed || (position === "absolute" && style.position !== "static");
      if ((position === "absolute" || position === "fixed") && !containing) continue;
      if (style.overflowX !== "visible") return { node, mode: style.overflowX };
      position = style.position === "absolute" || style.position === "fixed" ? style.position : "static";
    }
    return null;
  }

  // The part of an element that scrolling and clipping ancestors leave on screen.
  function visibleRect(el) {
    const r = el.getBoundingClientRect();
    const box = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    for (let node = el; node && node !== document.body; node = parentOf(node)) {
      if (getComputedStyle(node).position === "fixed") break;  // fixed boxes escape their ancestors' clip
      const parent = parentOf(node);
      if (!parent || parent === document.body || parent === document.documentElement) break;
      const style = getComputedStyle(parent);
      if (style.overflowX === "visible" && style.overflowY === "visible") continue;
      const clip = parent.getBoundingClientRect();
      box.left = Math.max(box.left, clip.left); box.right = Math.min(box.right, clip.right);
      box.top = Math.max(box.top, clip.top); box.bottom = Math.min(box.bottom, clip.bottom);
    }
    box.width = Math.max(box.right - box.left, 0);
    box.height = Math.max(box.bottom - box.top, 0);
    return box;
  }

  const truncates = (style) => style.textOverflow === "ellipsis" || (style.webkitLineClamp && style.webkitLineClamp !== "none");

  // Up to `limit` non-blank text nodes laid out inside el, in order: into open shadow roots and
  // what their slots show, not into light children that no slot shows.
  function flatText(el, limit) {
    const out = [];
    const visit = (node) => {
      const children = node.tagName === "SLOT" ? node.assignedNodes({ flatten: true })
        : node.shadowRoot ? node.shadowRoot.childNodes : node.childNodes;
      for (const child of children) {
        if (out.length >= limit) return;
        if (child.nodeType === 3) {
          if (child.nodeValue.trim()) out.push(child);
        } else if (child.nodeType === 1) {
          visit(child);
        }
      }
    };
    visit(el);
    return out;
  }

  // Whether glyphs, not just line spacing or padding, cross the box that clips them.
  // scrollHeight counts the empty leading of a line box, so a 20px line in an 18px
  // box "overflows" although every letter is visible.
  function inkIsClipped(el, horizontal) {
    const box = el.getBoundingClientRect();
    const range = document.createRange();
    for (const node of flatText(el, 200)) {
      const parent = node.parentElement;
      if (!parent || !isVisible(parent) || isScreenReaderOnly(parent)) continue;
      // Text that a box in between already shortens on purpose is not this box's defect.
      let intended = false;
      for (let up = node.assignedSlot || parent; up && up !== el; up = parentOf(up)) {
        if (truncates(getComputedStyle(up))) { intended = true; break; }
      }
      if (intended) continue;
      const fontSize = parseFloat(getComputedStyle(parent).fontSize) || 16;
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) {
        if (!r.width || !r.height) continue;
        if (horizontal) {
          if (r.left < box.left - 1 || r.right > box.right + 1) {
            if (!inParkedPanel(parent, el, box)) return true;
          }
        } else {
          const slack = Math.max(r.height - fontSize, 0) / 2;  // leading above and below the glyphs
          if (r.top + slack < box.top - 1 || r.bottom - slack > box.bottom + 1) return true;
        }
      }
    }
    return false;
  }

  // A panel as wide as the clipping box, moved sideways as a whole: a carousel slide, or the
  // second level of a drawer menu waiting beside the first. It is out of view on purpose.
  function inParkedPanel(node, clipper, box) {
    for (let up = node; up && up !== clipper; up = parentOf(up)) {
      const r = up.getBoundingClientRect();
      if (Math.abs(r.width - box.width) <= Math.max(2, box.width * 0.05)
          && (r.left < box.left - 1 || r.right > box.right + 1)) return true;
    }
    return false;
  }

  // The nearest box el is laid out in, past slots and other display: contents boxes.
  function layoutParent(el) {
    let parent = parentOf(el);
    while (parent && parent !== document.body && getComputedStyle(parent).display === "contents") parent = parentOf(parent);
    return parent;
  }

  // Whether el's text below `parent` is its own to show: not in a box in between that is
  // positioned, scrolls or clips, or spills out of a fixed height itself.
  function ownsText(el, parent) {
    for (let up = parent; up && up !== el; up = parentOf(up)) {
      const style = getComputedStyle(up);
      if (style.position === "absolute" || style.position === "fixed" || style.overflowY !== "visible") return false;
      if (style.display !== "inline" && up.clientHeight > 0 && up.scrollHeight > up.clientHeight + 1) return false;
    }
    return true;
  }

  // Text that runs out of the bottom of a box of fixed height onto the content after it: how
  // far its letters reach below the box, and what they land on. Text spilling into empty
  // space (an app root of height: 100% on a long page) changes nothing anyone sees.
  function spillBelow(el) {
    const box = el.getBoundingClientRect();
    const range = document.createRange();
    let spill = null;
    for (const node of flatText(el, 200)) {
      const parent = node.parentElement;
      if (!parent || !isVisible(parent) || isScreenReaderOnly(parent) || !ownsText(el, node.assignedSlot || parent)) continue;
      const fontSize = parseFloat(getComputedStyle(parent).fontSize) || 16;
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) {
        if (!r.width || !r.height) continue;
        const bottom = r.bottom - Math.max(r.height - fontSize, 0) / 2;  // the letters, not the leading
        if (bottom <= box.bottom + 1) continue;
        if (!spill) spill = { left: r.left, right: r.right, bottom };
        spill.left = Math.min(spill.left, r.left);
        spill.right = Math.max(spill.right, r.right);
        spill.bottom = Math.max(spill.bottom, bottom);
      }
    }
    if (!spill) return null;
    // The boxes that follow el in the flow, at its level and further up, until one starts
    // below the spilled text.
    let tried = 0;
    for (let node = el; node && node !== document.body && node !== document.documentElement && tried < 12; node = parentOf(node)) {
      for (let next = node.nextElementSibling; next && tried < 12; next = next.nextElementSibling) {
        const style = getComputedStyle(next);
        if (style.position === "absolute" || style.position === "fixed" || !isVisible(next)) continue;
        tried++;
        const r = next.getBoundingClientRect();
        if (r.top >= spill.bottom - 1) return null;
        if (r.bottom > box.bottom + 1 && r.left < spill.right - 1 && r.right > spill.left + 1) {
          const text = snippet(next).slice(0, 30);
          return { by: Math.round(spill.bottom - box.bottom), onto: text ? `"${text}"` : `the ${next.tagName.toLowerCase()} after it` };
        }
      }
    }
    return null;
  }

  // Whether a box between el and `other` (el itself included, their common ancestor not) paints
  // a background that hides whatever lies under it.
  function coversWithBackground(el, other) {
    for (let node = el; node && !containsDeep(node, other); node = parentOf(node)) {
      const style = getComputedStyle(node);
      if (style.backgroundImage !== "none") return true;
      const alpha = style.backgroundColor.match(/rgba?\(([^)]*)\)/);
      const parts = alpha ? alpha[1].split(/[\s,/]+/).filter(Boolean) : [];
      if (parts.length && (parts.length < 4 || parseFloat(parts[3]) > 0.5)) return true;
    }
    return false;
  }

  // Lines of text, from different elements, drawn over each other. Only the middle half of a
  // line counts, where its letters are: tight line spacing makes line boxes overlap, not words.
  // Badges of up to three characters, controls (overlapping-controls covers those), layers
  // over the page, text under an opaque background and text a spill already explains are left out.
  // Lines past MAX_TEXT_RUNS are not looked at; `capped` says so.
  const MAX_TEXT_RUNS = 5000;
  function overlappingText(visible, spilled) {
    const runs = [];
    const range = document.createRange();
    let capped = false;
    for (const el of visible) {
      if (runs.length >= MAX_TEXT_RUNS) {
        capped = true;
        break;
      }
      if (!hasOwnText(el) || isScreenReaderOnly(el) || closestDeep(el, "svg,select,textarea,[aria-hidden=true]")) continue;
      for (const node of el.childNodes) {
        if (node.nodeType !== 3 || node.nodeValue.trim().length <= 3) continue;
        range.selectNodeContents(node);
        for (const r of range.getClientRects()) {
          if (r.width < 1 || r.height < 1) continue;
          const inset = r.height / 4;
          runs.push({ el, text: node.nodeValue.replace(/\s+/g, " ").trim(), left: r.left, right: r.right, top: r.top + inset, bottom: r.bottom - inset });
        }
      }
    }
    // Runs that share a 100px cell are compared; nothing else can overlap.
    const cells = new Map();
    runs.forEach((run, i) => {
      for (let x = Math.floor(run.left / 100); x <= Math.floor(run.right / 100); x++) {
        for (let y = Math.floor(run.top / 100); y <= Math.floor(run.bottom / 100); y++) {
          const key = `${x},${y}`;
          if (!cells.has(key)) cells.set(key, []);
          cells.get(key).push(i);
        }
      }
    });
    const found = [];
    const compared = new Set();
    const reported = new Set();
    const clipOf = new Map();
    const clip = (el) => {
      if (!clipOf.has(el)) clipOf.set(el, visibleRect(el));
      return clipOf.get(el);
    };
    const area = (r) => Math.max(r.right - r.left, 0) * Math.max(r.bottom - r.top, 0);
    const meet = (p, q) => ({ left: Math.max(p.left, q.left), right: Math.min(p.right, q.right), top: Math.max(p.top, q.top), bottom: Math.min(p.bottom, q.bottom) });
    for (const members of cells.values()) {
      for (let m = 0; m < members.length; m++) {
        for (let n = m + 1; n < members.length; n++) {
          const a = runs[members[m]], b = runs[members[n]];
          if (a.el === b.el || reported.has(b.el)) continue;
          const pair = `${members[m]},${members[n]}`;
          if (compared.has(pair)) continue;
          compared.add(pair);
          // What scrolling and clipping ancestors leave of both lines.
          const both = meet(meet(a, b), meet(clip(a.el), clip(b.el)));
          if (area(both) < 0.3 * Math.min(area(meet(a, clip(a.el))), area(meet(b, clip(b.el)))) || !area(both)) continue;
          if (containsDeep(a.el, b.el) || containsDeep(b.el, a.el)) continue;
          if (closestDeep(a.el, INTERACTIVE) && closestDeep(b.el, INTERACTIVE)) continue;
          if (closestDeep(a.el, LAYER) !== closestDeep(b.el, LAYER)) continue;
          if (passesOver(pinnedLayer(a.el), pinnedLayer(b.el)) || apartLayers(openPopup(a.el), openPopup(b.el))) continue;
          if (spilled.some((s) => containsDeep(s, a.el) || containsDeep(s, b.el))) continue;
          if (coversWithBackground(a.el, b.el) || coversWithBackground(b.el, a.el)) continue;
          const cx = (both.left + both.right) / 2, cy = (both.top + both.bottom) / 2;
          if (cx >= 0 && cy >= 0 && cx <= window.innerWidth && cy <= window.innerHeight) {
            const top = elementAt(cx, cy);
            if (top && ![a.el, b.el].some((el) => containsDeep(el, top) || containsDeep(top, el))) continue;  // something else lies over both
          }
          reported.add(b.el);
          found.push(makeIssue("text-overlap", "P2", b.el, `Text "${b.text.slice(0, 40)}" is drawn over "${a.text.slice(0, 40)}" (${cssPath(a.el)}).`));
        }
      }
    }
    return { found, capped };
  }

  // Dialogs that reach past the top or bottom of the screen with nothing to scroll them into
  // view: a fixed dialog moves with neither the page nor its own scrolling, only an overlay
  // around it that scrolls brings the rest in.
  const DIALOG = "dialog,[role=dialog],[role=alertdialog],[aria-modal=true]";
  function tallDialogs(visible) {
    const vh = document.documentElement.clientHeight || window.innerHeight;
    const found = [];
    for (const el of visible) {
      if (!el.matches(DIALOG) || !insideFixed(el)) continue;
      const up = parentOf(el);
      if (up && closestDeep(up, DIALOG)) continue;  // the outermost dialog is the one to fix
      const r = el.getBoundingClientRect();
      const below = Math.round(r.bottom - vh), above = Math.round(-r.top);
      if (below <= 1 && above <= 1) continue;
      let reachable = false;
      for (let node = el; node && !reachable; node = parentOf(node)) {
        const style = getComputedStyle(node);
        reachable = node !== el && /auto|scroll|overlay/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1;
        if (style.position === "fixed") break;
      }
      if (reachable) continue;
      const lost = queryAllDeep(INTERACTIVE, el).find((c) => {
        const cr = c.getBoundingClientRect();
        return isVisible(c) && (cr.top >= vh || cr.bottom <= 0);
      });
      const cut = [below > 1 ? `${below}px below` : "", above > 1 ? `${above}px above` : ""].filter(Boolean).join(" and ");
      found.push(makeIssue("dialog-too-tall", lost ? "P1" : "P2", el,
        `Dialog is ${Math.round(r.height)}px high in a ${vh}px high viewport and does not scroll; ${cut} the screen cannot be reached`
        + (lost ? `, including "${(accessibleName(lost) || lost.tagName.toLowerCase()).slice(0, 40)}".` : ".")));
    }
    return found;
  }

  function hasOwnText(el) {
    for (const child of el.childNodes) {
      if (child.nodeType === 3 && child.textContent.trim()) return true;
    }
    return false;
  }

  function snippet(el) {
    let text = el.innerText || el.textContent || "";
    // innerText leaves out what a slot or a shadow root shows.
    if (!text.trim() && (el.shadowRoot || el.querySelector("slot"))) text = flatText(el, 20).map((n) => n.nodeValue).join(" ");
    return text.replace(/\s+/g, " ").trim().slice(0, 60);
  }

  function accessibleName(el) {
    const label = el.getAttribute("aria-label");
    if (label && label.trim()) return label.trim();
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const root = rootOf(el);
      const text = labelledBy.split(/\s+/).map((id) => root.getElementById(id))
        .filter(Boolean).map((n) => n.textContent.trim()).join(" ");
      if (text) return text;
    }
    if (el.labels && el.labels.length) {
      const text = Array.from(el.labels).map((l) => l.textContent.trim()).join(" ");
      if (text) return text;
    }
    const text = (el.innerText || el.textContent || "").trim();
    if (text) return text;
    if (el.getAttribute("title")) return el.getAttribute("title").trim();
    const img = el.querySelector("img[alt]");
    if (img && img.alt.trim()) return img.alt.trim();
    const svgTitle = el.querySelector("svg title");
    if (svgTitle && svgTitle.textContent.trim()) return svgTitle.textContent.trim();
    if (el.tagName === "INPUT" && ["button", "submit", "reset"].includes(el.type) && el.value) return el.value;
    if (el.tagName === "INPUT" && el.type === "image" && el.alt) return el.alt;
    if (el.placeholder) return el.placeholder.trim();
    return "";
  }

  // `deep` follows the component tree past the first few components, for an element that a
  // library renders (a dialog's content) where the app's own file is several layers up.
  function sourceInfo(el, deep) {
    const components = [];
    const files = [];
    const addFile = (file, line) => {
      if (file && !files.some((f) => f.file === file)) files.push({ file, line: line || null });
    };
    let node = el;
    for (let depth = 0; node && depth < 15; depth++, node = parentOf(node)) {
      const fiberKey = Object.keys(node).find((k) => k.startsWith("__reactFiber$"));
      if (fiberKey) {
        let fiber = node[fiberKey];
        for (let hops = 0; fiber && hops < (deep ? 120 : 30); hops++, fiber = fiber.return) {
          if (fiber._debugSource) addFile(fiber._debugSource.fileName, fiber._debugSource.lineNumber);
          if (typeof fiber.type === "function" && (!deep || fiber._debugSource)) {
            const name = fiber.type.displayName || fiber.type.name;
            if (name && name.length > 1 && !components.includes(name)) components.push(name);
          }
          if (deep ? files.length >= 3 : components.length >= 3) break;
        }
        break;
      }
      const vue = node.__vueParentComponent;
      if (vue && vue.type) {
        const name = vue.type.__name || vue.type.name;
        if (name && !components.includes(name)) components.push(name);
        addFile(vue.type.__file);
        break;
      }
      if (node.__svelte_meta && node.__svelte_meta.loc) {
        addFile(node.__svelte_meta.loc.file, node.__svelte_meta.loc.line);
        break;
      }
    }
    return {
      components,
      files,
      id: el.id || null,
      classes: Array.from(el.classList).slice(0, 8),
      contextClasses: [el.parentElement, el.parentElement && el.parentElement.parentElement]
        .filter((n) => n && n !== document.body).flatMap((n) => Array.from(n.classList)).slice(0, 6),
      tag: el.tagName.toLowerCase(),
      text: snippet(el),
    };
  }

  // The nearest fixed or sticky ancestor (or the element itself), or null for page content.
  // The opened menu or popover el sits in, when it has no role saying so: a positioned box
  // that an expanded control points at (aria-controls) or sits right next to.
  function openPopup(el) {
    for (let node = parentOf(el); node && node !== document.body; node = parentOf(node)) {
      const position = getComputedStyle(node).position;
      if (position !== "absolute" && position !== "fixed") continue;
      if (node.id && rootOf(node).querySelector(`[aria-expanded=true][aria-controls~="${CSS.escape(node.id)}"]`)) return node;
      const siblings = node.parentNode && node.parentNode.children ? Array.from(node.parentNode.children) : [];
      if (siblings.some((s) => s !== node && s.matches("[aria-expanded=true]"))) return node;
    }
    return null;
  }

  // Whether two controls sit in different layers: one in an opened popup and one under it,
  // or a flyout and the menu it opened from. Two separate popups can still cover each other.
  function apartLayers(p, q) {
    if (p === q) return false;
    if (!p || !q) return true;
    return containsDeep(p, q) || containsDeep(q, p);
  }

  function pinnedLayer(el) {
    for (let node = el; node && node !== document.documentElement; node = parentOf(node)) {
      const position = getComputedStyle(node).position;
      if (position === "fixed" || position === "sticky") return { node, sticky: position === "sticky" };
    }
    return null;
  }

  // A fixed or sticky bar passes over scrolling content by design, and a sticky row or
  // header slides under a fixed bar the same way. Two fixed layers stay where they are,
  // so when they overlap they always do.
  function passesOver(a, b) {
    if (!a && !b) return false;
    if (!a || !b) return true;
    return a.node !== b.node && (a.sticky || b.sticky);
  }

  function isAdornment(field, fieldRect, other, otherRect) {
    if (!field.matches(TEXT_FIELD) || other.matches(TEXT_FIELD)) return false;
    const w = Math.min(fieldRect.right, otherRect.right) - Math.max(fieldRect.left, otherRect.left);
    const h = Math.min(fieldRect.bottom, otherRect.bottom) - Math.max(fieldRect.top, otherRect.top);
    const area = otherRect.width * otherRect.height;
    // Mostly inside the field and clearly smaller than it; focus rings often poke out a little.
    return w > 0 && h > 0 && w * h >= 0.8 * area && area <= 0.5 * fieldRect.width * fieldRect.height;
  }

  function isOverlaidAction(small, smallRect, bigRect) {
    const area = smallRect.width * smallRect.height;
    if (!area || area * 3 > bigRect.width * bigRect.height) return false;
    const w = Math.min(smallRect.right, bigRect.right) - Math.max(smallRect.left, bigRect.left);
    const h = Math.min(smallRect.bottom, bigRect.bottom) - Math.max(smallRect.top, bigRect.top);
    if (w <= 0 || h <= 0 || w * h < 0.95 * area) return false;
    const cx = smallRect.left + smallRect.width / 2, cy = smallRect.top + smallRect.height / 2;
    if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) return true;  // cannot hit-test off screen
    // An open modal layer switches pointer events off underneath it; nothing there can be hit-tested.
    if (getComputedStyle(small).pointerEvents === "none") return true;
    const top = elementAt(cx, cy);
    return !!top && (small === top || containsDeep(small, top));
  }

  // The line boxes of an inline control that wraps; its bounding box also covers text it does not own.
  function lineBoxes(el) {
    if (getComputedStyle(el).display !== "inline") return null;
    const rects = Array.from(el.getClientRects());
    return rects.length > 1 ? rects : null;
  }

  // A box that floats over the page: a dialog, a region or aside, or a fixed, sticky or high
  // stacked layer. Consent banners are one; a table row or a page footer is not.
  function isFloatingLayer(el) {
    if (el.matches("dialog,aside,[role=dialog],[role=alertdialog],[role=region],[aria-modal=true]")) return true;
    const style = getComputedStyle(el);
    if (style.position === "fixed" || style.position === "sticky") return true;
    return style.position !== "static" && (parseInt(style.zIndex, 10) || 0) >= 1000;
  }

  // The button that turns optional cookies down in a consent banner, if one is showing. Only a
  // button inside a floating layer whose own, banner-sized text is about cookies or consent
  // counts: a "Reject" in an admin table under a footer "Cookie policy" link is never clicked.
  function consentDecline() {
    for (const el of queryAllDeep("button,[role=button],a[href]")) {
      if (!isVisible(el)) continue;
      const name = (accessibleName(el) || "").replace(/\s+/g, " ").trim();
      if (!name || name.length > 60 || !CONSENT_DECLINE.test(name)) continue;
      for (let node = parentOf(el), depth = 0; node && node !== document.body && depth < 8; node = parentOf(node), depth++) {
        if (!isFloatingLayer(node)) continue;
        const text = (node.innerText || "").replace(/\s+/g, " ");
        if (text.length <= 1500 && CONSENT_TOPIC.test(text)) return { selector: cssPath(el), label: name };
      }
    }
    return null;
  }

  function rectOf(el) {
    const r = el.getBoundingClientRect();
    return {
      x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY),
      width: Math.round(r.width), height: Math.round(r.height),
    };
  }

  // Up to this many pixels past the edge is a nuisance (a page that wiggles sideways), not
  // lost content, and is rated one step lower.
  const SMALL_OVERFLOW = 4;
  // The pairwise control checks are quadratic, so only this many controls are looked at.
  const MAX_CONTROLS = 400;
  const CONTROL_CHECKS = ["overlapping-controls", "small-target", "unnamed-control"];

  // The grid whose columns are wider than its own box. Items placed in those columns
  // overflow because of the column sizes, so the grid is what to report and fix.
  function overflowingGrid(el) {
    const parent = el.parentElement;
    if (!parent || parent === document.body || parent === document.documentElement) return null;
    const style = getComputedStyle(parent);
    if (!/grid/.test(style.display) || style.overflowX !== "visible") return null;
    const tracks = style.gridTemplateColumns.split(/\s+/).map(parseFloat).filter((n) => !isNaN(n));
    if (!tracks.length) return null;
    const gap = parseFloat(style.columnGap) || 0;
    const needed = tracks.reduce((sum, n) => sum + n, 0) + gap * (tracks.length - 1);
    const box = parent.clientWidth - (parseFloat(style.paddingLeft) || 0) - (parseFloat(style.paddingRight) || 0);
    return needed > box + 1 ? { node: parent, needed: Math.round(needed), box: Math.round(box) } : null;
  }

  // Why el sticks out past the right edge (the left edge on a right-to-left page), as a short
  // clause for the message, or null when it is not clear: a flex item that cannot shrink, a box
  // wider than the viewport, a transform, a negative margin or offset, or 100vw that includes
  // the scrollbar.
  function overflowCause(el, vw, rtl) {
    const style = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const px = (value) => Math.round(parseFloat(value) || 0);
    const [end, start] = rtl ? ["left", "right"] : ["right", "left"];
    const endMargin = rtl ? style.marginLeft : style.marginRight, startMargin = rtl ? style.marginRight : style.marginLeft;
    if (style.transform && style.transform !== "none") {
      try {
        const shift = new DOMMatrixReadOnly(style.transform).m41 * (rtl ? -1 : 1);
        const back = rtl ? r.left + window.scrollX + shift >= -1 : r.right - shift <= vw + 1;
        if (shift > 1 && back) return `transform moves it ${Math.round(shift)}px to the ${end}`;
      } catch (e) { /* not a 2D matrix */ }
    }
    if (style.position !== "static" && px(style[end]) < 0 && style[end] !== "auto") {
      return `it is positioned past the edge with ${end}: ${style[end]}`;
    }
    if (px(endMargin) < 0) return `a negative margin-${end} (${endMargin}) pulls it past its container`;
    if (px(startMargin) < 0 && r.width <= vw) return `a negative margin-${start} (${startMargin}) shifts it sideways`;
    // A phone page zoomed out to show the overflow also has innerWidth above clientWidth; a
    // scrollbar is narrow.
    const scrollbar = window.innerWidth - document.documentElement.clientWidth;
    if (scrollbar > 0 && scrollbar <= 24 && Math.abs(r.width - window.innerWidth) <= 1) {
      return `it is 100vw wide, which includes the ${scrollbar}px scrollbar; use 100% instead`;
    }
    const parent = el.parentElement;
    const parentStyle = parent ? getComputedStyle(parent) : null;
    if (parentStyle && /flex/.test(parentStyle.display) && !/column/.test(parentStyle.flexDirection)) {
      if (style.flexShrink === "0") return "it is a flex item that does not shrink (flex-shrink: 0)";
      const p = parent.getBoundingClientRect();
      if (style.minWidth === "auto" && (rtl ? r.left < p.left - 1 : r.right > p.right + 1)) {
        return "it is a flex item with min-width: auto that cannot shrink below its content (a long word, URL or pre); give it min-width: 0";
      }
    }
    if (["IMG", "VIDEO", "IFRAME", "CANVAS", "SVG"].includes(el.tagName.toUpperCase()) && r.width > vw + 1) {
      return `it is ${Math.round(r.width)}px wide with no max-width: 100%`;
    }
    if (px(style.minWidth) > vw) return `min-width: ${style.minWidth} is wider than the viewport`;
    if (parent && r.width > vw + 1 && style.display !== "inline" && !/table/.test(style.display)) {
      const box = parent.clientWidth - px(parentStyle.paddingLeft) - px(parentStyle.paddingRight);
      if (r.width > box + 1) return `it has a fixed width of ${Math.round(r.width)}px`;
    }
    return null;
  }

  // Below this width a page is read as a phone layout.
  const PHONE_WIDTH = 768;
  // Iframes inside iframes are measured this many levels deep.
  const MAX_FRAME_DEPTH = 2;

  // Fixed and sticky bars along the top or bottom of the viewport, with the outermost box of each.
  // Dialogs, opened menus and consent banners (the audit closes those first) cover the page on purpose.
  function pinnedBars(visible, vw, vh) {
    const bars = [];
    for (const el of visible) {
      const style = getComputedStyle(el);
      if (style.position !== "fixed" && style.position !== "sticky") continue;
      if (parentOf(el) && pinnedLayer(parentOf(el))) continue;
      if (closestDeep(el, LAYER) || el.querySelector("[aria-modal=true],[aria-expanded=true]")) continue;
      if (CONSENT_TOPIC.test(el.innerText || "")) continue;
      const r = el.getBoundingClientRect();
      if (r.width < vw * 0.6 || r.height < 8 || r.height > vh * 0.6) continue;
      // A sticky box only stays while its parent is on screen; in a parent about its own height it scrolls away.
      if (style.position === "sticky" && el.parentElement && el.parentElement.getBoundingClientRect().height < r.height + vh * 0.5) continue;
      const top = r.top <= 1 && r.bottom > 0 && style.top !== "auto";
      const bottom = r.bottom >= vh - 1 && r.top < vh && (style.position === "fixed" || style.bottom !== "auto");
      if (top || bottom) bars.push({ el, r, edge: top ? "top" : "bottom", fixed: style.position === "fixed" });
    }
    return bars;
  }

  function pinnedBarIssues(visible, vw) {
    const vh = document.documentElement.clientHeight || window.innerHeight;
    const scrollHeight = document.documentElement.scrollHeight;
    const bars = pinnedBars(visible, vw, vh);
    const issues = [];
    // a) On a phone, bars that together take more than 30% of the screen leave little to read.
    if (vw < PHONE_WIDTH && bars.length && scrollHeight > vh + 1) {
      let covered = 0;
      for (const edge of ["top", "bottom"]) {
        const spans = bars.filter((b) => b.edge === edge).map((b) => [Math.max(b.r.top, 0), Math.min(b.r.bottom, vh)]).sort((a, b) => a[0] - b[0]);
        let end = -Infinity;
        for (const [from, to] of spans) {
          covered += Math.max(to - Math.max(from, end), 0);
          end = Math.max(end, to);
        }
      }
      if (covered > vh * 0.3) {
        const tallest = bars.reduce((a, b) => (b.r.height > a.r.height ? b : a));
        issues.push(makeIssue("sticky-covers-viewport", "P2", tallest.el,
          `Fixed and sticky bars cover ${Math.round(covered)}px (${Math.round(covered / vh * 100)}%) of a ${vh}px high screen; this one is ${Math.round(tallest.r.height)}px.`));
      }
    }
    // b) Scrolled to the end, a fixed bottom bar lies over the last text or control. Where the
    // page itself scrolls, a fixed bar's place in the page at the end follows from its place now.
    const endShift = Math.max(scrollHeight - vh, 0) - window.scrollY;
    for (const bar of bars) {
      if (bar.edge !== "bottom" || !bar.fixed) continue;
      const from = bar.r.top + endShift, to = bar.r.bottom + endShift;  // where the bar sits, in today's coordinates
      for (const el of visible) {
        if (containsDeep(bar.el, el) || pinnedLayer(el) || closestDeep(el, LAYER)) continue;
        if (!el.matches(INTERACTIVE) && !hasOwnText(el)) continue;
        if (isScreenReaderOnly(el) || scrollingAncestor(el)) continue;
        const r = el.getBoundingClientRect();
        const overlap = Math.min(r.bottom, to) - Math.max(r.top, from);
        if (r.height && overlap >= r.height * 0.5) {
          issues.push(makeIssue("fixed-covers-end", "P2", bar.el,
            `Scrolled to the end, this ${Math.round(bar.r.height)}px fixed bar covers ${el.matches(INTERACTIVE) ? "the control" : "the text"} "${(accessibleName(el) || snippet(el)).slice(0, 40)}"; leave room for it below the content.`));
          break;
        }
      }
    }
    return issues;
  }

  // An ancestor that scrolls or clips vertically: content inside an app's own scroll area moves
  // under a fixed bar while the page stays put, so where it is now says nothing about the end.
  function scrollingAncestor(el) {
    for (let node = parentOf(el); node && node !== document.body && node !== document.documentElement; node = parentOf(node)) {
      if (getComputedStyle(node).overflowY !== "visible") return node;
    }
    return null;
  }

  // Elements whose own text is under 12px. Footnote marks (sup, sub), hidden text, short badges
  // ("3", "New") and chart labels drawn in SVG are left out.
  function tinyText(visible) {
    const found = [];
    for (const el of visible) {
      if (!hasOwnText(el) || closestDeep(el, "sup,sub,svg,select,[aria-hidden=true]") || isScreenReaderOnly(el)) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (!size || size >= 12) continue;
      const own = Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.nodeValue).join("").replace(/\s+/g, " ").trim();
      if (own.length <= 3) continue;
      found.push(el);
    }
    return found;
  }

  // A meta viewport phones can use: missing, without width=device-width, or blocking zoom.
  function viewportMeta() {
    const metas = document.querySelectorAll("meta[name=viewport i]");
    const meta = metas[metas.length - 1];
    if (!meta) {
      return { check: "viewport-meta", severity: "P1", selector: "head", message:
        "The page has no <meta name=\"viewport\">; phones lay it out 980px wide and shrink it, so text is tiny and the page's own breakpoints never apply." };
    }
    const content = (meta.getAttribute("content") || "").toLowerCase();
    const props = {};
    for (const part of content.split(/[,;]/)) {
      const [key, value] = part.split("=").map((t) => (t || "").trim());
      if (key) props[key] = value || "";
    }
    const selector = "meta[name=viewport]";
    if (props.width !== "device-width" && !(props.width === undefined && parseFloat(props["initial-scale"]) === 1)) {
      return { check: "viewport-meta", severity: "P1", selector, message:
        `<meta name="viewport" content="${content.slice(0, 80)}"> does not set width=device-width; phones lay the page out ${props.width && /^\d+$/.test(props.width) ? props.width : 980}px wide instead.` };
    }
    const max = parseFloat(props["maximum-scale"]);
    if (["no", "0"].includes(props["user-scalable"]) || (!isNaN(max) && max < 2)) {
      return { check: "viewport-meta", severity: "P2", selector, message:
        `<meta name="viewport" content="${content.slice(0, 80)}"> stops people zooming in (WCAG 1.4.4); drop user-scalable=no and maximum-scale.` };
    }
    return null;
  }

  // Selector, box and source hints are worked out only for findings that are reported: a check
  // over its cap still counts the rest, and a path is several document-wide queries.
  function makeIssue(check, severity, el, message) {
    return { check, severity, el, message };
  }

  function finishIssue({ check, severity, el, message, cause }) {
    const issue = { check, severity, selector: cssPath(el), message, rect: rectOf(el), hints: sourceInfo(el) };
    if (cause) issue.cause = cause;
    return issue;
  }

  function probe(opts) {
    pathCache = new Map();
    styleCache = new Map();
    rootCache = new Map();
    try {
      return measure(opts);
    } finally {
      pathCache = null;
      styleCache = null;
      rootCache = null;
    }
  }

  function measure(opts) {
    opts = opts || {};
    const ignore = opts.ignoreSelectors || [];
    // ?? rather than ||: a configured 0 means 0.
    const minTarget = opts.minTarget ?? 24;
    const overlapThreshold = opts.overlapThreshold ?? 0.2;
    const maxPer = opts.maxPerCheck ?? 15;
    const vw = document.documentElement.clientWidth || window.innerWidth;
    // An iframe is measured with the page's phone checks, whatever its own width.
    const frameDepth = opts.frameDepth || 0;
    const phone = opts.phone ?? vw < PHONE_WIDTH;
    const issues = [];
    const counts = {};
    const push = (issue) => {
      counts[issue.check] = (counts[issue.check] || 0) + 1;
      if (counts[issue.check] <= maxPer) issues.push(finishIssue(issue));
    };

    const all = (document.body ? deepElements(document.body) : [])
      .filter((el) => !isIgnored(el, ignore) && !["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "BR"].includes(el.tagName));
    const visible = all.filter(isVisible);

    // 1. Horizontal page overflow and its top-most culprits. A right-to-left page overflows,
    // and scrolls, to the left; what sticks out on the right of it cannot be scrolled to.
    const rtl = getComputedStyle(document.documentElement).direction === "rtl";
    const scrollWidth = Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0);
    const pageOverflows = scrollWidth > vw + 1;
    const beyondEdge = rtl
      ? (el) => el.getBoundingClientRect().left + window.scrollX < -1
      : (el) => el.getBoundingClientRect().right + window.scrollX > vw + 1;
    // Where a box that sticks out ends, for the message.
    const reach = (el) => {
      const r = el.getBoundingClientRect();
      return rtl ? `${Math.round(-(r.left + window.scrollX))}px past the left edge of` : `to ${Math.round(r.right + window.scrollX)}px in`;
    };
    // What the overflow check reported; the edge check below does not report the same cause again.
    const overflowRoots = new Set();
    // overflow-x: hidden or clip on html or body: what sticks out is cut off, not scrollable.
    const pageClip = [document.documentElement, document.body].filter(Boolean)
      .map((n) => getComputedStyle(n).overflowX).find((v) => v === "hidden" || v === "clip");
    const page = frameDepth ? "frame" : "page";
    const scrolls = (by) => pageClip
      ? `${by}px cut off by overflow-x: ${pageClip} on the ${page}, so it cannot be scrolled to`
      : `${page} scrolls sideways by ${by}px`;
    if (pageOverflows) {
      const by = scrollWidth - vw;
      const severity = by > SMALL_OVERFLOW ? "P1" : "P2";
      const culprits = visible.filter((el) => {
        if (!beyondEdge(el)) return false;
        if (getComputedStyle(el).position === "fixed") return false;
        if (clippingAncestor(el)) return false;
        const parent = layoutParent(el);
        return !parent || parent === document.body || parent === document.documentElement || !beyondEdge(parent)
          || Boolean(clippingAncestor(parent));  // the parent is cut off where el is not
      });
      if (culprits.length) {
        for (const el of culprits) {
          const grid = overflowingGrid(el);
          const target = grid ? grid.node : el;
          if (overflowRoots.has(target)) continue;
          overflowRoots.add(target);
          if (grid) {
            push(makeIssue("horizontal-overflow", severity, target,
              `Grid columns need ${grid.needed}px but the grid is ${grid.box}px wide in a ${vw}px viewport (${scrolls(by)}).`));
          } else if (isScreenReaderOnly(el)) {
            const r = el.getBoundingClientRect();
            const at = rtl ? `${Math.round(-(r.left + window.scrollX))}px past the left edge of` : `at ${Math.round(r.right + window.scrollX)}px in`;
            push(makeIssue("horizontal-overflow", severity, el,
              `Screen-reader-only text "${snippet(el).slice(0, 40)}" sits ${at} a ${vw}px viewport, outside the scrolling box it belongs to (${scrolls(by)}); give that box position: relative so it clips the text.`));
          } else {
            const cause = overflowCause(el, vw, rtl);
            const issue = makeIssue("horizontal-overflow", severity, el,
              `Extends ${reach(el)} a ${vw}px viewport (${scrolls(by)}).` + (cause ? ` Cause: ${cause}.` : ""));
            if (cause) issue.cause = cause;
            push(issue);
          }
        }
      } else {
        // No box sticks out, so the page is widened by text that overflows its box (a long
        // word that cannot wrap) or by a box nobody sees (a hidden tooltip left in place).
        const culprit = overflowingText(all, vw, rtl) || all.find((el) => !isVisible(el) && el.getClientRects().length
          && beyondEdge(el) && getComputedStyle(el).position !== "fixed" && !clippingAncestor(el));
        if (culprit && culprit.el) {
          overflowRoots.add(culprit.el);
          const runs = rtl ? `runs ${-culprit.edge}px past the left edge of` : `runs to ${culprit.edge}px in`;
          push(makeIssue("horizontal-overflow", severity, culprit.el,
            `Text "${culprit.text}" ${runs} a ${vw}px viewport (${scrolls(by)}).`));
        } else if (culprit) {
          overflowRoots.add(culprit);
          push(makeIssue("horizontal-overflow", severity, culprit,
            `An invisible element extends ${reach(culprit)} a ${vw}px viewport (${scrolls(by)}).`));
        } else {
          push(makeIssue("horizontal-overflow", severity, document.documentElement,
            `Page is ${scrollWidth}px wide in a ${vw}px viewport.`));
        }
      }
    }
    const sameCause = (el) => {
      for (const root of overflowRoots) {
        if (containsDeep(root, el) || containsDeep(el, root)) return true;
      }
      return false;
    };

    // 2. Content or controls cut off at the viewport edge. The edge the page scrolls towards
    // is the overflow above when the page overflows. Boxes are placed in the page: a phone
    // shows an overflowing right-to-left page zoomed out and scrolled to its right end.
    const sx = window.scrollX;
    const cutLeft = (r) => r.left + sx < -1 && r.right + sx > 1 && (!rtl || !pageOverflows);
    const cutRight = (r) => r.left + sx < vw - 1 && r.right + sx > vw + 1 && (rtl || !pageOverflows);
    for (const el of visible) {
      const r = el.getBoundingClientRect();
      const straddlesLeft = cutLeft(r);
      const straddlesRight = cutRight(r);
      if (!straddlesLeft && !straddlesRight) continue;
      // Inside any non-visible overflow container: a carousel or a container
      // clip, which the clipped-content check reports at the container.
      if (clippingAncestor(el)) continue;
      const parent = layoutParent(el);
      if (parent && parent !== document.body) {
        const pr = parent.getBoundingClientRect();
        if (cutLeft(pr) || cutRight(pr)) continue;
      }
      const interactive = el.matches(INTERACTIVE);
      if (!interactive && !hasOwnText(el) && !el.querySelector(INTERACTIVE)) continue;
      // A centred row that is too wide sticks out on both sides: the right side is the page
      // overflow reported above, the left side the same defect.
      if (sameCause(el)) continue;
      const edge = straddlesLeft ? "left" : "right";
      const small = (straddlesLeft ? -(r.left + sx) : r.right + sx - vw) <= SMALL_OVERFLOW;
      const grid = overflowingGrid(el);
      if (grid) {
        overflowRoots.add(grid.node);
        push(makeIssue("offscreen-content", small ? "P3" : "P2", grid.node,
          `Grid columns need ${grid.needed}px but the grid is ${grid.box}px wide; content is cut off at the ${edge} edge of a ${vw}px viewport.`));
      } else if (interactive) {
        push(makeIssue("offscreen-control", small ? "P2" : "P1", el, `Control is cut off at the ${edge} edge of a ${vw}px viewport.`));
      } else {
        push(makeIssue("offscreen-content", small ? "P3" : "P2", el, `Content is cut off at the ${edge} edge of a ${vw}px viewport.`));
      }
    }

    // 3. Text clipped by its own box, or spilling out of it.
    const spilled = [];
    for (const el of visible) {
      if (["INPUT", "TEXTAREA", "SELECT", "HTML", "BODY"].includes(el.tagName)) continue;
      if (isScreenReaderOnly(el)) continue;
      const style = getComputedStyle(el);
      const clipsX = style.overflowX === "hidden" || style.overflowX === "clip";
      const clipsY = style.overflowY === "hidden" || style.overflowY === "clip";
      const overX = el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0;
      const overY = el.scrollHeight > el.clientHeight + 1 && el.clientHeight > 0;
      if (!overX && !overY) continue;
      // innerText lays out the whole subtree, so it is read only for boxes that overflow. It
      // leaves out what slots show.
      if (!snippet(el)) continue;
      const clamped = truncates(style);
      if ((clipsX && overX) || (clipsY && overY)) {
        if (clamped) continue;
        if (!inkIsClipped(el, clipsX && overX)) continue;
        const axis = clipsX && overX ? `${el.scrollWidth - el.clientWidth}px horizontally` : `${el.scrollHeight - el.clientHeight}px vertically`;
        push(makeIssue("clipped-content", "P2", el, `Content is clipped by ${axis}: "${snippet(el)}"`));
      } else if (style.overflowX === "visible" && overX && hasOwnText(el) && style.display !== "inline") {
        push(makeIssue("text-spill", "P3", el, `Text spills ${el.scrollWidth - el.clientWidth}px outside its box: "${snippet(el)}"`));
      } else if (style.overflowY === "visible" && overY && style.display !== "inline") {
        const spill = spillBelow(el);
        if (!spill) continue;
        spilled.push(el);
        push(makeIssue("text-spill", "P2", el,
          `Text spills ${spill.by}px below its ${Math.round(el.getBoundingClientRect().height)}px high box onto ${spill.onto}: "${snippet(el)}"`));
      }
    }

    // 3b. Text drawn over other text, and dialogs that do not fit the screen.
    const overlaps = overlappingText(visible, spilled);
    for (const issue of overlaps.found) push(issue);
    for (const issue of tallDialogs(visible)) push(issue);

    // 4. Interactive controls: overlap, target size, accessible name.
    const allControls = visible.filter((el) => el.matches(INTERACTIVE));
    const controls = allControls.slice(0, MAX_CONTROLS);
    // Overlap is judged on what is visible: a list scrolled under a footer does not cover it.
    const boxes = controls.map(visibleRect);
    const pinned = controls.map(pinnedLayer);
    const popups = controls.map(openPopup);
    const lines = controls.map(lineBoxes);
    for (let i = 0; i < controls.length; i++) {
      for (let j = i + 1; j < controls.length; j++) {
        const a = controls[i], b = controls[j];
        if (containsDeep(a, b) || containsDeep(b, a)) continue;
        if (passesOver(pinned[i], pinned[j])) continue;
        let ra = boxes[i], rb = boxes[j];
        // A button placed inside a text field (show password, clear search) is an adornment.
        if (isAdornment(a, ra, b, rb) || isAdornment(b, rb, a, ra)) continue;
        // A small action laid over a larger row (expand, favourite, remove) that stays on top.
        if (isOverlaidAction(a, ra, rb) || isOverlaidAction(b, rb, ra)) continue;
        let w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
        let h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
        if (w <= 0 || h <= 0) continue;
        if (lines[i] || lines[j]) {
          let best = null;
          for (const fa of lines[i] || [ra]) {
            for (const fb of lines[j] || [rb]) {
              const fw = Math.min(fa.right, fb.right) - Math.max(fa.left, fb.left);
              const fh = Math.min(fa.bottom, fb.bottom) - Math.max(fa.top, fb.top);
              if (fw > 0 && fh > 0 && (!best || fw * fh > best.w * best.h)) best = { ra: fa, rb: fb, w: fw, h: fh };
            }
          }
          if (!best) continue;
          ({ ra, rb, w, h } = best);
        }
        const ratio = (w * h) / Math.min(ra.width * ra.height, rb.width * rb.height);
        if (ratio < overlapThreshold) continue;
        if (closestDeep(a, LAYER) !== closestDeep(b, LAYER)) continue;
        if (apartLayers(popups[i], popups[j])) continue;
        const cx = Math.max(ra.left, rb.left) + w / 2, cy = Math.max(ra.top, rb.top) + h / 2;
        if (cx >= 0 && cy >= 0 && cx <= window.innerWidth && cy <= window.innerHeight) {
          const top = elementAt(cx, cy);
          if (top && !containsDeep(a, top) && !containsDeep(b, top) && !containsDeep(top, a) && !containsDeep(top, b)) continue;
        }
        push(makeIssue("overlapping-controls", "P2", b,
          `Overlaps ${cssPath(a)} by ${Math.round(ratio * 100)}% of the smaller control.`));
      }
    }

    // WCAG 2.5.8: an undersized target still passes when a circle of the minimum size around
    // its centre touches no other target and no other undersized target's circle.
    const targets = controls.map((el) => {
      const r = el.getBoundingClientRect();
      // Rounded as the message shows it: a 23.8px link is 24px to anyone looking at it.
      return { r, x: r.left + r.width / 2, y: r.top + r.height / 2, small: Math.round(r.width) < minTarget || Math.round(r.height) < minTarget };
    });
    const crowdedBy = (k) => {
      const me = targets[k];
      for (let m = 0; m < controls.length; m++) {
        if (m === k || containsDeep(controls[k], controls[m]) || containsDeep(controls[m], controls[k])) continue;
        // A floating panel is not a neighbour of the page under it.
        if (passesOver(pinned[m], pinned[k]) || apartLayers(popups[m], popups[k])) continue;
        const other = targets[m];
        if (!other.r.width || !other.r.height) continue;
        if (other.small) {
          if (Math.hypot(me.x - other.x, me.y - other.y) < minTarget) return controls[m];
        } else {
          const dx = Math.max(other.r.left - me.x, 0, me.x - other.r.right);
          const dy = Math.max(other.r.top - me.y, 0, me.y - other.r.bottom);
          if (Math.hypot(dx, dy) < minTarget / 2) return controls[m];
        }
      }
      return null;
    };
    for (let k = 0; k < controls.length; k++) {
      const el = controls[k], r = targets[k].r;
      if (!targets[k].small) continue;
      if (el.tagName === "A" && getComputedStyle(el).display === "inline" && el.parentElement && hasOwnText(el.parentElement)) continue;
      if (isScreenReaderOnly(el)) continue;
      const neighbour = crowdedBy(k);
      if (!neighbour) continue;
      push(makeIssue("small-target", phone ? "P2" : "P3", el,
        `Target is ${Math.round(r.width)}×${Math.round(r.height)}px, under ${minTarget}×${minTarget}px, and too close to "${accessibleName(neighbour).slice(0, 30) || neighbour.tagName.toLowerCase()}".`));
    }

    for (const el of controls) {
      if (accessibleName(el)) continue;
      push(makeIssue("unnamed-control", "P2", el, `${el.tagName.toLowerCase()} has no accessible name.`));
    }

    // 5. Bars that stay on screen and cover the page (the page's, not an iframe's).
    if (!frameDepth) for (const issue of pinnedBarIssues(visible, vw)) push(issue);

    // 6. Phone readability: field text iOS zooms in on, and text too small to read.
    if (phone) {
      for (const el of visible) {
        if (!el.matches(TEXT_FIELD) || el.disabled || el.readOnly) continue;
        const size = parseFloat(getComputedStyle(el).fontSize);
        if (size && size < 16) {
          push(makeIssue("small-input-font", "P3", el,
            `Field text is ${Math.round(size * 10) / 10}px; iOS zooms the page in when a field under 16px gets focus.`));
        }
      }
    }
    for (const el of tinyText(visible)) {
      push(makeIssue("tiny-text", "P3", el,
        `Text is ${Math.round(parseFloat(getComputedStyle(el).fontSize) * 10) / 10}px, under 12px: "${snippet(el).slice(0, 40)}"`));
    }

    // 7. Images that did not load, or are drawn in another aspect ratio than their picture.
    for (const img of all) {
      if (img.tagName !== "IMG") continue;
      const style = getComputedStyle(img);
      if (style.display === "none" || style.visibility === "hidden" || !img.getClientRects().length) continue;
      const src = img.currentSrc || img.getAttribute("src") || "";
      if (img.complete && img.naturalWidth === 0 && src.trim()) {
        push(makeIssue("broken-image", "P2", img, `Image did not load: ${src.slice(0, 100)}`));
        continue;
      }
      if (!img.complete || !img.naturalWidth || !img.naturalHeight || style.objectFit !== "fill" || !isVisible(img)) continue;
      if (/\.svg([?#]|$)|^data:image\/svg/i.test(src)) continue;  // an SVG keeps its own aspect ratio
      const w = img.clientWidth - (parseFloat(style.paddingLeft) || 0) - (parseFloat(style.paddingRight) || 0);
      const h = img.clientHeight - (parseFloat(style.paddingTop) || 0) - (parseFloat(style.paddingBottom) || 0);
      if (w < 16 || h < 16) continue;
      const drawn = w / h, natural = img.naturalWidth / img.naturalHeight;
      if (Math.abs(drawn / natural - 1) > 0.05) {
        push(makeIssue("distorted-image", "P2", img,
          `Image is drawn ${Math.round(w)}×${Math.round(h)}px but its picture is ${img.naturalWidth}×${img.naturalHeight}; it is stretched (use object-fit: cover or keep its aspect ratio).`));
      }
    }

    // 8. Same-origin iframes, measured by their own copy of the probe at their own size. Their
    // findings are named through the frame, as Playwright's frame locators do, and placed on the page.
    const frameTruncated = {};
    if (frameDepth < MAX_FRAME_DEPTH) {
      for (const frame of visible) {
        if (frame.tagName !== "IFRAME") continue;
        let inner = null, view = null;
        try {
          view = frame.contentWindow;
          inner = view && view.__uiAudit;
        } catch (e) { inner = null; }  // another origin
        if (!inner) continue;
        let result;
        try {
          result = inner.probe({ ...opts, frameDepth: frameDepth + 1, phone });
        } catch (e) { continue; }
        const prefix = `${cssPath(frame)} >> ${FRAME_STEP} >> `;
        const offset = frameOffset(frame);
        const dx = offset.x + window.scrollX - view.scrollX, dy = offset.y + window.scrollY - view.scrollY;
        for (const issue of result.issues) {
          counts[issue.check] = (counts[issue.check] || 0) + 1;
          if (counts[issue.check] > maxPer) continue;
          const rect = { ...issue.rect, x: Math.round(issue.rect.x + dx), y: Math.round(issue.rect.y + dy) };
          issues.push({ ...issue, selector: prefix + issue.selector, rect });
        }
        for (const [check, n] of Object.entries(result.truncated || {})) frameTruncated[check] = (frameTruncated[check] || 0) + n;
      }
    }

    // Checks that did not report everything they found, or did not look at every control:
    // check name → findings counted. verify does not count their findings as fixed here.
    const truncated = Object.fromEntries(Object.entries(counts).filter(([, n]) => n > maxPer));
    if (allControls.length > controls.length) {
      for (const check of CONTROL_CHECKS) truncated[check] = counts[check] || 0;
    }
    if (overlaps.capped) truncated["text-overlap"] = counts["text-overlap"] || 0;
    for (const [check, n] of Object.entries(frameTruncated)) truncated[check] = Math.max(truncated[check] || 0, n);
    return {
      viewport: { width: vw, height: window.innerHeight },
      scrollWidth,
      scrollHeight: document.documentElement.scrollHeight,
      issues,
      truncated,
    };
  }

  // Widths in media and container queries: min-/max-width and -inline-size, and range syntax
  // either way round (width >= 600px, 600px <= width, 400px < width < 800px). viewports.py
  // reads stylesheets the page may not (another origin without CORS) the same way.
  const QUERY_WIDTHS = [
    /(?:min|max)-(?:width|inline-size)\s*:\s*([\d.]+)(px|em|rem)/g,
    /(?:width|inline-size)\s*[<>]=?\s*([\d.]+)(px|em|rem)/g,
    /([\d.]+)(px|em|rem)\s*[<>]=?\s*(?:width|inline-size)/g,
  ];

  // Every stylesheet of the page: linked, @imported, constructed, and those of open shadow roots.
  function styleSheets() {
    const sheets = [];
    const add = (list) => {
      for (const sheet of list || []) sheets.push(sheet);
    };
    add(document.styleSheets);
    add(document.adoptedStyleSheets);
    for (const el of deepElements(document)) {
      if (el.shadowRoot) {
        add(el.shadowRoot.styleSheets);
        add(el.shadowRoot.adoptedStyleSheets);
      }
    }
    return sheets;
  }

  function breakpoints() {
    const found = new Set();
    const toPx = (value, unit) => Math.round(parseFloat(value) * (unit === "px" ? 1 : 16));
    const read = (text) => {
      for (const pattern of QUERY_WIDTHS) {
        for (const m of text.matchAll(pattern)) found.add(toPx(m[1], m[2]));
      }
    };
    // A container query's width is the container's, not the viewport's; most containers span
    // most of the viewport, so it is a fair guess where the layout changes.
    const container = typeof CSSContainerRule === "undefined" ? null : CSSContainerRule;
    const walk = (rules) => {
      for (const rule of rules) {
        if (rule.media && rule.media.mediaText) read(rule.media.mediaText);
        if (container && rule instanceof container) read(rule.conditionText || "");
        try {
          if (rule.styleSheet) walk(rule.styleSheet.cssRules);  // @import
          if (rule.cssRules) walk(rule.cssRules);
        } catch (e) { /* ignore */ }
      }
    };
    for (const sheet of styleSheets()) {
      try {
        if (sheet.media && sheet.media.mediaText) read(sheet.media.mediaText);
        walk(sheet.cssRules);
      } catch (e) { /* cross-origin sheet */ }
    }
    return Array.from(found).filter((n) => n > 0).sort((a, b) => a - b);
  }

  // Stylesheets from another origin that do not allow the page to read them; the audit
  // fetches those itself.
  function unreadableSheets() {
    const hrefs = [];
    for (const sheet of styleSheets()) {
      try {
        void sheet.cssRules;
      } catch (e) {
        if (sheet.href && !hrefs.includes(sheet.href)) hrefs.push(sheet.href);
      }
    }
    return hrefs;
  }

  // A control that opens a dialog or popover without saying so with aria-haspopup or
  // aria-expanded: the popover and invoker attributes, Bootstrap's data-toggle, or aria-controls
  // naming a dialog that is closed.
  function opensDialog(el) {
    if (el.matches("[popovertarget],[data-bs-toggle=modal],[data-toggle=modal]")) return true;
    if (el.matches("[commandfor]")) return /^(show-modal|show-popover|toggle-popover)$/.test(el.getAttribute("command") || "");
    const id = (el.getAttribute("aria-controls") || "").trim().split(/\s+/)[0];
    const target = id ? rootOf(el).getElementById(id) : null;
    return !!target && target.matches(`${DIALOG},[popover]`) && !isVisible(target);
  }

  // An item of a navigation or menu bar with a menu inside that stays hidden until the pointer
  // is over it. Hovering clicks nothing; whether it opens anything is tried like a click.
  function hidesHoverMenu(el) {
    if (el.querySelector("[aria-expanded],[aria-haspopup]")) return false;  // opened by clicking, found as such
    const menu = el.querySelector(":scope > ul, :scope > ol, :scope > [role=menu], :scope > div");
    return !!menu && !isVisible(menu) && !!menu.querySelector("a[href],button,[role=menuitem]");
  }

  function stateCandidates(opts) {
    opts = opts || {};
    const unsafe = wordPattern(DEFAULT_UNSAFE.concat(opts.unsafeWords || []));
    const selectors = [
      ["[aria-expanded=false]", "expand"],
      ["[aria-haspopup]:not([aria-expanded=true])", "popup"],
      ["[role=tab][aria-selected=false]", "tab"],
      ["details:not([open]) > summary", "details"],
      ["[data-ui-audit-state]", "marked"],
      ["[popovertarget],[commandfor],[data-bs-toggle=modal],[data-toggle=modal],[aria-controls]", "dialog", opensDialog],
      ["nav li, [role=menubar] > *, [role=menubar] li", "hover", hidesHoverMenu],
    ];
    const out = [];
    const seen = new Set();
    for (const [selector, kind, test] of selectors) {
      for (const el of queryAllDeep(selector)) {
        if (seen.has(el) || !isVisible(el) || isIgnored(el, opts.ignoreSelectors)) continue;
        if (test && !test(el)) continue;
        seen.add(el);
        if (kind === "hover") {
          const item = el.querySelector("a,button,[role=menuitem]");
          out.push({ selector: cssPath(el), kind, label: (item ? accessibleName(item) : snippet(el)).slice(0, 40) || kind, action: "hover" });
          continue;
        }
        if (closestDeep(el, "form")) continue;
        if (el.matches("[type=submit]")) continue;
        if (el.tagName === "A") {
          const href = el.getAttribute("href") || "";
          if (href && !href.startsWith("#") && !href.startsWith("javascript:")) continue;
        }
        if (unsafe.test(accessibleName(el) || "")) continue;
        out.push({ selector: cssPath(el), kind, label: accessibleName(el).slice(0, 40) || kind });
      }
    }
    return out;
  }

  function domFingerprint() {
    const expanded = queryAllDeep("[aria-expanded],[aria-selected],details,[open]")
      .map((el) => `${el.getAttribute("aria-expanded")}${el.getAttribute("aria-selected")}${el.open}`).join("");
    const shown = deepElements(document.body).filter(isVisible).length;
    return `${expanded}|${shown}`;
  }

  // The page's text, with what open shadow roots show, which innerText leaves out.
  function pageText() {
    let text = document.body ? document.body.innerText : "";
    for (const el of document.body ? deepElements(document.body) : []) {
      if (!el.shadowRoot) continue;
      for (const child of el.shadowRoot.children) {
        if (!["STYLE", "SCRIPT", "TEMPLATE"].includes(child.tagName) && child.innerText) text += `\n${child.innerText}`;
      }
    }
    return text;
  }

  // Source files of the components on the page, as far as a dev build reveals them
  // (React's _debugSource, Vue's __file, Svelte's __svelte_meta). Empty in production builds.
  function sourceFiles() {
    const files = new Set();
    const seen = new WeakSet();
    const all = document.body ? deepElements(document.body) : [];
    for (let n = 0; n < all.length && n < 5000; n++) {
      const node = all[n];
      const key = Object.keys(node).find((k) => k.startsWith("__reactFiber$"));
      for (let fiber = key && node[key]; fiber && !seen.has(fiber); fiber = fiber.return) {
        seen.add(fiber);
        if (fiber._debugSource && fiber._debugSource.fileName) files.add(fiber._debugSource.fileName);
      }
      const vue = node.__vueParentComponent;
      if (vue && vue.type && vue.type.__file) files.add(vue.type.__file);
      const svelte = node.__svelte_meta;
      if (svelte && svelte.loc && svelte.loc.file) files.add(svelte.loc.file);
    }
    return Array.from(files);
  }

  // Whether the page shows what it is for. A skeleton, an error screen or an almost
  // empty page measures clean and says nothing about the real page.
  function contentState() {
    const shown = (sel) => queryAllDeep(sel).filter(isVisible);
    // A progress bar with a value is a meter on the page; only one without a value says "wait".
    const busy = shown('[aria-busy="true"],[role=progressbar]:not([aria-valuenow])').length;
    const skeletons = shown('[class*="skeleton" i],[class*="shimmer" i]').length;
    if (busy || skeletons >= 3) return { state: "loading", detail: busy ? "a region is still marked busy" : `${skeletons} skeleton placeholders` };
    const heading = shown("h1,h2,[role=heading]").map((el) => (el.innerText || "").replace(/\s+/g, " ").trim()).find(Boolean) || "";
    if (PROBLEM_HEADING.test(heading)) return { state: "error-like", detail: heading.slice(0, 80) };
    const hidden = hiddenSections();
    if (hidden) return { state: "hidden", detail: hidden === 1 ? "1 section stays invisible" : `${hidden} sections stay invisible` };
    const text = pageText().replace(/\s+/g, " ").trim();
    // Little to read and next to nothing to operate. A sign-in form is short too, but it has controls.
    const controls = shown(INTERACTIVE).length;
    if (text.length < 250 && controls < 3) return { state: "thin", detail: `${text.length} characters of text, ${controls} control${controls === 1 ? "" : "s"}` };
    return { state: "ok", detail: "" };
  }

  // Blocks of text that stay fully transparent after the page was scrolled through: content
  // that waits for an animation which never ran, so the page measures clean without it.
  // Stacked slides and other absolutely placed layers fade by design and are left out.
  function hiddenSections() {
    let count = 0;
    const counted = [];
    for (const el of document.body ? deepElements(document.body) : []) {
      if (counted.some((c) => containsDeep(c, el))) continue;
      const style = getComputedStyle(el);
      if (style.opacity !== "0" || style.display === "none" || style.visibility === "hidden") continue;
      if (style.position === "absolute" || style.position === "fixed" || closestDeep(el, "[aria-hidden=true]")) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 120 || r.height < 40) continue;
      if ((el.innerText || "").replace(/\s+/g, " ").trim().length < 20) continue;
      const parent = el.parentElement;
      const twins = parent ? Array.from(parent.children).filter((c) => c !== el && c.className === el.className) : [];
      if (twins.some((c) => getComputedStyle(c).opacity !== "0")) continue;  // one slide of several
      counted.push(el);
      count++;
    }
    return count;
  }

  // The component an opened state brought on screen: the newest dialog, menu or popover, or
  // else the control that opened it. Errors logged while it opened point there.
  function layerInfo(trigger) {
    const layers = queryAllDeep(LAYER).filter(isVisible);
    let el = layers[layers.length - 1] || null;
    if (!el && trigger) {
      const found = queryDeep(trigger);
      el = found && found.el;
    }
    return el ? sourceInfo(el, true) : null;
  }

  // Identifies what a route renders, independent of its URL, so the audit can
  // tell a not-found page or an alias from a page of its own.
  function pageFingerprint() {
    let text = pageText();
    const path = location.pathname;
    if (path.length > 1) text = text.split(path).join("");
    text = text.replace(/\s+/g, " ").trim();
    const hashOf = (s) => {
      let h = 0;
      for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
      return h;
    };
    const visible = document.body ? deepElements(document.body).filter(isVisible) : [];
    // Same text in different markup (a button here, a link there) is a different page:
    // its controls, styles and images can have defects of their own.
    const structure = visible.map((el) => [el.tagName, el.getAttribute("class") || "", el.getAttribute("role") || "",
      el.getAttribute("type") || "", el.getAttribute("src") || ""].join(" ")).join("\n");
    return `${text.length}:${hashOf(text)}:${visible.length}:${hashOf(structure)}`;
  }

  function isTriggerVisible(selector) {
    try {
      const found = queryDeep(selector);
      return !!found && isVisible(found.el);
    } catch (e) {
      return false;
    }
  }

  function annotate(items) {
    clearAnnotations();
    const layer = document.createElement("div");
    layer.setAttribute(OVERLAY_ATTR, "");
    layer.style.cssText = "position:absolute;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;";
    const colors = { P1: "#d92d20", P2: "#dc6803", P3: "#7a5af8" };
    let drawn = 0;
    for (const item of items) {
      const found = queryDeep(item.selector);
      if (!found) continue;
      const at = found.el.getBoundingClientRect();
      const r = {
        x: Math.round(at.left + found.dx + window.scrollX), y: Math.round(at.top + found.dy + window.scrollY),
        width: Math.round(at.width), height: Math.round(at.height),
      };
      const color = colors[item.severity] || "#d92d20";
      const box = document.createElement("div");
      box.style.cssText = `position:absolute;left:${r.x}px;top:${r.y}px;width:${Math.max(r.width, 2)}px;height:${Math.max(r.height, 2)}px;outline:3px solid ${color};outline-offset:-1px;background:${color}1a;`;
      const tag = document.createElement("div");
      tag.textContent = `${item.index}. ${item.check}`;
      const docWidth = document.documentElement.scrollWidth;
      tag.style.cssText = `position:absolute;left:${Math.max(Math.min(r.x, docWidth - 170), 0)}px;top:${Math.max(r.y - 18, 0)}px;font:600 11px/16px system-ui,sans-serif;color:#fff;background:${color};padding:0 4px;border-radius:2px;white-space:nowrap;`;
      layer.append(box, tag);
      drawn++;
    }
    document.body.append(layer);
    return drawn;
  }

  function clearAnnotations() {
    for (const el of document.querySelectorAll(`[${OVERLAY_ATTR}]`)) el.remove();
  }

  window.__uiAudit = {
    probe, viewportMeta, breakpoints, unreadableSheets, stateCandidates, consentDecline, contentState, sourceFiles, domFingerprint, pageFingerprint, isTriggerVisible, layerInfo, annotate, clearAnnotations,
  };
})();
