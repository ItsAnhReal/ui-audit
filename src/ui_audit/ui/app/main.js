/* Start: load the state, then render. */

// ---------------------------------------------------------------- start

async function start() {
  if (!IS_APP && !DATA) {
    root.replaceChildren(h("main", { class: "main" }, h("div", { class: "card" }, emptyState("alert", t("error.title"), t("error.noData")))));
    return;
  }
  if (IS_APP) {
    await refreshState();
    schedule();
  }
  await render();
}
start();
