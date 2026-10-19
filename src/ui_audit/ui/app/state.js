/* App state, preferences, the server API and polling. */

const readJson = (id) => { try { return JSON.parse(document.getElementById(id).textContent); } catch (_) { return null; } };
const DATA = readJson("report-data");
const APP = readJson("app-config");
const IS_APP = !!(APP && APP.token);

// ---------------------------------------------------------------- preferences

const prefs = {
  get(key, fallback) { try { const v = localStorage.getItem("ui-audit:" + key); return v === null ? fallback : v; } catch (_) { return fallback; } },
  set(key, value) { try { localStorage.setItem("ui-audit:" + key, value); } catch (_) { /* private window */ } },
  json(key, fallback) { try { return JSON.parse(this.get(key, "")) || fallback; } catch (_) { return fallback; } },
};
function applyTheme() {
  const theme = prefs.get("theme", "system");
  if (theme === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = theme;
}
applyTheme();
I18N.use(prefs.get("lang", "auto"));
document.documentElement.lang = I18N.lang;

// ---------------------------------------------------------------- server

async function api(path, body) {
  const response = await fetch("/api/" + path, {
    method: body ? "POST" : "GET",
    headers: { "X-UI-Audit-Token": APP.token, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await response.json(); } catch (_) { /* empty body */ }
  if (!response.ok) throw new Error((data && data.error) || `HTTP ${response.status}`);
  return data;
}

// ---------------------------------------------------------------- app state

const S = {
  state: null,            // GET /api/state
  stateError: null,
  runs: new Map(),        // run name -> { stamp, model }
  views: new Map(),       // run name -> list filters, selection and screenshot choices
  picked: [],             // runs ticked for comparing
  page: null,             // the mounted view: { kind, key, update(route), onState() }
  knownJobs: new Map(),   // job id -> last seen status, to notice when one finishes
  reach: new Map(),       // base URL -> reachability result
};

function viewState(name) {
  if (!S.views.has(name)) {
    S.views.set(name, { mode: prefs.get("list-mode", "cause"), sev: new Set(), route: "", check: "", text: "", width: null,
      accepted: false, occ: {}, shot: {}, fit: true, zoom: true, others: false, accepting: null });
  }
  return S.views.get(name);
}

// ---------------------------------------------------------------- run model

async function loadRun(name) {
  if (!IS_APP) {
    if (!S.runs.has("")) S.runs.set("", { stamp: 0, model: buildModel(DATA) });
    return S.runs.get("").model;
  }
  const summary = (S.state && S.state.runs || []).find((r) => r.name === name);
  const stamp = summary ? JSON.stringify([summary.counts, summary.accepted, summary.agent, summary.verify, summary.created]) : null;
  const cached = S.runs.get(name);
  if (cached && (stamp === null || cached.stamp === stamp)) return cached.model;
  const data = await api("runs/" + enc(name));
  const model = buildModel(data);
  S.runs.set(name, { stamp, model });
  return model;
}
function forgetRun(name) { S.runs.delete(name); }

async function checkReach(url) {
  const cached = S.reach.get(url);
  if (cached && Date.now() - cached.at < 15000) return cached.result;
  let result;
  try { result = await api("check?url=" + enc(url)); } catch (error) { result = { ok: false, detail: error.message }; }
  S.reach.set(url, { at: Date.now(), result });
  return result;
}

async function cancelJob(job) {
  try { await api(`jobs/${job.id}/cancel`, {}); toast("info", t("toast.cancelling")); } catch (error) { toast("bad", error.message); }
  refreshState();
}
async function runAgain(name, anyway) {
  const run = S.state && S.state.runs.find((r) => r.name === name);
  if (!anyway && run && run.base_url) {
    const reach = await checkReach(run.base_url);
    if (!reach.ok) { toast("bad", t("toast.unreachable", { url: run.base_url }), { label: t("action.startAnyway"), run: () => runAgain(name, true) }, 0); return; }
  }
  try {
    const job = await api(`runs/${enc(name)}/again`, {});
    toast("good", t("toast.started", { name: job.name }), parseHash().view === "home" ? null : { label: t("toast.showProgress"), run: () => go({ view: "home" }) });
    askNotify();
    refreshState();
  } catch (error) { toast("bad", error.message); }
}

async function reveal(name) {
  try { await api(`runs/${enc(name)}/reveal`, {}); } catch (error) { toast("bad", error.message); }
}
async function deleteRun(run) {
  const ok = await confirmDialog({ title: t("delete.title", { name: run.name }), text: t("delete.text", { size: fmt.bytes(run.bytes) }), confirm: t("action.delete"), danger: true });
  if (!ok) return;
  try {
    await api(`runs/${enc(run.name)}/delete`, {});
    S.picked = S.picked.filter((n) => n !== run.name);
    forgetRun(run.name);
    toast("good", t("toast.deleted", { name: run.name }));
    await refreshState();
    if (parseHash().view !== "home") go({ view: "home" });
  } catch (error) { toast("bad", error.message); }
}

let askedNotify = false;
function askNotify() {
  if (askedNotify || !("Notification" in window) || Notification.permission !== "default") return;
  askedNotify = true;
  Notification.requestPermission().catch(() => null);
}

// ---------------------------------------------------------------- polling

let pollTimer = null;
async function refreshState() {
  if (!IS_APP) return;
  try {
    const state = await api("state");
    const first = !S.state;
    S.state = state;
    S.stateError = null;
    noticeFinishedJobs(state.jobs, first);
    updateJobPill();
    if (S.page && S.page.onState) S.page.onState();
  } catch (error) {
    if (!S.stateError) toast("bad", t("error.server"), null, 0);
    S.stateError = error;
  }
}
function noticeFinishedJobs(jobs, first) {
  for (const job of jobs) {
    const before = S.knownJobs.get(job.id);
    S.knownJobs.set(job.id, job.status);
    if (first || !before || !ACTIVE.has(before) || ACTIVE.has(job.status) || job.kind === "login") continue;
    if (job.status === "done") {
      const empty = job.result && job.result.empty;
      const c = (job.result && job.result.counts) || {};
      const text = job.kind === "recheck" ? recheckText(job) : empty ? t("job.nothing") : t("toast.finished", { name: job.name, counts: SEVS.map((s) => `${c[s] || 0} ${s}`).join(" · ") });
      const kind = job.kind === "recheck" ? recheckKind(job) : "good";
      // on the home page the job's own card already says it
      if (parseHash().view !== "home" || job.kind === "recheck") toast(kind, text, empty ? null : { label: t("job.open"), run: () => go({ view: "run", run: job.name }) }, 9000);
      notify(text);
      if (job.source) forgetRun(job.source);
    } else if (job.status === "failed") {
      toast("bad", t("toast.failed", { name: job.name, error: job.error || "" }), { label: t("toast.showLog"), run: () => go({ view: "home" }) }, 0);
      notify(t("toast.failed", { name: job.name, error: "" }));
    }
  }
}
function recheckKind(job) {
  const values = Object.values((job.result && job.result.recheck && job.result.recheck.issues) || {});
  return values.includes("persistent") ? "bad" : values.includes("fixed") ? "good" : "info";
}
function recheckText(job) {
  const outcome = (job.result && job.result.recheck && job.result.recheck.issues) || {};
  const values = Object.values(outcome);
  const fixed = values.filter((v) => v === "fixed").length, still = values.filter((v) => v === "persistent").length;
  return still ? t("recheck.still", { n: still, total: values.length }) : fixed ? t("recheck.fixedToast", { n: fixed }) : t("recheck.unclear");
}
function notify(text) {
  if (!document.hidden || !("Notification" in window) || Notification.permission !== "granted") return;
  try { new Notification("ui-audit", { body: text }); } catch (_) { /* some browsers only allow it from a service worker */ }
}
function schedule() {
  clearTimeout(pollTimer);
  const busy = S.state && S.state.jobs.some((j) => ACTIVE.has(j.status));
  pollTimer = setTimeout(async () => { await refreshState(); schedule(); }, busy ? 1000 : document.hidden ? 20000 : 6000);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && IS_APP) { refreshState().then(schedule); } });
