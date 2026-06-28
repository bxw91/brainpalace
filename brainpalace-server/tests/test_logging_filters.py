"""The uvicorn access log must not record health-check polling: it was 95%
of the stdout log volume (a /health/ hit every couple seconds)."""

import logging

from brainpalace_server.logging_filters import HealthCheckAccessFilter


def _access_record(path: str) -> logging.LogRecord:
    # uvicorn access args: (client_addr, method, full_path, http_version, status)
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_filter_drops_health_check_access():
    f = HealthCheckAccessFilter()
    assert f.filter(_access_record("/health/")) is False
    assert f.filter(_access_record("/health")) is False


def test_filter_keeps_real_traffic():
    f = HealthCheckAccessFilter()
    assert f.filter(_access_record("/query/")) is True
    assert f.filter(_access_record("/jobs/")) is True
