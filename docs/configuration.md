# Configuration reference

`ui-audit` reads `ui-audit.toml` from the current folder or the nearest parent folder (`--config <file>` picks another). Every key is optional; the defaults below apply when it is left out. `ui-audit init` writes a starting file.

An unknown key, a number out of range or a malformed table is a config error (exit code 2) that names the key, so a typo never silently does nothing.

## Environment variables

Any string can use `${VAR}`, read from the environment when the file is loaded:

```toml
base_url = "${STAGING_URL}"
headers = { "X-Preview-Token" = "${PREVIEW_TOKEN}" }
```

- `${VAR:-default}` uses `default` when `VAR` is unset or empty.
- `$${VAR}` is the literal text `${VAR}`.
- An unset variable without a default is a config error naming the variable and the key.

`report.json` stores the settings a run used, with values from the environment written as their `${VAR}`, never their value. Secrets written straight into the file (`headers` values, `http_credentials.password`) are stored as `<redacted>`. Re-running such a report (`audit --like`, the app's "run again" and re-check) reads the variables again from the environment. A redacted secret cannot be re-run, so write secrets as `${VAR}`.

## Top level

| Key | Default | Meaning |
|---|---|---|
| `base_url` | `"http://localhost:3000"` | The running app. Routes are relative to it, also when it has a path (`http://host/app/`). |
| `project_root` | `"."` | The app's source, for route discovery and source hints. Relative to the config file. |
| `output` | `".ui-audit/latest"` | Where `report.json`, `index.html` and the screenshots go. |
| `annotate` | `true` | Also save each screenshot with the findings drawn on it. |
| `storage_state` | `""` | Playwright storage state (cookies, local storage) for pages behind a login; `ui-audit login` writes one. |
| `browser_path` | `""` | A Chromium executable to use instead of Playwright's own. |
| `browsers` | `["chromium"]` | Engines to audit in: `chromium`, `webkit` (Safari's engine, alias `safari`), `firefox`. The first one finds routes and states. |
| `settle_ms` | `150` | Extra wait in milliseconds after loading a page or opening a state. |
| `locale` | `""` | Browser language, e.g. `"de"` or `"fr-FR"`. Empty keeps Chromium's default (en-US). |
| `accepted_file` | `"ui-audit.accepted.json"` | Findings accepted as intentional, relative to `project_root`. |
| `setup` | `[]` | [Actions](#actions) run on `/` before anything is measured, and again on every page loaded. |
| `block_requests` | `["trackers"]` | Requests turned away. `"trackers"` stands for analytics that render nothing; `"third-party"` adds ad networks and tag managers (they can render boxes, so it is off by default); anything else is a host name, matched with its subdomains. `[]` blocks nothing. The app's own host is never blocked. |
| `workers` | `1` | Routes measured at the same time, each in a browser of its own (0 to 16); `0` picks from the CPU count. |
| `headers` | `{}` | HTTP headers sent with every request to the app's own origin (scheme, host and port of `base_url`), never to other hosts. Also sent when sitemaps are fetched. |
| `http_credentials` | `{}` | Basic auth for a staging server: `{ username = "...", password = "${STAGING_PASSWORD}" }`. Sent to the app's origin only, also for sitemaps and `ui-audit login`. |
| `ignore_https_errors` | `false` | Accept self-signed and otherwise invalid certificates. |

A request that fails on an analytics, ad or tag-manager host (Google Tag Manager, DoubleClick, Hotjar, Facebook, …) is never reported as `failed-resource`, whether it was blocked or not: whether they load is up to them, not the app.

## [routes]

| Key | Default | Meaning |
|---|---|---|
| `include` | `[]` | Routes to audit, always first. |
| `exclude` | `["/logout*", "/signout*", "/api/*"]` | Patterns never audited (`*` matches anything). |
| `discover` | `["config", "source", "sitemap", "crawl"]` | Where routes come from: this file, framework conventions in `project_root`, sitemaps, a same-origin crawl. |
| `samples` | `{}` | Concrete values for dynamic routes: `{ "/blog/[slug]" = "/blog/hello-world" }`. |
| `max_routes` | `25` | Routes measured at most. Skipped routes do not count. |
| `crawl_depth` | `2` | Link levels the crawl follows. |
| `dedupe` | `true` | Skip routes that render the not-found page, redirect to, or repeat a route already audited. |

### [[routes.overrides]]

Settings for some routes only. `route` is a route or a pattern (`*` matches anything); every matching override applies.

```toml
[[routes.overrides]]
route = "/admin/*"
widths = [1280, 1920]          # only these widths, instead of the sweep
ignore_selectors = [".chart"]  # added to [checks] ignore_selectors
```

| Key | Meaning |
|---|---|
| `route` | Required. The route or pattern. |
| `widths` | Widths that replace the sweep on these routes, like `[viewports] widths`. The first matching override with widths wins. |
| `ignore_selectors` | Elements left out on these routes, on top of `[checks] ignore_selectors`. |

## [states]

| Key | Default | Meaning |
|---|---|---|
| `auto` | `true` | Discover menus, tabs, dialogs and `<details>` by clicking disclosure controls (never forms, links or destructive-sounding controls). |
| `max_per_route` | `4` | Discovered states per route at most. |
| `unsafe_words` | `[]` | More words that keep a control from being clicked automatically (whole words). |
| `dismiss_consent` | `true` | Turn optional cookies down once, so a consent banner does not cover every page. |
| `sweep` | `"full"` | `"key"` probes opened states only at the presets, the breakpoints and the widths where the initial page changed. |
| `custom` | `[]` | States you define, see below. |

### [[states.custom]]

```toml
[[states.custom]]
name = "cart-open"
route = "/shop"
applies_to = "any"      # "narrow" (below 1024px), "wide" (768px and up) or "any"
actions = [{ click = "#cart" }, { wait_for = ".cart-drawer" }]
```

When a step fails, the state is skipped and both its status in `report.json` and `errors` say which step failed and why, e.g. `step 2 (click '#cart') failed: not on the page or not visible`.

### Actions

Used by `setup` and `[[states.custom]]`. Each action is a table with exactly one of these keys:

| Action | Example | What it does |
|---|---|---|
| `click` | `{ click = "#menu" }` | Clicks the first visible match. |
| `hover` | `{ hover = ".nav-item" }` | Moves the pointer over it. |
| `fill` | `{ fill = "#search", value = "shoes" }` | Types into a field. |
| `select` | `{ select = "#size", value = "m" }` | Picks an option by value or label; `value` can be a list for multi-selects. |
| `check` / `uncheck` | `{ check = "#terms" }` | Ticks or clears a checkbox or radio button. |
| `press` | `{ press = "Escape" }` | Presses a key. |
| `scroll` | `{ scroll = "#footer" }`, `{ scroll = 800 }` | Scrolls an element into view, or the page to that many pixels from the top. |
| `goto` | `{ goto = "/cart?step=2" }` | Opens a route of the app. |
| `wait` | `{ wait = 500 }` | Waits that many milliseconds. |
| `wait_for` | `{ wait_for = ".drawer" }` | Waits until the element exists. |
| `wait_for_url` | `{ wait_for_url = "/cart" }`, `{ wait_for_url = "**/done*" }` | Waits until the address is that route, or matches that pattern. |

Selectors are Playwright selectors (CSS, or `text=...`, `role=...`).

## [viewports]

| Key | Default | Meaning |
|---|---|---|
| `min_width` / `max_width` | `320` / `1920` | The width range swept. |
| `sweep_step` | `80` | Pixels between swept widths. |
| `breakpoint_neighbors` | `true` | Also probe each CSS breakpoint and one pixel on both sides of it. |
| `refine` | `true` | Search for the exact width where a defect starts or ends. |
| `max_refinements` | `6` | Extra probes spent on that search, per state. |
| `max_captures` | `10` | Screenshots per state at most. |
| `mobile_below` | `768` | Widths below this are measured as a phone (meta viewport, touch, `hover: none`); `0` turns it off. Firefox stays a desktop browser. |
| `widths` | `[]` | Explicit widths that replace the sweep (targeted reruns). |

## [checks]

| Key | Default | Meaning |
|---|---|---|
| `min_target_size` | `24` | Smallest pointer target in pixels for `small-target`. |
| `overlap_threshold` | `0.2` | Share of the smaller control two controls must overlap by for `overlapping-controls` (0 to 1). |
| `max_issues_per_check` | `15` | Findings reported per check and width at most; `verify` does not count findings as fixed where a check hit this cap. |
| `ignore_selectors` | `[]` | Elements (and everything inside them) left out of every check. |
| `disable` | `[]` | Checks neither run nor reported, e.g. `["tiny-text"]`. |
| `severity` | `{}` | Severity per check instead of the measured one: `{ "small-target" = "P3" }`. |
| `rules` | `[]` | Checks of your own, see below. |

`disable` and `severity` take the check names listed in the README, plus `rule:<name>` for your rules; any other name is a config error.

### Rule files

A rule is a JavaScript file, relative to `project_root`, holding one function. It runs in the page at every probed width and state, after the built-in checks, and returns findings:

```js
// rules/autoplay-video.js: videos that start playing on their own.
(context) => Array.from(document.querySelectorAll("video[autoplay]")).map((element) => ({
  element,                        // or selector: "#promo"
  severity: "P3",                 // P1, P2 or P3; P2 when left out
  message: `Video plays on its own at ${context.width}px.`,
}));
```

```toml
[checks]
rules = ["rules/autoplay-video.js"]
```

- `context` holds the viewport's `width` and `height`. The function may be `async`.
- Each finding names an `element` or a `selector`, a `message`, and optionally a `severity`. With an element, the selector, box and source hints are worked out as for built-in findings; a given `selector` is kept as it is, which keeps the finding's signature stable.
- Findings are reported as check `rule:<file name>` (here `rule:autoplay-video`) with `origin: "rule"`, so they are never mistaken for built-in measurements. They go through everything a built-in finding does: `ignore_selectors`, `max_issues_per_check`, `disable`, `severity`, screenshots, `verify` and `accept`.
- A rule must not change the page. A rule that throws is reported in `errors` once per state, and the audit goes on.

## [timeouts]

All in milliseconds.

| Key | Default | Meaning |
|---|---|---|
| `navigation` | `30000` | How long a page may take to load. |
| `network_idle` | `5000` | How long to wait after loading for the network to go quiet; `0` does not wait. Long-polling apps never go quiet, so this is a cap, not an error. |
| `action` | `3000` | How long a `click`, `hover`, `fill`, `select`, `check`, `uncheck` or `scroll` waits for its element. |
| `wait_for` | `5000` | How long `wait_for` and `wait_for_url` wait. |
