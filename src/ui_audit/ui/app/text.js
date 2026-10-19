/* Texts derived from report data: labels, translated messages, selectors. No DOM. */

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

function sourceReason(reason) {
  const m = /^(class|component|defines) (.*)$/.exec(reason);
  if (m) return t(`src.why.${m[1]}`, { name: m[2] });
  return known(`src.why.${reason.replace(/\s+/g, "-")}`, reason);
}
function reasonText(reasons) {
  return (reasons || []).map((r) => known(`reason.${r}`, r)).join(", ");
}

// one word for a POSIX shell: plain when safe, otherwise single-quoted
function shellQuote(v) { return /^[\w./:@%+=,-]+$/.test(v) ? v : `'${v.replace(/'/g, "'\\''")}'`; }
