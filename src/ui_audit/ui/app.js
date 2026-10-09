/* ui-audit: the local app (`ui-audit ui`) and the static report viewer (index.html of a run).
   One script for both. With an app config it talks to the local server; with inlined report
   data it shows that one run and offers commands to copy instead of buttons that act. */
(() => {
  "use strict";

  const I18N = window.uiAuditI18n;
  const t = I18N.t;
  const readJson = (id) => { try { return JSON.parse(document.getElementById(id).textContent); } catch (_) { return null; } };
  const DATA = readJson("report-data");
  const APP = readJson("app-config");
  const IS_APP = !!(APP && APP.token);
  const ORDER = { P1: 0, P2: 1, P3: 2 };
  const SEVS = ["P1", "P2", "P3"];
  const ACTIVE = new Set(["queued", "running", "waiting"]);
  const RUNTIME_CHECKS = new Set(["console-error", "failed-resource"]);

  // ---------------------------------------------------------------- preferences

  const prefs = {
    get(key, fallback) { try { const v = localStorage.getItem("ui-audit:" + key); return v === null ? fallback : v; } catch (_) { return fallback; } },
    set(key, value) { try { localStorage.setItem("ui-audit:" + key, value); } catch (_) { /* private window */ } },
    json(key, fallback) { try { return JSON.parse(this.get(key, "")) || fallback; } catch (_) { return fallback; } },
  };
  function applyTheme() {
    const theme = prefs.get("theme", "system");
    if (theme === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = theme;
  }
  applyTheme();
  I18N.use(prefs.get("lang", "auto"));
  document.documentElement.lang = I18N.lang;

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
  const debounce = (fn, ms) => { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); }; };
  const enc = encodeURIComponent;
  const plural = (n, one, many) => t(n === 1 ? one : many, { n: fmt.n(n) });
  const known = (key, raw) => (I18N.has(key) ? t(key) : raw);  // values written by newer or older versions

  // ---------------------------------------------------------------- formatting

  const fmt = {
    n: (v) => new Intl.NumberFormat(I18N.lang).format(v || 0),
    bytes(b) {
      if (!b) return "0 MB";
      if (b >= 1e9) return `${new Intl.NumberFormat(I18N.lang, { maximumFractionDigits: 1 }).format(b / 1e9)} GB`;
      if (b >= 1e6) return `${fmt.n(Math.round(b / 1e6))} MB`;
      return `${fmt.n(Math.max(1, Math.round(b / 1e3)))} KB`;
    },
    dur(s) {
      if (s === null || s === undefined || Number.isNaN(s)) return "–";
      if (s < 60) return t("dur.s", { n: Math.max(1, Math.round(s)) });
      if (s < 3600) return t("dur.m", { n: Math.round(s / 60) });
      return t("dur.h", { h: Math.floor(s / 3600), m: Math.round((s % 3600) / 60) });
    },
    clock(s) { s = Math.max(0, Math.round(s)); const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; },
    ago(iso) {
      const then = typeof iso === "number" ? iso : Date.parse(iso);
      if (!then) return "";
      const diff = (then - Date.now()) / 1000;
      const rtf = new Intl.RelativeTimeFormat(I18N.lang, { numeric: "auto" });
      const abs = Math.abs(diff);
      if (abs < 45) return t("time.now");
      if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
      if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
      if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), "day");
      return fmt.date(iso);
    },
    date(iso) { const d = new Date(iso); return Number.isNaN(+d) ? "" : new Intl.DateTimeFormat(I18N.lang, { dateStyle: "medium", timeStyle: "short" }).format(d); },
    range(lo, hi) { return lo === undefined ? t("widths.none") : lo === hi ? `${lo} px` : `${lo}–${hi} px`; },
  };
  const lo = (i) => (i.widths && i.widths.length ? Math.min(...i.widths) : undefined);
  const hi = (i) => (i.widths && i.widths.length ? Math.max(...i.widths) : undefined);
  const worst = (issues) => SEVS[Math.min(...issues.map((i) => ORDER[i.severity] ?? 2))] || "P3";
  const span = (issues) => {
    const all = issues.flatMap((i) => i.widths || []);
    return all.length ? [Math.min(...all), Math.max(...all)] : [undefined, undefined];
  };
  const shotWidth = (file) => { const m = /__(\d+)(__annotated)?\.png$/.exec(file || ""); return m ? Number(m[1]) : null; };

  // ---------------------------------------------------------------- server

  async function api(path, body) {
    const response = await fetch("/api/" + path, {
      method: body ? "POST" : "GET",
      headers: { "X-UI-Audit-Token": APP.token, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await response.json(); } catch (_) { /* empty body */ }
    if (!response.ok) throw new Error((data && data.error) || `HTTP ${response.status}`);
    return data;
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

  // ---------------------------------------------------------------- app state

  const S = {
    state: null,            // GET /api/state
    stateError: null,
    runs: new Map(),        // run name -> { stamp, model }
    views: new Map(),       // run name -> list filters, selection and screenshot choices
    picked: [],             // runs ticked for comparing
    page: null,             // the mounted view: { kind, key, update(route), onState() }
    knownJobs: new Map(),   // job id -> last seen status, to notice when one finishes
    reach: new Map(),       // base URL -> reachability result
  };

  function viewState(name) {
    if (!S.views.has(name)) {
      S.views.set(name, { mode: prefs.get("list-mode", "cause"), sev: new Set(), route: "", check: "", text: "", width: null,
        accepted: false, occ: {}, shot: {}, fit: true, zoom: true, others: false, accepting: null });
    }
    return S.views.get(name);
  }

  // ---------------------------------------------------------------- routing

  function parseHash() {
    const raw = location.hash.replace(/^#\/?/, "");
    const [path, query = ""] = raw.split("?");
    const parts = path.split("/").filter(Boolean).map((p) => { try { return decodeURIComponent(p); } catch (_) { return p; } });
    const f = new URLSearchParams(query).get("f");
    if (!IS_APP) return { view: "run", run: "", tab: parts[0] || "findings", f };
    if (parts[0] === "run" && parts[1]) return { view: "run", run: parts[1], tab: parts[2] || "findings", f };
    if (parts[0] === "compare") return { view: "compare", base: parts[1] || "", current: parts[2] || "" };
    return { view: "home" };
  }
  function link(route) {
    if (route.view === "run") {
      const query = route.f ? `?f=${enc(route.f)}` : "";
      const tab = route.tab && route.tab !== "findings" ? route.tab : "";
      if (!IS_APP) return `#/${tab || "findings"}${query}`;
      return `#/run/${enc(route.run)}${tab ? "/" + tab : ""}${query}`;
    }
    if (route.view === "compare") return `#/compare/${enc(route.base || "")}/${enc(route.current || "")}`;
    return "#/";
  }
  function go(route, replace) {
    const target = link(route);
    if (replace) { history.replaceState(null, "", target); render(); } else if (location.hash === target) render(); else location.hash = target;
  }
  window.addEventListener("hashchange", () => render());

  // ---------------------------------------------------------------- run model

  async function loadRun(name) {
    if (!IS_APP) {
      if (!S.runs.has("")) S.runs.set("", { stamp: 0, model: buildModel(DATA) });
      return S.runs.get("").model;
    }
    const summary = (S.state && S.state.runs || []).find((r) => r.name === name);
    const stamp = summary ? JSON.stringify([summary.counts, summary.accepted, summary.agent, summary.verify, summary.created]) : null;
    const cached = S.runs.get(name);
    if (cached && (stamp === null || cached.stamp === stamp)) return cached.model;
    const data = await api("runs/" + enc(name));
    const model = buildModel(data);
    S.runs.set(name, { stamp, model });
    return model;
  }
  function forgetRun(name) { S.runs.delete(name); }

  function buildModel(data) {
    data = data || { issues: [], routes: [], captures: [], states: [] };
    const issues = (data.issues || []).slice().sort((a, b) => (ORDER[a.severity] ?? 9) - (ORDER[b.severity] ?? 9)
      || a.route.localeCompare(b.route) || a.check.localeCompare(b.check));
    const byId = new Map(issues.map((i) => [i.id, i]));
    const info = new Map((data.groups || []).map((g) => [g.id, g]));
    const groups = new Map();
    for (const issue of issues) {
      const key = issue.group || issue.id;
      if (!groups.has(key)) groups.set(key, { id: key, info: info.get(key), issues: [] });
      groups.get(key).issues.push(issue);
    }
    const captures = new Map();
    for (const capture of data.captures || []) {
      const key = capture.route + "|" + capture.state;
      if (!captures.has(key)) captures.set(key, []);
      captures.get(key).push(capture);
    }
    const browsers = data.browsers || ["chromium"];
    const engineOrder = (c) => browsers.indexOf(c.browser || "chromium");
    for (const list of captures.values()) list.sort((a, b) => a.width - b.width || engineOrder(a) - engineOrder(b));
    const states = new Map((data.states || []).map((s) => [s.route + "|" + s.id, s]));
    const viewports = (data.config && data.config.viewports) || {};
    const routes = data.routes || [];
    const audited = routes.filter((r) => (r.status || "audited") === "audited" && r.loaded !== false);
    return {
      data, issues, byId, groups, captures, states, routes, audited, browsers,
      name: data.name || "",
      LO: viewports.min_width || 320, HI: Math.max(viewports.max_width || 1920, (viewports.min_width || 320) + 1),
      accepted: issues.filter((i) => i.accepted).length,
      breakpoints: data.breakpoints || [],
    };
  }
  function fileUrl(model, path) {
    if (!path) return "";
    if (!IS_APP) return path.split("/").map(enc).join("/");
    return `/files/${enc(model.name)}/${path.split("/").map(enc).join("/")}`;
  }
  function absPath(model, rel) {
    const dir = IS_APP ? model.data.dir : model.data.output_dir;
    return dir ? `${dir.replace(/\/$/, "")}/${rel}` : rel;
  }
  function runDir(model) { return IS_APP ? model.data.dir : (model.data.output_dir || "."); }
  function stateLabel(model, route, state) {
    if (!state || state === "default") return t("state.default");
    const record = model.states.get(route + "|" + state);
    const label = (record && record.label) || state;
    // automatic states are labelled "<kind>: <control name>"
    const auto = /^(expand|popup|tab|details|marked): ([^]*)$/.exec(label);
    return auto ? t(auto[1] === "tab" ? "state.tab" : "state.clicked", { name: auto[2].replace(/\s+/g, " ").trim() }) : label.replace(/\s+/g, " ");
  }
  // The audit writes these in English; known shapes get translated, anything else is shown as is.
  function skipText(why) {
    let m;
    if (why === "not found") return t("skip.notFound");
    if ((m = /^redirects to (.*)$/.exec(why))) return t("skip.redirects", { to: m[1] });
    if ((m = /^same page as (.*)$/.exec(why))) return t("skip.same", { as: m[1] });
    return why;
  }
  // The probe measures in English; its known sentences are shown in the app's language. The fix prompt keeps the original.
  const MESSAGES = [
    [/^Page is (\d+)px wide in a (\d+)px viewport\.$/, "msg.pageWide", ["page", "vw"]],
    [/^Extends to (\d+)px in a (\d+)px viewport \(page scrolls sideways by (\d+)px\)\.$/, "msg.extends", ["right", "vw", "by"]],
    [/^Control is cut off at the (left|right) edge of a (\d+)px viewport\.$/, "msg.controlCut", ["edge", "vw"]],
    [/^Content is cut off at the (left|right) edge of a (\d+)px viewport\.$/, "msg.contentCut", ["edge", "vw"]],
    [/^Grid columns need (\d+)px but the grid is (\d+)px wide in a (\d+)px viewport \(page scrolls sideways by (\d+)px\)\.$/, "msg.gridExtends", ["needed", "box", "vw", "by"]],
    [/^Grid columns need (\d+)px but the grid is (\d+)px wide; content is cut off at the (left|right) edge of a (\d+)px viewport\.$/, "msg.gridCut", ["needed", "box", "edge", "vw"]],
    [/^Content is clipped by (\d+)px horizontally: "([^]*)"$/, "msg.clippedX", ["px", "text"]],
    [/^Content is clipped by (\d+)px vertically: "([^]*)"$/, "msg.clippedY", ["px", "text"]],
    [/^Text spills (\d+)px outside its box: "([^]*)"$/, "msg.spill", ["px", "text"]],
    [/^Overlaps (.+) by (\d+)% of the smaller control\.$/, "msg.overlaps", ["other", "pct"]],
    [/^Target is (\d+)×(\d+)px, under (\d+)×\d+px, and too close to "([^]*)"\.$/, "msg.target", ["w", "h", "min", "near"]],
    [/^(\w+) has no accessible name\.$/, "msg.unnamed", ["tag"]],
  ];
  function messageText(issue) {
    const raw = issue.message || "";
    if (issue.origin === "agent" || RUNTIME_CHECKS.has(issue.check)) return raw;
    for (const [pattern, key, names] of MESSAGES) {
      const m = pattern.exec(raw);
      if (!m) continue;
      const vars = Object.fromEntries(names.map((name, n) => [name, m[n + 1]]));
      if (vars.edge) vars.edge = t(`msg.edge.${vars.edge}`);
      if (vars.other) vars.other = shortSelector(vars.other);
      return t(key, vars);
    }
    return raw;
  }
  function contentDetail(detail) {
    let m;
    if ((m = /^(\d+) characters of text, (\d+) controls?$/.exec(detail))) return t("content.thinDetail", { chars: fmt.n(+m[1]), controls: fmt.n(+m[2]) });
    if ((m = /^(\d+) sections? stays? invisible$/.exec(detail))) return t("content.hiddenDetail", { n: fmt.n(+m[1]) });
    if ((m = /^(\d+) skeleton placeholders$/.exec(detail))) return t("content.skeletons", { n: fmt.n(+m[1]) });
    if (detail === "a region is still marked busy") return t("content.busy");
    return detail;
  }
  // A screenshot that is gone (deleted, or never copied along) shows as an empty tile, not a broken image.
  function missingImage(event) {
    const img = event.currentTarget;
    img.removeAttribute("src");
    img.classList.add("missing");
    if (img.parentElement) img.parentElement.dataset.missing = t("shots.missing");
  }
  function counts(issues) {
    const c = { P1: 0, P2: 0, P3: 0 };
    for (const i of issues) if (!i.accepted) c[i.severity] = (c[i.severity] || 0) + 1;
    return c;
  }
  // Other browsers than Chromium: their screenshots and boxes carry the browser's name.
  function browserName(name) {
    return { chromium: t("browser.chromium"), webkit: t("browser.webkit"), firefox: t("browser.firefox") }[name] || name;
  }
  function rectKey(capture) { return !capture.browser || capture.browser === "chromium" ? String(capture.width) : `${capture.width}@${capture.browser}`; }
  function shotLabel(model, capture, unit = "") {
    return `${capture.width}${unit}` + (model.browsers.length > 1 ? ` · ${browserName(capture.browser || "chromium")}` : "");
  }
  function onlyIn(model, issue) {
    const seen = (issue.browsers || ["chromium"]).filter((b) => model.browsers.includes(b));
    return model.browsers.length > 1 && seen.length && seen.length < model.browsers.length ? seen : null;
  }
  function capturesFor(model, issue) {
    const seen = issue.browsers || ["chromium"];
    return (model.captures.get(issue.route + "|" + issue.state) || []).filter((c) => seen.includes(c.browser || "chromium"));
  }
  function bestCapture(model, issue) {
    const caps = capturesFor(model, issue);
    if (!caps.length) return null;
    const boxed = caps.filter((c) => issue.rects && issue.rects[rectKey(c)]);
    if (boxed.length) return boxed[Math.floor((boxed.length - 1) / 2)];
    const a = lo(issue), b = hi(issue);
    if (a === undefined) return caps[0];
    const middle = (a + b) / 2;
    return caps.reduce((best, c) => (Math.abs(c.width - middle) < Math.abs(best.width - middle) ? c : best), caps[0]);
  }
  function nearestCapture(model, route, state, width) {
    const caps = model.captures.get(route + "|" + state) || [];
    if (!caps.length) return null;
    return caps.reduce((best, c) => (Math.abs(c.width - width) < Math.abs(best.width - width) ? c : best), caps[0]);
  }
  function boxesAt(model, capture, focusIds) {
    const boxes = [];
    for (const issue of model.issues) {
      if (issue.route !== capture.route || issue.state !== capture.state) continue;
      const rect = issue.rects && issue.rects[rectKey(capture)];
      if (!rect) continue;
      const focus = focusIds ? focusIds.has(issue.id) : !issue.accepted;
      if (!focus && (issue.accepted || !focusIds)) continue;
      boxes.push({ rect, severity: issue.severity, label: I18N.check(issue.check), other: focusIds ? !focus : false, id: issue.id });
    }
    return boxes;
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
  // Whether two runs measured the same thing, so their counts can be set side by side.
  function comparable(a, b) {
    if (b.targeted || a.base_url !== b.base_url || a.fast !== b.fast || a.signed_in !== b.signed_in || (a.locale || "") !== (b.locale || "")) return false;
    const mine = new Set(a.paths || []), theirs = new Set(b.paths || []);
    if (!mine.size || !theirs.size) return true;  // runs listed before paths were recorded
    const shared = [...mine].filter((p) => theirs.has(p)).length;
    return shared / new Set([...mine, ...theirs]).size >= 0.8;
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
    box.append(node);
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
      node.append(h("button", { role: item.checked === undefined ? "menuitem" : "menuitemradio", class: item.danger ? "danger" : null,
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

  function modal(content, { onClose, cls = "modal" } = {}) {
    const dialog = h("dialog", { class: cls }, content);
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
      h("div", { class: "frame" }, stage)), { cls: "lightbox" });
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
  // The part of a screenshot worth zooming into: the marked boxes with some room around them,
  // at least a phone's width of context, never taller than wide. Screenshots are taken at a device
  // pixel ratio of 1, so image and CSS pixels match. Null when zooming would barely enlarge it.
  function zoomCrop(rects, W, H, frameWidth) {
    if (!rects.length || !W || !H) return null;
    const x0 = Math.min(...rects.map((r) => r.x)), y0 = Math.min(...rects.map((r) => r.y));
    const x1 = Math.max(...rects.map((r) => r.x + r.width)), y1 = Math.max(...rects.map((r) => r.y + r.height));
    const pad = Math.max(40, 0.3 * Math.max(x1 - x0, y1 - y0));
    let w = Math.max(x1 - x0 + 2 * pad, 360);
    let ht = y1 - y0 + 2 * pad;
    if (ht > w * 0.75) w = ht / 0.75;
    ht = Math.min(Math.max(ht, w * 0.4), w * 0.75);
    w = Math.min(w, W); ht = Math.min(ht, H);
    // fitted, the whole screenshot shows at most at its real size; the close-up at most at twice that
    const frame = frameWidth || W;
    if (Math.min(2, frame / w) < Math.min(1, frame / W) * 1.3) return null;
    const clamp = (v, max) => Math.min(Math.max(0, v), max);
    return { x: clamp((x0 + x1) / 2 - w / 2, W - w), y: clamp((y0 + y1) / 2 - ht / 2, H - ht), width: w, height: ht };
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

  // ---------------------------------------------------------------- top bar

  function topbar(crumbs, extra, { newButton = true } = {}) {
    const bar = h("header", { class: "topbar" },
      h("a", { class: "brand", href: IS_APP ? "#/" : "#/findings", "aria-label": "ui-audit" },
        h("span", { class: "mark" }, icon("width")), h("span", { class: "word", text: "ui-audit" })),
      crumbs ? h("nav", { class: "crumbs", "aria-label": t("nav.crumbs") }, crumbs) : null,
      h("div", { class: "spacer" }),
      IS_APP ? h("span", { id: "job-pill" }) : null,
      extra,
      h("button", { class: "btn ghost icon", "aria-label": t("settings.title"), title: t("settings.title"), "aria-haspopup": "menu", "aria-expanded": "false", onClick: (e) => settingsMenu(e.currentTarget) }, icon("sliders")),
      IS_APP && newButton ? h("button", { class: "btn primary", onClick: () => newAuditSheet() }, icon("plus"), h("span", { class: "new-label", text: t("action.newAudit") })) : null);
    return bar;
  }
  function settingsMenu(anchor) {
    const pick = (key, value, after) => () => { prefs.set(key, value); after(); };
    const rerender = () => { render(true); };
    menu(anchor, [
      { head: t("settings.language") },
      { label: "Deutsch", checked: I18N.lang === "de", run: pick("lang", "de", () => { I18N.use("de"); document.documentElement.lang = "de"; rerender(); }) },
      { label: "English", checked: I18N.lang === "en", run: pick("lang", "en", () => { I18N.use("en"); document.documentElement.lang = "en"; rerender(); }) },
      "sep",
      { head: t("settings.theme") },
      ...["system", "light", "dark"].map((theme) => ({ label: t(`theme.${theme}`), checked: prefs.get("theme", "system") === theme, run: pick("theme", theme, applyTheme) })),
      "sep",
      { head: t("settings.editor") },
      ...["vscode", "cursor", "windsurf", "zed", "copy"].map((editor) => ({ label: t(`editor.${editor}`), checked: prefs.get("editor", "vscode") === editor, run: pick("editor", editor, rerender) })),
    ]);
  }
  function updateJobPill() {
    const pill = document.getElementById("job-pill");
    if (!pill || !S.state) return;
    const active = S.state.jobs.filter((j) => ACTIVE.has(j.status) && j.kind !== "login");
    pill.replaceChildren();
    if (!active.length) { document.title = baseTitle; return; }
    const job = active.find((j) => j.status === "running") || active[0];
    const fraction = job.progress && job.progress.fraction;
    const measuring = job.progress && job.progress.route;
    const text = job.status === "queued" ? t("job.queued") : fraction || measuring ? t("job.pill", { pct: Math.round((fraction || 0) * 100) }) : t("job.starting");
    pill.append(h("a", { class: "job-pill", href: "#/", title: job.name }, ring(fraction), h("span", { class: "txt", text }),
      active.length > 1 ? badge(`+${active.length - 1}`) : null));
    document.title = `${fraction ? Math.round(fraction * 100) + "% · " : ""}${baseTitle}`;
  }
  let baseTitle = "ui-audit";
  function ring(fraction) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 20 20");
    svg.setAttribute("class", "ring" + (fraction ? "" : " spin"));
    const r = 8, c = 2 * Math.PI * r;
    svg.innerHTML = `<circle cx="10" cy="10" r="${r}" fill="none" stroke="var(--surface-3)" stroke-width="3"/>` +
      `<circle cx="10" cy="10" r="${r}" fill="none" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - (fraction || 0.25))}" transform="rotate(-90 10 10)"/>`;
    return svg;
  }

  // ---------------------------------------------------------------- render

  const root = document.getElementById("app");
  async function render(force) {
    closeMenu();
    const route = parseHash();
    const key = route.view === "run" ? `run|${route.run}|${route.tab}` : route.view === "compare" ? `compare|${route.base}|${route.current}` : "home";
    if (!force && S.page && S.page.key === key && S.page.update) { S.page.update(route); return; }
    if (S.page && S.page.unmount) S.page.unmount();
    S.page = null;
    try {
      if (route.view === "home") S.page = homeView();
      else if (route.view === "compare") S.page = await compareView(route);
      else S.page = await runView(route);
      if (S.page) S.page.key = key;
    } catch (error) {
      root.replaceChildren(topbar(null), h("main", { class: "main" }, h("div", { class: "card" },
        emptyState("alert", t("error.title"), error.message, IS_APP ? h("a", { class: "btn", href: "#/" }, t("nav.allRuns")) : null))));
    }
    root.removeAttribute("aria-busy");
    updateJobPill();
  }

  // ---------------------------------------------------------------- home

  function homeView() {
    baseTitle = S.state ? `${S.state.project} · ui-audit` : "ui-audit";
    document.title = baseTitle;
    const main = h("main", { class: "main" });
    const jobsBox = h("div", { class: "jobs" });
    const setupBox = h("div", { class: "setup" });
    const body = h("div");
    root.replaceChildren(topbar(h("span", { class: "here", text: S.state ? S.state.project : "" }), null, { newButton: false }), main);
    let lastRuns = "";

    function head() {
      const st = S.state;
      const cfg = st.config || {};
      const reach = h("span", { class: "status-dot wait", text: t("home.checking") });
      if (cfg.base_url) checkReach(cfg.base_url).then((r) => {
        reach.className = `status-dot ${r.ok ? "ok" : "bad"}`;
        reach.textContent = r.ok ? t("home.reachable") : t("home.unreachable");
        reach.title = r.detail || "";
      });
      return h("div", { class: "page-head" },
        h("div", {}, h("h1", { text: st.project }),
          h("p", {}, cfg.base_url ? [h("span", { class: "mono", text: cfg.base_url }), " ", reach, " · "] : null,
            t("home.runsIn", { dir: st.runs_dir }), cfg.path ? ` · ${t("home.settings", { file: cfg.path })}` : ` · ${t("home.noSettings")}`)),
        h("div", { class: "actions" }, h("button", { class: "btn primary lg", onClick: () => newAuditSheet() }, icon("plus"), t("action.newAudit"))));
    }

    function setup() {
      const st = S.state, rows = [];
      if (st.browser && st.browser.ok === false) {
        rows.push(h("div", { class: "notice bad" }, icon("alert"), h("div", { class: "grow" }, h("b", { text: t("setup.browser") }), " ",
          t("setup.browserHelp"), h("div", { class: "cmd", style: { marginTop: "8px" } }, "playwright install chromium"))));
      }
      if (st.config && st.config.error) rows.push(h("div", { class: "notice bad" }, icon("alert"), h("div", { class: "grow" }, h("b", { text: t("setup.config") }), " ", st.config.error)));
      setupBox.replaceChildren(...rows);
    }

    function runsBlock() {
      const runs = S.state.runs;
      if (!runs.length && S.state.jobs.some((j) => ACTIVE.has(j.status) && j.kind !== "login")) return [];
      if (!runs.length) {
        return h("div", { class: "card" }, emptyState("width", t("home.empty.title"), t("home.empty.text"),
          h("button", { class: "btn primary lg", onClick: () => newAuditSheet() }, icon("play"), t("home.empty.start"))));
      }
      return [hero(runs), h("div", { class: "section-title" }, t("home.allRuns"), h("span", { class: "muted", text: plural(runs.length, "home.runs.one", "home.runs.many") })), runsTable(runs)];
    }

    function hero(runs) {
      const latest = runs.find((r) => !r.targeted && !/-recheck(-|$)/.test(r.name)) || runs[0];
      const previous = latest.targeted ? null : runs.slice(runs.indexOf(latest) + 1).find((r) => comparable(latest, r));
      const tile = (s) => {
        const value = latest.counts[s] || 0;
        const delta = previous ? value - (previous.counts[s] || 0) : null;
        return h("div", { class: `tile ${s}` }, h("div", { class: "k", text: `${s} · ${t(`sev.${s}`)}` }), h("div", { class: "v num", text: fmt.n(value) }),
          delta === null ? null : h("div", { class: `d ${delta > 0 ? "up" : delta < 0 ? "down" : ""}`, text: delta === 0 ? t("hero.same") : `${delta > 0 ? "+" : "−"}${fmt.n(Math.abs(delta))}` }));
      };
      return h("section", { class: "card hero" },
        h("div", {}, h("div", { class: "label", text: t("hero.latest") }), h("h2", {}, h("a", { href: link({ view: "run", run: latest.name }), text: latest.name })),
          h("div", { class: "meta" }, [fmt.ago(latest.created), plural(latest.pages, "unit.pages.one", "unit.pages.many"), fmt.dur(latest.seconds),
            latest.causes ? plural(latest.causes, "unit.causes.one", "unit.causes.many") : null].filter(Boolean).join(" · ")),
          h("div", { class: "tags", style: { display: "flex", gap: "4px", flexWrap: "wrap", marginTop: "8px" } }, runTags(latest))),
        h("div", { class: "tiles" }, SEVS.map(tile)),
        h("div", { class: "foot" },
          h("span", { class: "muted", text: previous ? t("hero.vs", { name: previous.name }) : "" }),
          h("button", { class: "btn", onClick: () => runAgain(latest.name) }, icon("recheck"), t("action.runAgain")),
          previous ? h("a", { class: "btn", href: link({ view: "compare", base: previous.name, current: latest.name }) }, icon("compare"), t("action.compare")) : null,
          h("a", { class: "btn primary", href: link({ view: "run", run: latest.name }) }, t("hero.open"), icon("right"))));
    }

    function runsTable(runs) {
      const rows = runs.map((run) => {
        const picked = S.picked.includes(run.name);
        const box = h("input", { type: "checkbox", "aria-label": t("runs.pick", { name: run.name }), checked: picked,
          onClick: (e) => { e.stopPropagation(); togglePick(run.name); } });
        const more = h("button", { class: "btn ghost icon sm", "aria-label": t("runs.actions", { name: run.name }), "aria-haspopup": "menu", "aria-expanded": "false", onClick: (e) => { e.stopPropagation(); runMenu(e.currentTarget, run, runs); } }, icon("more"));
        return h("tr", { class: picked ? "selected" : null, onClick: () => go({ view: "run", run: run.name }) },
          h("td", { class: "pick" }, h("label", { onClick: (e) => e.stopPropagation() }, box)),
          h("td", { class: "run" }, h("a", { class: "name", href: link({ view: "run", run: run.name }), onClick: (e) => e.stopPropagation() }, run.name),
            h("div", { class: "tags" }, runTags(run))),
          h("td", { class: "when", title: fmt.date(run.created) }, fmt.ago(run.created)),
          h("td", { class: "right" }, plural(run.pages, "unit.pages.one", "unit.pages.many")),
          h("td", { class: "findings" }, countChips(run.counts)),
          h("td", { class: "right" }, fmt.dur(run.seconds)),
          h("td", { class: "right size" }, fmt.bytes(run.bytes)),
          h("td", { class: "menu-cell" }, more));
      });
      return h("div", { class: "card runs" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", { class: "pick" }, h("span", { class: "sr-only", text: t("runs.compareCol") })), h("th", { text: t("runs.run") }), h("th", { text: t("runs.when") }),
          h("th", { class: "right", text: t("runs.pages") }), h("th", { text: t("runs.findings") }), h("th", { class: "right", text: t("runs.took") }),
          h("th", { class: "right size", text: t("runs.size") }), h("th", { class: "menu-cell" }, h("span", { class: "sr-only", text: t("runs.actionsCol") })))),
        h("tbody", {}, rows)));
    }

    function togglePick(name) {
      S.picked = S.picked.includes(name) ? S.picked.filter((n) => n !== name) : [...S.picked, name].slice(-2);
      lastRuns = "";
      drawRuns();
    }
    function compareBar() {
      document.querySelector(".compare-bar")?.remove();
      const runs = S.state.runs;
      const picked = S.picked.map((n) => runs.find((r) => r.name === n)).filter(Boolean);
      if (!picked.length) return;
      picked.sort((a, b) => (a.created || "").localeCompare(b.created || ""));
      const text = picked.length === 2 ? t("compare.bar", { a: picked[0].name, b: picked[1].name }) : t("compare.pickOne");
      main.append(h("div", { class: "compare-bar" }, h("span", { text }),
        picked.length === 2 ? h("a", { class: "btn primary sm", href: link({ view: "compare", base: picked[0].name, current: picked[1].name }) }, icon("compare"), t("action.compare")) : null,
        h("button", { class: "btn ghost icon sm", "aria-label": t("compare.clear"), onClick: () => { S.picked = []; lastRuns = ""; drawRuns(); } }, icon("x"))));
    }
    function drawRuns() {
      const key = JSON.stringify([S.state.runs, S.picked, I18N.lang, S.state.runs.length || S.state.jobs.some((j) => ACTIVE.has(j.status))]);
      if (key === lastRuns) return;
      lastRuns = key;
      body.replaceChildren(...[runsBlock()].flat());
      compareBar();
    }
    const jobCards = new Map();
    function drawJobs() {
      const jobs = S.state.jobs.filter((j) => j.kind !== "login" && (ACTIVE.has(j.status) || (j.ended && Date.now() / 1000 - j.ended < 600 && !dismissedJobs.has(j.id))));
      const seen = new Set();
      for (const job of jobs) {
        seen.add(job.id);
        if (!jobCards.has(job.id)) jobCards.set(job.id, jobCard());
        jobCards.get(job.id).update(job);
      }
      for (const [id, card] of jobCards) if (!seen.has(id)) { card.node.remove(); jobCards.delete(id); }
      jobsBox.replaceChildren(...jobs.map((j) => jobCards.get(j.id).node));
    }

    function draw() {
      if (!S.state) { main.replaceChildren(h("div", { class: "boot", text: t("app.loading") })); return; }
      main.replaceChildren(head(), setupBox, jobsBox, body);
      setup();
      drawJobs();
      lastRuns = "";
      drawRuns();
    }
    draw();
    return {
      onState() { if (!main.querySelector(".page-head")) { draw(); return; } setup(); drawJobs(); drawRuns(); },
      unmount() { document.querySelector(".compare-bar")?.remove(); },
    };
  }
  const dismissedJobs = new Set();

  async function checkReach(url) {
    const cached = S.reach.get(url);
    if (cached && Date.now() - cached.at < 15000) return cached.result;
    let result;
    try { result = await api("check?url=" + enc(url)); } catch (error) { result = { ok: false, detail: error.message }; }
    S.reach.set(url, { at: Date.now(), result });
    return result;
  }

  function jobCard() {
    const node = h("section", { class: "card job" });
    const logBox = h("pre", { class: "log" });
    const details = h("details", {}, h("summary", { text: t("job.log") }), logBox);
    let built = false;
    const parts = {};
    function build() {
      parts.icon = h("div", { class: "state-icon" });
      parts.title = h("b");
      parts.sub = h("span");
      parts.actions = h("div", { class: "actions" });
      parts.bar = h("div", { class: "bar" }, h("i"));
      parts.stats = h("div", { class: "stats" });
      node.append(h("div", { class: "top" }, parts.icon, h("div", { class: "title" }, parts.title, parts.sub), parts.actions), parts.bar, parts.stats, details);
      built = true;
    }
    function update(job) {
      if (!built) build();
      const p = job.progress || {};
      const running = job.status === "running", queued = job.status === "queued";
      const now = Date.now() / 1000;
      const elapsed = job.started ? (job.ended || now) - job.started : 0;
      parts.icon.className = `state-icon ${job.status === "done" ? "good" : job.status === "failed" ? "bad" : job.status === "cancelled" || queued ? "idle" : ""}`;
      parts.icon.replaceChildren(job.status === "done" ? icon("check") : job.status === "failed" ? icon("alert") : job.status === "cancelled" ? icon("stop") : queued ? icon("clock") : icon("spinner", "spin"));
      const kindLabel = job.kind === "recheck" ? t("job.recheck") : t("job.audit");
      parts.title.textContent = `${kindLabel}: ${job.name}`;
      let sub = "";
      if (queued) sub = t("job.waiting");
      else if (running) sub = p.route ? t("job.page", { n: fmt.n(Math.min(p.measured, p.expected || p.measured)), total: fmt.n(p.expected || p.measured), route: p.route }) : p.scope || t("job.preparing");
      else if (job.status === "done") sub = job.result && job.result.empty ? t("job.nothing") : t("job.doneSub", { counts: SEVS.map((s) => `${(job.result.counts || {})[s] || 0} ${s}`).join(" · "), took: fmt.dur(elapsed) });
      else if (job.status === "failed") sub = job.error || t("job.failed");
      else if (job.status === "cancelled") sub = t("job.cancelled");
      parts.sub.textContent = sub;
      parts.sub.title = sub;
      const actions = [];
      if (ACTIVE.has(job.status)) actions.push(h("button", { class: "btn sm", onClick: async () => { await cancelJob(job); } }, icon("stop"), t("action.cancel")));
      if (job.status === "done" && !(job.result && job.result.empty)) {
        if (job.kind === "recheck" && job.source) actions.push(h("a", { class: "btn sm", href: link({ view: "run", run: job.source }) }, t("job.backToSource")));
        actions.push(h("a", { class: "btn sm primary", href: link({ view: "run", run: job.name }) }, t("job.open"), icon("right")));
      }
      if (!ACTIVE.has(job.status)) actions.push(h("button", { class: "btn ghost icon sm", "aria-label": t("action.dismiss"), onClick: () => { dismissedJobs.add(job.id); node.remove(); } }, icon("x")));
      parts.actions.replaceChildren(...actions);
      parts.bar.hidden = !(running || queued);
      parts.bar.className = `bar${!p.fraction ? " indeterminate" : ""}`;
      parts.bar.firstChild.style.width = `${Math.round((p.fraction || 0) * 100)}%`;
      const stats = [];
      if (running || queued) {
        stats.push(t("job.elapsed", { t: fmt.clock(elapsed) }));
        if (p.fraction > 0.04 && elapsed > 20) stats.push(t("job.left", { t: fmt.dur((elapsed / p.fraction) * (1 - p.fraction)) }));
        if (p.state && p.state !== "default") stats.push(t("job.state", { state: p.state }));
        if (p.skipped) stats.push(plural(p.skipped, "job.skipped.one", "job.skipped.many"));
      }
      parts.stats.replaceChildren(...stats.map((s) => h("span", { text: s })));
      const stick = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 8;
      logBox.textContent = (job.log || []).join("\n") || t("job.noLog");
      if (stick) logBox.scrollTop = logBox.scrollHeight;
      if (job.status === "failed" && !details.dataset.opened) { details.open = true; details.dataset.opened = "1"; }
    }
    return { node, update };
  }

  async function cancelJob(job) {
    try { await api(`jobs/${job.id}/cancel`, {}); toast("info", t("toast.cancelling")); } catch (error) { toast("bad", error.message); }
    refreshState();
  }
  async function runAgain(name, anyway) {
    const run = S.state && S.state.runs.find((r) => r.name === name);
    if (!anyway && run && run.base_url) {
      const reach = await checkReach(run.base_url);
      if (!reach.ok) { toast("bad", t("toast.unreachable", { url: run.base_url }), { label: t("action.startAnyway"), run: () => runAgain(name, true) }, 0); return; }
    }
    try {
      const job = await api(`runs/${enc(name)}/again`, {});
      toast("good", t("toast.started", { name: job.name }), parseHash().view === "home" ? null : { label: t("toast.showProgress"), run: () => go({ view: "home" }) });
      askNotify();
      refreshState();
    } catch (error) { toast("bad", error.message); }
  }
  function runMenu(anchor, run, runs) {
    const older = runs.slice(runs.indexOf(run) + 1).find((r) => r.base_url === run.base_url);
    menu(anchor, [
      { icon: "right", label: t("action.open"), run: () => go({ view: "run", run: run.name }) },
      older ? { icon: "compare", label: t("runs.compareWith", { name: older.name }), run: () => go({ view: "compare", base: older.name, current: run.name }) } : null,
      { icon: "recheck", label: t("action.runAgain"), run: () => runAgain(run.name) },
      { icon: "folder", label: t("action.reveal"), run: () => reveal(run.name) },
      "sep",
      { icon: "trash", label: t("action.delete"), danger: true, run: () => deleteRun(run) },
    ]);
  }
  async function reveal(name) {
    try { await api(`runs/${enc(name)}/reveal`, {}); } catch (error) { toast("bad", error.message); }
  }
  async function deleteRun(run) {
    const ok = await confirmDialog({ title: t("delete.title", { name: run.name }), text: t("delete.text", { size: fmt.bytes(run.bytes) }), confirm: t("action.delete"), danger: true });
    if (!ok) return;
    try {
      await api(`runs/${enc(run.name)}/delete`, {});
      S.picked = S.picked.filter((n) => n !== run.name);
      forgetRun(run.name);
      toast("good", t("toast.deleted", { name: run.name }));
      await refreshState();
      if (parseHash().view !== "home") go({ view: "home" });
    } catch (error) { toast("bad", error.message); }
  }

  // ---------------------------------------------------------------- new audit

  function newAuditSheet(preset) {
    const st = S.state;
    if (!st) return;
    const saved = prefs.json("new-audit", {});
    const configs = st.configs.filter((c) => !c.error);
    const defaultConfig = (configs.find((c) => c.path === saved.config) || configs.find((c) => c.default) || configs[0] || { path: "" });
    const form = {
      config: preset?.config ?? defaultConfig.path ?? "",
      base_url: "",
      mode: preset?.mode || saved.mode || "quick",
      routes: preset?.routes || "",
      widths: preset?.widths || "",
      session: saved.session ?? null,
      locale: saved.locale ?? null,
      states: true,
      annotate: saved.annotate ?? false,
      changed_since: "",
      name: "",
    };
    const configInfo = () => configs.find((c) => c.path === form.config) || {};

    const urlInput = h("input", { type: "url", id: "na-url", placeholder: "http://localhost:3000", autocomplete: "off", spellcheck: "false", "aria-describedby": "na-url-err" });
    const fieldError = (id) => h("div", { class: "field-error", id, hidden: true, role: "alert" });
    const urlError = fieldError("na-url-err"), routesError = fieldError("na-routes-err"), widthsError = fieldError("na-widths-err");
    const urlStatus = h("span", { class: "status-dot", "aria-live": "polite" });
    const configSelect = h("select", { id: "na-config" }, configs.map((c) => h("option", { value: c.path, text: c.path })), h("option", { value: "", text: t("na.noSettings") }));
    const modeButtons = ["quick", "complete", "pages"].map((mode) => h("button", { type: "button", "aria-pressed": "false", "data-mode": mode, onClick: () => { form.mode = mode; sync(); } },
      h("b", { text: t(`na.mode.${mode}`) }), h("span", { text: t(`na.mode.${mode}.help`) })));
    const routesInput = h("textarea", { id: "na-routes", rows: "3", placeholder: t("na.routes.placeholder"), spellcheck: "false", "aria-describedby": "na-routes-err" });
    const knownRoutes = [...new Set(st.runs.flatMap((r) => r.routes || []))];
    const widthsInput = h("input", { type: "text", id: "na-widths", placeholder: t("na.widths.placeholder"), inputmode: "numeric", "aria-describedby": "na-widths-err" });
    const pagesBox = h("div", { class: "field" },
      h("label", { for: "na-routes", text: t("na.routes") }), routesInput, routesError,
      knownRoutes.length ? h("div", { class: "help" }, t("na.routesSeen"), " ", knownRoutes.slice(0, 8).map((r) => h("button", { type: "button", class: "chip", style: { margin: "2px" }, onClick: () => {
        routesInput.value = [...new Set([...routesInput.value.split(/\s+/).filter(Boolean), r])].join("\n"); form.routes = routesInput.value; sync();
      } }, r))) : null,
      h("label", { for: "na-widths", text: t("na.widths"), style: { marginTop: "6px" } }), widthsInput, widthsError, h("div", { class: "help", text: t("na.widths.help") }));
    const sessionSelect = h("select", { id: "na-session" });
    const loginBox = h("div", { class: "login-box", hidden: true });
    const localeSelect = h("select", { id: "na-locale" });
    const statesBox = h("input", { type: "checkbox", id: "na-states", checked: true });
    const annotateBox = h("input", { type: "checkbox", id: "na-annotate" });
    const changedInput = h("input", { type: "text", id: "na-changed", placeholder: t("na.changed.placeholder"), spellcheck: "false" });
    const nameInput = h("input", { type: "text", id: "na-name", spellcheck: "false" });
    const command = h("pre", { class: "cmd" });
    const estimate = h("span", { class: "hint", "aria-live": "polite" });
    let reachable = true, submitError = "";
    const start = h("button", { class: "btn primary", type: "submit" }, icon("play"), t("na.start"));

    function fillSessions(selected) {
      sessionSelect.replaceChildren(h("option", { value: "", text: t("na.notSignedIn") }),
        ...S.state.sessions.map((s) => h("option", { value: s.path, text: `${s.path} · ${t("na.savedAgo", { ago: fmt.ago(s.modified) })}` })));
      sessionSelect.value = selected || "";
    }
    function fillLocales() {
      const options = [["", t("na.locale.default")], ["de", "Deutsch (de)"], ["en", "English (en)"], ["fr", "Français (fr)"], ["es", "Español (es)"], ["it", "Italiano (it)"], ["nl", "Nederlands (nl)"], ["pl", "Polski (pl)"], ["tr", "Türkçe (tr)"], ["ja", "日本語 (ja)"]];
      localeSelect.replaceChildren(...options.map(([v, label]) => h("option", { value: v, text: label })));
    }
    fillLocales();

    function applyConfig() {
      const info = configInfo();
      urlInput.value = info.base_url || urlInput.value || "http://localhost:3000";
      const session = form.session !== null && S.state.sessions.some((s) => s.path === form.session) ? form.session
        : (S.state.sessions.find((s) => info.storage_state && (s.path === info.storage_state || s.path.endsWith(info.storage_state.replace(/^\.\//, ""))))?.path || "");
      fillSessions(session);
      localeSelect.value = form.locale !== null ? form.locale : (info.locale || "");
      if (![...localeSelect.options].some((o) => o.value === localeSelect.value)) localeSelect.append(h("option", { value: localeSelect.value, text: localeSelect.value }));
      checkUrl();
    }
    const checkUrl = debounce(async () => {
      const url = urlInput.value.trim();
      urlStatus.className = "status-dot wait"; urlStatus.textContent = t("home.checking");
      const result = await checkReach(url);
      if (url !== urlInput.value.trim()) return;
      urlStatus.className = `status-dot ${result.ok ? "ok" : "bad"}`;
      urlStatus.textContent = result.ok ? t("na.reachable") : t("na.unreachable");
      urlStatus.title = result.detail || "";
      reachable = result.ok;
      footNote();
    }, 350);
    // The footer says the one thing that matters most: why it did not start, that it will fail, or how long it takes.
    function footNote() {
      const similar = S.state.runs.find((r) => !r.targeted && r.base_url === urlInput.value.trim() && r.fast === (form.mode === "quick"));
      const [kind, text] = submitError ? ["bad", submitError] : !reachable ? ["warn", t("na.willFail")]
        : ["", form.mode === "pages" ? t("na.estimate.pages") : similar ? t("na.estimate", { took: fmt.dur(similar.seconds), name: similar.name }) : ""];
      estimate.className = `hint${kind ? " " + kind : ""}`;
      estimate.textContent = text;
    }
    // Checked here so a mistake shows next to its field instead of as a failed start.
    function validate() {
      const problems = [];
      const show = (box, input, text) => { box.hidden = !text; box.textContent = text || ""; input.setAttribute("aria-invalid", String(!!text)); if (text) problems.push(input); };
      show(urlError, urlInput, /^https?:\/\/\S+$/.test(urlInput.value.trim()) ? "" : t("na.err.url"));
      if (form.mode === "pages") {
        const routes = routesInput.value.split(/[\s,]+/).filter(Boolean);
        show(routesError, routesInput, !routes.length ? t("na.err.noRoutes") : routes.some((r) => !r.startsWith("/")) ? t("na.err.slash") : "");
        const widths = widthsInput.value.split(/[\s,]+/).filter(Boolean);
        show(widthsError, widthsInput, widths.some((w) => !/^\d{3,4}$/.test(w)) ? t("na.err.widths") : "");
      } else {
        show(routesError, routesInput, ""); show(widthsError, widthsInput, "");
      }
      return problems;
    }

    function body() {
      const routes = routesInput.value.split(/[\s,]+/).filter(Boolean);
      const out = {
        config: configSelect.value, base_url: urlInput.value.trim(), mode: form.mode,
        storage_state: sessionSelect.value, locale: localeSelect.value, states: statesBox.checked, annotate: annotateBox.checked,
      };
      if (form.mode === "pages") { out.routes = routes; out.widths = widthsInput.value.split(/[\s,]+/).filter(Boolean); }
      if (changedInput.value.trim() && form.mode !== "pages") out.changed_since = changedInput.value.trim();
      if (nameInput.value.trim()) out.name = nameInput.value.trim();
      return out;
    }
    function cli() {
      const b = body();
      const quote = (s) => (/^[\w./:@%+=,-]+$/.test(s) ? s : `'${s.replace(/'/g, "'\\''")}'`);
      const parts = ["ui-audit audit"];
      if (b.config) parts.push(`--config ${quote(b.config)}`);
      if (b.base_url && b.base_url !== configInfo().base_url) parts.push(`--base-url ${quote(b.base_url)}`);
      if (b.mode === "quick") parts.push("--fast");
      for (const r of b.routes || []) parts.push(`--route ${quote(r)}`);
      if (b.widths && b.widths.length) parts.push(`--width ${b.widths.join(",")}`);
      if (b.storage_state) parts.push(`--storage-state ${quote(b.storage_state)}`);
      if (b.locale) parts.push(`--locale ${quote(b.locale)}`);
      if (!b.states) parts.push("--no-states");
      if (!b.annotate) parts.push("--no-annotate");
      if (b.changed_since) parts.push(`--changed-since ${quote(b.changed_since)}`);
      if (b.name) parts.push(`--output ${quote(S.state.runs_dir + "/" + b.name)}`);
      return parts.join(" \\\n  ");
    }
    function sync() {
      for (const button of modeButtons) button.setAttribute("aria-pressed", String(button.dataset.mode === form.mode));
      pagesBox.hidden = form.mode !== "pages";
      changedField.hidden = form.mode === "pages";
      command.textContent = cli();
      command.append(h("button", { type: "button", class: "btn ghost icon sm", "aria-label": t("action.copy"), onClick: () => copy(cli().replace(/ \\\n {2}/g, " ")) }, icon("copy")));
      footNote();
    }

    const changedField = h("div", { class: "field" }, h("label", { for: "na-changed", text: t("na.changed") }), changedInput, h("div", { class: "help", text: t("na.changed.help") }));
    const content = h("form", { style: { display: "contents" }, onSubmit: async (event) => {
      event.preventDefault();
      submitError = "";
      const problems = validate();
      if (problems.length) { problems[0].focus(); footNote(); return; }
      start.disabled = true;
      try {
        const job = await api("runs", body());
        prefs.set("new-audit", JSON.stringify({ config: configSelect.value, mode: form.mode, session: sessionSelect.value, locale: localeSelect.value, annotate: annotateBox.checked }));
        dialog.close();
        toast("good", t("toast.started", { name: job.name }));
        askNotify();
        await refreshState();
        go({ view: "home" });
      } catch (error) {
        submitError = t("na.failed", { error: error.message });
        footNote();
        start.disabled = false;
      }
    } },
    h("header", {}, h("h2", { text: t("na.title") }), h("button", { type: "button", class: "btn ghost icon", "aria-label": t("action.close"), onClick: () => dialog.close() }, icon("x"))),
    h("div", { class: "body" },
      configs.length ? h("div", { class: "field" }, h("label", { for: "na-config", text: t("na.settings") }), configSelect, h("div", { class: "help", text: t("na.settings.help") })) : null,
      h("div", { class: "field" }, h("label", { for: "na-url", text: t("na.url") }), h("div", { class: "row" }, urlInput, urlStatus), urlError),
      h("div", { class: "field" }, h("div", { class: "lbl", id: "na-mode-label", text: t("na.mode") }), h("div", { class: "seg big", role: "group", "aria-labelledby": "na-mode-label" }, modeButtons)),
      pagesBox,
      h("div", { class: "field" }, h("label", { for: "na-session", text: t("na.session") }),
        h("div", { class: "row" }, sessionSelect, h("button", { type: "button", class: "btn", onClick: () => startLogin() }, icon("lock"), t("na.signIn"))),
        h("div", { class: "help", text: t("na.session.help") }), loginBox),
      h("div", { class: "field" }, h("label", { for: "na-locale", text: t("na.locale") }), localeSelect, h("div", { class: "help", text: t("na.locale.help") })),
      h("details", { class: "more" }, h("summary", {}, icon("right"), t("na.more")),
        h("div", {},
          h("label", { class: "check" }, statesBox, h("span", {}, h("b", { text: t("na.states") }), h("span", { text: t("na.states.help") }))),
          h("label", { class: "check" }, annotateBox, h("span", {}, h("b", { text: t("na.annotate") }), h("span", { text: t("na.annotate.help") }))),
          changedField,
          h("div", { class: "field" }, h("label", { for: "na-name", text: t("na.name") }), nameInput, h("div", { class: "help", text: t("na.name.help") })),
          h("div", { class: "field" }, h("div", { class: "lbl", text: t("na.cli") }), command)))),
    h("footer", {}, estimate, h("button", { type: "button", class: "btn", onClick: () => dialog.close() }, t("action.cancel")), start));
    const dialog = modal(content, { cls: "sheet" });

    async function startLogin() {
      const pathInput = h("input", { type: "text", value: "/", spellcheck: "false", "aria-label": t("na.login.path") });
      const go2 = h("button", { type: "button", class: "btn primary sm" }, t("na.login.open"));
      loginBox.hidden = false;
      loginBox.replaceChildren(h("div", { class: "help", text: t("na.login.intro") }), h("div", { class: "row" }, pathInput, go2));
      pathInput.focus();
      go2.addEventListener("click", async () => {
        go2.disabled = true;
        let job;
        try { job = await api("login", { config: configSelect.value, base_url: urlInput.value.trim(), path: pathInput.value.trim() || "/" }); } catch (error) { toast("bad", error.message); go2.disabled = false; return; }
        const done = h("button", { type: "button", class: "btn primary sm" }, icon("check"), t("na.login.done"));
        const stop = h("button", { type: "button", class: "btn sm" }, t("action.cancel"));
        loginBox.replaceChildren(h("div", {}, h("b", { text: t("na.login.waiting") })), h("div", { class: "help", text: t("na.login.waitingHelp") }), h("div", { class: "row" }, done, stop));
        stop.addEventListener("click", async () => { await api(`jobs/${job.id}/cancel`, {}).catch(() => null); loginBox.hidden = true; });
        done.addEventListener("click", async () => {
          done.disabled = true;
          try { await api(`jobs/${job.id}/continue`, {}); } catch (error) { toast("bad", error.message); done.disabled = false; return; }
          for (let n = 0; n < 40; n++) {
            await new Promise((r) => setTimeout(r, 500));
            const state = await api("state");
            S.state = state;
            const current = state.jobs.find((j) => j.id === job.id);
            if (current && current.status === "done") {
              fillSessions(current.result.session);
              loginBox.hidden = true;
              toast("good", t("toast.signedIn", { file: current.result.session }));
              return;
            }
            if (current && (current.status === "failed" || current.status === "cancelled")) { toast("bad", current.error || t("job.failed")); loginBox.hidden = true; return; }
          }
        });
      });
    }

    configSelect.value = form.config;
    configSelect.addEventListener("change", () => { form.config = configSelect.value; form.session = null; form.locale = null; applyConfig(); sync(); });
    const edited = () => { submitError = ""; for (const box of [urlError, routesError, widthsError]) if (!box.hidden) validate(); sync(); };
    urlInput.addEventListener("input", () => { checkUrl(); edited(); });
    for (const input of [routesInput, widthsInput, changedInput, nameInput]) input.addEventListener("input", edited);
    for (const input of [sessionSelect, localeSelect, statesBox, annotateBox]) input.addEventListener("change", sync);
    routesInput.value = form.routes;
    widthsInput.value = form.widths;
    annotateBox.checked = !!form.annotate;
    applyConfig();
    sync();
    (form.mode === "pages" ? routesInput : configs.length ? configSelect : urlInput).focus();  // not Start: Enter would launch it
  }

  let askedNotify = false;
  function askNotify() {
    if (askedNotify || !("Notification" in window) || Notification.permission !== "default") return;
    askedNotify = true;
    Notification.requestPermission().catch(() => null);
  }

  // ---------------------------------------------------------------- run view

  async function runView(route) {
    if (IS_APP && !S.state) await refreshState();
    root.replaceChildren(topbar(null), h("main", { class: "main" }, h("div", { class: "boot", text: t("app.loading") })));
    const model = await loadRun(route.run);
    const data = model.data;
    const name = IS_APP ? route.run : (data.output_dir ? data.output_dir.split("/").filter(Boolean).pop() : t("static.report"));
    baseTitle = `${name} · ui-audit`;
    document.title = baseTitle;
    const vs = viewState(route.run);

    const switcher = IS_APP ? h("button", { class: "run-switch", "aria-haspopup": "menu", "aria-expanded": "false", onClick: (e) => runSwitcher(e.currentTarget, route.run) }, h("span", { text: name }), icon("down")) : h("span", { class: "here", text: name });
    const crumbs = IS_APP ? [h("a", { href: "#/", class: "optional", text: t("nav.runs") }), icon("right", "optional"), switcher] : [h("span", { class: "optional", text: t("static.report") }), icon("right", "optional"), switcher];
    const tabsDef = [
      ["findings", t("tab.findings"), model.issues.length - model.accepted],
      ["pages", t("tab.pages"), model.audited.length],
      ["shots", t("tab.shots"), (data.captures || []).length],
      ["info", t("tab.info"), null],
    ];
    const tab = tabsDef.some(([k]) => k === route.tab) ? route.tab : "findings";
    const runActions = IS_APP ? [
      h("button", { class: "btn sm", onClick: () => runAgain(route.run) }, icon("recheck"), t("action.runAgain")),
      h("button", { class: "btn sm ghost icon", "aria-label": t("runs.actions", { name }), "aria-haspopup": "menu", "aria-expanded": "false", onClick: (e) => {
        const runs = S.state.runs, me = runs.find((r) => r.name === route.run);
        const older = me ? runs.slice(runs.indexOf(me) + 1).find((r) => r.base_url === me.base_url) : null;
        menu(e.currentTarget, [
          older ? { icon: "compare", label: t("runs.compareWith", { name: older.name }), run: () => go({ view: "compare", base: older.name, current: route.run }) } : null,
          { icon: "folder", label: t("action.reveal"), run: () => reveal(route.run) },
          "sep",
          me ? { icon: "trash", label: t("action.delete"), danger: true, run: () => deleteRun(me) } : null,
        ]);
      } }, icon("more")),
    ] : [];
    const tabs = h("nav", { class: "tabs", "aria-label": t("nav.tabs") },
      tabsDef.map(([key, label, n]) => h("a", { href: link({ view: "run", run: route.run, tab: key }), "aria-current": key === tab ? "page" : null }, label, n === null ? null : h("span", { class: "n", text: fmt.n(n) }))));
    const body = h("div", { class: "tab-body" });
    root.replaceChildren(topbar(crumbs), runHeader(model, name, runActions), runNotices(model), tabs, body);

    let page;
    if (tab === "findings") page = findingsTab(model, route, vs, body);
    else if (tab === "pages") page = pagesTab(model, route, vs, body);
    else if (tab === "shots") page = shotsTab(model, body);
    else page = infoTab(model, body);
    return {
      update(next) { if (page && page.update) page.update(next); },
      onState() { if (page && page.onState) page.onState(); },
      unmount() { if (page && page.unmount) page.unmount(); },
    };
  }

  function runSwitcher(anchor, current) {
    const runs = S.state.runs;
    menu(anchor, [
      { head: t("nav.switchRun") },
      ...runs.slice(0, 30).map((run) => ({ node: h("button", { class: "run-opt", "aria-current": String(run.name === current), onClick: () => { closeMenu(); go({ view: "run", run: run.name }); } },
        h("span", { text: run.name }), h("small", {}, `${fmt.ago(run.created)} · `, SEVS.map((s) => `${run.counts[s]} ${s}`).join(" · "))) })),
      "sep",
      { icon: "layers", label: t("nav.allRuns"), run: () => go({ view: "home" }) },
    ]);
  }

  function runHeader(model, name, actions) {
    const data = model.data;
    const meta = [];
    if (data.base_url) meta.push(h("span", {}, icon("monitor"), h("span", { class: "mono", text: data.base_url.replace(/^https?:\/\//, "") })));
    if (data.created) meta.push(h("span", { title: fmt.date(data.created) }, icon("clock"), `${fmt.date(data.created)} · ${fmt.dur((data.stats || {}).seconds)}`));
    meta.push(h("span", {}, icon("file"), plural(model.audited.length, "unit.pages.one", "unit.pages.many"), " · ", plural((data.states || []).length, "unit.states.one", "unit.states.many")));
    if (data.locale) meta.push(h("span", {}, icon("globe"), data.locale));
    if (data.config && data.config.signed_in) meta.push(h("span", {}, icon("lock"), t("tag.signedIn")));
    if (data.config && data.config.sweep === "key") meta.push(h("span", { title: t("tag.fast.title") }, t("tag.fast")));
    if ((data.only_routes || []).length) meta.push(h("span", { title: data.only_routes.join("  ") }, t("tag.targeted")));
    const doubtful = model.audited.filter((r) => r.content && r.content.state !== "ok");
    if (doubtful.length) {
      meta.push(h("button", { class: "badge warn as-btn", "aria-haspopup": "true", "aria-expanded": "false", onClick: (e) => menu(e.currentTarget, [
        { head: plural(doubtful.length, "notice.doubtful.one", "notice.doubtful.many") },
        { node: h("div", { class: "menu-note" }, h("p", { text: t("notice.doubtful.text") }), h("ul", {}, doubtful.map((r) => h("li", {}, h("code", { text: r.path }), " ",
          known(`content.${r.content.state}`, r.content.state), r.content.detail ? h("span", { class: "dim", text: ` · ${contentDetail(r.content.detail)}` }) : "")))) },
      ]) }, icon("alert"), plural(doubtful.length, "tag.doubtful.one", "tag.doubtful.many")));
    }
    return h("div", { class: "run-head" },
      h("div", { class: "title-row" }, h("h1", { text: name }), headCounts(model), h("span", { class: "spacer" }), actions && actions.length ? h("div", { class: "head-actions" }, actions) : null),
      h("div", { class: "meta" }, meta));
  }
  function headCounts(model) {
    const c = counts(model.issues);
    return h("div", { class: "head-counts" }, SEVS.map((s) => h("span", { class: `hc ${s}${c[s] ? "" : " zero"}`, title: t(`sev.${s}.long`) }, h("b", { class: "num", text: fmt.n(c[s]) }), s)));
  }

  function runNotices(model) {
    const data = model.data, notes = [];
    if (data.verify && (data.verify.fixed || data.verify.introduced)) {
      const v = data.verify;
      const baseName = (v.baseline || "").split("/").filter(Boolean).pop();
      notes.push(h("div", { class: `notice slim ${v.introduced.length ? "warn" : "good"}` }, icon("compare"), h("div", { class: "grow" },
        h("b", { text: t("notice.verify", { name: baseName || "?" }) }), " ",
        t("notice.verify.counts", { fixed: v.fixed.length, introduced: v.introduced.length, persistent: v.persistent.length })),
      IS_APP && baseName && S.state && S.state.runs.some((r) => r.name === baseName) ? h("a", { class: "btn sm", href: link({ view: "compare", base: baseName, current: model.name }) }, t("action.compare")) : null));
    }
    return h("div", { class: "run-notices", hidden: !notes.length }, notes);
  }

  // ----- findings tab

  function findingsTab(model, route, vs, body) {
    const search = h("input", { type: "search", placeholder: t("list.searchShort"), "aria-label": t("list.search"), title: t("list.search"), value: vs.text });
    const modeSeg = h("div", { class: "seg", role: "group", "aria-label": t("list.groupBy") },
      ["cause", "page"].map((mode) => h("button", { "data-mode": mode, "aria-pressed": String(vs.mode === mode), title: t(`list.by.${mode}.title`), onClick: () => {
        vs.mode = mode; prefs.set("list-mode", mode);
        const item = currentItem();
        let f = route.f;
        if (item && mode === "page" && f && f.startsWith("g:")) f = `i:${item.issues[0].id}`;
        if (item && mode === "cause" && f && f.startsWith("i:")) { const issue = model.byId.get(f.slice(2)); f = issue ? `g:${issue.group || issue.id}` : null; }
        route.f = f;
        history.replaceState(null, "", link({ view: "run", run: route.run, f }));
        drawList(); drawDetail();
        list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
      } }, t(`list.by.${mode}`))));
    const sevChips = SEVS.map((s) => h("button", { class: `chip ${s}`, "data-sev": s, "aria-pressed": String(vs.sev.has(s)), onClick: () => {
      if (vs.sev.has(s)) vs.sev.delete(s); else vs.sev.add(s);
      drawList();
    } }, h("span", { class: "sev" }, s), h("span", { class: "n" })));
    const routeSelect = h("select", { "aria-label": t("list.page") }, h("option", { value: "", text: t("list.allPages") }),
      [...new Set(model.issues.map((i) => i.route))].sort().map((r) => h("option", { value: r, text: r })));
    const checkSelect = h("select", { "aria-label": t("list.check") }, h("option", { value: "", text: t("list.allChecks") }),
      [...new Set(model.issues.map((i) => i.check))].sort().map((c) => h("option", { value: c, text: I18N.check(c) })));
    routeSelect.value = vs.route; checkSelect.value = vs.check;
    const acceptedChip = h("button", { class: "chip", "aria-pressed": String(vs.accepted), title: t("list.accepted.title"), onClick: () => { vs.accepted = !vs.accepted; drawList(); } });
    const metaLine = h("div", { class: "list-meta" });
    const placesShown = {};  // cause key -> show every place, not the first few
    const chartBox = h("div", { class: "wchart" });
    const list = h("div", { class: "list", role: "listbox", "aria-label": t("tab.findings"), tabindex: "-1" });
    const detail = h("section", { class: "detail" });
    const split = h("div", { class: "split" },
      h("div", { class: "list-pane" },
        h("div", { class: "list-tools" },
          h("div", { class: "row" }, h("label", { class: "search" }, icon("search"), search), modeSeg),
          h("div", { class: "row wrap" }, sevChips, acceptedChip),
          h("div", { class: "row selects" }, routeSelect, checkSelect),
          chartBox, metaLine),
        list,
        h("div", { class: "shortcuts" }, h("span", {}, h("span", { class: "kbd", text: "↑" }), h("span", { class: "kbd", text: "↓" }), " ", t("keys.move")),
          h("span", {}, h("span", { class: "kbd", text: "←" }), h("span", { class: "kbd", text: "→" }), " ", t("keys.widths")),
          h("span", {}, h("span", { class: "kbd", text: "/" }), " ", t("keys.search")))),
      detail);
    body.replaceChildren(split);
    const fitHeight = () => { split.style.setProperty("--split-top", `${Math.max(140, split.getBoundingClientRect().top + window.scrollY) + 24}px`); };
    fitHeight();

    let items = [];
    const matches = (i, ignoreWidth) => {
      if (!!i.accepted !== vs.accepted) return false;
      if (vs.sev.size && !vs.sev.has(i.severity)) return false;
      if (vs.route && i.route !== vs.route) return false;
      if (vs.check && i.check !== vs.check) return false;
      if (!ignoreWidth && vs.width !== null && !(lo(i) <= vs.width && vs.width <= hi(i))) return false;
      if (vs.text) {
        const hay = [i.message, messageText(i), i.selector, i.check, I18N.check(i.check), i.route, i.state, ...(i.source_candidates || []).map((c) => c.file)].join(" ").toLowerCase();
        if (!vs.text.split(/\s+/).every((word) => hay.includes(word))) return false;
      }
      return true;
    };
    function buildItems() {
      const shown = model.issues.filter((i) => matches(i, false));
      if (vs.mode === "page") {
        const byRoute = new Map();
        for (const i of shown) { if (!byRoute.has(i.route)) byRoute.set(i.route, []); byRoute.get(i.route).push(i); }
        return [...byRoute].sort((a, b) => ORDER[worst(a[1])] - ORDER[worst(b[1])] || b[1].length - a[1].length || a[0].localeCompare(b[0]))
          .map(([r, issues]) => {
            const ordered = issues.slice().sort((a, b) => RUNTIME_CHECKS.has(a.check) - RUNTIME_CHECKS.has(b.check));
            const labels = selectorLabels(ordered.map((i) => i.selector));
            return { route: r, issues, items: ordered.map((i, n) => ({ key: `i:${i.id}`, issues: [i], all: [i], severity: i.severity, check: i.check, label: labels[n] })) };
          });
      }
      const byGroup = new Map();
      for (const i of shown) { const k = i.group || i.id; if (!byGroup.has(k)) byGroup.set(k, []); byGroup.get(k).push(i); }
      const routesOf = (issues) => new Set(issues.map((i) => i.route)).size;
      const all = [...byGroup].map(([k, issues]) => ({ key: `g:${k}`, issues, all: (model.groups.get(k) || { issues }).issues, severity: worst(issues), check: issues[0].check, info: (model.groups.get(k) || {}).info }))
        .sort((a, b) => ORDER[a.severity] - ORDER[b.severity] || routesOf(b.issues) - routesOf(a.issues) || b.issues.length - a.issues.length || a.check.localeCompare(b.check));
      const runtime = all.filter((item) => RUNTIME_CHECKS.has(item.check));
      const layout = all.filter((item) => !RUNTIME_CHECKS.has(item.check));
      return [{ route: null, items: layout }, ...(runtime.length ? [{ route: null, title: t("list.runtime"), items: runtime }] : [])];
    }
    function itemNode(item) {
      const first = item.issues[0];
      const [a, b] = span(item.issues);
      const routes = [...new Set(item.issues.map((i) => i.route))];
      const source = item.info && item.info.source ? `${item.info.source.file}:${item.info.source.line}` : (first.source_candidates || [])[0] ? first.source_candidates[0].file : null;
      const selected = route.f === item.key;
      const runtime = RUNTIME_CHECKS.has(first.check);
      // the quoted text tells text findings apart; elsewhere the likely source file does
      const quoted = /^(text-spill|clipped-content)$/.test(first.check);
      const node = h("button", { class: `item ${item.severity}${first.accepted ? " accepted" : ""}`, role: "option", "aria-selected": String(selected), "data-key": item.key, id: `item-${item.key.replace(":", "-")}`,
        tabindex: "-1", onClick: () => select(item.key) },
      h("span", { class: "rail" }),
      h("span", { class: "t" }, h("span", { class: "sev", text: item.severity }), h("span", { text: I18N.check(first.check) })),
      h("span", { class: "w", text: a === undefined || runtime ? "" : fmt.range(a, b) }),
      vs.mode === "page"
        ? h("span", { class: "s" }, first.state !== "default" ? badge(stateLabel(model, first.route, first.state)) : null, runtime ? null : h("span", { class: "route", text: item.label || shortSelector(first.selector) }))
        : h("span", { class: "s" }, h("span", { class: "route", text: routes[0] }), routes.length > 1 ? badge(t("list.morePages", { n: routes.length - 1 })) : null,
          item.issues.length > routes.length ? badge(`${item.issues.length}×`) : null, first.state !== "default" && routes.length === 1 ? badge(stateLabel(model, first.route, first.state)) : null),
      vs.mode === "page" || quoted || runtime ? h("span", { class: "x", text: messageText(first) }) : h("span", { class: "x", text: source || messageText(first) }));
      return node;
    }
    function drawList() {
      const groups = buildItems();
      items = groups.flatMap((g) => g.items);
      list.replaceChildren();
      for (const group of groups) {
        if (group.route !== null) {
          const c = counts(group.issues);
          list.append(h("div", { class: "list-group" }, h("b", { text: group.route }), h("span", { text: SEVS.filter((s) => c[s]).map((s) => `${c[s]} ${s}`).join(" · ") || t("list.accepted") })));
        } else if (group.title && group.items.length) {
          list.append(h("div", { class: "list-group plain" }, h("b", { text: group.title }), h("span", { text: fmt.n(group.items.length) })));
        }
        list.append(...group.items.map(itemNode));
      }
      // one tab stop for the whole list; ↑ ↓ move inside it
      const stop = list.querySelector('.item[aria-selected="true"]') || list.querySelector(".item");
      if (stop) stop.tabIndex = 0;
      const total = model.issues.filter((i) => !!i.accepted === vs.accepted).length;
      const shown = items.reduce((n, item) => n + item.issues.length, 0);
      if (!items.length) {
        const filtered = vs.sev.size || vs.route || vs.check || vs.text || vs.width !== null;
        list.append(h("div", { class: "none" }, filtered ? t("list.noMatch") : vs.accepted ? t("list.noAccepted") : t("list.clean", { n: model.audited.length }),
          filtered ? h("div", {}, h("button", { class: "btn sm", onClick: clearFilters }, t("list.clear"))) : null));
      }
      // counts on the chips: what each severity would show with the other filters as they are
      const base = model.issues.filter((i) => !!i.accepted === vs.accepted && (!vs.route || i.route === vs.route) && (!vs.check || i.check === vs.check));
      sevChips.forEach((chip, n) => { chip.setAttribute("aria-pressed", String(vs.sev.has(SEVS[n]))); chip.querySelector(".n").textContent = fmt.n(base.filter((i) => i.severity === SEVS[n]).length); });
      acceptedChip.hidden = !model.accepted;
      acceptedChip.setAttribute("aria-pressed", String(vs.accepted));
      acceptedChip.textContent = t("list.acceptedChip", { n: model.accepted });
      const causeCount = vs.mode === "cause" ? items.length : new Set(items.map((i) => i.issues[0].group || i.issues[0].id)).size;
      metaLine.replaceChildren(h("span", { class: "grow" }, shown === total ? plural(total, "list.findings.one", "list.findings.many") : t("list.findingsOf", { n: fmt.n(shown), total: fmt.n(total) }),
        causeCount < shown ? ` · ${plural(causeCount, "unit.causes.one", "unit.causes.many")}` : ""),
      vs.width !== null ? h("button", { class: "chip clear", onClick: () => { vs.width = null; drawList(); } }, t("list.atWidth", { w: vs.width }), icon("x")) : h("span", { class: "cap", text: t("chart.title") }));
      drawChart();
    }
    const filtered = () => !!(vs.sev.size || vs.route || vs.check || vs.text || vs.width !== null);
    function clearFilters() {
      vs.sev.clear(); vs.route = ""; vs.check = ""; vs.text = ""; vs.width = null;
      search.value = ""; routeSelect.value = ""; checkSelect.value = "";
      drawList(); drawDetail();
    }
    const chartKeys = { w: null };  // where the keyboard cursor sits, kept across redraws
    function drawChart() {
      const pool = model.issues.filter((i) => matches(i, true) && i.widths && i.widths.length && !RUNTIME_CHECKS.has(i.check));
      const item = currentItem();
      const focused = chartBox.contains(document.activeElement);
      const chart = widthChart(model, pool, vs.width, item ? span(item.issues) : null, (w) => { vs.width = w === null || vs.width === w ? null : w; drawList(); }, chartKeys);
      chartBox.replaceChildren(chart);
      if (focused) chart.focusAt(chartKeys.w);
    }
    function currentItem() {
      if (!route.f) return null;
      const found = items.find((i) => i.key === route.f);
      if (found) return found;
      const [kind, id] = [route.f.slice(0, 1), route.f.slice(2)];
      if (kind === "g" && model.groups.has(id)) { const g = model.groups.get(id); return { key: route.f, issues: g.issues, all: g.issues, severity: worst(g.issues), check: g.issues[0].check, info: g.info }; }
      if (kind === "i" && model.byId.has(id)) { const i = model.byId.get(id); return { key: route.f, issues: [i], all: [i], severity: i.severity, check: i.check }; }
      return null;
    }
    function select(key, focusList) {
      route.f = key;
      history.replaceState(null, "", link({ view: "run", run: route.run, f: key }));
      for (const node of list.querySelectorAll(".item")) { node.setAttribute("aria-selected", String(node.dataset.key === key)); node.tabIndex = node.dataset.key === key ? 0 : -1; }
      const node = list.querySelector(`[data-key="${CSS.escape(key)}"]`);
      if (node) { node.scrollIntoView({ block: "nearest" }); if (focusList) node.focus({ preventScroll: true }); }
      drawDetail();
      drawChart();
      if (window.matchMedia("(max-width: 860px)").matches) window.scrollTo({ top: split.offsetTop - 70 });
    }
    function step(by) {
      if (!items.length) return;
      const at = items.findIndex((i) => i.key === route.f);
      const next = items[Math.max(0, Math.min(items.length - 1, at < 0 ? 0 : at + by))];
      select(next.key, true);
    }
    function drawDetail() {
      const item = currentItem();
      split.classList.toggle("has-detail", !!item);
      if (!item) {
        if (items.length) detail.replaceChildren(emptyState("layers", t("detail.pick.title"), t("detail.pick.text")));
        else if (filtered()) detail.replaceChildren(emptyState("search", t("detail.noMatch.title"), t("detail.noMatch.text"), h("button", { class: "btn", onClick: clearFilters }, t("list.clear"))));
        else if (vs.accepted) detail.replaceChildren(emptyState("checkCircle", t("detail.noAccepted.title"), t("detail.noAccepted.text")));
        else {
          const doubtful = model.audited.filter((r) => r.content && r.content.state !== "ok").length;
          detail.replaceChildren(emptyState("checkCircle", t("detail.clean.title"), plural(model.audited.length, "detail.clean.one", "detail.clean.many"),
            doubtful ? h("p", { class: "warn-text" }, icon("alert"), plural(doubtful, "detail.clean.doubtful.one", "detail.clean.doubtful.many")) : null));
        }
        return;
      }
      detail.replaceChildren(findingDetail(model, item, vs, {
        hidden: !items.some((i) => i.key === item.key),
        clear: clearFilters,
        placesShown,
        back: () => { route.f = null; history.replaceState(null, "", link({ view: "run", run: route.run })); split.classList.remove("has-detail"); drawList(); },
        changed: async (nextKey) => { await reloadModel(nextKey); },
        redraw: () => drawDetail(),
      }));
      detail.scrollTop = 0;
    }
    async function reloadModel(nextKey) {
      if (nextKey === "next") {  // the current one leaves the list: move on to its neighbour
        const at = items.findIndex((i) => i.key === route.f);
        const neighbour = at < 0 ? null : items[at + 1] || items[at - 1];
        nextKey = neighbour ? neighbour.key : null;
      }
      forgetRun(route.run);
      if (IS_APP) await refreshState();
      const fresh = await loadRun(route.run);
      Object.assign(model, fresh);
      route.f = nextKey === undefined ? route.f : nextKey;
      history.replaceState(null, "", link({ view: "run", run: route.run, f: route.f }));
      drawList(); drawDetail();
      root.querySelector(".run-head .head-counts")?.replaceWith(headCounts(model));
    }

    const searchNow = () => { vs.text = search.value.trim().toLowerCase(); drawList(); };
    search.addEventListener("input", debounce(searchNow, 120));
    search.addEventListener("search", searchNow);
    search.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      if (search.value || vs.text) { search.value = ""; searchNow(); } else search.blur();
    });
    routeSelect.addEventListener("change", () => { vs.route = routeSelect.value; drawList(); });
    checkSelect.addEventListener("change", () => { vs.check = checkSelect.value; drawList(); });
    const onKey = (event) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || document.querySelector("dialog[open]")) return;
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
      if (event.key === "/" && !typing) { event.preventDefault(); search.focus(); search.select(); return; }
      if (typing) { if (event.key === "Escape") document.activeElement.blur(); return; }
      if (event.key === "ArrowDown" || event.key === "j") { event.preventDefault(); step(1); }
      else if (event.key === "ArrowUp" || event.key === "k") { event.preventDefault(); step(-1); }
      else if (event.key === "ArrowRight" || event.key === "ArrowLeft") { const pick = detail.querySelector(".widths"); if (pick) { event.preventDefault(); pick.dispatchEvent(new CustomEvent("step", { detail: event.key === "ArrowRight" ? 1 : -1 })); } }
      else if (event.key === "Escape" && route.f) { route.f = null; history.replaceState(null, "", link({ view: "run", run: route.run })); drawList(); drawDetail(); }
    };
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", fitHeight);

    drawList();
    if (!route.f && items.length && !window.matchMedia("(max-width: 860px)").matches) route.f = items[0].key, history.replaceState(null, "", link({ view: "run", run: route.run, f: route.f }));
    drawList();
    drawDetail();
    const selected = list.querySelector('[aria-selected="true"]');
    if (selected) selected.scrollIntoView({ block: "nearest" });
    return {
      update(next) { if (next.f !== route.f) { route.f = next.f; drawList(); drawDetail(); } },
      onState() { const box = detail.querySelector("[data-recheck]"); if (box) box.dispatchEvent(new CustomEvent("refresh")); },
      unmount() { document.removeEventListener("keydown", onKey); window.removeEventListener("resize", fitHeight); },
    };
  }

  function shortSelector(selector) {
    const tail = (selector || "").split(" > ").pop();
    return tail.length > 80 ? tail.slice(0, 77) + "…" : tail;
  }
  // The last part of each selector, with more of the path wherever two would read the same.
  function selectorLabels(selectors) {
    const parts = selectors.map((sel) => (sel || "").split(" > "));
    const labels = parts.map((p) => p[p.length - 1]);
    for (let depth = 2; depth <= 5; depth++) {
      const seen = new Map();
      for (const label of labels) seen.set(label, (seen.get(label) || 0) + 1);
      let longer = false;
      labels.forEach((label, n) => { if (seen.get(label) > 1 && parts[n].length >= depth) { labels[n] = parts[n].slice(-depth).join(" > "); longer = true; } });
      if (!longer) break;
    }
    return labels.map((label) => (label.length > 80 ? "…" + label.slice(-79) : label));
  }

  // The width chart: how many findings sit at each width, stacked by severity.
  // Keyboard: ← → jump to the next width where the findings change, Shift moves 10 px,
  // Home / End go to the ends, Enter filters the list to that width, Esc clears the filter.
  function widthChart(model, issues, picked, band, onPick, keys = { w: null }) {
    const { LO, HI } = model;
    const N = 160;
    const step = (HI - LO) / N;
    const buckets = Array.from({ length: N }, () => ({ P1: 0, P2: 0, P3: 0 }));
    for (const i of issues) {
      const a = Math.max(LO, lo(i)), b = Math.min(HI, hi(i));
      for (let n = Math.max(0, Math.floor((a - LO) / step)); n < N && LO + n * step <= b; n++) {
        const center = LO + (n + 0.5) * step;
        if ((center >= a && center <= b) || (b - a < step && n === Math.floor((a - LO) / step))) buckets[n][i.severity] += 1;
      }
    }
    const max = Math.max(1, ...buckets.map((b) => b.P1 + b.P2 + b.P3));
    const pct = (w) => ((Math.min(HI, Math.max(LO, w)) - LO) / (HI - LO)) * 100;
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    const HT = 32;
    svg.setAttribute("viewBox", `0 0 ${N} ${HT}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");
    svg.style.height = `${HT}px`;
    const layer = (cls, d, extra) => { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); p.setAttribute("class", cls); for (const [k, v] of Object.entries(extra || {})) p.setAttribute(k, v); svg.append(p); };
    if (band && band[0] !== undefined) {
      const x0 = (pct(band[0]) / 100) * N, x1 = Math.max(x0 + 0.6, (pct(band[1]) / 100) * N);
      layer("sel", `M${x0} 0H${x1}V${HT}H${x0}Z`);
    }
    const y = (v) => HT - (v / max) * (HT - 3);
    for (const s of SEVS) {
      let d = "";
      buckets.forEach((b, n) => {
        const below = SEVS.slice(0, SEVS.indexOf(s)).reduce((sum, k) => sum + b[k], 0);
        if (!b[s]) return;
        d += `M${n} ${y(below + b[s])}H${n + 1}V${y(below)}H${n}Z`;
      });
      if (d) layer("", d, { fill: `var(--${s.toLowerCase()})` });
    }
    layer("base", `M0 ${HT}H${N}`, { "vector-effect": "non-scaling-stroke" });
    const hint = h("span", { class: "sr-only", id: `wchart-keys-${++widthChart.n}`, text: t("chart.keys") });
    const wrap = h("div", { class: "slider", style: { position: "relative" }, tabindex: "0", role: "slider", "aria-label": t("chart.aria", { n: issues.length }),
      "aria-describedby": hint.id, "aria-valuemin": String(LO), "aria-valuemax": String(HI) }, svg, hint);
    const axis = h("div", { style: { position: "relative", height: "18px" } });
    const labels = new Map([[LO, ""], [HI, ""]]);
    for (const w of [390, 768, 1366]) if (w > LO && w < HI) labels.set(w, "");
    let last = -100;
    for (const w of [...new Set([...model.breakpoints.filter((b) => b > LO && b < HI)])]) axis.append(h("span", { style: { position: "absolute", left: `${pct(w)}%`, top: "0", width: "1px", height: "5px", background: "var(--accent)" }, title: t("chart.breakpoint", { w }) }));
    for (const w of [...labels.keys()].sort((a, b) => a - b)) {
      const p = pct(w);
      if (w !== LO && w !== HI && (p - last < 13 || 100 - p < 10)) continue;
      axis.append(h("span", { class: "axis", style: { position: "absolute", left: `${p}%`, top: "4px", transform: w === LO ? "none" : w === HI ? "translateX(-100%)" : "translateX(-50%)", font: "10.5px var(--mono)", color: "var(--text-3)" }, text: w }));
      last = p;
    }
    const cursor = h("div", { style: { position: "absolute", top: "0", bottom: "0", width: "1.5px", background: "var(--text)", pointerEvents: "none", display: "none" } });
    const pin = picked !== null ? h("div", { style: { position: "absolute", top: "-2px", bottom: "0", left: `${pct(picked)}%`, width: "2px", marginLeft: "-1px", background: "var(--accent)", pointerEvents: "none" } }) : null;
    const tip = h("div", { class: "tip", hidden: true });
    wrap.append(cursor, tip);
    if (pin) wrap.append(pin);
    const widthAt = (event) => {
      const box = svg.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
      return Math.round(LO + ratio * (HI - LO));
    };
    const findingsAt = (w) => issues.filter((i) => lo(i) <= w && w <= hi(i));
    const valueText = (w) => {
      const c = counts(findingsAt(w).map((i) => ({ ...i, accepted: false })));
      return [`${w} px`, plural(findingsAt(w).length, "list.findings.one", "list.findings.many"), ...SEVS.filter((s) => c[s]).map((s) => `${c[s]} ${s}`)].join(", ");
    };
    const showAt = (w) => {
      const box = svg.getBoundingClientRect();
      const x = (pct(w) / 100) * box.width;
      const c = counts(findingsAt(w).map((i) => ({ ...i, accepted: false })));
      cursor.style.display = "block";
      cursor.style.left = `${x}px`;
      tip.hidden = false;
      tip.replaceChildren(h("b", { text: `${w} px` }), h("div", { style: { color: "var(--text-3)" }, text: plural(findingsAt(w).length, "list.findings.one", "list.findings.many") }),
        ...SEVS.filter((s) => c[s]).map((s) => h("div", { class: `row ${s}` }, h("i"), `${c[s]} ${s}`)));
      const left = x + 12 + tip.offsetWidth > box.width ? x - tip.offsetWidth - 12 : x + 12;
      tip.style.left = `${Math.max(0, left)}px`;
      tip.style.top = "-6px";
    };
    const hide = () => { cursor.style.display = "none"; tip.hidden = true; };
    // a width without findings would only empty the list
    const pick = (w) => onPick(findingsAt(w).length ? w : null);
    svg.addEventListener("pointermove", (event) => showAt(widthAt(event)));
    svg.addEventListener("pointerleave", () => { if (document.activeElement === wrap) showAt(keys.w); else hide(); });
    svg.addEventListener("click", (event) => { keys.w = widthAt(event); pick(keys.w); });

    // the widths where the set of findings changes: the stops for ← →
    const setAt = (w) => findingsAt(w).map((i) => i.id).join(" ");
    const stops = [...new Set([LO, ...issues.flatMap((i) => [lo(i), hi(i) + 1])])]
      .filter((w) => w >= LO && w <= HI).sort((a, b) => a - b)
      .filter((w, n, all) => n === 0 || setAt(w) !== setAt(all[n - 1]));
    if (stops[stops.length - 1] !== HI) stops.push(HI);
    const clamp = (w) => Math.min(HI, Math.max(LO, Math.round(w)));
    const start = () => clamp(picked ?? (band && band[0] !== undefined ? band[0] : stops.find((w) => findingsAt(w).length) ?? LO));
    const moveTo = (w) => {
      keys.w = clamp(w);
      wrap.setAttribute("aria-valuenow", String(keys.w));
      wrap.setAttribute("aria-valuetext", valueText(keys.w));
      showAt(keys.w);
    };
    wrap.addEventListener("focus", () => moveTo(keys.w ?? start()));
    wrap.addEventListener("blur", hide);
    wrap.addEventListener("keydown", (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const w = keys.w ?? start();
      let next = null;
      if (event.key === "ArrowRight" || event.key === "ArrowUp") next = event.shiftKey ? w + 10 : stops.find((s) => s > w) ?? HI;
      else if (event.key === "ArrowLeft" || event.key === "ArrowDown") next = event.shiftKey ? w - 10 : [...stops].reverse().find((s) => s < w) ?? LO;
      else if (event.key === "PageUp") next = w + 100;
      else if (event.key === "PageDown") next = w - 100;
      else if (event.key === "Home") next = LO;
      else if (event.key === "End") next = HI;
      else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); pick(w); return; }
      else if (event.key === "Escape" && picked !== null) { event.preventDefault(); event.stopPropagation(); onPick(null); return; }
      if (next === null) return;
      event.preventDefault();
      moveTo(next);
    });
    wrap.setAttribute("aria-valuenow", String(keys.w ?? start()));
    wrap.setAttribute("aria-valuetext", valueText(keys.w ?? start()));
    const node = h("div", {}, wrap, axis);
    node.focusAt = (w) => { wrap.focus({ preventScroll: true }); if (w !== null) moveTo(w); };
    return node;
  }
  widthChart.n = 0;

  // ----- one finding (or one cause with all its places)

  function findingDetail(model, item, vs, hooks) {
    const all = item.issues;
    const activeId = vs.occ[item.key] && all.some((i) => i.id === vs.occ[item.key]) ? vs.occ[item.key] : all[0].id;
    const issue = all.find((i) => i.id === activeId) || all[0];
    const first = all[0];
    const runtime = RUNTIME_CHECKS.has(issue.check);
    const agent = issue.origin === "agent";
    const groupId = item.key.startsWith("g:") ? item.key.slice(2) : null;
    const ids = all.map((i) => i.id);
    const node = h("div", { class: "detail-inner" });
    const pageCount = new Set(all.map((i) => i.route)).size;

    const headline = h("div", { class: "headline" }, sev(item.severity, true),
      agent ? badge(t("detail.agent"), "accent", "spark", t("detail.agent.title")) : null,
      first.accepted ? badge(t("detail.acceptedBadge"), "good", "check") : null,
      onlyIn(model, issue) ? badge(t("detail.onlyIn", { browsers: onlyIn(model, issue).map(browserName).join(", ") }), "accent", "info", t("detail.onlyIn.title")) : null,
      pageCount > 1 ? badge(plural(pageCount, "detail.onPages.one", "detail.onPages.many"), "accent", "layers") : all.length > 1 ? badge(t("detail.places", { n: all.length }), "accent", "layers") : null);
    node.append(h("button", { class: "btn sm ghost back", onClick: hooks.back }, icon("left"), t("detail.back")));
    if (hooks.hidden) {
      node.append(h("div", { class: "notice slim" }, icon("info"), h("div", { class: "grow", text: t("detail.hidden") }),
        h("button", { class: "btn sm", onClick: hooks.clear }, t("list.clear"))));
    }
    node.append(h("div", {}, headline, h("h2", { text: I18N.check(issue.check) }), h("p", { class: "msg", text: messageText(issue) })));

    // actions
    const actions = h("div", { class: "actions" });
    let recheckButton = null;
    actions.append(h("button", { class: "btn primary", onClick: () => copy(fixPrompt(model, item, issue), t("toast.promptCopied")), title: t("detail.prompt.title") }, icon("spark"), t("detail.prompt")));
    if (IS_APP) {
      recheckButton = h("button", { class: "btn", onClick: () => startRecheck(model, item), title: t("detail.recheck.title") }, icon("recheck"), t("detail.recheck"));
      actions.append(recheckButton);
      if (first.accepted) actions.append(h("button", { class: "btn", onClick: () => unaccept(model, item, hooks) }, icon("undo"), t("detail.unaccept")));
      else actions.append(h("button", { class: "btn", "aria-expanded": String(vs.accepting === item.key), onClick: () => { vs.accepting = vs.accepting === item.key ? null : item.key; hooks.redraw(); } }, icon("checkCircle"), t("detail.accept")));
    } else {
      actions.append(h("button", { class: "btn", onClick: () => copy(recheckCommand(model, all), t("toast.commandCopied")) }, icon("recheck"), t("detail.copyRecheck")));
      if (!first.accepted) actions.append(h("button", { class: "btn", onClick: () => copy(`ui-audit accept ${runDir(model)} ${groupId || issue.id} --reason "why this is fine"`, t("toast.commandCopied")) }, icon("checkCircle"), t("detail.copyAccept")));
    }
    node.append(actions);
    if (IS_APP && vs.accepting === item.key && !first.accepted) node.append(acceptForm(model, item, groupId || issue.id, vs, hooks));
    if (IS_APP) node.append(recheckBox(model, ids, recheckButton));

    // the screenshot first: it shows the problem
    if (runtime) {
      node.append(h("div", {}, h("p", { class: "label", text: t("detail.error") }), h("div", { class: "copyable" }, h("code", { text: issue.message }),
        h("button", { class: "btn ghost icon sm", "aria-label": t("action.copy"), onClick: () => copy(issue.message) }, icon("copy")))));
    } else {
      node.append(screenshotBlock(model, issue, vs, item));
    }

    // where it is
    const facts = h("dl", { class: "facts" });
    const fact = (label, ...value) => facts.append(h("dt", { text: label }), h("dd", {}, value));
    const pageUrl = model.data.base_url ? model.data.base_url.replace(/\/$/, "") + issue.route : null;
    fact(t("detail.page"), h("span", { class: "mono", text: issue.route }), pageUrl && !/[[\]]/.test(issue.route) ? [" ", h("a", { href: pageUrl, target: "_blank", rel: "noopener", title: pageUrl, "aria-label": t("detail.openPage") }, icon("external"))] : null);
    fact(t("detail.state"), stateLabel(model, issue.route, issue.state),
      (issue.also_in_states || []).length ? h("div", { class: "muted", text: t("detail.alsoIn", { states: issue.also_in_states.map((s) => stateLabel(model, issue.route, s)).join(", ") }) }) : null);
    if (!runtime) fact(t("detail.widths"), fmt.range(lo(issue), hi(issue)), issue.widths && issue.widths.length > 1 ? h("span", { class: "muted", text: ` · ${plural(issue.widths.length, "detail.measuredAt.one", "detail.measuredAt.many")}` }) : null);
    const candidates = issue.source_candidates || [];
    if (candidates.length) {
      fact(t("detail.source"), h("div", { class: "src-list" }, candidates.map((c) => h("div", {}, editorLink(model, c), c.reasons && c.reasons.length ? h("div", { class: "why", text: c.reasons.map(sourceReason).join(", ") }) : null)),
        h("div", { class: "why", text: t("detail.source.note") })));
    }
    if (!runtime && issue.selector && !agent) fact(t("detail.element"), h("div", { class: "copyable" }, h("code", { text: issue.selector }), h("button", { class: "btn ghost icon sm", "aria-label": t("action.copy"), onClick: () => copy(issue.selector, t("toast.selectorCopied")) }, icon("copy"))));
    if (first.accepted) fact(t("detail.accepted"), `${first.accepted.reason || "–"}${first.accepted.date ? ` · ${first.accepted.date}` : ""}`);
    node.append(facts);

    // places, when one cause shows up in several: the first few, the rest on request
    if (all.length > 1) {
      const FEW = 5;
      const open = hooks.placesShown[item.key] || all.findIndex((i) => i.id === issue.id) >= FEW;
      const shown = open ? all.slice(0, 40) : all.slice(0, FEW);
      const labels = selectorLabels(all.map((i) => i.selector));
      const sameSpot = all.length > new Set(all.map((x) => x.route + "|" + x.state)).size;
      node.append(h("div", {}, h("p", { class: "label", text: t("detail.places", { n: all.length }) }),
        h("div", { class: "occ" }, shown.map((i) => h("button", { "aria-pressed": String(i.id === issue.id), onClick: () => { vs.occ[item.key] = i.id; hooks.redraw(); } },
          h("span", { class: "where" }, h("span", { class: "route", text: i.route + (i.state !== "default" ? ` · ${stateLabel(model, i.route, i.state)}` : "") }),
            pageCount === 1 || sameSpot ? h("span", { class: "sel", text: labels[all.indexOf(i)] }) : null),
          h("span", { class: "w", text: RUNTIME_CHECKS.has(i.check) ? "" : fmt.range(lo(i), hi(i)) })))),
        !open && all.length > FEW ? h("button", { class: "btn sm ghost more-places", onClick: () => { hooks.placesShown[item.key] = true; hooks.redraw(); } }, icon("down"), t("detail.allPlaces", { n: all.length })) : null,
        open && all.length > 40 ? h("p", { class: "muted", text: t("detail.morePlaces", { n: all.length - 40 }) }) : null));
    }

    node.append(h("div", { class: "tipbox" }, h("b", { text: t("detail.howToFix") }), " ", I18N.tip(issue.check)));
    return node;
  }

  function screenshotBlock(model, issue, vs, item) {
    const caps = capturesFor(model, issue);
    const box = h("div", {});
    if (!caps.length) {
      box.append(h("p", { class: "label", text: t("detail.screenshot") }), h("div", { class: "stage-wrap" }, h("div", { class: "stage-empty", text: t("detail.noShots") })));
      return box;
    }
    const chosen = vs.shot[issue.id];
    let capture = caps.find((c) => c.file === chosen) || bestCapture(model, issue);
    const tools = h("div", { class: "shot-tools" });
    const widths = h("div", { class: "widths", role: "group", "aria-label": t("detail.screenshotWidths") });
    const wrapEl = h("div", { class: "stage-wrap" });
    const note = h("p", { class: "stage-note" });
    const fitBtn = h("button", { class: "btn sm", "aria-pressed": String(!vs.fit), title: t("detail.actual.title") });
    const zoomBtn = h("button", { class: "btn sm", title: t("detail.zoom.title"), hidden: true }, icon("search"), t("detail.zoom"));
    const othersBtn = h("button", { class: "btn sm" });
    const bigBtn = h("button", { class: "btn sm icon", "aria-label": t("detail.fullscreen"), title: t("detail.fullscreen") }, icon("expand"));
    tools.append(widths, othersBtn, zoomBtn, fitBtn, bigBtn);
    box.append(h("p", { class: "label", text: t("detail.screenshot") }), tools, note, wrapEl);

    const inRange = (c) => lo(issue) !== undefined && c.width >= lo(issue) && c.width <= hi(issue);
    function show() {
      vs.shot[issue.id] = capture.file;
      widths.replaceChildren(...caps.map((c) => h("button", { class: `${inRange(c) ? "hit " : ""}${issue.severity}`, "aria-pressed": String(c === capture), title: inRange(c) ? t("detail.widthHit") : t("detail.widthMiss"),
        onClick: () => { capture = c; show(); } }, shotLabel(model, c))));
      widths.querySelector('[aria-pressed="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
      const focus = new Set([issue.id]);
      const boxes = boxesAt(model, capture, focus).filter((b) => !b.other || vs.others);
      const others = boxesAt(model, capture, focus).filter((b) => b.other).length;
      othersBtn.hidden = !others;
      othersBtn.textContent = vs.others ? t("detail.hideOthers") : t("detail.showOthers", { n: others });
      fitBtn.textContent = vs.fit ? t("detail.actual") : t("detail.fit");
      const img = h("img", { src: fileUrl(model, capture.file), alt: t("detail.shotAlt", { route: issue.route, w: capture.width }), decoding: "async" });
      const stage = h("div", { class: `stage${vs.fit ? "" : " actual"}` }, img);
      wrapEl.replaceChildren(stage);
      zoomBtn.hidden = true;
      fitBtn.hidden = false;
      let zoomed = false;
      // zoom into the marked element once the image's real size is known, before the boxes are placed
      const zoom = () => {
        const W = img.naturalWidth, H = img.naturalHeight;
        const crop = zoomCrop(boxes.filter((b) => !b.other).map((b) => b.rect), W, H, wrapEl.clientWidth);
        zoomBtn.hidden = !crop;
        zoomBtn.setAttribute("aria-pressed", String(!!crop && vs.zoom));
        if (!crop || !vs.zoom) return;
        zoomed = true;
        fitBtn.hidden = true;
        stage.className = "stage";
        // at most twice the real size, so small elements don't turn into a blur
        const frame = h("div", { class: "crop", style: { aspectRatio: `${crop.width} / ${crop.height}`, maxWidth: `${Math.round(crop.width * 2)}px` } });
        stage.style.width = `${(W / crop.width) * 100}%`;
        stage.style.transform = `translate(${(-crop.x / W) * 100}%, ${(-crop.y / H) * 100}%)`;
        wrapEl.replaceChildren(frame);
        frame.append(stage);
      };
      if (img.complete && img.naturalWidth) zoom(); else img.addEventListener("load", zoom, { once: true });
      wrapEl.classList.add("loading-img");
      img.addEventListener("load", () => wrapEl.classList.remove("loading-img"), { once: true });
      img.addEventListener("error", () => {
        wrapEl.classList.remove("loading-img");
        wrapEl.replaceChildren(h("div", { class: "stage-empty" }, icon("image"), h("div", { text: t("detail.shotMissing", { file: capture.file }) })));
        note.textContent = ""; note.className = "stage-note";
      }, { once: true });
      drawBoxes(stage, img, boxes, (rect, W) => {
        if (!rect || zoomed) return;
        const scale = img.clientWidth / W;
        // near the top, so the box shows even when the frame runs past the bottom of the window
        wrapEl.scrollTop = Math.max(0, rect.y * scale - Math.min(96, wrapEl.clientHeight * 0.3));
        if (!vs.fit) wrapEl.scrollLeft = Math.max(0, rect.x * scale - wrapEl.clientWidth * 0.3);
      });
      const hasBox = boxes.some((b) => !b.other);
      const outside = !hasBox && issue.origin !== "agent" && !inRange(capture);
      note.className = `stage-note${outside ? " out" : ""}`;
      note.replaceChildren(outside ? icon("info") : "", hasBox ? t("detail.boxNote", { w: capture.width, reasons: reasonText(capture.reasons) })
        : issue.origin === "agent" ? t("detail.agentNoBox") : inRange(capture) ? t("detail.noBoxHere", { w: capture.width }) : t("detail.outside", { w: capture.width, range: fmt.range(lo(issue), hi(issue)) }));
      bigBtn.onclick = () => lightbox(caps.map((c) => ({ src: fileUrl(model, c.file), caption: `${issue.route} · ${stateLabel(model, issue.route, issue.state)} · ${shotLabel(model, c, "px")}`,
        boxes: boxesAt(model, c, focus).filter((b) => !b.other || vs.others) })), caps.indexOf(capture));
    }
    fitBtn.addEventListener("click", () => { vs.fit = !vs.fit; fitBtn.setAttribute("aria-pressed", String(!vs.fit)); show(); });
    othersBtn.addEventListener("click", () => { vs.others = !vs.others; show(); });
    zoomBtn.addEventListener("click", () => { vs.zoom = !vs.zoom; show(); zoomBtn.focus(); });
    widths.addEventListener("step", (event) => {
      const at = caps.indexOf(capture);
      const ahead = event.detail > 0 ? caps.slice(at + 1) : caps.slice(0, at).reverse();
      const next = ahead.find(inRange) || ahead[0];  // the widths where it occurs first
      if (next) { capture = next; show(); }
    });
    show();
    return box;
  }
  function sourceReason(reason) {
    const m = /^(class|component|defines) (.*)$/.exec(reason);
    if (m) return t(`src.why.${m[1]}`, { name: m[2] });
    return known(`src.why.${reason.replace(/\s+/g, "-")}`, reason);
  }
  function reasonText(reasons) {
    return (reasons || []).map((r) => known(`reason.${r}`, r)).join(", ");
  }

  function acceptForm(model, item, id, vs, hooks) {
    const reason = h("textarea", { rows: "2", placeholder: t("accept.placeholder"), "aria-label": t("accept.reason") });
    const many = item.all && item.all.length > 1;
    const submit = h("button", { class: "btn primary sm", type: "submit" }, icon("check"), many ? t("accept.allN", { n: item.all.length }) : t("accept.one"));
    const form = h("form", { class: "accept-form", onSubmit: async (event) => {
      event.preventDefault();
      if (!reason.value.trim()) { reason.focus(); return; }
      submit.disabled = true;
      try {
        await api(`runs/${enc(model.name)}/accept`, { ids: [id], reason: reason.value.trim() });
        vs.accepting = null;
        toast("good", t("toast.accepted"), { label: t("action.undo"), run: () => unaccept(model, item, hooks) });
        await hooks.changed("next");
      } catch (error) { toast("bad", error.message); submit.disabled = false; }
    } }, h("div", { class: "help", text: t("accept.help") }), reason,
    h("div", { class: "row" }, h("button", { type: "button", class: "btn sm", onClick: () => { vs.accepting = null; hooks.redraw(); } }, t("action.cancel")), submit));
    setTimeout(() => reason.focus(), 0);
    return form;
  }
  async function unaccept(model, item, hooks) {
    try {
      await api(`runs/${enc(model.name)}/unaccept`, { ids: item.all.map((i) => i.id) });
      toast("good", t("toast.unaccepted"));
      await hooks.changed();
    } catch (error) { toast("bad", error.message); }
  }

  async function startRecheck(model, item) {
    try {
      await api(`runs/${enc(model.name)}/recheck`, { ids: item.all.map((i) => i.id) });
      askNotify();
      await refreshState();
    } catch (error) { toast("bad", error.message); }
  }
  function recheckBox(model, ids, button) {
    const box = h("div", { "data-recheck": "1" });
    const wanted = new Set(ids);
    function draw() {
      const jobs = (S.state && S.state.jobs || []).filter((j) => j.kind === "recheck" && j.source === model.name && j.issue_ids.some((id) => wanted.has(id)));
      const job = jobs[0];
      if (button) button.disabled = !!(job && ACTIVE.has(job.status));
      box.replaceChildren();
      if (!job || job.status === "cancelled") return;
      const p = job.progress || {};
      if (ACTIVE.has(job.status)) {
        box.append(h("div", { class: "recheck-box" }, h("div", { class: "state-icon" }, icon("spinner", "spin")),
          h("div", { class: "grow" }, h("b", { text: job.status === "queued" ? t("recheck.queued") : t("recheck.running") }),
            h("div", { class: "bar", style: { marginTop: "8px" } }, h("i", { style: { width: `${Math.round((p.fraction || 0.05) * 100)}%` } }))),
          h("button", { class: "btn sm", onClick: () => cancelJob(job) }, t("action.cancel"))));
        return;
      }
      if (job.status === "failed") {
        box.append(h("div", { class: "recheck-box bad" }, icon("alert"), h("div", { class: "grow" }, h("b", { text: t("recheck.failed") }), h("div", { class: "muted", text: job.error || "" })),
          h("a", { class: "btn sm", href: "#/" }, t("recheck.log"))));
        return;
      }
      const outcome = (job.result && job.result.recheck && job.result.recheck.issues) || {};
      const mine = ids.map((id) => outcome[id]).filter(Boolean);
      const fixed = mine.filter((o) => o === "fixed").length, still = mine.filter((o) => o === "persistent").length;
      const good = still === 0 && fixed > 0;
      const text = good ? (fixed === ids.length ? t("recheck.fixed") : t("recheck.fixedSome", { n: fixed, total: ids.length }))
        : still ? t("recheck.still", { n: still, total: ids.length }) : t("recheck.unclear");
      box.append(h("div", { class: `recheck-box ${good ? "good" : still ? "bad" : ""}` }, icon(good ? "checkCircle" : still ? "alert" : "info"),
        h("div", { class: "grow" }, h("b", { text }), h("div", { class: "muted", text: `${fmt.ago(job.ended * 1000)} · ${job.name}` })),
        h("a", { class: "btn sm", href: link({ view: "run", run: job.name }) }, t("recheck.open"))));
    }
    box.addEventListener("refresh", draw);
    draw();
    return box;
  }

  function recheckWidths(issues, low, high, limit = 14) {
    const edges = new Set(), middles = new Set();
    for (const issue of issues) {
      const seen = (issue.widths || []).slice().sort((a, b) => a - b);
      if (!seen.length) continue;
      for (const w of [seen[0], seen[seen.length - 1], seen[0] - 1, seen[seen.length - 1] + 1]) edges.add(w);
      middles.add(seen[Math.floor(seen.length / 2)]);
    }
    const inRange = (w) => w >= low && w <= high;
    const widths = [...new Set([...edges, ...middles])].filter(inRange).sort((a, b) => a - b);
    if (widths.length <= limit) return widths;
    let kept = [...edges].filter(inRange).sort((a, b) => a - b);
    if (kept.length > limit) { const step = kept.length / limit; kept = Array.from({ length: limit }, (_, n) => kept[Math.floor(n * step)]); }
    return kept;
  }
  function recheckCommand(model, issues) {
    const dir = runDir(model).replace(/\/$/, "");
    const out = `${dir}-recheck`;
    const quote = (v) => (/^[\w./:@%+=,-]+$/.test(v) ? v : `'${v.replace(/'/g, "'\\''")}'`);
    const routes = [...new Set(issues.map((i) => i.route))].map((r) => `--route ${quote(r)}`).join(" ");
    const widths = recheckWidths(issues, model.LO, model.HI).join(",");
    const states = issues.every((i) => i.state === "default") ? " --no-states" : "";
    return `ui-audit audit --like ${quote(dir)} ${routes} --width ${widths}${states} --output ${quote(out)}\nui-audit verify ${quote(dir)} ${quote(out)}`;
  }
  function fixPrompt(model, item, issue) {
    const all = item.all || item.issues;
    const lines = [`Fix this UI defect that ui-audit measured in the running app at ${model.data.base_url || "the app"}.`, ""];
    lines.push(`Problem: ${I18N.check(issue.check, "en")} (${issue.check}), severity ${issue.severity}.`);
    lines.push(`Measured: ${issue.message}`);
    if (all.length === 1) {
      lines.push(`Page: ${issue.route}${issue.state !== "default" ? ` (state: ${stateLabel(model, issue.route, issue.state)})` : ""}`);
      lines.push(`Widths: ${fmt.range(lo(issue), hi(issue))}`);
      if (!RUNTIME_CHECKS.has(issue.check)) lines.push(`Element: ${issue.selector}`);
    } else {
      lines.push(`It shows up ${all.length} times, probably from one cause:`);
      for (const i of all.slice(0, 12)) lines.push(`- ${i.route}${i.state !== "default" ? ` (${stateLabel(model, i.route, i.state)})` : ""} at ${fmt.range(lo(i), hi(i))}: ${i.selector}`);
      if (all.length > 12) lines.push(`- and ${all.length - 12} more`);
    }
    const sources = issue.source_candidates || [];
    if (sources.length) lines.push(`Likely source (search hints, confirm before editing): ${sources.map((c) => (c.line ? `${c.file}:${c.line}` : c.file)).join(", ")}`);
    const capture = bestCapture(model, issue);
    if (capture && !RUNTIME_CHECKS.has(issue.check)) lines.push(`Screenshot: ${absPath(model, capture.file)}`);
    lines.push("", `Hint: ${I18N.tip(issue.check, "en")}`, "", "When the fix is in, prove it with a targeted rerun and compare:", recheckCommand(model, all));
    return lines.join("\n");
  }

  // ----- pages tab

  function pagesTab(model, route, vs, body) {
    const data = model.data;
    const head = () => h("thead", {}, h("tr", {}, [t("pages.page"), t("pages.result"), t("pages.findings"), t("pages.states"), t("pages.foundBy")].map((label) => h("th", { text: label }))));
    const row = (r) => {
      const ok = model.audited.includes(r);
      const issues = model.issues.filter((i) => i.route === r.path);
      const states = (data.states || []).filter((s) => s.route === r.path && s.id !== "default");
      const names = states.map((s) => stateLabel(model, r.path, s.id));
      let result;
      if (!ok) result = r.loaded === false ? badge(t("pages.notLoaded"), "bad") : h("span", { class: "dim", text: t("pages.skipped", { why: skipText((r.status || "").replace(/^skipped: /, "")) }) });
      else if (r.content && r.content.state !== "ok") result = badge(known(`content.${r.content.state}`, r.content.state), "warn", "alert", contentDetail(r.content.detail || ""));
      else result = badge(t("pages.measured"), "good", "check");
      return h("tr", {},
        h("td", {}, ok && issues.length ? h("a", { class: "path", href: link({ view: "run", run: route.run }), onClick: (e) => { e.preventDefault(); vs.route = r.path; vs.mode = "page"; go({ view: "run", run: route.run }); } }, r.path) : h("span", { class: "path", text: r.path })),
        h("td", {}, result),
        h("td", {}, ok ? countChips(counts(issues)) : h("span", { class: "dim", text: "–" })),
        h("td", { class: "states", title: names.join("\n") }, ok ? (names.length ? `${names.length} · ${names.slice(0, 3).join(", ")}${names.length > 3 ? " …" : ""}` : h("span", { class: "dim", text: t("pages.noStates") })) : ""),
        h("td", { class: "dim nowrap", text: (r.discovered_by || []).map((d) => known(`found.${d}`, d)).join(", ") }));
    };
    // measured pages first, worst first; the skipped ones fold away
    const measured = model.routes.filter((r) => model.audited.includes(r) || r.loaded === false);
    const score = (r) => { const c = counts(model.issues.filter((i) => i.route === r.path)); return [c.P1, c.P2, c.P3]; };
    measured.sort((a, b) => { const x = score(a), y = score(b); return y[0] - x[0] || y[1] - x[1] || y[2] - x[2] || a.path.localeCompare(b.path); });
    const skipped = model.routes.filter((r) => !measured.includes(r));
    const parts = [h("div", { class: "card table-card" }, h("table", { class: "table" }, head(), h("tbody", {}, measured.map(row))))];
    if (skipped.length) {
      parts.push(h("details", { class: "card skipped" }, h("summary", {}, icon("right"), plural(skipped.length, "pages.skippedN.one", "pages.skippedN.many"), h("span", { class: "muted", text: t("pages.skippedWhy") })),
        h("div", { class: "table-wrap" }, h("table", { class: "table" }, head(), h("tbody", {}, skipped.map(row))))));
    }
    const note = (count, one, many, text, list) => h("div", { class: "notice" }, icon("info"), h("div", { class: "grow" }, h("b", { text: plural(count, one, many) }), " ", text,
      h("div", { class: "mono route-list", text: list.join("   ") })));
    if ((data.truncated_routes || []).length) parts.push(note(data.truncated_routes.length, "pages.truncated.one", "pages.truncated.many", t("pages.truncated.text"), data.truncated_routes));
    if ((data.skipped_dynamic_routes || []).length) parts.push(note(data.skipped_dynamic_routes.length, "pages.dynamic.one", "pages.dynamic.many", t("pages.dynamic.text"), data.skipped_dynamic_routes));
    body.replaceChildren(h("div", { class: "pages-tab" }, parts));
    return {};
  }

  // ----- screenshots tab

  function shotsTab(model, body) {
    const filter = h("input", { type: "search", placeholder: t("shots.filter"), "aria-label": t("shots.filter") });
    const onlyIssues = h("input", { type: "checkbox" });
    const gallery = h("div", { class: "gallery" });
    const keys = [...model.captures.keys()];
    function draw() {
      const q = filter.value.trim().toLowerCase();
      gallery.replaceChildren();
      let shown = 0;
      for (const key of keys) {
        const [r, s] = key.split("|");
        if (q && !`${r} ${stateLabel(model, r, s)}`.toLowerCase().includes(q)) continue;
        let caps = model.captures.get(key);
        const issuesAt = (c) => model.issues.filter((i) => !i.accepted && i.route === c.route && i.state === c.state && (i.widths || []).includes(c.width)
          && (i.browsers || ["chromium"]).includes(c.browser || "chromium"));
        if (onlyIssues.checked) caps = caps.filter((c) => issuesAt(c).length);
        if (!caps.length) continue;
        shown += caps.length;
        const items = caps.map((c) => ({ src: fileUrl(model, c.file), caption: `${r} · ${stateLabel(model, r, s)} · ${shotLabel(model, c, "px")}`, boxes: boxesAt(model, c, null) }));
        gallery.append(h("section", { class: "card" }, h("h3", {}, r, h("span", { text: `${stateLabel(model, r, s)} · ${plural(caps.length, "unit.shots.one", "unit.shots.many")}` })),
          h("div", { class: "thumbs" }, caps.map((c, n) => {
            const found = issuesAt(c);
            return h("button", { class: `thumb ${found.length ? worst(found) : ""}`, "aria-label": t("shots.open", { w: c.width }), onClick: () => lightbox(items, n) },
              h("img", { src: fileUrl(model, c.file), loading: "lazy", alt: "", decoding: "async", onError: missingImage }), h("b", { text: shotLabel(model, c) }), found.length ? h("i", { text: found.length }) : null);
          }))));
      }
      if (!shown) gallery.append(h("div", { class: "card" }, emptyState("image", t("shots.none"), "")));
    }
    filter.addEventListener("input", debounce(draw, 120));
    onlyIssues.addEventListener("change", draw);
    body.replaceChildren(h("div", { class: "gallery-tools" }, h("label", { class: "search" }, icon("search"), filter),
      h("label", { class: "check" }, onlyIssues, h("span", {}, h("b", { text: t("shots.onlyIssues") })))), gallery);
    draw();
    return {};
  }

  // ----- run details tab

  function infoTab(model, body) {
    const data = model.data, stats = data.stats || {}, vp = (data.config && data.config.viewports) || {};
    const kv = (rows) => h("dl", { class: "kv" }, rows.filter(Boolean).flatMap(([k, v]) => [h("dt", { text: k }), h("dd", {}, v)]));
    const folder = runDir(model);
    const cards = [
      h("div", { class: "card" }, h("h3", { text: t("info.run") }), kv([
        [t("info.app"), h("span", { class: "mono", text: data.base_url || "–" })],
        [t("info.when"), fmt.date(data.created)],
        [t("info.took"), fmt.dur(stats.seconds)],
        [t("info.version"), `ui-audit ${data.version || "?"}`],
        [t("info.language"), data.locale || t("info.browserDefault")],
        [t("info.browsers"), model.browsers.map(browserName).join(", ")],
        [t("info.signedIn"), data.config && data.config.signed_in ? t("info.yes") : t("info.no")],
        data.consent_dismissed ? [t("info.consent"), `“${data.consent_dismissed}”`] : null,
        [t("info.folder"), h("div", { class: "copyable" }, h("code", { text: folder }), h("button", { class: "btn ghost icon sm", "aria-label": t("action.copy"), onClick: () => copy(folder, t("toast.pathCopied")) }, icon("copy")))],
      ]), IS_APP ? h("div", { class: "actions", style: { marginTop: "14px" } }, h("button", { class: "btn sm", onClick: () => reveal(model.name) }, icon("folder"), t("action.reveal"))) : null),
      h("div", { class: "card" }, h("h3", { text: t("info.coverage") }), kv([
        [t("info.pages"), `${fmt.n(model.audited.length)}${model.routes.length > model.audited.length ? ` · ${t("info.skippedN", { n: model.routes.length - model.audited.length })}` : ""}`],
        [t("info.states"), fmt.n((data.states || []).length)],
        [t("info.probes"), fmt.n(stats.probes)],
        [t("info.shots"), `${fmt.n((data.captures || []).length)} · ${fmt.bytes(stats.screenshot_bytes)}`],
        [t("info.range"), `${vp.min_width || 320}–${vp.max_width || 1920} px · ${vp.widths && vp.widths.length ? t("info.only", { w: vp.widths.join(", ") })
          : data.config && data.config.sweep === "key" ? t("info.keyWidths") : t("info.step", { n: vp.sweep_step || 80 })}`],
        [t("info.mode"), data.config && data.config.sweep === "key" ? t("tag.fast.title") : t("info.full")],
        [t("info.breakpoints"), (data.breakpoints || []).length ? data.breakpoints.join(", ") : "–"],
      ])),
    ];
    if ((data.errors || []).length) cards.push(h("div", { class: "card" }, h("h3", { text: t("info.errors", { n: data.errors.length }) }), h("ul", { class: "plain-list" }, data.errors.map((e) => h("li", { text: e })))));
    body.replaceChildren(h("div", { class: "info-grid" }, cards));
    return {};
  }

  // ---------------------------------------------------------------- compare

  async function compareView(route) {
    if (!S.state) await refreshState();
    const runs = S.state.runs;
    let current = route.current || (runs[0] && runs[0].name) || "";
    let base = route.base;
    if (!base && current) {
      const me = runs.find((r) => r.name === current);
      const older = me ? runs.slice(runs.indexOf(me) + 1).find((r) => r.base_url === me.base_url) : null;
      base = older ? older.name : "";
    }
    baseTitle = `${t("compare.title")} · ui-audit`;
    document.title = baseTitle;
    const main = h("main", { class: "main" });
    root.replaceChildren(topbar([h("a", { href: "#/", text: t("nav.runs") }), icon("right"), h("span", { class: "here", text: t("compare.title") })]), main);
    const option = (r) => h("option", { value: r.name, text: `${r.name} · ${fmt.ago(r.created)}` });
    const baseSelect = h("select", { id: "cmp-base" }, runs.map(option));
    const currentSelect = h("select", { id: "cmp-current" }, runs.map(option));
    baseSelect.value = base; currentSelect.value = current;
    const change = () => go({ view: "compare", base: baseSelect.value, current: currentSelect.value });
    baseSelect.addEventListener("change", change);
    currentSelect.addEventListener("change", change);
    const head = h("div", { class: "page-head" }, h("div", {}, h("h1", { text: t("compare.title") }), h("p", { text: t("compare.lead") })),
      h("div", { class: "compare-head" }, h("label", { for: "cmp-base" }, t("compare.before"), baseSelect),
        h("button", { class: "btn icon", "aria-label": t("compare.swap"), title: t("compare.swap"), onClick: () => go({ view: "compare", base: currentSelect.value, current: baseSelect.value }) }, icon("compare")),
        h("label", { for: "cmp-current" }, t("compare.after"), currentSelect)));
    main.append(head);
    if (!base || !current || base === current) {
      main.append(h("div", { class: "card" }, emptyState("compare", t("compare.pick.title"), t("compare.pick.text"))));
      return {};
    }
    const loading = h("div", { class: "boot", text: t("app.loading") });
    main.append(loading);
    const [result, before, after] = await Promise.all([api("compare", { baseline: base, current }), loadRun(base), loadRun(current)]);
    loading.remove();
    const sections = [
      ["introduced", t("compare.new"), "bad", "alert"],
      ["persistent", t("compare.still"), "warn", "clock"],
      ["fixed", t("compare.fixed"), "good", "checkCircle"],
      ["needs_review", t("compare.review"), "", "spark"],
    ];
    let showing = new Set(["introduced", "persistent", "fixed", "needs_review"]);
    const tiles = h("div", { class: "compare-tiles" });
    const list = h("div");
    function drawTiles() {
      tiles.replaceChildren(...sections.filter(([k]) => k !== "needs_review" || result.needs_review.length).map(([key, label, kind, ic]) => h("button", { class: `ctile ${kind}`, "aria-pressed": String(showing.size === 1 && showing.has(key)),
        onClick: () => { showing = showing.size === 1 && showing.has(key) ? new Set(sections.map((s) => s[0])) : new Set([key]); drawTiles(); drawList(); } },
      h("div", { class: "k" }, icon(ic), label), h("div", { class: "v num", text: fmt.n(result[key].length) }))),
      h("div", { class: "ctile static", title: t("compare.outTitle") }, h("div", { class: "k" }, icon("info"), t("compare.out")), h("div", { class: "v num", text: fmt.n(result.out_of_scope) }), h("div", { class: "sub", text: t("compare.outShort") })));
    }
    function thumb(model, issue, label) {
      const capture = issue.widths && issue.widths.length ? nearestCapture(model, issue.route, issue.state, Math.round((lo(issue) + hi(issue)) / 2)) : null;
      if (!capture) return h("figure", {}, h("div", { class: "none", text: t("compare.noShot") }), h("figcaption", { text: label }));
      const own = model.byId.get(issue.id);
      const items = [{ src: fileUrl(model, capture.file), caption: `${label} · ${issue.route} · ${capture.width}px`, boxes: own ? boxesAt(model, capture, new Set([own.id])).filter((b) => !b.other) : [] }];
      return h("figure", {}, h("button", { class: `thumb ${issue.severity}`, "aria-label": `${label} ${capture.width}px`, onClick: () => lightbox(items, 0) },
        h("img", { src: items[0].src, loading: "lazy", alt: "", onError: missingImage }), h("b", { text: capture.width })), h("figcaption", { text: label }));
    }
    function drawList() {
      list.replaceChildren();
      for (const [key, label] of sections) {
        if (!showing.has(key) || !result[key].length) continue;
        list.append(h("div", { class: "section-title" }, label, h("span", { class: "muted", text: fmt.n(result[key].length) })));
        list.append(h("div", { class: "diffs" }, result[key].slice(0, 150).map((issue) => {
          const runName = key === "fixed" ? base : current;
          return h("div", { class: "card diff" },
            h("div", {}, h("div", { class: "t" }, sev(issue.severity), I18N.check(issue.check), RUNTIME_CHECKS.has(issue.check) ? null : h("span", { class: "muted", style: { fontWeight: "400" }, text: fmt.range(lo(issue), hi(issue)) })),
              h("div", { class: "s", title: issue.message }, h("a", { class: "mono", href: link({ view: "run", run: runName, f: `i:${issue.id}` }), text: issue.route }),
                issue.state !== "default" ? ` · ${stateLabel(key === "fixed" ? before : after, issue.route, issue.state)}` : "", " — ", messageText(issue)),
              RUNTIME_CHECKS.has(issue.check) ? null : h("code", { text: issue.selector, title: issue.selector })),
            RUNTIME_CHECKS.has(issue.check) ? null : h("div", { class: "pair" }, thumb(before, issue, t("compare.beforeShort")), thumb(after, issue, t("compare.afterShort"))));
        })));
        if (result[key].length > 150) list.append(h("p", { class: "muted", text: t("compare.more", { n: result[key].length - 150 }) }));
      }
      if (!list.children.length) list.append(h("div", { class: "card" }, emptyState("checkCircle", t("compare.same.title"), t("compare.same.text"))));
    }
    drawTiles();
    drawList();
    main.append(tiles, h("p", { class: "muted", style: { fontSize: "13px", margin: "0 0 6px" }, text: `${t("compare.tilesFilter")} ${t("compare.rule")}` }), list);
    return {};
  }

  // ---------------------------------------------------------------- polling

  let pollTimer = null;
  async function refreshState() {
    if (!IS_APP) return;
    try {
      const state = await api("state");
      const first = !S.state;
      S.state = state;
      S.stateError = null;
      noticeFinishedJobs(state.jobs, first);
      updateJobPill();
      if (S.page && S.page.onState) S.page.onState();
    } catch (error) {
      if (!S.stateError) toast("bad", t("error.server"), null, 0);
      S.stateError = error;
    }
  }
  function noticeFinishedJobs(jobs, first) {
    for (const job of jobs) {
      const before = S.knownJobs.get(job.id);
      S.knownJobs.set(job.id, job.status);
      if (first || !before || !ACTIVE.has(before) || ACTIVE.has(job.status) || job.kind === "login") continue;
      if (job.status === "done") {
        const empty = job.result && job.result.empty;
        const c = (job.result && job.result.counts) || {};
        const text = job.kind === "recheck" ? recheckText(job) : empty ? t("job.nothing") : t("toast.finished", { name: job.name, counts: SEVS.map((s) => `${c[s] || 0} ${s}`).join(" · ") });
        const kind = job.kind === "recheck" ? recheckKind(job) : "good";
        // on the home page the job's own card already says it
        if (parseHash().view !== "home" || job.kind === "recheck") toast(kind, text, empty ? null : { label: t("job.open"), run: () => go({ view: "run", run: job.name }) }, 9000);
        notify(text);
        if (job.source) forgetRun(job.source);
      } else if (job.status === "failed") {
        toast("bad", t("toast.failed", { name: job.name, error: job.error || "" }), { label: t("toast.showLog"), run: () => go({ view: "home" }) }, 0);
        notify(t("toast.failed", { name: job.name, error: "" }));
      }
    }
  }
  function recheckKind(job) {
    const values = Object.values((job.result && job.result.recheck && job.result.recheck.issues) || {});
    return values.includes("persistent") ? "bad" : values.includes("fixed") ? "good" : "info";
  }
  function recheckText(job) {
    const outcome = (job.result && job.result.recheck && job.result.recheck.issues) || {};
    const values = Object.values(outcome);
    const fixed = values.filter((v) => v === "fixed").length, still = values.filter((v) => v === "persistent").length;
    return still ? t("recheck.still", { n: still, total: values.length }) : fixed ? t("recheck.fixedToast", { n: fixed }) : t("recheck.unclear");
  }
  function notify(text) {
    if (!document.hidden || !("Notification" in window) || Notification.permission !== "granted") return;
    try { new Notification("ui-audit", { body: text }); } catch (_) { /* some browsers only allow it from a service worker */ }
  }
  function schedule() {
    clearTimeout(pollTimer);
    const busy = S.state && S.state.jobs.some((j) => ACTIVE.has(j.status));
    pollTimer = setTimeout(async () => { await refreshState(); schedule(); }, busy ? 1000 : document.hidden ? 20000 : 6000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && IS_APP) { refreshState().then(schedule); } });

  // ---------------------------------------------------------------- start

  async function start() {
    if (!IS_APP && !DATA) {
      root.replaceChildren(h("main", { class: "main" }, h("div", { class: "card" }, emptyState("alert", t("error.title"), t("error.noData")))));
      return;
    }
    if (IS_APP) {
      await refreshState();
      schedule();
    }
    await render();
  }
  start();
})();
