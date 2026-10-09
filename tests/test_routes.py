import functools
import http.server
import threading
from pathlib import Path

import pytest

from ui_audit.audit import _skip_reason
from ui_audit.browser import url_for
from ui_audit.config import from_dict
from ui_audit.routes import (base_path, discover, is_excluded, normalize, route_of, routes_from_sitemap,
                             routes_from_source, same_document, same_origin_links)


def touch(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_normalize():
    assert normalize("") == "/"
    assert normalize("pricing/") == "/pricing"
    assert normalize("//a//b/") == "/a/b"
    assert normalize("/index.html") == "/"
    assert normalize("/docs/index.html") == "/docs"
    assert normalize("http://x.test/a?b=1#c") == "/a"


def test_is_excluded():
    assert is_excluded("/logout", ["/logout*"])
    assert is_excluded("/api/users", ["/api/*"])
    assert not is_excluded("/pricing", ["/api/*"])


def test_next_app_router_groups_and_dynamic(tmp_path):
    touch(tmp_path, "app/page.tsx")
    touch(tmp_path, "app/(marketing)/pricing/page.tsx")
    touch(tmp_path, "app/dashboard/settings/page.tsx")
    touch(tmp_path, "app/blog/[slug]/page.tsx")
    touch(tmp_path, "app/@modal/login/page.tsx")
    touch(tmp_path, "app/_components/thing/page.tsx")
    touch(tmp_path, "node_modules/pkg/app/hidden/page.tsx")
    found, dynamic = routes_from_source(tmp_path, {})
    assert set(found) == {"/", "/pricing", "/dashboard/settings"}
    assert dynamic == ["/blog/[slug]"]

    found, dynamic = routes_from_source(tmp_path, {"/blog/[slug]": "/blog/hello"})
    assert "/blog/hello" in found and dynamic == []


def test_pages_router_sveltekit_static_and_react_router(tmp_path):
    touch(tmp_path, "pages/index.tsx")
    touch(tmp_path, "pages/about.tsx")
    touch(tmp_path, "pages/_app.tsx")
    touch(tmp_path, "pages/api/hello.ts")
    touch(tmp_path, "src/routes/+page.svelte")
    touch(tmp_path, "src/routes/contact/+page.svelte")
    touch(tmp_path, "public/landing.html")
    touch(tmp_path, "src/router.tsx", '<Route path="/settings" element={<S/>} />\nconst r = [{ path: "/reports/:id" }]')
    found, dynamic = routes_from_source(tmp_path, {})
    assert {"/", "/about", "/contact", "/landing.html", "/settings"} <= set(found)
    assert "/api/hello" not in found and "/_app" not in found
    assert dynamic == ["/reports/:id"]


def test_same_origin_links():
    hrefs = ["/a", "b", "#top", "mailto:x@y", "https://other.test/x", "/file.pdf", "http://app.test/c/"]
    assert same_origin_links("http://app.test", "http://app.test/dir/page", hrefs) == ["/a", "/dir/b", "/c"]


def test_client_router_app_ignores_page_file_names(tmp_path):
    touch(tmp_path, "package.json", '{"dependencies": {"react-router-dom": "^6"}, "devDependencies": {"vite": "^5"}}')
    touch(tmp_path, "src/pages/AccountBilling.tsx")
    touch(tmp_path, "src/pages/Index.tsx")
    touch(tmp_path, "src/App.tsx", '<Route path="/billing" element={<AccountBilling/>} />')
    found, _ = routes_from_source(tmp_path, {})
    assert found == ["/billing"]

    # With a file-based router next to it, src/pages is the route table again.
    touch(tmp_path, "package.json", '{"dependencies": {"react-router-dom": "^6", "astro": "^4"}}')
    found, _ = routes_from_source(tmp_path, {})
    assert set(found) == {"/AccountBilling", "/Index", "/billing"}


def test_configured_routes_rank_before_source_guesses(tmp_path):
    touch(tmp_path, "pages/a.tsx")
    touch(tmp_path, "pages/b.tsx")
    cfg = from_dict({"project_root": str(tmp_path),
                     "routes": {"include": ["/z"], "discover": ["source", "config"], "max_routes": 2}})
    result = discover(cfg)
    # Ranked, not cut: the audit spends max_routes on routes it actually measures.
    assert [r.path for r in result.routes] == ["/z", "/a", "/b"]


def test_endpoints_that_serve_files_are_not_pages(tmp_path):
    touch(tmp_path, "package.json", '{"dependencies": {"astro": "^5"}}')
    touch(tmp_path, "src/pages/index.astro")
    touch(tmp_path, "src/pages/rss.xml.js")
    touch(tmp_path, "src/pages/legal.notice.astro")  # a page whose name has a dot
    touch(tmp_path, "src/pages/blog/[...slug].astro")
    found, dynamic = routes_from_source(tmp_path, {})
    assert sorted(found) == ["/", "/legal.notice"] and dynamic == ["/blog/[...slug]"]


def test_hash_routes_stay_and_anchors_go():
    assert normalize("http://x.test/#/settings") == "/#/settings"
    assert normalize("/#!/users//42/?tab=1") == "/#!/users/42"
    assert normalize("/app.html#/a/") == "/app.html#/a"
    assert normalize("/docs#install") == "/docs"
    assert normalize("/#/") == "/" and normalize("/#") == "/"


def test_routes_are_relative_to_the_base_path():
    base = "http://h/app/"
    assert base_path(base) == "/app" and base_path("http://h") == "" and base_path("http://h/app") == "/app"
    assert route_of(base, "http://h/app/x/") == "/x"
    assert route_of(base, "http://h/app") == "/" and route_of(base, "/app/") == "/"
    assert route_of(base, "http://h/app/#/settings") == "/#/settings"
    assert route_of(base, "http://h/other") is None and route_of(base, "/application") is None
    assert url_for(base, "/x") == "http://h/app/x" and url_for(base, "/") == "http://h/app/"
    assert url_for(base, "/#/settings") == "http://h/app/#/settings"
    assert url_for("http://h", "/a:b") == "http://h/a:b"


def test_links_under_a_base_path_and_hash_router_links():
    hrefs = ["/app/x", "y", "/other", "/app", "#top", "#/settings", "#!/users", "/app/#/billing"]
    assert same_origin_links("http://h/app/", "http://h/app/page", hrefs) == [
        "/x", "/y", "/", "/page#/settings", "/page#!/users", "/#/billing"]
    assert same_origin_links("http://h", "http://h/#/home", ["#/a", "#b"]) == ["/#/a"]


def test_only_a_fragment_change_needs_a_fresh_load():
    assert same_document("http://h/#/a", "http://h/#/b")
    assert same_document("http://h/", "http://h/#/b")
    assert not same_document("http://h/#/a", "http://h/")
    assert not same_document("http://h/a", "http://h/b#/c")


class FakePage:
    def __init__(self, url, fingerprint):
        self.url, self.fingerprint = url, fingerprint

    def evaluate(self, _script):
        return self.fingerprint


def test_redirects_are_recognised_under_a_base_path():
    seen_pages, seen_paths = {}, {}
    base = "http://h/app/"
    assert _skip_reason(FakePage("http://h/app/home", "5:home"), None, "/home", None, seen_pages, seen_paths,
                        base_url=base) is None
    assert _skip_reason(FakePage("http://h/app/home", "5:other"), None, "/start", None, seen_pages, seen_paths,
                        base_url=base) == "redirects to /home"
    # A page outside the app's path matches no route.
    assert _skip_reason(FakePage("http://h/home", "5:login"), None, "/x", None, seen_pages, seen_paths,
                        base_url=base) is None


def test_remix_flat_routes(tmp_path):
    touch(tmp_path, "package.json",
          '{"dependencies": {"@remix-run/react": "^2"}, "devDependencies": {"@remix-run/dev": "^2"}}')
    for name in ["_index.tsx", "about.tsx", "concerts.$city.tsx", "concerts.trending.tsx", "concerts_.mine.tsx",
                 "_auth.login.tsx", "($lang).pricing.tsx", "sitemap[.]xml.tsx", "legal[.]notice.tsx",
                 "app.server.ts", "$.tsx", "settings/route.tsx", "settings/form.tsx", "users.$id.edit/route.jsx"]:
        touch(tmp_path, f"app/routes/{name}")
    found, dynamic = routes_from_source(tmp_path, {"/concerts/$city": "/concerts/berlin"})
    assert sorted(found) == ["/", "/about", "/concerts/berlin", "/concerts/mine", "/concerts/trending",
                             "/legal.notice", "/login", "/pricing", "/settings"]
    assert sorted(dynamic) == ["/$", "/users/$id/edit"]

    # Without Remix or React Router, app/routes is just a folder.
    touch(tmp_path, "package.json", '{"dependencies": {"next": "^15"}}')
    found, _ = routes_from_source(tmp_path, {})
    assert found == []


@pytest.fixture
def site(tmp_path):
    """A directory served on a free port: (url, directory)."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path
    server.shutdown()
    server.server_close()


URLSET = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{}</urlset>'
INDEX = '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{}</sitemapindex>'


def entries(tag, locs):
    return "".join(f"<{tag}><loc>{loc}</loc></{tag}>" for loc in locs)


def test_sitemap_index_production_host_and_robots(site):
    url, root = site
    touch(root, "robots.txt", "User-agent: *\nSitemap: https://shop.example/sitemaps/index.xml\n")
    touch(root, "sitemaps/index.xml", INDEX.format(entries("sitemap", [
        "https://shop.example/sitemaps/pages.xml", "https://shop.example/sitemaps/nested.xml"])))
    touch(root, "sitemaps/pages.xml", URLSET.format(entries("url", [
        "https://shop.example/", "https://shop.example/pricing/", f"{url}/about",
        "https://shop.example/brochure.pdf"])))
    touch(root, "sitemaps/nested.xml", INDEX.format(entries("sitemap", ["https://shop.example/sitemaps/blog.xml"])))
    touch(root, "sitemaps/blog.xml", URLSET.format(entries("url", ["https://shop.example/blog/first"])))
    errors = []
    # The production host's paths count on the audited app; the index files are not routes.
    assert routes_from_sitemap(url, errors=errors) == ["/", "/pricing", "/about", "/blog/first"]
    assert errors == []


def test_sitemap_under_a_base_path(site):
    url, root = site
    touch(root, "app/sitemap.xml", URLSET.format(entries("url", [
        "https://shop.example/app/", "https://shop.example/app/team", "https://shop.example/blog"])))
    errors = []
    assert routes_from_sitemap(f"{url}/app/", errors=errors) == ["/", "/team"]
    assert errors == []


def test_missing_sitemap_is_not_an_error_but_a_listed_one_is(site):
    url, root = site
    errors = []
    assert routes_from_sitemap(url, errors=errors) == [] and errors == []
    touch(root, "robots.txt", "Sitemap: /sitemap.xml\n")
    assert routes_from_sitemap(url, errors=errors) == []
    assert errors == ["sitemap: HTTP 404 for /sitemap.xml"]


def test_sitemap_index_depth_is_bounded(site):
    url, root = site
    touch(root, "sitemap.xml", INDEX.format(entries("sitemap", ["/a.xml"])))
    touch(root, "a.xml", INDEX.format(entries("sitemap", ["/b.xml"])))
    touch(root, "b.xml", INDEX.format(entries("sitemap", ["/c.xml"])))
    touch(root, "c.xml", URLSET.format(entries("url", ["/deep"])))
    assert routes_from_sitemap(url) == []


HASH_APP = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Hash app</title><style>
body { margin: 0; font: 16px/1.5 sans-serif; } nav a { display: inline-block; padding: 12px; }
</style></head><body>
<nav><a href="#/">Home</a> <a href="#/settings">Settings</a> <a href="#/about">About</a> <a href="#top">Top</a>
<a href="/elsewhere.html">Elsewhere</a></nav><main id="view"></main>
<script>
const views = {"/": "<h1>Home</h1>", "/settings": "<h1>Settings</h1><p>Your account.</p>",
               "/about": "<h1>About</h1><p>Who we are.</p><p>Since 2020.</p>"};
const render = () => { const v = views[location.hash.slice(1) || "/"];
  document.getElementById("view").innerHTML = v || "<h1>Page not found</h1>"; };
addEventListener("hashchange", render); render();
</script></body></html>"""


@pytest.mark.e2e
@pytest.mark.usefixtures("chromium_available")
def test_hash_router_app_under_a_base_path(demo_site, tmp_path):
    from ui_audit import audit

    url, site = demo_site
    touch(site, "app/index.html", HASH_APP)
    cfg = from_dict({"base_url": f"{url}/app/", "project_root": str(tmp_path / "empty"),
                     "output": str(tmp_path / "run"), "settle_ms": 50,
                     "routes": {"discover": ["crawl"]}, "states": {"auto": False}, "viewports": {"widths": [390]}})
    report = audit.run(cfg, log=lambda _: None)
    status = {r["path"]: r["status"] for r in report["routes"]}
    # Each hash route is its own page, loaded fresh under /app/; the link outside /app/ is not a route.
    assert status == {"/": "audited", "/#/settings": "audited", "/#/about": "audited"}


def test_hash_routes_get_their_own_screenshot_names():
    from ui_audit.audit import _file_slug

    assert _file_slug("/settings") == "settings"
    assert _file_slug("/#/settings") != _file_slug("/settings")
    assert _file_slug("/") == "root"
