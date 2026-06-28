"""Process-wide usage recorder: the single record_usage() choke point + the
usage_source contextvar. Best-effort — never breaks the caller (§6-F5)."""

from __future__ import annotations

import contextlib
import contextvars
import logging
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brainpalace_server.storage.usage_metrics_store import UsageMetricsStore

logger = logging.getLogger(__name__)

_store: UsageMetricsStore | None = None  # None == disabled / unwired
_dropped = 0
_usage_source: contextvars.ContextVar[str] = contextvars.ContextVar(
    "usage_source", default="unknown"
)


def set_usage_store(store: UsageMetricsStore | None) -> None:
    global _store
    _store = store


def get_usage_store() -> UsageMetricsStore | None:
    return _store


def dropped_writes() -> int:
    return _dropped


def current_usage_source() -> str:
    return _usage_source.get()


@contextlib.contextmanager
def usage_scope(source: str) -> Iterator[None]:
    """Set the usage source for the duration; reset via the Token (§6-F4)."""
    tok = _usage_source.set(source)
    try:
        yield
    finally:
        _usage_source.reset(tok)


def _now_bucket() -> int:
    return int(time.time()) // 60  # minute bucket


def record_usage(
    channel: str,
    provider: str,
    model: str,
    source: str,
    *,
    chunks: int = 0,
    calls: int = 0,
    triplets: int = 0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
    errors: int = 0,
) -> None:
    global _dropped
    store = _store
    if store is None:
        return  # disabled / unwired — no-op
    try:
        store.record(
            _now_bucket(),
            channel,
            provider,
            model,
            source,
            chunks=chunks,
            calls=calls,
            triplets=triplets,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cache_read=cache_read,
            cache_write=cache_write,
            errors=errors,
        )
    except Exception as exc:  # noqa: BLE001 — telemetry must never break the caller
        _dropped += 1
        logger.debug("usage record dropped (%s): %s", channel, exc)


def sample_queue(source: str, depth: int) -> None:
    global _dropped
    store = _store
    if store is None:
        return
    try:
        now = int(time.time())
        store.sample_queue(now // 60, source, depth, now)
    except Exception as exc:  # noqa: BLE001
        _dropped += 1
        logger.debug("queue sample dropped (%s): %s", source, exc)
