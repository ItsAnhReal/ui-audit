from pathlib import Path

from ui_audit.config import from_dict
from ui_audit.routes import discover, is_excluded, normalize, routes_from_source, same_origin_links


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
    touch(tmp_path, "src/pages/blog/[...slug].astro")
    found, dynamic = routes_from_source(tmp_path, {})
    assert found == ["/"] and dynamic == ["/blog/[...slug]"]
