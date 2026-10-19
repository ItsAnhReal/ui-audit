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
// MESSAGES); known keys are shown in the app's language. Agent findings, runtime errors, reports
// from before the keys and keys this version does not know keep the English text, as does the fix prompt.
function messageText(issue) {
  const raw = issue.message || "";
  if (!issue.message_key || issue.origin === "agent") return raw;
  const text = translatedMessage(issue.message_key, issue.message_params || {});
  return text === null ? raw : text;
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
// Why a page may not show its real content; translated when the probe sent a key.
function contentDetail(content) {
  const key = content && content.detail_key && `content.${content.detail_key}`;
  if (!key || !I18N.has(key)) return (content && content.detail) || "";
  const vars = {};
  for (const [name, value] of Object.entries(content.detail_params || {})) vars[name] = typeof value === "number" ? fmt.n(value) : value;
  return t(key, vars);
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
