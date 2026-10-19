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
// The probe measures in English and sends each message's key and values along (probe.js
// MESSAGES); known keys are shown in the app's language. Runs audited before the keys existed
// get their known sentence shapes recognised instead. Agent findings, runtime errors and keys
// this version does not know keep the English text, as does the fix prompt.
function messageText(issue) {
  const raw = issue.message || "";
  if (issue.origin === "agent" || RUNTIME_CHECKS.has(issue.check)) return raw;
  const keyed = issue.message_key ? { key: issue.message_key, params: issue.message_params || {} } : legacyMessage(raw);
  const text = keyed ? translatedMessage(keyed.key, keyed.params) : null;
  return text === null ? raw : text;
}
// The sentences reports from before message_key held, as key and values.
const scrolls = (by) => ({ key: "scrolls", params: { by } });
const LEGACY_MESSAGES = [
  [/^Page is (\d+)px wide in a (\d+)px viewport\.$/, "pageWide", (m) => ({ page: m[1], vw: m[2] })],
  [/^Extends to (\d+)px in a (\d+)px viewport \(page scrolls sideways by (\d+)px\)\.$/, "extends", (m) => ({ right: m[1], vw: m[2], scroll: scrolls(m[3]) })],
  [/^Control is cut off at the (left|right) edge of a (\d+)px viewport\.$/, "controlCut", (m) => ({ edge: m[1], vw: m[2] })],
  [/^Content is cut off at the (left|right) edge of a (\d+)px viewport\.$/, "contentCut", (m) => ({ edge: m[1], vw: m[2] })],
  [/^Grid columns need (\d+)px but the grid is (\d+)px wide in a (\d+)px viewport \(page scrolls sideways by (\d+)px\)\.$/, "gridExtends",
    (m) => ({ needed: m[1], box: m[2], vw: m[3], scroll: scrolls(m[4]) })],
  [/^Grid columns need (\d+)px but the grid is (\d+)px wide; content is cut off at the (left|right) edge of a (\d+)px viewport\.$/, "gridCut",
    (m) => ({ needed: m[1], box: m[2], edge: m[3], vw: m[4] })],
  [/^Content is clipped by (\d+)px horizontally: "([^]*)"$/, "clippedX", (m) => ({ px: m[1], text: m[2] })],
  [/^Content is clipped by (\d+)px vertically: "([^]*)"$/, "clippedY", (m) => ({ px: m[1], text: m[2] })],
  [/^Text spills (\d+)px outside its box: "([^]*)"$/, "spill", (m) => ({ px: m[1], text: m[2] })],
  [/^Overlaps (.+) by (\d+)% of the smaller control\.$/, "overlaps", (m) => ({ other: m[1], pct: m[2] })],
  [/^Target is (\d+)×(\d+)px, under (\d+)×\d+px, and too close to "([^]*)"\.$/, "target", (m) => ({ w: m[1], h: m[2], min: m[3], near: m[4] })],
  [/^(\w+) has no accessible name\.$/, "unnamed", (m) => ({ tag: m[1] })],
];
function legacyMessage(raw) {
  for (const [pattern, key, params] of LEGACY_MESSAGES) {
    const m = pattern.exec(raw);
    if (m) return { key, params: params(m) };
  }
  return null;
}
function translatedMessage(key, params) {
  if (!I18N.has(`msg.${key}`)) return null;
  const vars = {};
  for (const [name, value] of Object.entries(params)) {
    if (value && typeof value === "object") {  // a clause that is a message of its own
      vars[name] = translatedMessage(value.key, value.params || {});
      if (vars[name] === null) return null;
    } else if (name === "edge") vars[name] = known(`msg.edge.${value}`, value);
    else if (name === "other") vars[name] = shortSelector(value);
    else vars[name] = value;
  }
  return t(`msg.${key}`, vars);
}
// Why a page may not show its real content; translated from the probe's key, or for runs from
// before the keys from the known English shapes.
function contentDetail(content) {
  const detail = (content && content.detail) || "";
  const keyed = content && content.detail_key ? { key: content.detail_key, params: content.detail_params || {} } : legacyDetail(detail);
  if (!keyed || !I18N.has(`content.${keyed.key}`)) return detail;
  const vars = {};
  for (const [name, value] of Object.entries(keyed.params)) vars[name] = typeof value === "number" ? fmt.n(value) : value;
  return t(`content.${keyed.key}`, vars);
}
function legacyDetail(detail) {
  let m;
  if ((m = /^(\d+) characters of text, (\d+) controls?$/.exec(detail))) return { key: "thinDetail", params: { chars: +m[1], controls: +m[2] } };
  if ((m = /^(\d+) sections? stays? invisible$/.exec(detail))) return { key: "hiddenDetail", params: { n: +m[1] } };
  if ((m = /^(\d+) skeleton placeholders$/.exec(detail))) return { key: "skeletons", params: { n: +m[1] } };
  if (detail === "a region is still marked busy") return { key: "busy", params: {} };
  return null;
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

// Server and job errors carry a code (err.<code>) with values; known codes are shown in the
// app's language, anything else in the English the server wrote.
function codeText(code, params, raw) {
  const key = `err.${code}`;
  if (!code || !I18N.has(key)) return raw;
  const text = t(key, params || {});
  return /\{\w+\}/.test(text) ? raw : text;  // a value this version expects is missing
}
function errorText(error) { return codeText(error.code, error.params, error.message); }
function jobError(job, fallback) { return codeText(job.error_code, job.error_params, job.error || fallback); }
