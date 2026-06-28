"""Logging filters for the server process.

``HealthCheckAccessFilter`` drops uvicorn access-log records for the health
endpoint. The dashboard/CLI poll ``/health/`` every couple of seconds; left
unfiltered that polling was ~95% of the captured stdout log volume.
"""

from __future__ import annotations

import logging

_HEALTH_PREFIXES = ("/health", "/health/")


class HealthCheckAccessFilter(logging.Filter):
    """Return False (drop) for uvicorn access records hitting ``/health``.

    uvicorn formats access logs with ``record.args`` of
    ``(client_addr, method, full_path, http_version, status)`` — the request
    path is ``args[2]``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            path = str(args[2])
            if path == "/health" or path.startswith("/health/"):
                return False
        return True


def install_health_check_access_filter() -> None:
    """Attach the health-check filter to the uvicorn access logger once."""
    access_logger = logging.getLogger("uvicorn.access")
    if any(isinstance(f, HealthCheckAccessFilter) for f in access_logger.filters):
        return
    access_logger.addFilter(HealthCheckAccessFilter())
