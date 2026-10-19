/* Routing, the top bar and rendering the current view. */

// ---------------------------------------------------------------- routing

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map((p) => { try { return decodeURIComponent(p); } catch (_) { return p; } });
  const params = new URLSearchParams(query);
  const f = params.get("f");
  const found = FILTER_KEYS.filter((key) => params.has(key));
  const filters = found.length ? Object.fromEntries(found.map((key) => [key, params.get(key)])) : null;
  if (!IS_APP) return { view: "run", run: "", tab: parts[0] || "findings", f, filters };
  if (parts[0] === "run" && parts[1]) return { view: "run", run: parts[1], tab: parts[2] || "findings", f, filters };
  if (parts[0] === "compare") return { view: "compare", base: parts[1] || "", current: parts[2] || "" };
  return { view: "home" };
}
function link(route) {
  if (route.view === "run") {
    const params = new URLSearchParams(route.f ? { f: route.f } : {});
    for (const [key, value] of Object.entries(route.filters || {})) params.set(key, value);
    const query = params.toString() ? `?${params}` : "";
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
    "sep",
    { head: t("settings.keyboard") },
    { label: t("settings.singleKeys"), toggle: true, checked: singleKeys(), run: pick("single-keys", singleKeys() ? "off" : "on", rerender) },
  ]);
}
// j, k and / act without a modifier; speech input can trigger them by accident (WCAG 2.1.4), so they can be turned off
function singleKeys() { return prefs.get("single-keys", "on") !== "off"; }
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
      emptyState("alert", t("error.title"), errorText(error), IS_APP ? h("a", { class: "btn", href: "#/" }, t("nav.allRuns")) : null))));
  }
  root.removeAttribute("aria-busy");
  updateJobPill();
}
