"""Doc source adapter for the extraction reconciler (Plan 2).

Drains the DocPendingStore: each pending (chunk_id, text) → provider triplet
extraction → graph store. Provider failure returns False so the chunk stays
pending for the next drain. ``is_ready`` carries the Plan 4 two-lock cost-safety
gate: graphrag on AND ``extraction.mode ∈ {provider, auto}`` AND the H2 env
provider lock. ``auto`` adds an H1 grace window so the free subagent gets first
dibs before the paid provider mops up stragglers.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from brainpalace_server.config import settings
from brainpalace_server.indexing.doc_triplet_extractor import extract_doc_triplets
from brainpalace_server.services.auto_grace import (
    provider_auto_eligible,
    read_last_drain,
)

logger = logging.getLogger(__name__)


class DocExtractionAdapter:
    name = "doc"

    def __init__(
        self,
        *,
        store: Any,
        graph_store: Any,
        provider_factory: Callable[[], Any],
        graphrag_enabled: bool = True,
        max_triplets: int | None = None,
        mode: str = "off",
        provider_enabled: bool = False,
        grace_hours: int = 24,
        project_root: str = "",
        server_start_ts: float = 0.0,
        first_request_seen: Callable[[], bool] | None = None,
    ) -> None:
        self._store = store
        self._graph = graph_store
        self._provider_factory = provider_factory
        # Task 4f: auto-grace anchored on subagent activity + cold-start gate.
        # first_request_seen is read live (a callable over app.state) so the gate
        # opens the moment the first HTTP request lands, not at construction.
        self._project_root = project_root
        self._server_start_ts = server_start_ts
        self._first_request_seen = first_request_seen or (lambda: False)
        # 2-6: persist the graph once per drain batch (flush), not per chunk.
        # mark_done is deferred to flush too so it always trails a successful
        # persist — a crash mid-batch leaves chunks pending (re-drained), never
        # marked-done-but-unpersisted.
        self._pending_done: list[str] = []
        self._graphrag_enabled = graphrag_enabled
        self._max_triplets = max_triplets or settings.GRAPH_MAX_TRIPLETS_PER_CHUNK
        # Plan 4: lifespan-resolved engine mode + the H2 provider lock + H1 grace.
        self._mode = mode
        self._provider_enabled = provider_enabled
        self._grace_seconds = grace_hours * 3600

    @property
    def is_ready(self) -> bool:
        # Plan 4 two-lock cost-safety: the PAID provider doc executor runs only
        # when graph indexing is on (settings + resolved graphrag), the engine
        # mode is provider/auto, AND the H2 env provider lock is set. subagent/
        # off never reach the paid path here (subagent drains via the HTTP queue).
        return bool(
            settings.ENABLE_GRAPH_INDEX
            and self._graphrag_enabled
            and self._mode in ("provider", "auto")
            and self._provider_enabled
        )

    async def select_pending(self, limit: int) -> list[tuple[str, str]]:
        # Task 4f: in auto the provider only mops up once the free subagent has
        # been absent for a whole grace window — anchored on subagent activity
        # (last-drain) + server_start (restart resets) + the cold-start gate, NOT
        # on chunk created_at. In provider mode grace does not apply (drain now).
        if self._mode == "auto" and self._grace_seconds > 0:
            eligible = provider_auto_eligible(
                now=time.time(),
                last_drain_ts=read_last_drain(self._project_root),
                server_start_ts=self._server_start_ts,
                first_request_seen=self._first_request_seen(),
                grace_seconds=self._grace_seconds,
            )
            if not eligible:
                return []  # defer — free subagent gets first dibs
            return list(self._store.select_pending(limit))
        result: list[tuple[str, str]] = self._store.select_pending(limit)
        return result

    async def process(self, item: tuple[str, str]) -> bool:
        chunk_id, text = item
        try:
            provider = self._provider_factory()
        except Exception as exc:  # noqa: BLE001 — misconfigured provider ⇒ retry later
            logger.warning("doc adapter: provider unavailable: %s", exc)
            return False
        triplets = await extract_doc_triplets(
            text, chunk_id, provider=provider, max_triplets=self._max_triplets
        )
        if triplets is None:
            return False  # provider error (Task 1 contract) → leave pending, retry
        # A completed call (even with no relations) marks done so a barren chunk
        # is not re-charged on the next drain.
        n_stored = 0
        for t in triplets:
            if self._graph.add_triplet(
                subject=t.subject,
                predicate=t.predicate,
                obj=t.object,
                subject_type=t.subject_type,
                object_type=t.object_type,
                source_chunk_id=t.source_chunk_id,
            ):
                n_stored += 1
        # Record provider usage — best-effort; never breaks the caller (§6-F5).
        try:
            from brainpalace_server.services.usage_metrics import (
                record_usage,
            )  # noqa: PLC0415

            record_usage(
                "provider",
                getattr(provider, "provider_name", ""),
                getattr(provider, "model_name", ""),
                "doc",
                calls=1,
                triplets=n_stored,
            )
        except Exception:  # noqa: BLE001
            pass
        # Defer persist + mark_done to flush() (2-6): one graph persist per batch.
        self._pending_done.append(chunk_id)
        return True

    async def flush(self) -> None:
        """Persist the graph once for the batch, then mark the drained chunks done.

        Persist-before-mark ordering (at batch granularity) keeps the queue
        crash-safe: if the server dies before flush, no chunk is marked done, so
        every drained chunk is re-processed (idempotent add_triplet) — nothing is
        silently lost (2-6)."""
        if not self._pending_done:
            return
        self._graph.persist()
        for chunk_id in self._pending_done:
            self._store.mark_done(chunk_id)
        self._pending_done = []
