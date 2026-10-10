"""Route discovery: config, source structure, sitemap, and same-origin crawl."""

from __future__ import annotations

import fnmatch
import gzip
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

SKIP_DIRS = {"node_modules", ".git", ".next", ".nuxt", ".svelte-kit", "dist", "build", "out",
             ".ui-audit", ".venv", "venv", "__pycache__", "coverage", ".turbo", ".vercel"}
PAGE_EXTS = {".tsx", ".jsx", ".ts", ".js", ".mdx", ".md"}
ASSET_EXTS = {".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp4", ".mp3",
              ".css", ".js", ".json", ".xml", ".txt", ".ico", ".woff", ".woff2"}
ROUTER_PATTERNS = [
    re.compile(r"""\bpath\s*:\s*["'](/[^"'\s]*)["']"""),
    re.compile(r"""<Route\b[^>]*\bpath\s*=\s*["'](/[^"'\s]*)["']"""),
]


# Code files that serve a non-HTML file when their name carries its extension (rss.xml.js).
ENDPOINT_EXTS = {".js", ".ts", ".mjs", ".mts"}
FILE_ROUTERS = {"next", "nuxt", "astro", "gatsby", "@remix-run/dev", "vite-plugin-pages", "vike",
                "unplugin-vue-router", "@react-router/fs-routes", "@react-router/dev", "@tanstack/router-plugin",
                "@docusaurus/core"}
# Packages whose apps route by the flat file names in app/routes (Remix 2, React Router 7).
FLAT_ROUTERS = {"@remix-run/dev", "@remix-run/react", "@react-router/fs-routes", "@react-router/dev"}
ROUTE_MODULE_EXTS = {".tsx", ".jsx", ".ts", ".js"}
# Sitemap indexes can nest; these bound how many files one discovery fetches and reads.
MAX_SITEMAPS = 10
MAX_SITEMAP_DEPTH = 2
MAX_SITEMAP_ROUTES = 2000
CLIENT_ROUTERS = {"react-router", "react-router-dom", "vue-router", "wouter", "@tanstack/react-router",
                  "@reach/router", "@solidjs/router", "preact-router"}
# Truncation keeps the most trustworthy routes: source conventions are guesses.
METHOD_RANK = {"cli": 0, "config": 0, "crawl": 1, "sitemap": 1, "source": 2, "default": 3}


@dataclass
class Route:
    path: str
    discovered_by: list[str] = field(default_factory=list)


@dataclass
class Discovery:
    routes: list[Route] = field(default_factory=list)
    skipped_dynamic: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Routes left unmeasured because max_routes was reached; the audit fills this in.
    truncated: list[str] = field(default_factory=list)

    def add(self, path: str, method: str) -> None:
        for route in self.routes:
            if route.path == path:
                if method not in route.discovered_by:
                    route.discovered_by.append(method)
                return
        self.routes.append(Route(path, [method]))


def normalize(path: str) -> str:
    """A route: the path without query, index file or trailing slash. A `#/route` or `#!/route`
    fragment is a hash router's page and stays (/#/settings); a plain `#anchor` is dropped."""
    if "://" in path:
        parsed = urlparse(path)
        path, fragment = parsed.path, parsed.fragment
    else:
        path, _, fragment = path.partition("#")
    path = path.split("?", maxsplit=1)[0] or "/"
    if not path.startswith("/"):
        path = "/" + path
    path = re.sub(r"/{2,}", "/", path)
    path = re.sub(r"/index\.html?$", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    hash_route = _hash_route(fragment)
    return f"{path}#{hash_route}" if hash_route else path


def _hash_route(fragment: str) -> str:
    """The client route in a `/route` or `!/route` fragment; "" for an in-page anchor or the start page."""
    match = re.match(r"(!?)(/.*)", fragment)
    if not match:
        return ""
    inner = re.sub(r"/{2,}", "/", re.split(r"[?#]", match.group(2), maxsplit=1)[0]).rstrip("/")
    return match.group(1) + inner if inner else ""


def base_path(base_url: str) -> str:
    """The path the app lives under, without the trailing slash ("" for an app at the root)."""
    return normalize(urlparse(base_url).path).split("#")[0].rstrip("/")


def route_of(base_url: str, url: str) -> str | None:
    """The route of a URL or site path relative to the app's base path; None outside it.
    Routes never carry the base path: url_for adds it back."""
    path = normalize(url)
    prefix = base_path(base_url)
    if not prefix:
        return path
    if path == prefix or path.startswith((prefix + "/", prefix + "#")):
        return normalize(path[len(prefix):])
    return None


def same_document(current: str, target: str) -> bool:
    """True when going from `current` to `target` only changes the fragment. That does not reload
    the page, so a hash router would carry the previous route's state over."""
    return "#" in target and current.split("#")[0] == target.split("#")[0]


def is_excluded(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _walk(root: Path, limit: int = 20000):
    count = 0
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
            else:
                count += 1
                if count > limit:
                    return
                yield entry


def _segments_to_route(segments: list[str]) -> tuple[str, bool]:
    """Convert file-system route segments; returns (route, is_dynamic)."""
    kept = []
    dynamic = False
    for segment in segments:
        if segment.startswith("(") and segment.endswith(")"):
            continue  # Next.js route group
        if segment.startswith("@"):
            return "", True  # parallel route slot
        if segment.startswith("_"):
            return "", True  # private folder
        if "[" in segment or segment.startswith(":"):
            dynamic = True
        kept.append(segment)
    return "/" + "/".join(kept), dynamic


def _package_names(root: Path) -> set[str]:
    """The dependencies package.json names (empty without one)."""
    try:
        package = json.loads((root / "package.json").read_text(errors="ignore"))
    except (OSError, ValueError):
        return set()
    if not isinstance(package, dict):
        return set()
    names: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        section = package.get(key)
        if isinstance(section, dict):
            names.update(section)
    return names


def uses_client_router_only(root: Path) -> bool:
    """True when package.json names a client-side router and no file-based one.

    In such apps `pages/` is just a folder of components: its file names are
    not URLs, and the route table is the only source of truth.
    """
    names = _package_names(root)
    return bool(names & CLIENT_ROUTERS) and not names & FILE_ROUTERS


def _flat_route(name: str) -> tuple[str, bool]:
    """Convert a Remix / React Router flat route name (concerts.$city, _auth.login, ($lang).about,
    sitemap[.]xml); returns (route, is_dynamic). Dots are slashes, brackets escape."""
    raw_segments, current, escaped = [], "", False
    for char in name:
        if char in "[]":
            escaped = char == "["
        elif char == "." and not escaped:
            raw_segments.append(current)
            current = ""
            continue
        current += char
    raw_segments.append(current)
    kept = []
    dynamic = False
    for raw in raw_segments:
        if not raw or raw.startswith("_"):
            continue  # _index, or a pathless layout such as _auth
        if raw.startswith("(") and raw.endswith(")"):
            continue  # optional segment: the URL without it works too
        if raw.endswith("_"):
            raw = raw[:-1]  # concerts_.mine: not nested in the concerts layout, same URL
        if raw.startswith("$"):
            dynamic = True
        kept.append(raw.replace("[", "").replace("]", ""))
    return "/" + "/".join(kept), dynamic


def routes_from_source(root: Path, samples: dict[str, str]) -> tuple[list[str], list[str]]:
    """Routes declared by common framework conventions under `root`."""
    found: list[str] = []
    dynamic: list[str] = []
    file_routed_pages = not uses_client_router_only(root)
    flat_routes = bool(_package_names(root) & FLAT_ROUTERS)

    def record(route: str, is_dynamic: bool) -> None:
        if not route:
            return
        route = normalize(route) if not is_dynamic else route
        if is_dynamic:
            if route in samples:
                found.append(normalize(samples[route]))
            elif route not in dynamic:
                dynamic.append(route)
        elif route not in found:
            found.append(route)

    for file in _walk(root):
        rel = file.relative_to(root)
        parts = list(rel.parts)
        name, suffix = file.stem, file.suffix

        # Next.js app router: app/**/page.tsx (also under src/)
        for base in (["app"], ["src", "app"]):
            if parts[: len(base)] == base and name == "page" and suffix in PAGE_EXTS:
                record(*_segments_to_route(parts[len(base):-1]))
        # Next.js pages router, Nuxt, Astro
        for base, exts in ((["pages"], PAGE_EXTS | {".vue"}), (["src", "pages"], PAGE_EXTS | {".vue", ".astro"})):
            if file_routed_pages and parts[: len(base)] == base and suffix in exts:
                inner = parts[len(base):-1]
                if inner and inner[0] == "api":
                    continue
                # An endpoint such as rss.xml.js or data.json.ts serves a file, not a page.
                if name.startswith("_") or ("." in name and suffix in ENDPOINT_EXTS and not name.startswith("[")):
                    continue
                segments = inner + ([] if name == "index" else [name])
                record(*_segments_to_route(segments))
        # Remix and React Router 7: app/routes/concerts.$city.tsx or app/routes/concerts.$city/route.tsx
        if flat_routes and parts[:2] == ["app", "routes"] and suffix in ROUTE_MODULE_EXTS:
            flat = name if len(parts) == 3 else parts[2] if len(parts) == 4 and name == "route" else None
            if flat is not None and flat.rsplit(".", 1)[-1] not in {"server", "client", "test", "spec", "stories"}:
                route, is_dynamic = _flat_route(flat)
                if Path(route).suffix.lower() not in ASSET_EXTS:  # a resource route such as sitemap[.]xml
                    record(route, is_dynamic)
        # SvelteKit: src/routes/**/+page.svelte
        if parts[:2] == ["src", "routes"] and name == "+page" and suffix == ".svelte":
            record(*_segments_to_route(parts[2:-1]))
        # Plain static sites: *.html in the root or public/
        if suffix == ".html" and (len(parts) == 1 or (len(parts) == 2 and parts[0] in {"public", "static", "site"})):
            record("/" if name == "index" else "/" + file.name, False)
        # React Router and similar route tables
        if suffix in {".tsx", ".jsx", ".ts", ".js"} and parts[0] == "src" and file.stat().st_size < 300_000:
            try:
                text = file.read_text(errors="ignore")
            except OSError:
                continue
            for pattern in ROUTER_PATTERNS:
                for match in pattern.finditer(text):
                    segments = [s for s in match.group(1).split("/") if s]
                    record(*_segments_to_route(segments))
    return found, dynamic


def _fetch(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - user-supplied local URL
        data = response.read()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def _on_audited_host(base_url: str, url: str) -> str:
    """`url` on the audited app's scheme and host: sitemaps usually name the production host."""
    base = urlparse(base_url)
    return urlparse(url)._replace(scheme=base.scheme, netloc=base.netloc).geturl()


def robots_sitemaps(base_url: str, timeout: float = 5.0) -> list[str]:
    """The sitemaps robots.txt names, moved to the audited host."""
    base = urlparse(base_url)
    robots = f"{base.scheme}://{base.netloc}/robots.txt"
    found: list[str] = []
    try:
        for line in _fetch(robots, timeout).decode("utf-8", "ignore").splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "sitemap" and value.strip():
                url = _on_audited_host(base_url, urljoin(robots, value.strip()))
                if url not in found:
                    found.append(url)
    except Exception:  # noqa: BLE001 - most apps have no robots.txt
        pass
    return found


def routes_from_sitemap(base_url: str, timeout: float = 5.0, errors: list[str] | None = None) -> list[str]:
    """Routes the app's sitemaps list. Sitemap indexes are followed a bounded number of levels and
    files. Entries naming another host (the production site) count by their path: the sitemaps
    are only ever fetched from the audited app. Problems go to `errors`; a missing sitemap is normal."""
    errors = [] if errors is None else errors
    listed = robots_sitemaps(base_url, timeout)
    default = urljoin(base_url.rstrip("/") + "/", "sitemap.xml")
    queue = [(url, 0) for url in listed + [default]]
    fetched: set[str] = set()
    paths: list[str] = []
    while queue and len(fetched) < MAX_SITEMAPS and len(paths) < MAX_SITEMAP_ROUTES:
        url, depth = queue.pop(0)
        if url in fetched:
            continue
        fetched.add(url)
        try:
            tree = ET.fromstring(_fetch(url, timeout))
        except urllib.error.HTTPError as exc:
            if exc.code != 404 or url != default or default in listed:  # no sitemap.xml at all is normal
                errors.append(f"sitemap: HTTP {exc.code} for {urlparse(url).path}")
            continue
        except Exception as exc:  # noqa: BLE001 - discovery must not fail on a sitemap
            errors.append(f"sitemap: {exc.__class__.__name__} for {urlparse(url).path}")
            continue
        # <urlset><url><loc> or <sitemapindex><sitemap><loc>; image and video <loc>s sit deeper.
        locs = [loc.text.strip() for entry in tree for loc in entry
                if loc.tag.rsplit("}", 1)[-1] == "loc" and loc.text and loc.text.strip()]
        if tree.tag.rsplit("}", 1)[-1] == "sitemapindex":
            if depth < MAX_SITEMAP_DEPTH:
                queue.extend((_on_audited_host(base_url, urljoin(url, loc)), depth + 1) for loc in locs)
            continue
        for loc in locs:
            parsed = urlparse(urljoin(url, loc))
            route = route_of(base_url, parsed.path)
            if route is not None and route not in paths and Path(parsed.path).suffix.lower() not in ASSET_EXTS:
                paths.append(route)
    return paths[:MAX_SITEMAP_ROUTES]


def same_origin_links(base_url: str, page_url: str, hrefs: list[str]) -> list[str]:
    """Routes the links point to: same origin, under the base path, not a file. Links to a hash
    router's pages (#/settings) are routes too, plain in-page anchors are not."""
    origin = urlparse(base_url).netloc
    paths = []
    for href in hrefs:
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        if href.startswith("#") and not _hash_route(href[1:]):
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or parsed.netloc != origin:
            continue
        if Path(parsed.path).suffix.lower() in ASSET_EXTS:
            continue
        route = route_of(base_url, absolute)
        if route is not None:
            paths.append(route)
    return paths


def crawl(page, base_url: str, depth: int, limit: int, exclude: list[str]) -> list[str]:
    """Breadth-first crawl of same-origin links using an open Playwright page."""
    seen = ["/"]
    frontier = ["/"]
    for _ in range(depth):
        next_frontier = []
        for path in frontier:
            url = urljoin(base_url.rstrip("/") + "/", "./" + path.lstrip("/"))
            try:
                if same_document(page.url, url):
                    page.goto("about:blank")  # a fresh load, so the hash router renders this route alone
                page.goto(url, wait_until="load", timeout=15000)
                try:  # client-rendered apps add their links after the document has loaded
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:  # noqa: BLE001 - long-polling apps never go idle
                    pass
                hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
            except Exception:  # noqa: BLE001 - a broken page must not stop discovery
                continue
            for link in same_origin_links(base_url, page.url, hrefs):
                if link not in seen and not is_excluded(link, exclude):
                    seen.append(link)
                    next_frontier.append(link)
                    if len(seen) >= limit:
                        return seen
        frontier = next_frontier
    return seen


def discover(cfg, page=None, only: list[str] | None = None) -> Discovery:
    """Run the configured discovery methods. `only` restricts to explicit routes."""
    result = Discovery()
    rc = cfg.routes
    if only:
        for path in only:
            result.add(normalize(path), "cli")
        return result
    methods = rc.discover
    if "config" in methods:
        for path in rc.include:
            result.add(normalize(path), "config")
    if "source" in methods:
        try:
            found, dynamic = routes_from_source(Path(cfg.project_root), rc.samples)
            for path in found:
                result.add(path, "source")
            result.skipped_dynamic = dynamic
        except OSError as exc:
            result.errors.append(f"source: {exc}")
    if "sitemap" in methods:
        for path in routes_from_sitemap(cfg.base_url, errors=result.errors):
            result.add(path, "sitemap")
    if "crawl" in methods and page is not None:
        for path in crawl(page, cfg.base_url, rc.crawl_depth, rc.max_routes * 2, rc.exclude):
            result.add(path, "crawl")
    if not result.routes:
        result.add("/", "default")
    kept = [r for r in result.routes if not is_excluded(r.path, rc.exclude)]
    # Every candidate is returned, most trustworthy first. max_routes counts routes that are
    # measured, so the audit applies it: a route that turns out to be a redirect, a repeat or
    # the not-found page costs one page load, not a place in the budget.
    kept.sort(key=lambda r: min(METHOD_RANK.get(m, 3) for m in r.discovered_by))  # stable
    result.routes = kept
    return result
