/* DOM helpers and shared widgets: elements, icons, toasts, menus, dialogs, the lightbox. */

// ---------------------------------------------------------------- DOM helpers

function h(tag, props, ...children) {
  const node = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "style") for (const [k, v] of Object.entries(value)) node.style.setProperty(k.startsWith("--") ? k : k.replace(/[A-Z]/g, (m) => "-" + m.toLowerCase()), v);
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (value === true) node.setAttribute(key, "");
      else node.setAttribute(key, String(value));
    }
  }
  add(node, children);
  return node;
}
function add(node, children) {
  for (const child of [children].flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === "") continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}
const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.7 2.7L16.5 9.5"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  left: '<path d="m15 18-6-6 6-6"/>',
  right: '<path d="m9 18 6-6-6-6"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5"/>',
  folder: '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"/>',
  trash: '<path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13M10 11v5M14 11v5"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  recheck: '<path d="M20 12a8 8 0 1 1-2.6-5.9L20 8.5M20 4v4.5h-4.5"/>',
  compare: '<path d="M7 7h13M16.5 3.5 20 7l-3.5 3.5M17 17H4M7.5 13.5 4 17l3.5 3.5"/>',
  external: '<path d="M14 4h6v6M20 4l-8.5 8.5M18 13.5V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5.5"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="1.8"/><path d="m21 15-4.5-4.5L6 21"/>',
  alert: '<path d="M10.3 4.2 2.7 17.5A2 2 0 0 0 4.4 20.5h15.2a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0zM12 9.5v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4.5M12 8h.01"/>',
  more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
  code: '<path d="m8 7-5 5 5 5M16 7l5 5-5 5"/>',
  spark: '<path d="M12 3.5 13.9 9l5.6 1.9-5.6 1.9L12 18.5l-1.9-5.7L4.5 10.9 10.1 9z"/><path d="M19 3v3M17.5 4.5h3"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  sliders: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  expand: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  width: '<path d="M4 5v14M20 5v14M8 12h8M10.5 9.5 8 12l2.5 2.5M13.5 9.5 16 12l-2.5 2.5"/>',
  spinner: '<path d="M12 3a9 9 0 1 0 9 9" />',
};
function icon(name, cls) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon" + (cls ? " " + cls : ""));
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = ICONS[name] || "";
  return svg;
}

async function copy(text, message) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    const area = h("textarea", { style: { position: "fixed", opacity: "0" } }, text);
    document.body.append(area); area.select();
    try { document.execCommand("copy"); } catch (_e) { /* nothing more to try */ }
    area.remove();
  }
  toast("good", message || t("toast.copied"));
}

// A screenshot that is gone (deleted, or never copied along) shows as an empty tile, not a broken image.
function missingImage(event) {
  const img = event.currentTarget;
  img.removeAttribute("src");
  img.classList.add("missing");
  if (img.parentElement) img.parentElement.dataset.missing = t("shots.missing");
}

// ---------------------------------------------------------------- shared pieces

function sev(level, withName) {
  return h("span", { class: `sev ${level}`, title: t(`sev.${level}.long`) }, withName ? `${level} · ${t(`sev.${level}`)}` : level);
}
function countChips(c, zeroDim = true) {
  return h("span", { class: "counts" }, SEVS.map((s) => h("span", { class: `count ${s}${zeroDim && !c[s] ? " zero" : ""}`, title: t(`sev.${s}.long`) }, fmt.n(c[s] || 0))));
}
function badge(text, kind, iconName, title) {
  return h("span", { class: `badge${kind ? " " + kind : ""}`, title }, iconName ? icon(iconName) : null, text);
}
function runTags(run) {
  const tags = [];
  if (/-recheck(-|$)/.test(run.name)) tags.push(badge(t("tag.recheck"), "accent", "recheck"));
  else if (run.targeted) tags.push(badge(run.routes && run.routes.length ? plural(run.routes.length, "tag.targeted.one", "tag.targeted.many") : t("tag.targeted"), "accent", null, (run.routes || []).join("  ")));
  if (run.fast) tags.push(badge(t("tag.fast"), null, null, t("tag.fast.title")));
  if (run.locale) tags.push(badge(run.locale, null, "globe"));
  if (run.signed_in) tags.push(badge(t("tag.signedIn"), null, "lock"));
  if (run.verify) tags.push(badge(t("tag.verify", { fixed: run.verify.fixed, introduced: run.verify.introduced }), run.verify.introduced ? "warn" : "good", "compare"));
  if (run.doubtful) tags.push(badge(plural(run.doubtful, "tag.doubtful.one", "tag.doubtful.many"), "warn", "alert"));
  if (run.agent) tags.push(badge(plural(run.agent, "tag.agent.one", "tag.agent.many"), null, "spark"));
  return tags;
}

function editorLink(model, candidate) {
  const label = candidate.line ? `${candidate.file}:${candidate.line}` : candidate.file;
  const root = (model.data.project_root || "").replace(/\/$/, "");
  const absolute = candidate.file.startsWith("/") ? candidate.file : `${root}/${candidate.file}`;
  const editor = prefs.get("editor", "vscode");
  const where = `${absolute}${candidate.line ? ":" + candidate.line : ""}`;
  if (editor === "copy") return h("a", { href: "#", title: t("src.copyPath"), onClick: (e) => { e.preventDefault(); copy(where, t("toast.pathCopied")); } }, label);
  const scheme = { vscode: "vscode", cursor: "cursor", windsurf: "windsurf", zed: "zed" }[editor] || "vscode";
  return h("a", { href: `${scheme}://file${encodeURI(absolute)}${candidate.line ? ":" + candidate.line : ""}`, title: t("src.open", { editor: t(`editor.${editor}`) }) }, label);
}
function emptyState(iconName, title, text, ...actions) {
  return h("div", { class: "empty" }, h("div", { class: "art" }, icon(iconName)), h("h2", { text: title }), text ? h("p", { text }) : null,
    actions.length ? h("div", { class: "actions" }, actions) : null);
}

// ---------------------------------------------------------------- toasts, menus, dialogs

function toast(kind, text, action, ms = 5200) {
  const node = h("div", { class: `toast ${kind}` }, icon(kind === "good" ? "checkCircle" : kind === "bad" ? "alert" : "info"),
    h("div", { class: "grow" }, text),
    action ? h("button", { class: "btn sm", onClick: () => { node.remove(); action.run(); } }, action.label) : null,
    h("button", { class: "btn ghost icon sm", "aria-label": t("action.close"), onClick: () => node.remove() }, icon("x")));
  const box = document.getElementById("toasts");
  const top = [...document.querySelectorAll("dialog[open]")].pop();
  if (box.parentElement !== (top || document.body)) (top || document.body).append(box);  // a modal dialog covers the page
  // errors are announced at once (role=alert), everything else politely (role=status)
  box.querySelector(kind === "bad" ? "#toasts-alert" : "#toasts-status").append(node);
  if (ms) setTimeout(() => node.remove(), action ? ms * 1.6 : ms);
  return node;
}

let openMenuNode = null, openMenuAnchor = null;
function closeMenu() {
  if (openMenuNode) { openMenuNode.remove(); openMenuNode = null; }
  if (openMenuAnchor) { openMenuAnchor.setAttribute("aria-expanded", "false"); openMenuAnchor = null; }
}
function menu(anchor, items) {
  closeMenu();
  openMenuAnchor = anchor;
  anchor.setAttribute("aria-expanded", "true");
  const node = h("div", { class: "menu", role: "menu", tabindex: "-1" });
  for (const item of items) {
    if (!item) continue;
    if (item === "sep") { node.append(h("div", { class: "sep", role: "separator" })); continue; }
    if (item.head) { node.append(h("div", { class: "head", text: item.head })); continue; }
    if (item.node) { node.append(item.node); continue; }
    node.append(h("button", { role: item.checked === undefined ? "menuitem" : item.toggle ? "menuitemcheckbox" : "menuitemradio", class: item.danger ? "danger" : null,
      "aria-checked": item.checked === undefined ? null : String(!!item.checked), disabled: item.disabled,
      onClick: () => { closeMenu(); item.run(); } }, item.icon ? icon(item.icon) : null, item.label));
  }
  document.body.append(node);
  const box = anchor.getBoundingClientRect();
  const width = node.offsetWidth, height = node.offsetHeight;
  let left = Math.min(box.right - width, window.innerWidth - width - 8);
  if (left < 8) left = Math.min(box.left, window.innerWidth - width - 8);
  let top = box.bottom + 6;
  if (top + height > window.innerHeight - 8 && box.top - height - 6 > 8) top = box.top - height - 6;
  node.style.left = `${Math.max(8, left)}px`;
  node.style.top = `${Math.max(8, top)}px`;
  openMenuNode = node;
  const buttons = () => [...node.querySelectorAll("button:not([disabled])")];
  (node.querySelector('[aria-checked="true"], [aria-current="true"]') || buttons()[0] || node).focus();
  node.addEventListener("keydown", (event) => {
    const list = buttons(), at = list.indexOf(document.activeElement);
    if (event.key === "ArrowDown") { event.preventDefault(); list[(at + 1) % list.length]?.focus(); }
    if (event.key === "ArrowUp") { event.preventDefault(); list[(at - 1 + list.length) % list.length]?.focus(); }
    if (event.key === "Escape" || event.key === "Tab") { if (event.key === "Escape") event.preventDefault(); closeMenu(); anchor.focus(); }
  });
  return node;
}
document.addEventListener("pointerdown", (event) => { if (openMenuNode && !openMenuNode.contains(event.target)) closeMenu(); }, true);
window.addEventListener("resize", closeMenu);

let modalCount = 0;
function modal(content, { onClose, cls = "modal", label } = {}) {
  const dialog = h("dialog", { class: cls }, content);
  const title = dialog.querySelector("h1, h2, h3");
  if (title) {  // screen readers name the dialog after its title
    title.id = title.id || `modal-title-${++modalCount}`;
    dialog.setAttribute("aria-labelledby", title.id);
  } else if (label) dialog.setAttribute("aria-label", label);
  document.body.append(dialog);
  dialog.addEventListener("close", () => {
    const toasts = document.getElementById("toasts");
    if (dialog.contains(toasts)) document.body.append(toasts);
    dialog.remove();
    if (onClose) onClose();
  });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.showModal();
  return dialog;
}
function confirmDialog({ title, text, confirm, danger }) {
  return new Promise((resolve) => {
    let answer = false;
    const yes = h("button", { class: `btn ${danger ? "danger solid" : "primary"}`, onClick: () => { answer = true; dialog.close(); } }, confirm);
    const dialog = modal([
      h("div", { class: "body" }, h("h2", { text: title }), h("p", { text })),
      h("div", { class: "foot" }, h("button", { class: "btn", onClick: () => dialog.close() }, t("action.cancel")), yes),
    ], { onClose: () => resolve(answer) });
    yes.focus();
  });
}

// Full-size screenshots with the measured boxes drawn on top.
function lightbox(items, index) {
  let at = index;
  const img = h("img", { alt: "" });
  const stage = h("div", { class: "stage" }, img);
  const cap = h("div", { class: "cap" });
  const prev = h("button", { class: "btn sm", onClick: () => step(-1), "aria-label": t("lightbox.prev") }, icon("left"));
  const next = h("button", { class: "btn sm", onClick: () => step(1), "aria-label": t("lightbox.next") }, icon("right"));
  const open = h("a", { class: "btn sm", target: "_blank", rel: "noopener" }, icon("external"), t("lightbox.open"));
  const dialog = modal(h("div", { class: "lb" },
    h("header", {}, prev, next, cap, open, h("button", { class: "btn sm", onClick: () => dialog.close() }, icon("x"), t("action.close"))),
    h("div", { class: "frame" }, stage)), { cls: "lightbox", label: t("lightbox.title") });
  function show() {
    const item = items[at];
    img.src = item.src;
    img.alt = item.caption;
    open.href = item.src;
    cap.textContent = `${item.caption} · ${at + 1} / ${items.length}`;
    prev.disabled = at === 0;
    next.disabled = at === items.length - 1;
    drawBoxes(stage, img, item.boxes || []);
  }
  function step(by) {
    if (at + by < 0 || at + by >= items.length) return;
    at += by;
    show();
    if (!dialog.contains(document.activeElement) || document.activeElement.disabled) (prev.disabled ? next : prev).focus();
  }
  const onKey = (event) => {
    if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); }
    if (event.key === "ArrowRight") { event.preventDefault(); step(1); }
  };
  document.addEventListener("keydown", onKey);
  dialog.addEventListener("close", () => document.removeEventListener("keydown", onKey));
  show();
}

function drawBoxes(stage, img, boxes, onPlaced) {
  const place = () => {
    for (const old of stage.querySelectorAll(".box")) old.remove();
    const W = img.naturalWidth, H = img.naturalHeight;
    if (!W || !H) return;
    let first = null;
    const scale = (img.getBoundingClientRect().width || W) / W;
    for (const box of boxes) {
      const r = box.rect;
      const page = r.width * r.height > W * H * 0.5 || (r.width >= W * 0.95 && r.height >= H * 0.6);
      const tiny = !page && !box.other && Math.min(r.width, r.height) * scale < 16;
      const inside = page || r.y * scale < 22;  // no room for the label above it
      const node = h("i", { class: `box ${box.severity}${box.other ? " other" : ""}${page ? " page" : ""}${tiny ? " tiny" : ""}${inside ? " label-in" : ""}`, style: {
        left: `${(r.x / W) * 100}%`, top: `${(r.y / H) * 100}%`, width: `${(Math.max(r.width, 3) / W) * 100}%`, height: `${(Math.max(r.height, 3) / H) * 100}%` } },
      box.other ? null : h("b", { text: box.label }));
      stage.append(node);
      if (!box.other && !first) first = r;
    }
    if (onPlaced) onPlaced(first, W, H);
  };
  if (img.complete && img.naturalWidth) place(); else img.addEventListener("load", place, { once: true });
}
