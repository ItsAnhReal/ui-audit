/* One finding (or one cause) in detail: screenshot, facts, accept and re-check. */

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
  // on a phone the list is hidden behind the detail: back to it, or on to the previous or next finding
  const { at, total } = hooks.position || { at: -1, total: 0 };
  node.append(h("div", { class: "detail-nav" }, h("button", { class: "btn sm ghost back", onClick: hooks.back }, icon("left"), t("detail.back")),
    at >= 0 && total > 1 ? [
      h("span", { class: "pos", text: t("detail.position", { n: fmt.n(at + 1), total: fmt.n(total) }) }),
      h("button", { class: "btn sm icon prev", "aria-label": t("detail.prev"), title: t("detail.prev"), disabled: at === 0, onClick: () => hooks.step(-1) }, icon("left")),
      h("button", { class: "btn sm icon next", "aria-label": t("detail.next"), title: t("detail.next"), disabled: at === total - 1, onClick: () => hooks.step(1) }, icon("right")),
    ] : null));
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
    const recheck = recheckCommand(model, all);
    if (recheck) actions.append(h("button", { class: "btn", onClick: () => copy(recheck, t("toast.commandCopied")) }, icon("recheck"), t("detail.copyRecheck")));
    if (!first.accepted && model.data.accept_command) actions.append(h("button", { class: "btn", onClick: () => copy(acceptCommand(model, groupId || issue.id), t("toast.commandCopied")) }, icon("checkCircle"), t("detail.copyAccept")));
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
  const pageUrl = /^https?:\/\//i.test(model.data.base_url || "") ? model.data.base_url.replace(/\/$/, "") + issue.route : null;  // never javascript: from a report
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
    } catch (error) { toast("bad", errorText(error)); submit.disabled = false; }
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
  } catch (error) { toast("bad", errorText(error)); }
}

// Accept every finding a filtered list shows, with one reason. The server takes 500 ids a call.
async function sendIds(model, action, ids, extra) {
  for (let n = 0; n < ids.length; n += 500) await api(`runs/${enc(model.name)}/${action}`, { ids: ids.slice(n, n + 500), ...extra });
}
function bulkAccept(model, issues, changed) {
  const ids = issues.map((i) => i.id);
  const reason = h("textarea", { rows: "3", placeholder: t("accept.placeholder"), "aria-label": t("accept.reason") });
  const submit = h("button", { class: "btn primary", type: "submit" }, icon("check"), plural(ids.length, "accept.bulk.one", "accept.bulk.many"));
  const form = h("form", { style: { display: "contents" }, onSubmit: async (event) => {
    event.preventDefault();
    if (!reason.value.trim()) { reason.focus(); return; }
    submit.disabled = true;
    try {
      await sendIds(model, "accept", ids, { reason: reason.value.trim() });
      dialog.close();
      toast("good", plural(ids.length, "toast.acceptedN.one", "toast.acceptedN.many"), { label: t("action.undo"), run: async () => {
        try { await sendIds(model, "unaccept", ids); toast("good", t("toast.unaccepted")); await changed(); } catch (error) { toast("bad", errorText(error)); }
      } });
      await changed();
    } catch (error) { toast("bad", errorText(error)); submit.disabled = false; }
  } },
  h("div", { class: "body" }, h("h2", { text: t("accept.bulk.title") }), h("p", { text: t("accept.help") }), reason),
  h("div", { class: "foot" }, h("button", { type: "button", class: "btn", onClick: () => dialog.close() }, t("action.cancel")), submit));
  const dialog = modal(form);
  reason.focus();
}

async function startRecheck(model, item) {
  try {
    await api(`runs/${enc(model.name)}/recheck`, { ids: item.all.map((i) => i.id) });
    askNotify();
    await refreshState();
  } catch (error) { toast("bad", errorText(error)); }
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
      box.append(h("div", { class: "recheck-box bad" }, icon("alert"), h("div", { class: "grow" }, h("b", { text: t("recheck.failed") }), h("div", { class: "muted", text: jobError(job, "") })),
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
