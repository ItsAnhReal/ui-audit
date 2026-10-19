/* The findings tab: filters, the list and the width chart. */

// ----- findings tab

function findingsTab(model, route, vs, body) {
  if (route.filters) Object.assign(vs, readFilters(route.filters));  // a shared link sets the filters
  // the URL carries the selection and the filters, so a filtered view can be shared or bookmarked
  const syncUrl = () => history.replaceState(null, "", link({ view: "run", run: route.run, f: route.f, filters: filterQuery(vs) }));
  const search = h("input", { type: "search", placeholder: t("list.searchShort"), "aria-label": t("list.search"), title: t("list.search"), value: vs.text });
  const modeSeg = h("div", { class: "seg", role: "group", "aria-label": t("list.groupBy") },
    ["cause", "page"].map((mode) => h("button", { "data-mode": mode, "aria-pressed": String(vs.mode === mode), title: t(`list.by.${mode}.title`), onClick: () => {
      vs.mode = mode; prefs.set("list-mode", mode);
      const item = currentItem();
      let f = route.f;
      if (item && mode === "page" && f && f.startsWith("g:")) f = `i:${item.issues[0].id}`;
      if (item && mode === "cause" && f && f.startsWith("i:")) { const issue = model.byId.get(f.slice(2)); f = issue ? `g:${issue.group || issue.id}` : null; }
      route.f = f;
      syncUrl();
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
        h("div", { class: "row" }, h("label", { class: "search" }, icon("search"), search), modeSeg,
          h("button", { class: "btn ghost icon sm", "aria-label": t("list.actions"), title: t("list.actions"), "aria-haspopup": "menu", "aria-expanded": "false",
            onClick: (e) => listMenu(e.currentTarget) }, icon("more"))),
        h("div", { class: "row wrap" }, sevChips, acceptedChip),
        h("div", { class: "row selects" }, routeSelect, checkSelect),
        chartBox, metaLine),
      list,
      h("div", { class: "shortcuts" }, h("span", {}, h("span", { class: "kbd", text: "↑" }), h("span", { class: "kbd", text: "↓" }), " ", t("keys.move")),
        h("span", {}, h("span", { class: "kbd", text: "←" }), h("span", { class: "kbd", text: "→" }), " ", t("keys.widths")),
        singleKeys() ? h("span", {}, h("span", { class: "kbd", text: "/" }), " ", t("keys.search")) : null)),
    detail);
  body.replaceChildren(split);
  const fitHeight = () => { split.style.setProperty("--split-top", `${Math.max(140, split.getBoundingClientRect().top + window.scrollY) + 24}px`); };
  fitHeight();

  let items = [];
  // What to do with every finding the filters show: copy, export, accept.
  function listMenu(anchor) {
    const shown = items.flatMap((item) => item.issues);
    const none = !shown.length;
    const file = `ui-audit-${(model.name || (model.data.output_dir || "").split("/").filter(Boolean).pop() || "report").replace(/[^\w.-]+/g, "-")}`;
    menu(anchor, [
      { head: plural(shown.length, "list.findings.one", "list.findings.many") },
      { icon: "spark", label: t("list.copyPrompts"), disabled: none,
        run: () => copy(items.map((item) => fixPrompt(model, item, item.issues[0])).join("\n\n---\n\n"), plural(items.length, "toast.promptsCopied.one", "toast.promptsCopied.many")) },
      { icon: "file", label: t("list.exportCsv"), disabled: none, run: () => download(`${file}.csv`, findingsCsv(shown), "text/csv") },
      { icon: "file", label: t("list.exportMarkdown"), disabled: none, run: () => download(`${file}.md`, findingsMarkdown(model, shown), "text/markdown") },
      { icon: "copy", label: t("list.copyLink"), run: () => copy(location.href, t("toast.linkCopied")) },
      vs.accepted || none ? null : "sep",
      vs.accepted || none ? null : IS_APP
        ? { icon: "checkCircle", label: plural(shown.length, "list.acceptAll.one", "list.acceptAll.many"), run: () => bulkAccept(model, shown, () => reloadModel(null)) }
        : model.data.accept_command ? { icon: "checkCircle", label: plural(shown.length, "list.copyAcceptAll.one", "list.copyAcceptAll.many"), run: () => copy(acceptCommand(model, shown.map((i) => i.id).join(" ")), t("toast.commandCopied")) } : null,
    ]);
  }
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
    syncUrl();
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
    syncUrl();
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
      back: () => { route.f = null; syncUrl(); split.classList.remove("has-detail"); drawList(); },
      position: { at: items.findIndex((i) => i.key === item.key), total: items.length },
      step: (by) => {
        step(by);
        // the same button again; at the end of the list the other one
        const [prev, next] = [".detail-nav .prev", ".detail-nav .next"].map((sel) => detail.querySelector(sel));
        const order = by < 0 ? [prev, next] : [next, prev];
        (order.find((button) => button && !button.disabled) || detail.querySelector(".detail-nav .back"))?.focus({ preventScroll: true });
      },
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
    syncUrl();
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
    const letters = singleKeys();
    if (event.key === "/" && !typing && letters) { event.preventDefault(); search.focus(); search.select(); return; }
    if (typing) { if (event.key === "Escape") document.activeElement.blur(); return; }
    if (event.key === "ArrowDown" || (letters && event.key === "j")) { event.preventDefault(); step(1); }
    else if (event.key === "ArrowUp" || (letters && event.key === "k")) { event.preventDefault(); step(-1); }
    else if (event.key === "ArrowRight" || event.key === "ArrowLeft") { const pick = detail.querySelector(".widths"); if (pick) { event.preventDefault(); pick.dispatchEvent(new CustomEvent("step", { detail: event.key === "ArrowRight" ? 1 : -1 })); } }
    else if (event.key === "Escape" && route.f) { route.f = null; syncUrl(); drawList(); drawDetail(); }
  };
  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", fitHeight);

  drawList();
  if (!route.f && items.length && !window.matchMedia("(max-width: 860px)").matches) route.f = items[0].key;
  drawList();
  drawDetail();
  const selected = list.querySelector('[aria-selected="true"]');
  if (selected) selected.scrollIntoView({ block: "nearest" });
  return {
    update(next) {
      // filters typed into the address bar: draw the tab again with them
      if (next.filters && JSON.stringify(next.filters) !== JSON.stringify(filterQuery(vs))) { render(true); return; }
      if (next.f !== route.f) { route.f = next.f; drawList(); drawDetail(); }
    },
    onState() { const box = detail.querySelector("[data-recheck]"); if (box) box.dispatchEvent(new CustomEvent("refresh")); },
    unmount() { document.removeEventListener("keydown", onKey); window.removeEventListener("resize", fitHeight); },
  };
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
