"""Periodic session-archive reconcile: copy (sync) + optional index + distiller
catch-up on a timer, replacing the per-event copy watcher. Copy cadence is the
``reconcile_seconds`` interval; ``sync`` dedups unchanged files so a quiet session
is copied once (final flush) and never re-summarized."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from brainpalace_server.config.session_config import retain_cutoff

logger = logging.getLogger(__name__)


@dataclass
class ExtractionDrainState:
    """One shared cooldown clock for the generalized extraction drain."""

    last_drain: float = 0.0


def should_drain(state: ExtractionDrainState, *, cooldown: int, now: float) -> bool:
    """True when the shared cooldown since the last drain has elapsed."""
    return (now - state.last_drain) >= cooldown


async def reconcile_once(
    *,
    sources: list[Any],
    project_root: str = "",
    archive_service: Any | None,
    sess_svc: Any | None,
    session_cfg: Any,
    caps: Any,
    distiller: Any | None,
    adapters: list[Any] | None = None,
    drain_state: ExtractionDrainState | None = None,
    drain_max_count: int = 8,
    drain_cooldown: int = 300,
    provider_budget: Any | None = None,
    provider_billable: bool = False,
) -> dict[str, int]:
    """One sweep: sync each live transcript, index when enabled, throttled drain.

    Returns ``{"archived": int, "indexed": int}``. ``sync`` is idempotent on
    unchanged files, so repeated sweeps copy a session at most once per real
    change (the final tail is captured on the first sweep after it goes quiet).
    The generalized throttled drain (doc + session adapters) runs when adapters
    are provided and the shared cooldown has elapsed.
    """
    import time as _time

    from brainpalace_server.services.extraction_reconciler import drain_once

    live_files: list[tuple[Path, Any]] = []
    for source in sources:
        for path in source.adapter.discover(source.directory, project_root):
            if not source.adapter.owns(path, project_root):
                continue  # another project's transcript — never archive it
            live_files.append((path, source.adapter))
    cutoff = retain_cutoff(session_cfg.retain_days)
    archived = indexed = 0
    # Transcripts to summarize (used by the legacy catch_up fallback when no
    # adapters are wired; the adapter path collects its own sessions via
    # SessionExtractionAdapter.select_pending).
    distill_paths: list[Path] = []
    for live, adapter in live_files:
        arch = None
        if archive_service is not None:
            arch = archive_service.sync(live, tool=adapter.slug)
            if arch is None:
                continue  # tombstoned / unreadable
            archived += 1
        if arch is not None or adapter.slug == "claude-code":
            # A LIVE non-CC path cannot be tool-inferred by parse_transcript's
            # archive-folder rule: it would parse as claude-code to zero turns
            # and distill_transcript would write a PERMANENT done-marker over
            # content it never read. Archived copies (the normal case) infer
            # correctly; live CC paths keep the legacy behaviour.
            distill_paths.append(arch if arch is not None else live)
        if not caps.index_enabled or sess_svc is None:
            continue
        if cutoff is not None:
            try:
                if live.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
        await sess_svc.index_session_file(
            arch if arch is not None else live,
            include_user_turns=session_cfg.include_user_turns,
            window=session_cfg.window,
            stride=session_cfg.stride,
            origin_path=str(live) if arch is not None else None,
            tool=adapter.slug,
        )
        indexed += 1

    # Enforce archive retention (retain_days <= 0 == forever). Best-effort: the
    # raw archive holds full transcripts, so an unbounded archive is a real disk
    # + privacy cost. Never let pruning break the sweep.
    if archive_service is not None:
        with contextlib.suppress(Exception):
            archive_service.prune(session_cfg.archive.retain_days)

    if adapters and drain_state is not None:
        # Generalized throttled drain (doc chunks + sessions). The session adapter
        # handles session summarization so both sources share one cooldown
        # (spec §8/OQ3). Replaces the uncapped catch_up when adapters are wired.
        now = _time.time()
        if should_drain(drain_state, cooldown=drain_cooldown, now=now):
            with contextlib.suppress(Exception):
                res = await drain_once(
                    adapters,
                    max_count=drain_max_count,
                    budget=provider_budget,
                    billable=provider_billable,
                )
                if res["processed"] or res["failed"]:
                    drain_state.last_drain = now

        # Queue gauge — sample pending depths for each source adapter.
        # Best-effort: any error is silently suppressed; never blocks the sweep.
        with contextlib.suppress(Exception):
            from brainpalace_server.services.usage_metrics import (  # noqa: PLC0415
                sample_queue,
            )

            for adapter in adapters:
                name = getattr(adapter, "name", None)
                if name == "doc":
                    store = getattr(adapter, "_store", None)
                    if store is not None and hasattr(store, "count_pending"):
                        # Doc-file and git-commit chunks share one pending table
                        # but report as separate backlog rows.
                        sample_queue("doc", store.count_pending(kind="doc"))
                        sample_queue("git", store.count_pending(kind="git"))
                elif name == "session":
                    # pending_sessions is synchronous and may do disk I/O; wrap
                    # in suppress so a slow filesystem never blocks the tick.
                    adapter_project_root = getattr(adapter, "_project_root", None)
                    archive_dir = getattr(adapter, "_archive_dir", None)
                    if adapter_project_root and archive_dir:
                        # Deferred import: avoids a circular init edge;
                        # safe here — reconciler runs after services wired.
                        import brainpalace_server.services.session_distill_service as _sds  # noqa: PLC0415,E501

                        depth = len(
                            _sds.pending_sessions(adapter_project_root, archive_dir)
                        )
                        sample_queue("session", depth)
    elif distiller is not None and distill_paths:
        # Legacy fallback: no adapters wired (e.g. tests or old callers); run the
        # uncapped catch_up so non-adapter paths remain unchanged.
        with contextlib.suppress(Exception):
            await distiller.catch_up(distill_paths)

    # 2b-6: drop resume sidecars whose transcript is gone (archive purged / never
    # archived). Best-effort, archive-gated, and only when we know project_root.
    if archive_service is not None and distiller is not None:
        distiller_project_root = getattr(distiller, "project_root", None)
        if distiller_project_root:
            with contextlib.suppress(Exception):
                from brainpalace_server.services.session_distill_service import (
                    prune_orphan_sidecars,
                )

                known = archive_service.known_session_ids() | {
                    path.stem for path, _adapter in live_files
                }
                prune_orphan_sidecars(distiller_project_root, known)

    return {"archived": archived, "indexed": indexed}


class SessionReconciler:
    """Runs ``reconcile_once`` immediately, then every ``interval_seconds``."""

    def __init__(
        self,
        *,
        interval_seconds: int,
        sources_provider: Callable[[], list[Any]],
        project_root: str = "",
        archive_service: Any | None,
        sess_svc: Any | None,
        session_cfg: Any,
        caps: Any,
        distiller: Any | None,
        adapters: list[Any] | None = None,
        drain_state: ExtractionDrainState | None = None,
        drain_max_count: int = 8,
        drain_cooldown: int = 300,
        provider_budget: Any | None = None,
        provider_billable: bool = False,
        usage_metrics_store: Any | None = None,
        usage_metrics_retain_days: int = 30,
        memory_curator: Any | None = None,
        curate_state_dir: Path | None = None,
    ) -> None:
        self.interval_seconds = max(1, interval_seconds)
        self._usage_metrics_store = usage_metrics_store
        self._usage_metrics_retain_days = usage_metrics_retain_days
        self._memory_curator = memory_curator
        self._curate_state_dir = curate_state_dir
        self._sources_provider = sources_provider
        self._kw: dict[str, Any] = {
            "project_root": project_root,
            "archive_service": archive_service,
            "sess_svc": sess_svc,
            "session_cfg": session_cfg,
            "caps": caps,
            "distiller": distiller,
            "adapters": adapters,
            "drain_state": drain_state,
            "drain_max_count": drain_max_count,
            "drain_cooldown": drain_cooldown,
            "provider_budget": provider_budget,
            "provider_billable": provider_billable,
        }
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _tick(self) -> dict[str, int]:
        try:
            result = await reconcile_once(sources=self._sources_provider(), **self._kw)
        except Exception as exc:  # noqa: BLE001 — one bad sweep must not kill the loop
            logger.warning("session reconcile sweep failed: %s", exc)
            result = {"archived": 0, "indexed": 0}
        # Provider-mode memory curation rides the same sweep (weekly cadence via the
        # stamp inside curate_if_due). None when not provider/auto+enabled.
        curator = self._memory_curator
        if curator is not None and self._curate_state_dir is not None:
            try:
                await curator.curate_if_due(self._curate_state_dir)
            except Exception as exc:  # noqa: BLE001 — curation must not kill the loop
                logger.warning("memory curation sweep failed: %s", exc)
        # Prune old usage-metrics buckets on each tick (§6-F6). Best-effort.
        if self._usage_metrics_store is not None:
            import time as _time  # noqa: PLC0415

            with contextlib.suppress(Exception):
                self._usage_metrics_store.prune(
                    int(_time.time()) // 60, self._usage_metrics_retain_days
                )
        return result

    async def _loop(self) -> None:
        await self._tick()  # immediate first sweep
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                await self._tick()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None
