from ui_audit.browser import RuntimeLog


def test_runtime_log_keeps_failures_and_drops_noise():
    log = RuntimeLog()
    log.on_failure("http://app.test/favicon.ico", "404")
    log.on_failure("http://app.test/api/orders?x=1", "net::ERR_ABORTED")
    log.on_failure("http://app.test/api/orders", "500")
    assert log.failed_resources == ["http://app.test/api/orders (500)"]
