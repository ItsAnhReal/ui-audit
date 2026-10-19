/* The home view: the run list and the running jobs. */

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
