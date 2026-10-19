/* The run model the views read, and what they derive from it: captures, boxes, fix prompts. No DOM. */

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

// Whether two runs measured the same thing, so their counts can be set side by side.
function comparable(a, b) {
  if (b.targeted || a.base_url !== b.base_url || a.fast !== b.fast || a.signed_in !== b.signed_in || (a.locale || "") !== (b.locale || "")) return false;
  const mine = new Set(a.paths || []), theirs = new Set(b.paths || []);
  if (!mine.size || !theirs.size) return true;  // runs listed before paths were recorded
  const shared = [...mine].filter((p) => theirs.has(p)).length;
  return shared / new Set([...mine, ...theirs]).size >= 0.8;
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

// The targeted rerun for these findings, as report.py worked it out (summary.recheck_command):
// a whole cause, or one finding of a larger one. Null for a set it has no command for.
function recheckCommand(model, issues) {
  if (!issues.length) return null;
  if (issues.length === 1 && issues[0].recheck) return issues[0].recheck;
  const group = model.groups.get(issues[0].group || issues[0].id);
  const same = group && group.issues.length === issues.length && issues.every((i) => (i.group || i.id) === group.id);
  return same && group.info && group.info.recheck ? group.info.recheck : null;
}
// What a job's log box adds: the lines logged since `shown` lines were drawn, or the whole tail
// again when nothing was drawn yet or more lines came than the tail the server sends holds.
function logLines(shown, job) {
  const lines = job.log || [], total = job.log_count ?? lines.length;
  if (shown !== null && shown === total) return { reset: false, lines: [], total };
  if (!shown || total < shown || total - shown > lines.length) return { reset: true, lines, total };
  return { reset: false, lines: lines.slice(lines.length - (total - shown)), total };
}

function acceptCommand(model, id) {
  return (model.data.accept_command || "").replace("{id}", id);
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
  lines.push("", `Hint: ${I18N.tip(issue.check, "en")}`);
  const recheck = recheckCommand(model, all);
  if (recheck) lines.push("", "When the fix is in, prove it with a targeted rerun and compare:", recheck);
  return lines.join("\n");
}

// The findings filters as values in the URL, so a filtered view can be shared, and back. A value
// left at its default is left out; a link with any of them sets all of them.
const FILTER_KEYS = ["sev", "page", "check", "q", "w", "accepted", "by"];
function filterQuery(vs) {
  const out = {};
  if (vs.sev.size) out.sev = SEVS.filter((s) => vs.sev.has(s)).join(",");
  if (vs.route) out.page = vs.route;
  if (vs.check) out.check = vs.check;
  if (vs.text) out.q = vs.text;
  if (vs.width !== null) out.w = String(vs.width);
  if (vs.accepted) out.accepted = "1";
  if (vs.mode === "page") out.by = "page";
  return out;
}
function readFilters(query) {
  const width = /^\d{1,5}$/.test(query.w || "") ? Number(query.w) : null;
  return {
    sev: new Set(String(query.sev || "").split(",").filter((s) => SEVS.includes(s))),
    route: query.page || "", check: query.check || "", text: String(query.q || "").trim().toLowerCase(), width,
    accepted: query.accepted === "1", mode: query.by === "page" ? "page" : "cause",
  };
}

// Exports of the findings a view shows, in English like report.json: one row per finding.
function exportRows(issues) {
  return issues.map((i) => {
    const source = (i.source_candidates || [])[0];
    const runtime = RUNTIME_CHECKS.has(i.check);
    return {
      id: i.id, severity: i.severity, check: i.check, page: i.route, state: i.state,
      widths: runtime || lo(i) === undefined ? "" : lo(i) === hi(i) ? String(lo(i)) : `${lo(i)}-${hi(i)}`,
      element: runtime ? "" : i.selector || "", message: i.message || "",
      source: source ? (source.line ? `${source.file}:${source.line}` : source.file) : "",
      accepted: i.accepted ? i.accepted.reason || "yes" : "", origin: i.origin || "deterministic",
    };
  });
}
function findingsCsv(issues) {
  const columns = ["id", "severity", "check", "page", "state", "widths", "element", "message", "source", "accepted", "origin"];
  const cell = (value) => {
    let text = String(value);
    if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;  // not a formula when a spreadsheet opens it
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [columns.join(","), ...exportRows(issues).map((row) => columns.map((c) => cell(row[c])).join(","))].join("\r\n") + "\r\n";
}
function findingsMarkdown(model, issues) {
  const flat = (value) => String(value).replace(/\s*[\r\n]+\s*/g, " ");
  const cell = (value) => flat(value).replace(/\\/g, "\\\\").replace(/\|/g, "\\|");
  const code = (value) => (value ? "`" + flat(value).replace(/`/g, "'").replace(/\|/g, "\\|") + "`" : "");
  const lines = [`# ui-audit findings${model.data.base_url ? ` for ${model.data.base_url}` : ""}`, ""];
  if (model.data.created) lines.push(`Run of ${model.data.created}: ${issues.length} finding${issues.length === 1 ? "" : "s"}.`, "");
  lines.push("| Severity | Check | Page | State | Widths | Element | Message |", "|---|---|---|---|---|---|---|");
  for (const row of exportRows(issues)) {
    lines.push(`| ${row.severity} | ${cell(row.check)} | ${code(row.page)} | ${cell(row.state)} | ${row.widths} | ${code(row.element)} | ${cell(row.message)} |`);
  }
  return lines.join("\n") + "\n";
}
