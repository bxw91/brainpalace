"""Source-agnostic extraction reconciler (Unified Extraction, Plan 2).

One generic drain over pluggable source adapters (docs, sessions). The adapter
owns selection + extraction + its own done/pending bookkeeping; this module owns
only the round-robin, the per-call ``max_count`` cap, and ready-gating. The
SHARED cooldown lives in the caller (lifespan tick) so there is exactly one
cooldown for the whole reconciler (spec §8/OQ3), not one per source.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class SourceAdapter(Protocol):
    name: str
    is_ready: bool

    async def select_pending(self, limit: int) -> list[Any]: ...
    async def process(self, item: Any) -> bool: ...


async def drain_once(
    adapters: list[SourceAdapter],
    *,
    max_count: int,
    budget: Any | None = None,
    billable: bool = False,
) -> dict[str, int]:
    """Process up to ``max_count`` pending items, round-robin across adapters.

    Task 4b — billable-only per-hour spend cap: when ``billable`` and a
    :class:`ProviderBudget` is supplied, the rolling-hour ceiling is checked
    **before** each paid item; at the cap the whole tick **stops** (remaining
    items stay pending for the next drain) and a successfully processed paid item
    is recorded against the window. ``budget`` is ignored for keyless/local
    providers (``billable=False``) — they are not spend-capped.
    """
    processed = 0
    failed = 0
    if max_count <= 0:
        return {"processed": 0, "failed": 0}

    _cap = budget if (billable and budget is not None) else None

    queues: list[tuple[SourceAdapter, list[Any]]] = []
    for a in adapters:
        if not a.is_ready:
            continue
        items = await a.select_pending(max_count)
        if items:
            queues.append((a, list(items)))

    # Round-robin so one large source cannot starve the others within a tick.
    capped = False
    while (
        not capped
        and processed + failed < max_count
        and any(items for _, items in queues)
    ):
        for adapter, items in queues:
            if not items:
                continue
            if processed + failed >= max_count:
                break
            # Billable spend cap: stop the ENTIRE tick at the per-hour ceiling so
            # remaining items stay pending (no partial-then-fail miscount).
            if _cap is not None and not _cap.allow(time.time()):
                logger.info(
                    "drain: per-hour provider cap reached — stopping tick "
                    "(items stay pending)"
                )
                capped = True
                break
            item = items.pop(0)
            try:
                ok = await adapter.process(item)
            except Exception as exc:  # noqa: BLE001 — one bad item never aborts drain
                logger.warning("drain: %s.process crashed: %s", adapter.name, exc)
                ok = False
            if ok:
                processed += 1
                if _cap is not None:
                    _cap.record(time.time())  # count the paid call against the window
            else:
                failed += 1

    # Per-batch flush (2-6): an adapter may defer expensive commits (e.g. the doc
    # adapter persists the graph once here instead of once per chunk). Optional —
    # adapters without flush (sessions) are untouched. A flush failure leaves that
    # adapter's items pending for the next drain (never silently lost).
    for adapter, _items in queues:
        flush = getattr(adapter, "flush", None)
        if flush is None:
            continue
        try:
            await flush()
        except Exception as exc:  # noqa: BLE001 — flush failure must not abort the tick
            logger.warning("drain: %s.flush crashed: %s", adapter.name, exc)

    return {"processed": processed, "failed": failed}
