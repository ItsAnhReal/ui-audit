/* ui-audit: the local app (`ui-audit ui`) and the static report viewer (index.html of a run).
   One script for both: report.py joins the files in this folder, in the order of
   report.APP_SCRIPTS, inside one function, so they share its scope. With an app config it
   talks to the local server; with inlined report data it shows that one run and offers
   commands to copy instead of buttons that act.

   core.js: constants and number, date and width formatting. No DOM. */

const I18N = window.uiAuditI18n;
const t = I18N.t;

const ORDER = { P1: 0, P2: 1, P3: 2 };
const SEVS = ["P1", "P2", "P3"];
const ACTIVE = new Set(["queued", "running", "waiting"]);
const RUNTIME_CHECKS = new Set(["console-error", "failed-resource"]);

const debounce = (fn, ms) => { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); }; };
const enc = encodeURIComponent;
const plural = (n, one, many) => t(n === 1 ? one : many, { n: fmt.n(n) });
const known = (key, raw) => (I18N.has(key) ? t(key) : raw);  // values written by newer or older versions

// ---------------------------------------------------------------- formatting

const fmt = {
  n: (v) => new Intl.NumberFormat(I18N.lang).format(v || 0),
  bytes(b) {
    if (!b) return "0 MB";
    if (b >= 1e9) return `${new Intl.NumberFormat(I18N.lang, { maximumFractionDigits: 1 }).format(b / 1e9)} GB`;
    if (b >= 1e6) return `${fmt.n(Math.round(b / 1e6))} MB`;
    return `${fmt.n(Math.max(1, Math.round(b / 1e3)))} KB`;
  },
  dur(s) {
    if (s === null || s === undefined || Number.isNaN(s)) return "–";
    if (s < 60) return t("dur.s", { n: Math.max(1, Math.round(s)) });
    if (s < 3600) return t("dur.m", { n: Math.round(s / 60) });
    return t("dur.h", { h: Math.floor(s / 3600), m: Math.round((s % 3600) / 60) });
  },
  clock(s) { s = Math.max(0, Math.round(s)); const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; },
  ago(iso) {
    const then = typeof iso === "number" ? iso : Date.parse(iso);
    if (!then) return "";
    const diff = (then - Date.now()) / 1000;
    const rtf = new Intl.RelativeTimeFormat(I18N.lang, { numeric: "auto" });
    const abs = Math.abs(diff);
    if (abs < 45) return t("time.now");
    if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
    if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), "day");
    return fmt.date(iso);
  },
  date(iso) { const d = new Date(iso); return Number.isNaN(+d) ? "" : new Intl.DateTimeFormat(I18N.lang, { dateStyle: "medium", timeStyle: "short" }).format(d); },
  range(lo, hi) { return lo === undefined ? t("widths.none") : lo === hi ? `${lo} px` : `${lo}–${hi} px`; },
};
const lo = (i) => (i.widths && i.widths.length ? Math.min(...i.widths) : undefined);
const hi = (i) => (i.widths && i.widths.length ? Math.max(...i.widths) : undefined);
const worst = (issues) => SEVS[Math.min(...issues.map((i) => ORDER[i.severity] ?? 2))] || "P3";
const span = (issues) => {
  const all = issues.flatMap((i) => i.widths || []);
  return all.length ? [Math.min(...all), Math.max(...all)] : [undefined, undefined];
};
const shotWidth = (file) => { const m = /__(\d+)(__annotated)?\.png$/.exec(file || ""); return m ? Number(m[1]) : null; };
