"""Route discovery: config, source structure, sitemap, and same-origin crawl."""

from __future__ import annotations

import fnmatch
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


@dataclass
class Route:
    path: str
    discovered_by: list[str] = field(default_factory=list)


@dataclass
class Discovery:
    routes: list[Route] = field(default_factory=list)
    skipped_dynamic: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(self, path: str, method: str) -> None:
        for route in self.routes:
            if route.path == path:
                if method not in route.discovered_by:
                    route.discovered_by.append(method)
                return
        self.routes.append(Route(path, [method]))


def normalize(path: str) -> str:
    if "://" in path:
        path = urlparse(path).path
    path = re.split(r"[?#]", path, maxsplit=1)[0] or "/"
    if not path.startswith("/"):
        path = "/" + path
    path = re.sub(r"/{2,}", "/", path)
    path = re.sub(r"/index\.html?$", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


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


def routes_from_source(root: Path, samples: dict[str, str]) -> tuple[list[str], list[str]]:
    """Routes declared by common framework conventions under `root`."""
    found: list[str] = []
    dynamic: list[str] = []

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
            if parts[: len(base)] == base and suffix in exts:
                inner = parts[len(base):-1]
                if inner and inner[0] == "api":
                    continue
                if name.startswith("_"):
                    continue
                segments = inner + ([] if name == "index" else [name])
                record(*_segments_to_route(segments))
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


def routes_from_sitemap(base_url: str, timeout: float = 5.0) -> list[str]:
    url = urljoin(base_url.rstrip("/") + "/", "sitemap.xml")
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - user-supplied local URL
        tree = ET.fromstring(response.read())
    origin = urlparse(base_url).netloc
    paths = []
    for loc in tree.iter():
        if loc.tag.endswith("loc") and loc.text:
            parsed = urlparse(loc.text.strip())
            if parsed.netloc in ("", origin):
                paths.append(normalize(parsed.path))
    return paths


def same_origin_links(base_url: str, page_url: str, hrefs: list[str]) -> list[str]:
    origin = urlparse(base_url).netloc
    paths = []
    for href in hrefs:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or parsed.netloc != origin:
            continue
        if Path(parsed.path).suffix.lower() in ASSET_EXTS:
            continue
        paths.append(normalize(parsed.path))
    return paths


def crawl(page, base_url: str, depth: int, limit: int, exclude: list[str]) -> list[str]:
    """Breadth-first crawl of same-origin links using an open Playwright page."""
    seen = ["/"]
    frontier = ["/"]
    for _ in range(depth):
        next_frontier = []
        for path in frontier:
            url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
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
        try:
            for path in routes_from_sitemap(cfg.base_url):
                result.add(path, "sitemap")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:  # a missing sitemap is normal
                result.errors.append(f"sitemap: HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001 - discovery must not fail on the sitemap
            result.errors.append(f"sitemap: {exc.__class__.__name__}")
    if "crawl" in methods and page is not None:
        for path in crawl(page, cfg.base_url, rc.crawl_depth, rc.max_routes, rc.exclude):
            result.add(path, "crawl")
    if not result.routes:
        result.add("/", "default")
    result.routes = [r for r in result.routes if not is_excluded(r.path, rc.exclude)][: rc.max_routes]
    return result
