/* One run: its header and the pages, screenshots and details tabs. */

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
