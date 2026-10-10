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
