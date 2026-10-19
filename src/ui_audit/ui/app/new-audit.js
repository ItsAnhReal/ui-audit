/* The sheet that starts a new audit. */

// ---------------------------------------------------------------- new audit

function newAuditSheet(preset) {
  const st = S.state;
  if (!st) return;
  const saved = prefs.json("new-audit", {});
  const configs = st.configs.filter((c) => !c.error);
  const defaultConfig = (configs.find((c) => c.path === saved.config) || configs.find((c) => c.default) || configs[0] || { path: "" });
  const form = {
    config: preset?.config ?? defaultConfig.path ?? "",
    base_url: "",
    mode: preset?.mode || saved.mode || "quick",
    routes: preset?.routes || "",
    widths: preset?.widths || "",
    session: saved.session ?? null,
    locale: saved.locale ?? null,
    states: true,
    annotate: saved.annotate ?? false,
    changed_since: "",
    name: "",
  };
  const configInfo = () => configs.find((c) => c.path === form.config) || {};

  const urlInput = h("input", { type: "url", id: "na-url", placeholder: "http://localhost:3000", autocomplete: "off", spellcheck: "false", "aria-describedby": "na-url-err" });
  const fieldError = (id) => h("div", { class: "field-error", id, hidden: true, role: "alert" });
  const urlError = fieldError("na-url-err"), routesError = fieldError("na-routes-err"), widthsError = fieldError("na-widths-err");
  const urlStatus = h("span", { class: "status-dot", "aria-live": "polite" });
  const configSelect = h("select", { id: "na-config" }, configs.map((c) => h("option", { value: c.path, text: c.path })), h("option", { value: "", text: t("na.noSettings") }));
  const modeButtons = ["quick", "complete", "pages"].map((mode) => h("button", { type: "button", "aria-pressed": "false", "data-mode": mode, onClick: () => { form.mode = mode; sync(); } },
    h("b", { text: t(`na.mode.${mode}`) }), h("span", { text: t(`na.mode.${mode}.help`) })));
  const routesInput = h("textarea", { id: "na-routes", rows: "3", placeholder: t("na.routes.placeholder"), spellcheck: "false", "aria-describedby": "na-routes-err" });
  const knownRoutes = [...new Set(st.runs.flatMap((r) => r.routes || []))];
  const widthsInput = h("input", { type: "text", id: "na-widths", placeholder: t("na.widths.placeholder"), inputmode: "numeric", "aria-describedby": "na-widths-err" });
  const pagesBox = h("div", { class: "field" },
    h("label", { for: "na-routes", text: t("na.routes") }), routesInput, routesError,
    knownRoutes.length ? h("div", { class: "help" }, t("na.routesSeen"), " ", knownRoutes.slice(0, 8).map((r) => h("button", { type: "button", class: "chip", style: { margin: "2px" }, onClick: () => {
      routesInput.value = [...new Set([...routesInput.value.split(/\s+/).filter(Boolean), r])].join("\n"); form.routes = routesInput.value; sync();
    } }, r))) : null,
    h("label", { for: "na-widths", text: t("na.widths"), style: { marginTop: "6px" } }), widthsInput, widthsError, h("div", { class: "help", text: t("na.widths.help") }));
  const sessionSelect = h("select", { id: "na-session" });
  const loginBox = h("div", { class: "login-box", hidden: true });
  const localeSelect = h("select", { id: "na-locale" });
  const statesBox = h("input", { type: "checkbox", id: "na-states", checked: true });
  const annotateBox = h("input", { type: "checkbox", id: "na-annotate" });
  const changedInput = h("input", { type: "text", id: "na-changed", placeholder: t("na.changed.placeholder"), spellcheck: "false" });
  const nameInput = h("input", { type: "text", id: "na-name", spellcheck: "false" });
  const command = h("pre", { class: "cmd" }, document.createTextNode(""),
    h("button", { type: "button", class: "btn ghost icon sm", "aria-label": t("action.copy"), onClick: () => copy(commandText.replace(/ \\\n {2}/g, " ")) }, icon("copy")));
  const estimate = h("span", { class: "hint", "aria-live": "polite" });
  let reachable = true, submitError = "";
  const start = h("button", { class: "btn primary", type: "submit" }, icon("play"), t("na.start"));

  function fillSessions(selected) {
    sessionSelect.replaceChildren(h("option", { value: "", text: t("na.notSignedIn") }),
      ...S.state.sessions.map((s) => h("option", { value: s.path, text: `${s.path} · ${t("na.savedAgo", { ago: fmt.ago(s.modified) })}` })));
    sessionSelect.value = selected || "";
  }
  function fillLocales() {
    const options = [["", t("na.locale.default")], ["de", "Deutsch (de)"], ["en", "English (en)"], ["fr", "Français (fr)"], ["es", "Español (es)"], ["it", "Italiano (it)"], ["nl", "Nederlands (nl)"], ["pl", "Polski (pl)"], ["tr", "Türkçe (tr)"], ["ja", "日本語 (ja)"]];
    localeSelect.replaceChildren(...options.map(([v, label]) => h("option", { value: v, text: label })));
  }
  fillLocales();

  function applyConfig() {
    const info = configInfo();
    urlInput.value = preset?.base_url || info.base_url || urlInput.value;
    if (!urlInput.value && !S.state.config?.path) {  // no settings file: a dev server found on a usual port, if any
      discover().then(({ found }) => { if (!urlInput.value && found.length) { urlInput.value = found[0]; checkUrl(); sync(); } });
    }
    if (!urlInput.value) urlInput.value = S.state.config?.path ? S.state.config.base_url || "" : "";
    const session = form.session !== null && S.state.sessions.some((s) => s.path === form.session) ? form.session
      : (S.state.sessions.find((s) => info.storage_state && (s.path === info.storage_state || s.path.endsWith(info.storage_state.replace(/^\.\//, ""))))?.path || "");
    fillSessions(session);
    localeSelect.value = form.locale !== null ? form.locale : (info.locale || "");
    if (![...localeSelect.options].some((o) => o.value === localeSelect.value)) localeSelect.append(h("option", { value: localeSelect.value, text: localeSelect.value }));
    checkUrl();
  }
  const checkUrl = debounce(async () => {
    const url = urlInput.value.trim();
    if (!url) { urlStatus.className = "status-dot"; urlStatus.textContent = ""; reachable = true; footNote(); return; }
    urlStatus.className = "status-dot wait"; urlStatus.textContent = t("home.checking");
    const result = await checkReach(url);
    if (url !== urlInput.value.trim()) return;
    urlStatus.className = `status-dot ${result.ok ? "ok" : "bad"}`;
    urlStatus.textContent = result.ok ? t("na.reachable") : t("na.unreachable");
    urlStatus.title = result.detail || "";
    reachable = result.ok;
    footNote();
  }, 350);
  // The footer says the one thing that matters most: why it did not start, that it will fail, or how long it takes.
  function footNote() {
    const similar = S.state.runs.find((r) => !r.targeted && r.base_url === urlInput.value.trim() && r.fast === (form.mode === "quick"));
    const [kind, text] = submitError ? ["bad", submitError] : !reachable ? ["warn", t("na.willFail")]
      : ["", form.mode === "pages" ? t("na.estimate.pages") : similar ? t("na.estimate", { took: fmt.dur(similar.seconds), name: similar.name }) : ""];
    estimate.className = `hint${kind ? " " + kind : ""}`;
    estimate.textContent = text;
  }
  // Checked here so a mistake shows next to its field instead of as a failed start.
  function validate() {
    const problems = [];
    const show = (box, input, text) => { box.hidden = !text; box.textContent = text || ""; input.setAttribute("aria-invalid", String(!!text)); if (text) problems.push(input); };
    show(urlError, urlInput, /^https?:\/\/\S+$/.test(urlInput.value.trim()) ? "" : t("na.err.url"));
    if (form.mode === "pages") {
      const routes = routesInput.value.split(/[\s,]+/).filter(Boolean);
      show(routesError, routesInput, !routes.length ? t("na.err.noRoutes") : routes.some((r) => !r.startsWith("/")) ? t("na.err.slash") : "");
      const widths = widthsInput.value.split(/[\s,]+/).filter(Boolean);
      show(widthsError, widthsInput, widths.some((w) => !/^\d{3,4}$/.test(w)) ? t("na.err.widths") : "");
    } else {
      show(routesError, routesInput, ""); show(widthsError, widthsInput, "");
    }
    return problems;
  }

  function body() {
    const routes = routesInput.value.split(/[\s,]+/).filter(Boolean);
    const out = {
      config: configSelect.value, base_url: urlInput.value.trim(), mode: form.mode,
      storage_state: sessionSelect.value, locale: localeSelect.value, states: statesBox.checked, annotate: annotateBox.checked,
    };
    if (form.mode === "pages") { out.routes = routes; out.widths = widthsInput.value.split(/[\s,]+/).filter(Boolean); }
    if (changedInput.value.trim() && form.mode !== "pages") out.changed_since = changedInput.value.trim();
    if (nameInput.value.trim()) out.name = nameInput.value.trim();
    return out;
  }
  // The same audit on the command line; the server writes it, with the CLI's quoting.
  let commandText = "";
  const showCommand = debounce(async () => {
    try { commandText = (await api("command", body())).command; } catch (_) { commandText = ""; }
    command.firstChild.textContent = commandText;
    command.hidden = !commandText;
  }, 150);
  function sync() {
    for (const button of modeButtons) button.setAttribute("aria-pressed", String(button.dataset.mode === form.mode));
    pagesBox.hidden = form.mode !== "pages";
    changedField.hidden = form.mode === "pages";
    showCommand();
    footNote();
  }

  const changedField = h("div", { class: "field" }, h("label", { for: "na-changed", text: t("na.changed") }), changedInput, h("div", { class: "help", text: t("na.changed.help") }));
  const content = h("form", { style: { display: "contents" }, onSubmit: async (event) => {
    event.preventDefault();
    submitError = "";
    const problems = validate();
    if (problems.length) { problems[0].focus(); footNote(); return; }
    start.disabled = true;
    try {
      const job = await api("runs", body());
      prefs.set("new-audit", JSON.stringify({ config: configSelect.value, mode: form.mode, session: sessionSelect.value, locale: localeSelect.value, annotate: annotateBox.checked }));
      dialog.close();
      toast("good", t("toast.started", { name: job.name }));
      askNotify();
      await refreshState();
      go({ view: "home" });
    } catch (error) {
      submitError = t("na.failed", { error: errorText(error) });
      footNote();
      start.disabled = false;
    }
  } },
  h("header", {}, h("h2", { text: t("na.title") }), h("button", { type: "button", class: "btn ghost icon", "aria-label": t("action.close"), onClick: () => dialog.close() }, icon("x"))),
  h("div", { class: "body" },
    configs.length ? h("div", { class: "field" }, h("label", { for: "na-config", text: t("na.settings") }), configSelect, h("div", { class: "help", text: t("na.settings.help") })) : null,
    h("div", { class: "field" }, h("label", { for: "na-url", text: t("na.url") }), h("div", { class: "row" }, urlInput, urlStatus), urlError),
    h("div", { class: "field" }, h("div", { class: "lbl", id: "na-mode-label", text: t("na.mode") }), h("div", { class: "seg big", role: "group", "aria-labelledby": "na-mode-label" }, modeButtons)),
    pagesBox,
    h("div", { class: "field" }, h("label", { for: "na-session", text: t("na.session") }),
      h("div", { class: "row" }, sessionSelect, h("button", { type: "button", class: "btn", onClick: () => startLogin() }, icon("lock"), t("na.signIn"))),
      h("div", { class: "help", text: t("na.session.help") }), loginBox),
    h("div", { class: "field" }, h("label", { for: "na-locale", text: t("na.locale") }), localeSelect, h("div", { class: "help", text: t("na.locale.help") })),
    h("details", { class: "more" }, h("summary", {}, icon("right"), t("na.more")),
      h("div", {},
        h("label", { class: "check" }, statesBox, h("span", {}, h("b", { text: t("na.states") }), h("span", { text: t("na.states.help") }))),
        h("label", { class: "check" }, annotateBox, h("span", {}, h("b", { text: t("na.annotate") }), h("span", { text: t("na.annotate.help") }))),
        changedField,
        h("div", { class: "field" }, h("label", { for: "na-name", text: t("na.name") }), nameInput, h("div", { class: "help", text: t("na.name.help") })),
        h("div", { class: "field" }, h("div", { class: "lbl", text: t("na.cli") }), command)))),
  h("footer", {}, estimate, h("button", { type: "button", class: "btn", onClick: () => dialog.close() }, t("action.cancel")), start));
  const dialog = modal(content, { cls: "sheet" });

  async function startLogin() {
    const pathInput = h("input", { type: "text", value: "/", spellcheck: "false", "aria-label": t("na.login.path") });
    const go2 = h("button", { type: "button", class: "btn primary sm" }, t("na.login.open"));
    loginBox.hidden = false;
    loginBox.replaceChildren(h("div", { class: "help", text: t("na.login.intro") }), h("div", { class: "row" }, pathInput, go2));
    pathInput.focus();
    go2.addEventListener("click", async () => {
      go2.disabled = true;
      let job;
      try { job = await api("login", { config: configSelect.value, base_url: urlInput.value.trim(), path: pathInput.value.trim() || "/" }); } catch (error) { toast("bad", errorText(error)); go2.disabled = false; return; }
      const done = h("button", { type: "button", class: "btn primary sm" }, icon("check"), t("na.login.done"));
      const stop = h("button", { type: "button", class: "btn sm" }, t("action.cancel"));
      loginBox.replaceChildren(h("div", {}, h("b", { text: t("na.login.waiting") })), h("div", { class: "help", text: t("na.login.waitingHelp") }), h("div", { class: "row" }, done, stop));
      stop.addEventListener("click", async () => { await api(`jobs/${job.id}/cancel`, {}).catch(() => null); loginBox.hidden = true; });
      done.addEventListener("click", async () => {
        done.disabled = true;
        try { await api(`jobs/${job.id}/continue`, {}); } catch (error) { toast("bad", errorText(error)); done.disabled = false; return; }
        for (let n = 0; n < 40; n++) {
          await new Promise((r) => setTimeout(r, 500));
          const state = await api("state");
          S.state = state;
          const current = state.jobs.find((j) => j.id === job.id);
          if (current && current.status === "done") {
            fillSessions(current.result.session);
            loginBox.hidden = true;
            toast("good", t("toast.signedIn", { file: current.result.session }));
            return;
          }
          if (current && (current.status === "failed" || current.status === "cancelled")) { toast("bad", jobError(current, t("job.failed"))); loginBox.hidden = true; return; }
        }
      });
    });
  }

  configSelect.value = form.config;
  configSelect.addEventListener("change", () => { form.config = configSelect.value; form.session = null; form.locale = null; applyConfig(); sync(); });
  const edited = () => { submitError = ""; for (const box of [urlError, routesError, widthsError]) if (!box.hidden) validate(); sync(); };
  urlInput.addEventListener("input", () => { checkUrl(); edited(); });
  for (const input of [routesInput, widthsInput, changedInput, nameInput]) input.addEventListener("input", edited);
  for (const input of [sessionSelect, localeSelect, statesBox, annotateBox]) input.addEventListener("change", sync);
  routesInput.value = form.routes;
  widthsInput.value = form.widths;
  annotateBox.checked = !!form.annotate;
  applyConfig();
  sync();
  (form.mode === "pages" ? routesInput : configs.length ? configSelect : urlInput).focus();  // not Start: Enter would launch it
}
