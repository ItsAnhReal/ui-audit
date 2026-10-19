/* Two runs side by side. */

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
