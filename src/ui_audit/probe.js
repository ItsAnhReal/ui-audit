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
  const CONSENT_TOPIC = /cookie|consent|einwilligung/i;
  const PROBLEM_HEADING = /not found|unavailable|went wrong|\berror\b|access denied|forbidden|no longer exists|nicht gefunden|nicht verfügbar|\bfehler\b|kein zugriff|introuvable|indisponible|no encontrad|no disponible/i;
  const DEFAULT_UNSAFE = [
    "delete", "remove", "logout", "log out", "sign out", "signout", "pay", "buy", "purchase",
    "checkout", "order", "submit", "send", "publish", "unsubscribe", "cancel subscription",
    "löschen", "entfernen", "abmelden", "kaufen", "bestellen", "bezahlen", "senden",
  ];

  function isIgnored(el, ignore) {
    if (el.closest(`[${OVERLAY_ATTR}]`)) return true;
    for (const selector of ignore || []) {
      try { if (el.closest(selector)) return true; } catch (e) { /* invalid selector */ }
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

  function stableClasses(el) {
    return Array.from(el.classList)
      .filter((c) => c.length <= 30 && !/[:\[\]\/.@%]/.test(c))
      .slice(0, 2);
  }

  function cssPath(el) {
    if (el.id && document.querySelectorAll(`#${CSS.escape(el.id)}`).length === 1) {
      return `#${CSS.escape(el.id)}`;
    }
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 5) {
      if (node === document.body || node === document.documentElement) {
        parts.unshift(node.tagName.toLowerCase());
        break;
      }
      if (node.id && document.querySelectorAll(`#${CSS.escape(node.id)}`).length === 1) {
        parts.unshift(`#${CSS.escape(node.id)}`);
        break;
      }
      let part = node.tagName.toLowerCase();
      const classes = stableClasses(node);
      if (classes.length) part += classes.map((c) => `.${CSS.escape(c)}`).join("");
      const parent = node.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(" > ");
  }

  // The first visible text that runs past the viewport's right edge with nothing clipping it.
  function overflowingText(vw) {
    if (!document.body) return null;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (!node.nodeValue.trim() || !parent || !isVisible(parent) || clippingAncestor(parent)) continue;
      if (getComputedStyle(parent).position === "fixed") continue;
      range.selectNodeContents(node);
      const right = range.getBoundingClientRect().right + window.scrollX;
      if (right > vw + 1) return { el: parent, text: node.nodeValue.trim().slice(0, 60), right: Math.round(right) };
    }
    return null;
  }

  function clippingAncestor(el) {
    for (let node = el.parentElement; node && node !== document.body && node !== document.documentElement; node = node.parentElement) {
      const ox = getComputedStyle(node).overflowX;
      if (ox !== "visible") return { node, mode: ox };
    }
    return null;
  }

  // The part of an element that scrolling and clipping ancestors leave on screen.
  function visibleRect(el) {
    const r = el.getBoundingClientRect();
    const box = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    for (let node = el; node && node !== document.body; node = node.parentElement) {
      if (getComputedStyle(node).position === "fixed") break;  // fixed boxes escape their ancestors' clip
      const parent = node.parentElement;
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

  // Whether glyphs, not just line spacing or padding, cross the box that clips them.
  // scrollHeight counts the empty leading of a line box, so a 20px line in an 18px
  // box "overflows" although every letter is visible.
  function inkIsClipped(el, horizontal) {
    const box = el.getBoundingClientRect();
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    for (let node = walker.nextNode(), seen = 0; node && seen < 200; node = walker.nextNode()) {
      if (!node.nodeValue.trim()) continue;
      seen++;
      const parent = node.parentElement;
      if (!parent || !isVisible(parent) || isScreenReaderOnly(parent)) continue;
      // Text that a box in between already shortens on purpose is not this box's defect.
      let intended = false;
      for (let up = parent; up && up !== el; up = up.parentElement) {
        if (truncates(getComputedStyle(up))) { intended = true; break; }
      }
      if (intended) continue;
      const fontSize = parseFloat(getComputedStyle(parent).fontSize) || 16;
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) {
        if (!r.width || !r.height) continue;
        if (horizontal) {
          if (r.left < box.left - 1 || r.right > box.right + 1) return true;
        } else {
          const slack = Math.max(r.height - fontSize, 0) / 2;  // leading above and below the glyphs
          if (r.top + slack < box.top - 1 || r.bottom - slack > box.bottom + 1) return true;
        }
      }
    }
    return false;
  }

  function hasOwnText(el) {
    for (const child of el.childNodes) {
      if (child.nodeType === 3 && child.textContent.trim()) return true;
    }
    return false;
  }

  function snippet(el) {
    return (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
  }

  function accessibleName(el) {
    const label = el.getAttribute("aria-label");
    if (label && label.trim()) return label.trim();
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const text = labelledBy.split(/\s+/).map((id) => document.getElementById(id))
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

  function sourceInfo(el) {
    const components = [];
    const files = [];
    const addFile = (file, line) => {
      if (file && !files.some((f) => f.file === file)) files.push({ file, line: line || null });
    };
    let node = el;
    for (let depth = 0; node && depth < 15; depth++, node = node.parentElement) {
      const fiberKey = Object.keys(node).find((k) => k.startsWith("__reactFiber$"));
      if (fiberKey) {
        let fiber = node[fiberKey];
        for (let hops = 0; fiber && hops < 30; hops++, fiber = fiber.return) {
          if (fiber._debugSource) addFile(fiber._debugSource.fileName, fiber._debugSource.lineNumber);
          if (typeof fiber.type === "function") {
            const name = fiber.type.displayName || fiber.type.name;
            if (name && name.length > 1 && !components.includes(name)) components.push(name);
          }
          if (components.length >= 3) break;
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
  function pinnedLayer(el) {
    for (let node = el; node && node !== document.documentElement; node = node.parentElement) {
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
    const top = document.elementFromPoint(cx, cy);
    return !!top && (small === top || small.contains(top));
  }

  // The line boxes of an inline control that wraps; its bounding box also covers text it does not own.
  function lineBoxes(el) {
    if (getComputedStyle(el).display !== "inline") return null;
    const rects = Array.from(el.getClientRects());
    return rects.length > 1 ? rects : null;
  }

  // The button that turns optional cookies down in a consent banner, if one is showing.
  function consentDecline() {
    for (const el of document.querySelectorAll("button,[role=button],a[href]")) {
      if (!isVisible(el)) continue;
      const name = (accessibleName(el) || "").replace(/\s+/g, " ").trim();
      if (!name || name.length > 60 || !CONSENT_DECLINE.test(name)) continue;
      for (let node = el.parentElement, depth = 0; node && node !== document.body && depth < 8; node = node.parentElement, depth++) {
        if (CONSENT_TOPIC.test(node.innerText || "")) return { selector: cssPath(el), label: name };
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

  function makeIssue(check, severity, el, message) {
    return { check, severity, selector: cssPath(el), message, rect: rectOf(el), hints: sourceInfo(el) };
  }

  function probe(opts) {
    opts = opts || {};
    const ignore = opts.ignoreSelectors || [];
    const minTarget = opts.minTarget || 24;
    const overlapThreshold = opts.overlapThreshold || 0.2;
    const maxPer = opts.maxPerCheck || 15;
    const vw = document.documentElement.clientWidth || window.innerWidth;
    const issues = [];
    const counts = {};
    const push = (issue) => {
      counts[issue.check] = (counts[issue.check] || 0) + 1;
      if (counts[issue.check] <= maxPer) issues.push(issue);
    };

    const all = Array.from(document.body ? document.body.querySelectorAll("*") : [])
      .filter((el) => !isIgnored(el, ignore) && !["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "BR"].includes(el.tagName));
    const visible = all.filter(isVisible);

    // 1. Horizontal page overflow and its top-most culprits.
    const scrollWidth = Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0);
    const pageOverflows = scrollWidth > vw + 1;
    const beyondRight = (el) => el.getBoundingClientRect().right + window.scrollX > vw + 1;
    if (pageOverflows) {
      const culprits = visible.filter((el) => {
        if (!beyondRight(el)) return false;
        if (getComputedStyle(el).position === "fixed") return false;
        if (clippingAncestor(el)) return false;
        const parent = el.parentElement;
        return !parent || parent === document.body || parent === document.documentElement || !beyondRight(parent);
      });
      if (culprits.length) {
        for (const el of culprits) {
          const right = Math.round(el.getBoundingClientRect().right + window.scrollX);
          push(makeIssue("horizontal-overflow", "P1", el,
            `Extends to ${right}px in a ${vw}px viewport (page scrolls sideways by ${scrollWidth - vw}px).`));
        }
      } else {
        // No box sticks out, so the page is widened by text that overflows its box (a long
        // word that cannot wrap) or by a box nobody sees (a hidden tooltip left in place).
        const culprit = overflowingText(vw) || all.find((el) => !isVisible(el) && el.getClientRects().length
          && beyondRight(el) && getComputedStyle(el).position !== "fixed" && !clippingAncestor(el));
        if (culprit && culprit.el) {
          push(makeIssue("horizontal-overflow", "P1", culprit.el,
            `Text "${culprit.text}" runs to ${culprit.right}px in a ${vw}px viewport (page scrolls sideways by ${scrollWidth - vw}px).`));
        } else if (culprit) {
          push(makeIssue("horizontal-overflow", "P1", culprit,
            `An invisible element extends to ${Math.round(culprit.getBoundingClientRect().right + window.scrollX)}px in a ${vw}px viewport (page scrolls sideways by ${scrollWidth - vw}px).`));
        } else {
          push(makeIssue("horizontal-overflow", "P1", document.documentElement,
            `Page is ${scrollWidth}px wide in a ${vw}px viewport.`));
        }
      }
    }

    // 2. Content or controls cut off at the viewport edge.
    for (const el of visible) {
      const r = el.getBoundingClientRect();
      const straddlesLeft = r.left < -1 && r.right > 1;
      const straddlesRight = !pageOverflows && r.left < vw - 1 && r.right > vw + 1;
      if (!straddlesLeft && !straddlesRight) continue;
      // Inside any non-visible overflow container: a carousel or a container
      // clip, which the clipped-content check reports at the container.
      if (clippingAncestor(el)) continue;
      const parent = el.parentElement;
      if (parent && parent !== document.body) {
        const pr = parent.getBoundingClientRect();
        if ((pr.left < -1 && pr.right > 1) || (!pageOverflows && pr.left < vw - 1 && pr.right > vw + 1)) continue;
      }
      const interactive = el.matches(INTERACTIVE);
      if (!interactive && !hasOwnText(el) && !el.querySelector(INTERACTIVE)) continue;
      const edge = straddlesLeft ? "left" : "right";
      if (interactive) {
        push(makeIssue("offscreen-control", "P1", el, `Control is cut off at the ${edge} edge of a ${vw}px viewport.`));
      } else {
        push(makeIssue("offscreen-content", "P2", el, `Content is cut off at the ${edge} edge of a ${vw}px viewport.`));
      }
    }

    // 3. Text clipped by its own box, or spilling out of it.
    for (const el of visible) {
      if (["INPUT", "TEXTAREA", "SELECT", "HTML", "BODY"].includes(el.tagName)) continue;
      if (isScreenReaderOnly(el)) continue;
      if (!el.innerText || !el.innerText.trim()) continue;
      const style = getComputedStyle(el);
      const clipsX = style.overflowX === "hidden" || style.overflowX === "clip";
      const clipsY = style.overflowY === "hidden" || style.overflowY === "clip";
      const overX = el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0;
      const overY = el.scrollHeight > el.clientHeight + 1 && el.clientHeight > 0;
      const clamped = truncates(style);
      if ((clipsX && overX) || (clipsY && overY)) {
        if (clamped) continue;
        if (!inkIsClipped(el, clipsX && overX)) continue;
        const axis = clipsX && overX ? `${el.scrollWidth - el.clientWidth}px horizontally` : `${el.scrollHeight - el.clientHeight}px vertically`;
        push(makeIssue("clipped-content", "P2", el, `Content is clipped by ${axis}: "${snippet(el)}"`));
      } else if (style.overflowX === "visible" && overX && hasOwnText(el) && style.display !== "inline") {
        push(makeIssue("text-spill", "P3", el, `Text spills ${el.scrollWidth - el.clientWidth}px outside its box: "${snippet(el)}"`));
      }
    }

    // 4. Interactive controls: overlap, target size, accessible name.
    const controls = visible.filter((el) => el.matches(INTERACTIVE)).slice(0, 400);
    // Overlap is judged on what is visible: a list scrolled under a footer does not cover it.
    const boxes = controls.map(visibleRect);
    const pinned = controls.map(pinnedLayer);
    const lines = controls.map(lineBoxes);
    for (let i = 0; i < controls.length; i++) {
      for (let j = i + 1; j < controls.length; j++) {
        const a = controls[i], b = controls[j];
        if (a.contains(b) || b.contains(a)) continue;
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
        if (a.closest(LAYER) !== b.closest(LAYER)) continue;
        const cx = Math.max(ra.left, rb.left) + w / 2, cy = Math.max(ra.top, rb.top) + h / 2;
        if (cx >= 0 && cy >= 0 && cx <= window.innerWidth && cy <= window.innerHeight) {
          const top = document.elementFromPoint(cx, cy);
          if (top && !a.contains(top) && !b.contains(top) && !top.contains(a) && !top.contains(b)) continue;
        }
        push(makeIssue("overlapping-controls", "P2", b,
          `Overlaps ${cssPath(a)} by ${Math.round(ratio * 100)}% of the smaller control.`));
      }
    }

    // WCAG 2.5.8: an undersized target still passes when a circle of the minimum size around
    // its centre touches no other target and no other undersized target's circle.
    const targets = controls.map((el) => {
      const r = el.getBoundingClientRect();
      return { r, x: r.left + r.width / 2, y: r.top + r.height / 2, small: r.width < minTarget || r.height < minTarget };
    });
    const crowdedBy = (k) => {
      const me = targets[k];
      for (let m = 0; m < controls.length; m++) {
        if (m === k || controls[k].contains(controls[m]) || controls[m].contains(controls[k])) continue;
        if (passesOver(pinned[m], pinned[k])) continue;  // a floating panel is not a neighbour of the page under it
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
      push(makeIssue("small-target", vw < 768 ? "P2" : "P3", el,
        `Target is ${Math.round(r.width)}×${Math.round(r.height)}px, under ${minTarget}×${minTarget}px, and too close to "${accessibleName(neighbour).slice(0, 30) || neighbour.tagName.toLowerCase()}".`));
    }

    for (const el of controls) {
      if (accessibleName(el)) continue;
      push(makeIssue("unnamed-control", "P2", el, `${el.tagName.toLowerCase()} has no accessible name.`));
    }

    return {
      viewport: { width: vw, height: window.innerHeight },
      scrollWidth,
      scrollHeight: document.documentElement.scrollHeight,
      issues,
      truncated: Object.fromEntries(Object.entries(counts).filter(([, n]) => n > maxPer)),
    };
  }

  function breakpoints() {
    const found = new Set();
    const toPx = (value, unit) => Math.round(parseFloat(value) * (unit === "px" ? 1 : 16));
    const read = (text) => {
      for (const m of text.matchAll(/(min|max)-width\s*:\s*([\d.]+)(px|em|rem)/g)) {
        found.add(toPx(m[2], m[3]));
      }
      for (const m of text.matchAll(/width\s*(<=|>=|<|>)\s*([\d.]+)(px|em|rem)/g)) {
        found.add(toPx(m[2], m[3]));
      }
    };
    const walk = (rules) => {
      for (const rule of rules) {
        if (rule.media && rule.media.mediaText) read(rule.media.mediaText);
        if (rule.cssRules) {
          try { walk(rule.cssRules); } catch (e) { /* ignore */ }
        }
      }
    };
    for (const sheet of document.styleSheets) {
      try {
        if (sheet.media && sheet.media.mediaText) read(sheet.media.mediaText);
        walk(sheet.cssRules);
      } catch (e) { /* cross-origin sheet */ }
    }
    return Array.from(found).filter((n) => n > 0).sort((a, b) => a - b);
  }

  function stateCandidates(opts) {
    opts = opts || {};
    const unsafe = DEFAULT_UNSAFE.concat(opts.unsafeWords || []).map((w) => w.toLowerCase());
    const selectors = [
      ["[aria-expanded=false]", "expand"],
      ["[aria-haspopup]:not([aria-expanded=true])", "popup"],
      ["[role=tab][aria-selected=false]", "tab"],
      ["details:not([open]) > summary", "details"],
      ["[data-ui-audit-state]", "marked"],
    ];
    const out = [];
    const seen = new Set();
    for (const [selector, kind] of selectors) {
      for (const el of document.querySelectorAll(selector)) {
        if (seen.has(el) || !isVisible(el) || isIgnored(el, opts.ignoreSelectors)) continue;
        seen.add(el);
        if (el.closest("form")) continue;
        if (el.matches("[type=submit]")) continue;
        if (el.tagName === "A") {
          const href = el.getAttribute("href") || "";
          if (href && !href.startsWith("#") && !href.startsWith("javascript:")) continue;
        }
        const name = (accessibleName(el) || "").toLowerCase();
        if (unsafe.some((w) => name.includes(w))) continue;
        out.push({ selector: cssPath(el), kind, label: accessibleName(el).slice(0, 40) || kind });
      }
    }
    return out;
  }

  function domFingerprint() {
    const expanded = Array.from(document.querySelectorAll("[aria-expanded],[aria-selected],details,[open]"))
      .map((el) => `${el.getAttribute("aria-expanded")}${el.getAttribute("aria-selected")}${el.open}`).join("");
    const shown = Array.from(document.body.querySelectorAll("*")).filter(isVisible).length;
    return `${expanded}|${shown}`;
  }

  // Source files of the components on the page, as far as a dev build reveals them
  // (React's _debugSource, Vue's __file, Svelte's __svelte_meta). Empty in production builds.
  function sourceFiles() {
    const files = new Set();
    const seen = new WeakSet();
    const all = document.body ? document.body.querySelectorAll("*") : [];
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
    const shown = (sel) => Array.from(document.querySelectorAll(sel)).filter(isVisible);
    const busy = shown('[aria-busy="true"],[role=progressbar]').length;
    const skeletons = shown('[class*="skeleton" i],[class*="shimmer" i]').length;
    if (busy || skeletons >= 3) return { state: "loading", detail: busy ? "a region is still marked busy" : `${skeletons} skeleton placeholders` };
    const heading = shown("h1,h2,[role=heading]").map((el) => (el.innerText || "").replace(/\s+/g, " ").trim()).find(Boolean) || "";
    if (PROBLEM_HEADING.test(heading)) return { state: "error-like", detail: heading.slice(0, 80) };
    const text = (document.body ? document.body.innerText : "").replace(/\s+/g, " ").trim();
    // Little to read and next to nothing to operate. A sign-in form is short too, but it has controls.
    const controls = shown(INTERACTIVE).length;
    if (text.length < 250 && controls < 3) return { state: "thin", detail: `${text.length} characters of text, ${controls} control${controls === 1 ? "" : "s"}` };
    return { state: "ok", detail: "" };
  }

  // Identifies what a route renders, independent of its URL, so the audit can
  // tell a not-found page or an alias from a page of its own.
  function pageFingerprint() {
    let text = document.body ? document.body.innerText : "";
    const path = location.pathname;
    if (path.length > 1) text = text.split(path).join("");
    text = text.replace(/\s+/g, " ").trim();
    const hashOf = (s) => {
      let h = 0;
      for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
      return h;
    };
    const visible = document.body ? Array.from(document.body.querySelectorAll("*")).filter(isVisible) : [];
    // Same text in different markup (a button here, a link there) is a different page:
    // its controls, styles and images can have defects of their own.
    const structure = visible.map((el) => [el.tagName, el.getAttribute("class") || "", el.getAttribute("role") || "",
      el.getAttribute("type") || "", el.getAttribute("src") || ""].join(" ")).join("\n");
    return `${text.length}:${hashOf(text)}:${visible.length}:${hashOf(structure)}`;
  }

  function isTriggerVisible(selector) {
    try {
      const el = document.querySelector(selector);
      return !!el && isVisible(el);
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
      let el = null;
      try { el = document.querySelector(item.selector); } catch (e) { el = null; }
      if (!el) continue;
      const r = rectOf(el);
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
    probe, breakpoints, stateCandidates, consentDecline, contentState, sourceFiles, domFingerprint, pageFingerprint, isTriggerVisible, annotate, clearAnnotations,
  };
})();
