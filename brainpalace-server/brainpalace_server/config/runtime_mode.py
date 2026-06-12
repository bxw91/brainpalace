"""Read-only runtime mode — the master provider kill switch.

When ON, the server performs no outbound provider work (embedding for index +
query, summarization, remote rerank) and the write/heal paths become
non-destructive. Resolved from ``server.read_only`` in the merged config
(``code < global < project``) with the ``BRAINPALACE_READ_ONLY`` env override on
top. Never raises — an unreadable/malformed config resolves to ``False``
(fail-open to normal operation, the historical default), logged once.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from brainpalace_server.config.provider_config import load_raw_config

logger = logging.getLogger(__name__)

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def is_read_only(config_path: Path | None = None) -> bool:
    """True when the server is in read-only mode. Env wins over config."""
    env = os.getenv("BRAINPALACE_READ_ONLY")
    if env is not None:
        token = env.strip().lower()
        if token in _TRUE:
            return True
        if token in _FALSE:
            return False
        logger.warning("Ignoring non-boolean BRAINPALACE_READ_ONLY=%r", env)

    try:
        raw = load_raw_config(config_path)
        block = raw.get("server")
        if isinstance(block, dict):
            return bool(block.get("read_only", False))
    except Exception as exc:  # noqa: BLE001 — fail-open: bad config => not read-only
        logger.warning("Could not resolve read-only config: %s", exc)
    return False
