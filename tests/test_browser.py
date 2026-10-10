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
