# brainpalace_server/rehome/orchestrator.py
"""Checkpointed, resumable rehome runner (spec D3/D8/D9/D10/A12/A15).

Rewrites old_root->new_root across every path-addressed store in six ordered
phases under a single-runner lock, resuming at (phase, cursor) after a crash.
Never re-embeds. Quarantine/lifespan wiring is Plan 05; CLI is Plan 06.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brainpalace_server import registry
from brainpalace_server.locking import try_file_lock
from brainpalace_server.rehome import swap
from brainpalace_server.rehome.config_excludes import rehome_project_excludes
from brainpalace_server.rehome.detect import MoveInfo, detect_move, prefix_swap
from brainpalace_server.rehome.identity import (
    ProjectIdentity,
    load_identity,
    write_identity,
)
from brainpalace_server.rehome.state import (
    RehomeState,
    load_rehome_state,
    new_rehome_state,
    write_rehome_state,
)

logger = logging.getLogger(__name__)

REHOME_LOCK_FILENAME = "rehome.lock"
VECTOR_BATCH = 500

PHASE_NAMES = {
    1: "config_excludes",
    2: "folder_records",
    3: "manifests",
    4: "graph",
    5: "vector_metadata",
    6: "bm25",
}


class RehomeLockBusy(Exception):  # noqa: N818 — cross-plan interface name (05/06)
    """Another process holds the rehome lock (D9)."""


class RehomeRefused(Exception):  # noqa: N818 — cross-plan interface name (05/06)
    """Nested move (D8) or a foreign/stale sentinel (A12) — refuse to run."""


def _validate_sentinels(
    state_dir: Path, current_root: Path
) -> tuple[ProjectIdentity, MoveInfo | None]:
    """A12 sentinel checks. Raises IdentityCorruptError / RehomeStateCorruptError
    (caller quarantines) or RehomeRefused on a uuid mismatch. Returns the
    identity and the detected move (None if unmoved and no pending rehome)."""
    identity = load_identity(state_dir)  # IdentityCorruptError propagates
    if identity is None:
        # No identity yet: nothing to rehome against (D7 backfill is the lifespan
        # caller's job in Plan 05). Treat as unmoved.
        raise RehomeRefused("no identity.json; backfill must run first (Plan 05)")
    existing = load_rehome_state(state_dir)  # RehomeStateCorruptError propagates
    if existing is not None and existing.project_uuid != identity.project_uuid:
        raise RehomeRefused(
            f"rehome.json uuid {existing.project_uuid} != "
            f"identity {identity.project_uuid}"
        )
    move = detect_move(identity, current_root)
    return identity, move


@dataclass
class RehomeContext:
    """Bundles the bound stores/roots/state so a phase has everything without a
    service locator. Stores are passed in by the caller (Plan 05 supplies live
    ones; tests supply fakes/reals). ``None`` means that store isn't wired for
    this project (e.g. graph indexing off) — the phase becomes a no-op."""

    state_dir: Path
    old_root: str
    new_root: str
    state: RehomeState
    vector: Any
    bm25: Any
    graph: Any
    refcat: Any
    folders: Any
    jobs: Any
    manifests: Any = None
    manifest_folder_paths: list[str] | None = None  # old folder_paths to re-key
    graph_simple_json: str | None = None  # default simple-graph JSON to prefix-swap


async def _run_phase(phase: int, ctx: RehomeContext) -> None:
    old, new = ctx.old_root, ctx.new_root
    if phase == 1:
        rehome_project_excludes(ctx.state_dir, old, new)
    elif phase == 2:
        if ctx.folders is not None:
            await ctx.folders.rehome(lambda r: swap.rehome_folder_record(r, old, new))
        if ctx.jobs is not None:
            await ctx.jobs.rehome(lambda p: prefix_swap(p, old, new))
    elif phase == 3:
        if ctx.manifests is not None and ctx.folders is not None:
            # Folder records were swapped in phase 2, so enumerate the CURRENT
            # (new) paths and reverse-swap to recover each old folder_path — the
            # manifest is still keyed by sha256(old_path). Skip unmoved/external
            # folders (old==new) or a save-then-delete would erase their manifest.
            for rec in await ctx.folders.list_folders():
                new_fp = rec.folder_path
                old_fp = prefix_swap(new_fp, new, old)  # reverse swap
                if old_fp == new_fp:
                    continue
                m = await ctx.manifests.load(old_fp)
                if m is None:
                    continue  # already re-keyed (resume) or no manifest
                await ctx.manifests.save(swap.rekey_manifest(m, old, new))
                await ctx.manifests.delete(old_fp)
    elif phase == 4:
        if ctx.graph is not None:
            ctx.graph.rehome(
                swap_node=lambda nid, props: (lambda s: (s.id, s.properties))(
                    swap.rehome_graph_node(nid, props, old, new)
                ),
                swap_edge=lambda s, t, lbl, sf: (
                    lambda e: (e.id, e.source_id, e.target_id, e.source_file)
                )(swap.rehome_graph_edge(s, t, lbl, sf, old, new)),
            )
        if ctx.graph_simple_json is not None:
            # Default `simple` (JSON) graph backend — prefix-swap its persisted
            # node ids / relation endpoints / triplets in place (no sqlite store).
            swap.rehome_simple_graph_json(ctx.graph_simple_json, old, new)
        if ctx.refcat is not None:
            _rehome_refcat(ctx.refcat, old, new)
    elif phase == 5:
        if ctx.vector is not None:
            await _rehome_vector(ctx)
    elif phase == 6:
        if ctx.bm25 is not None:
            ctx.bm25.rehome(lambda md: swap.swap_chunk_metadata(md, old, new))


def _rehome_refcat(refcat: Any, old: str, new: str) -> None:
    old_ids: list[str] = []
    new_entries = []
    for e in refcat.list():
        swapped = swap.rehome_reference_entry(e, old, new)
        if swapped.id != e.id:
            old_ids.append(e.id)
            new_entries.append(swapped)
    if new_entries:
        refcat.upsert(new_entries)
        refcat.delete_by_id(old_ids)


async def _rehome_vector(ctx: RehomeContext) -> None:
    old, new = ctx.old_root, ctx.new_root
    all_ids = await ctx.vector.get_all_ids()
    # resume: skip everything strictly before the recorded cursor id
    cursor = ctx.state.cursor
    start = 0
    if cursor is not None:
        start = next((i for i, cid in enumerate(all_ids) if cid > cursor), len(all_ids))
    for i in range(start, len(all_ids), VECTOR_BATCH):
        batch = all_ids[i : i + VECTOR_BATCH]
        mds = await ctx.vector.get_metadatas(batch)
        new_mds = [swap.swap_chunk_metadata(m, old, new) for m in mds]
        await ctx.vector.update_metadata(ids=batch, metadatas=new_mds)
        ctx.state.cursor = batch[-1]
        write_rehome_state(ctx.state_dir, ctx.state)
    ctx.state.cursor = None
    write_rehome_state(ctx.state_dir, ctx.state)


@dataclass
class RehomeStores:
    """The live stores/managers Plan 05 passes in from the lifespan seam. Any
    field left ``None`` means that store isn't wired for this project and its
    phase becomes a no-op."""

    vector: Any = None
    bm25: Any = None
    graph: Any = None
    refcat: Any = None
    folders: Any = None
    jobs: Any = None
    manifests: Any = None
    manifest_folder_paths: list[str] | None = None
    #: Path to the default ``simple`` graph store's JSON (rehomed by a prefix-swap
    #: when the sqlite ``graph`` handle is absent — the two backends are exclusive).
    graph_simple_json: str | None = None


async def run_rehome(
    state_dir: Path,
    current_root: Path,
    *,
    stores: RehomeStores,
    embedder_guard: Any = None,
) -> RehomeState:
    """Entry for a FRESH detected move OR a resume (D3/D8/D9/D10/A12/A15).

    Loads identity + rehome.json, validates sentinels, refuses nested moves,
    runs remaining phases under the D9 lock, finalizes (A15 registry remap +
    status=done). Raises RehomeLockBusy if another runner holds the lock.
    """
    identity, move = _validate_sentinels(state_dir, current_root)
    existing = load_rehome_state(state_dir)
    if existing is not None and existing.status == "done":
        if move is None:
            return existing  # already rehomed, no new move — nothing to do
        # A SECOND move after a completed rehome: the done-state is stale. Discard
        # it so this run mints a fresh state for the new move (else the phases would
        # never run and the new move would be silently ignored).
        existing = None
    if move is None and existing is None:
        raise RehomeRefused("no move detected and no pending rehome")
    if move is not None and move.nested:
        st = existing or new_rehome_state(
            identity.project_uuid, move.old_root, move.new_root
        )
        st.status = "failed"
        st.error = (
            "nested self-containing move refused (D8) — "
            "reset + re-index or --force-nested"
        )
        write_rehome_state(state_dir, st)
        raise RehomeRefused(st.error)

    lock_path = Path(state_dir) / REHOME_LOCK_FILENAME
    with try_file_lock(lock_path) as got:
        if not got:
            raise RehomeLockBusy(str(lock_path))
        state = existing or new_rehome_state(
            identity.project_uuid, move.old_root, move.new_root  # type: ignore[union-attr]
        )
        state.status = "in_progress"
        write_rehome_state(state_dir, state)
        ctx = RehomeContext(
            state_dir=state_dir,
            old_root=state.old_root,
            new_root=state.new_root,
            state=state,
            vector=stores.vector,
            bm25=stores.bm25,
            graph=stores.graph,
            refcat=stores.refcat,
            folders=stores.folders,
            jobs=stores.jobs,
            manifests=stores.manifests,
            manifest_folder_paths=stores.manifest_folder_paths,
            graph_simple_json=stores.graph_simple_json,
        )
        try:
            for phase in range(state.phase, 7):
                state.phase = phase
                write_rehome_state(state_dir, state)
                await _run_phase(phase, ctx)
                state.cursor = None
            # A15: registry remap old->new. Only drop the OLD entry when the old
            # root is genuinely gone (a move). If it still exists on disk this is a
            # COPY — the original project still lives there and owns that shared
            # registry entry, so de-registering it would wrongly drop the original
            # from the dashboard fleet.
            if not Path(state.old_root).exists():
                registry.remove_entry(Path(state.old_root))
            registry.upsert_entry(Path(state.new_root), Path(state_dir))
            # Identity now lives at new_root — update so later boots detect NO
            # move (else detect_move keeps firing against the stale indexed_root).
            write_identity(
                state_dir, ProjectIdentity(identity.project_uuid, state.new_root)
            )
            state.status = "done"
            state.error = None
            write_rehome_state(state_dir, state)
        except Exception as exc:  # noqa: BLE001 — record + re-raise for quarantine
            state.status = "failed"
            state.error = f"{type(exc).__name__}: {exc}"
            write_rehome_state(state_dir, state)
            raise
    return state


async def resume_rehome(
    state_dir: Path, current_root: Path, *, stores: RehomeStores
) -> RehomeState:
    """Thin alias used by CLI/endpoint — same as run_rehome (re-enters at
    phase/cursor)."""
    return await run_rehome(state_dir, current_root, stores=stores)
