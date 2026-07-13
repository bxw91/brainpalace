# brainpalace_server/rehome/quarantine.py
"""Quarantine policy + startup decision for the rehome lifespan seam (D4/D7/D11/A12).

Pure, server-free: the lifespan wiring (Plan 05, api/main.py) calls these to decide
whether to run rehome, whether to serve fail-closed, and which requests bypass the
503 gate. No FastAPI import here so it is unit-testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brainpalace_server.rehome.detect import MoveInfo, detect_move
from brainpalace_server.rehome.identity import ProjectIdentity, ensure_identity
from brainpalace_server.rehome.orchestrator import RehomeStores
from brainpalace_server.rehome.state import (
    RehomeState,
    load_rehome_state,
)

logger = logging.getLogger(__name__)

REHOME_STATE_FILENAME = "rehome.json"

# Any path under these prefixes (segment-exact), or exactly one of _ALLOW_EXACT,
# bypasses the 503 quarantine gate (D4).
_ALLOW_PREFIXES = ("/health", "/runtime", "/rehome")
_ALLOW_EXACT = ("/", "/docs", "/redoc", "/openapi.json")


@dataclass
class StartupRehomePlan:
    identity: ProjectIdentity
    needs_rehome: bool
    existing: RehomeState | None
    move: MoveInfo | None
    stale_done: bool


@dataclass
class QuarantineState:
    active: bool
    reason: str | None = None
    status: str | None = None


def is_request_allowed(path: str) -> bool:
    """True if `path` bypasses the quarantine 503 gate (D4 allowlist)."""
    if path in _ALLOW_EXACT:
        return True
    for pre in _ALLOW_PREFIXES:
        if path == pre or path.startswith(pre + "/"):
            return True
    return False


def evaluate_startup(state_dir: Path, current_root: Path) -> StartupRehomePlan:
    """D7 backfill, then decide whether a rehome is needed.

    needs_rehome is True when a rehome.json is pending/in_progress/failed, OR a move
    is detected. `stale_done` flags the corner case where a PRIOR rehome completed
    (status==done) yet the project has moved AGAIN — the stale done-state must be
    cleared before run_rehome (which early-returns on a done state).
    Raises IdentityCorruptError / RehomeStateCorruptError (caller quarantines).
    """
    identity = ensure_identity(state_dir, current_root)  # D7
    existing = load_rehome_state(state_dir)
    move = detect_move(identity, current_root)
    if existing is not None and existing.status != "done":
        return StartupRehomePlan(identity, True, existing, move, stale_done=False)
    stale_done = existing is not None and existing.status == "done" and move is not None
    needs = move is not None
    return StartupRehomePlan(identity, needs, existing, move, stale_done=stale_done)


# Background mutators constructed-but-frozen under quarantine (D11). The lifespan
# seam exposes each on app.state even when it skips starting it, so a successful
# in-process resume can start them without a server restart.
_FROZEN_MUTATOR_ATTRS = ("job_worker", "file_watcher_service", "session_reconciler")


async def start_frozen_mutators(app_state: Any) -> list[str]:
    """Start the D11-frozen background mutators after an in-process resume.

    Best-effort: each worker was already constructed + wired during lifespan (only
    its ``.start()`` was skipped under quarantine), so starting it now is the same
    as the boot start, deferred. One worker's failure never fails the resume.
    Returns the names actually started.
    """
    started: list[str] = []
    for attr in _FROZEN_MUTATOR_ATTRS:
        worker = getattr(app_state, attr, None)
        start = getattr(worker, "start", None) if worker is not None else None
        if start is None:
            continue
        try:
            await start()
            started.append(attr)
        except Exception as exc:  # noqa: BLE001 — one worker != the whole resume
            logger.warning("resume: failed to start %s: %s", attr, exc)
    return started


def clear_stale_rehome_state(state_dir: Path) -> None:
    """Remove a completed rehome.json so a fresh (second) move re-runs from phase 1."""
    p = Path(state_dir) / REHOME_STATE_FILENAME
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def build_rehome_stores(app_state: Any, state_dir: Path) -> RehomeStores:
    """Assemble a RehomeStores bundle of thin on-disk handles for the seam.

    vector/bm25 are reused from app.state (already initialized). folders, manifests,
    jobs, refcat, graph are freshly opened (cheap handles over the same on-disk files
    that normal lifespan re-opens later). Any store not configured -> None (no-op).

    Graph note: both backends are rehomed. `GRAPH_STORE_TYPE == "sqlite"` → a direct
    `SQLitePropertyGraphStore` handle (its `.rehome()` swaps node ids + edge PKs); the
    default `simple` (JSON) backend → `graph_simple_json` (the orchestrator prefix-swaps
    its persisted node ids / relation endpoints / triplets in phase 4).
    """
    from brainpalace_server.job_queue.job_store import JobQueueStore
    from brainpalace_server.services.folder_manager import FolderManager
    from brainpalace_server.services.manifest_tracker import ManifestTracker

    folders = FolderManager(state_dir=state_dir)

    manifests: Any = None
    manifests_dir = state_dir / "manifests"
    if manifests_dir.exists():
        manifests = ManifestTracker(manifests_dir=manifests_dir)

    jobs = JobQueueStore(state_dir)

    refcat: Any = None
    try:
        from brainpalace_server.storage.reference_catalog_store import (
            ReferenceCatalogStore,
        )
        from brainpalace_server.storage_paths import db_path

        _refdb = db_path(state_dir, "reference_catalog.db")
        if _refdb.exists():
            refcat = ReferenceCatalogStore(_refdb)
    except Exception as exc:  # noqa: BLE001 — optional store
        logger.debug("refcat rehome handle skipped: %s", exc)

    # Graph rehome. The two backends are exclusive and rehomed differently:
    #  - `sqlite`: `SQLitePropertyGraphStore.rehome()` (path-encoded node ids +
    #    edge PKs). Opened as a direct handle at the known db — avoids the
    #    `GraphStoreManager` singleton's lazy-init ordering.
    #  - `simple` (default): a JSON store; prefix-swap its persisted node ids /
    #    relations / triplets via `graph_simple_json` (orchestrator phase 4).
    graph: Any = None
    graph_simple_json: str | None = None
    try:
        from brainpalace_server.config.settings import settings
        from brainpalace_server.storage_paths import resolve_storage_paths

        _gdir = resolve_storage_paths(state_dir)["graph_index"]
        if getattr(settings, "GRAPH_STORE_TYPE", "simple") == "sqlite":
            from brainpalace_server.storage.sqlite_graph_store import (
                SQLitePropertyGraphStore,
            )

            _graph_db = _gdir / "graph_store.db"
            if _graph_db.exists():
                graph = SQLitePropertyGraphStore(str(_graph_db))
        else:
            _graph_json = _gdir / "graph_store_llamaindex.json"
            if _graph_json.exists():
                graph_simple_json = str(_graph_json)
    except Exception as exc:  # noqa: BLE001 — graph optional/off
        logger.debug("graph rehome handle skipped: %s", exc)

    return RehomeStores(
        vector=getattr(app_state, "vector_store", None),
        bm25=getattr(app_state, "bm25_manager", None),
        graph=graph,
        refcat=refcat,
        folders=folders,
        jobs=jobs,
        manifests=manifests,
        graph_simple_json=graph_simple_json,
    )
