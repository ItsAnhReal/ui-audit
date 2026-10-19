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
  const routes = [...new Set(issues.map((i) => i.route))].map((r) => `--route ${shellQuote(r)}`).join(" ");
  const widths = recheckWidths(issues, model.LO, model.HI).join(",");
  const states = issues.every((i) => i.state === "default") ? " --no-states" : "";
  return `ui-audit audit --like ${shellQuote(dir)} ${routes} --width ${widths}${states} --output ${shellQuote(out)}\nui-audit verify ${shellQuote(dir)} ${shellQuote(out)}`;
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
