from ui_audit.browser import RuntimeLog, Session


def test_runtime_log_keeps_failures_and_drops_noise():
    log = RuntimeLog()
    log.on_failure("http://app.test/favicon.ico", "404")
    log.on_failure("http://app.test/api/orders?x=1", "net::ERR_ABORTED")
    log.on_failure("http://app.test/api/orders", "500")
    assert log.failed_resources == ["http://app.test/api/orders (500)"]


class FakeContext:
    closed = False

    def close(self):
        self.closed = True


def test_session_measures_narrow_widths_on_a_phone_page_opened_once():
    opened = []

    def opener():
        opened.append((FakeContext(), object()))
        return opened[-1]

    session = Session("desktop", RuntimeLog(), opener, 768)
    page, log = session
    assert page == "desktop" and session.page_for(768) == "desktop" and not opened
    phone = session.page_for(390)
    assert session.page_for(320) is phone and len(opened) == 1
    session.reset_mobile()
    assert opened[0][0].closed and session.page_for(390) is not phone
    assert Session("desktop", RuntimeLog()).page_for(390) == "desktop"  # Firefox, or mobile_below = 0


def test_trackers_and_named_hosts_are_blocked_but_never_the_app():
    from ui_audit.browser import blocked_requests

    pattern = blocked_requests(["trackers", "Ads.Example"], "http://localhost:3000")
    assert pattern.search("https://www.google-analytics.com/g/collect?v=2")
    assert pattern.search("https://region1.analytics.google.com/g/collect")
    assert pattern.search("https://ads.example:8443/x.js") and pattern.search("https://cdn.ads.example/")
    assert not pattern.search("https://notgoogle-analytics.com/a.js")
    assert not pattern.search("https://example.com/?u=https://www.google-analytics.com/")
    assert not pattern.search("http://localhost:3000/plausible.io.js")
    assert blocked_requests([], "http://localhost") is None
    assert blocked_requests(["app.test"], "http://www.app.test/") is None

    log = RuntimeLog(blocked=pattern)
    log.on_failure("https://www.google-analytics.com/analytics.js", "net::ERR_BLOCKED_BY_CLIENT")
    log.on_failure("https://cdn.example.org/lib.js", "net::ERR_NAME_NOT_RESOLVED")
    assert log.failed_resources == ["https://cdn.example.org/lib.js (net::ERR_NAME_NOT_RESOLVED)"]


def test_failed_requests_to_ads_and_analytics_are_not_the_apps():
    from ui_audit.browser import blocked_requests

    log = RuntimeLog(third_party=blocked_requests(["trackers", "third-party"], "http://localhost:3000"))
    log.on_failure("https://www.googletagmanager.com/gtm.js?id=GTM-X", "net::ERR_NAME_NOT_RESOLVED")
    log.on_failure("https://securepubads.g.doubleclick.net/tag/js/gpt.js", "404")
    log.on_failure("https://www.google-analytics.com/g/collect", "net::ERR_FAILED")
    log.on_failure("http://localhost:3000/api/data", "500")
    assert log.failed_resources == ["http://localhost:3000/api/data (500)"]


class RecordingContext:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.calls.append((name, args))


def test_contexts_get_auth_for_the_app_origin_timeouts_and_headers():
    from ui_audit.browser import context_options, prepare
    from ui_audit.config import from_dict

    cfg = from_dict({"base_url": "https://staging.example/app/", "ignore_https_errors": True,
                     "http_credentials": {"username": "u", "password": "p"}, "headers": {"X-A": "1"},
                     "timeouts": {"navigation": 12345}})
    options = context_options(cfg)
    assert options["http_credentials"] == {"username": "u", "password": "p", "origin": "https://staging.example"}
    assert options["ignore_https_errors"] is True
    assert "http_credentials" not in context_options(from_dict({}))
    context = RecordingContext()
    prepare(context, cfg)
    assert ("set_default_navigation_timeout", (12345,)) in context.calls
    routes = [args[0] for name, args in context.calls if name == "route"]
    assert routes == ["https://staging.example/**"]  # headers for the app's origin; nothing blocked
