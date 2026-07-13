"""Plan 05 Task 5 — lifespan rehome/quarantine e2e (D4/D11/A9).

Drives the Plan-05 startup path end to end without standing up the full
``main.app`` (which needs live embedding/summarization provider keys). Instead a
MINIMAL FastAPI app wires ONLY the two Plan-05 HTTP surfaces —
``_install_quarantine_middleware`` + the ``/rehome`` router — and a helper
replays the exact lifespan seam logic (``evaluate_startup`` →
``build_rehome_stores`` → ``run_rehome``), seeding real stores (chroma vector +
FolderManager) the way the orchestrator e2e does. Graph is None in production
(GraphStoreManager exposes no rehome-capable handle), so graph-node rehome is NOT
asserted here — it is covered by tests/rehome/test_orchestrator_e2e.py directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.main import _install_quarantine_middleware
from brainpalace_server.api.routers.rehome import router as rehome_router
from brainpalace_server.rehome import orchestrator as orch
from brainpalace_server.rehome import quarantine as rq
from brainpalace_server.rehome.identity import (
    ProjectIdentity,
    load_identity,
    write_identity,
)
from brainpalace_server.rehome.quarantine import QuarantineState
from brainpalace_server.rehome.state import (
    load_rehome_state,
    new_rehome_state,
    write_rehome_state,
)
from brainpalace_server.services.folder_manager import FolderManager
from brainpalace_server.storage.vector_store import VectorStoreManager


@dataclass
class _Seeded:
    state_dir: Path
    old_root: Path
    new_root: Path
    vector: VectorStoreManager
    folders: FolderManager


async def _seed_moved(tmp_path: Path) -> _Seeded:
    """Seed identity at an OLD root + chroma chunks + a folder record citing it."""
    state_dir = tmp_path / "state"
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    for d in (state_dir, old_root, new_root):
        d.mkdir()

    write_identity(
        state_dir, ProjectIdentity(project_uuid="u", indexed_root=str(old_root))
    )

    vector = VectorStoreManager(
        persist_dir=str(state_dir / "chroma"), collection_name="tcol"
    )
    await vector.initialize()
    await vector.upsert_documents(
        ids=["c0", "c1", "c2"],
        embeddings=[[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
        documents=["a", "b", "c"],
        metadatas=[
            {"source": f"{old_root}/f{i}.py", "file_path": f"{old_root}/f{i}.py"}
            for i in range(3)
        ],
    )

    folders = FolderManager(state_dir)
    await folders.add_folder(
        str(old_root / "pkg"), chunk_count=3, chunk_ids=["c0", "c1", "c2"]
    )

    return _Seeded(
        state_dir=state_dir,
        old_root=old_root,
        new_root=new_root,
        vector=vector,
        folders=folders,
    )


def _mk_app() -> FastAPI:
    """Minimal app with only the Plan-05 HTTP surfaces + a non-allowlisted route."""
    app = FastAPI()
    _install_quarantine_middleware(app)
    app.include_router(rehome_router, prefix="/rehome")

    @app.get("/query/ping")
    async def _q() -> dict[str, bool]:  # a non-allowlisted route
        return {"ok": True}

    app.state.rehome_quarantine = QuarantineState(active=False)
    return app


async def _drive_seam(app: FastAPI, state_dir: Path, current_root: Path):
    """Replay the api/main.py lifespan rehome seam against the minimal app.

    Mirrors the production seam exactly: D7 backfill + move decision, stale-done
    clear, build the store bundle, run the swap, quarantine on non-done. Returns
    the RehomeState (or None when no rehome was needed).
    """
    app.state.state_dir_str = str(state_dir)
    app.state.project_root = str(current_root)
    plan = rq.evaluate_startup(state_dir, current_root)
    if plan.stale_done:
        rq.clear_stale_rehome_state(state_dir)
    if not plan.needs_rehome:
        return None
    stores = rq.build_rehome_stores(app.state, state_dir)
    app.state.rehome_stores = stores
    # Reference orch.run_rehome (module attr) so monkeypatch on it applies.
    result = await orch.run_rehome(state_dir, current_root, stores=stores)
    if result.status != "done":
        app.state.rehome_quarantine = QuarantineState(
            active=True, reason=result.error, status=result.status
        )
    return result


@pytest.mark.asyncio
async def test_moved_project_boots_and_completes_rehome(tmp_path):
    s = await _seed_moved(tmp_path)
    app = _mk_app()
    app.state.vector_store = s.vector
    app.state.bm25_manager = None

    result = await _drive_seam(app, s.state_dir, s.new_root)

    # The rehome ran to completion in-boot, so the instance is NOT quarantined.
    assert result is not None and result.status == "done"
    assert app.state.rehome_quarantine.active is False

    # Folder record now cites the NEW root (re-read from disk — the seam swapped a
    # freshly-opened FolderManager handle and persisted it). prune=False so the
    # inspection doesn't drop the record for the (non-existent-on-disk) new path.
    fm = FolderManager(s.state_dir)
    await fm.initialize(prune=False)
    paths = {r.folder_path for r in await fm.list_folders()}
    assert str(s.new_root / "pkg") in paths
    assert str(s.old_root / "pkg") not in paths

    # Vector metadata swapped, no re-embed / no duplication.
    for i in range(3):
        row = await s.vector.get_by_id(f"c{i}")
        assert row["metadata"]["source"] == f"{s.new_root}/f{i}.py"
    assert await s.vector.get_count() == 3

    # Identity was re-stamped to the new root (finalize, A15).
    ident = load_identity(s.state_dir)
    assert ident is not None and ident.indexed_root == str(s.new_root)

    # HTTP: not quarantined -> normal route reachable, /rehome/ reports clear.
    c = TestClient(app)
    assert c.get("/query/ping").status_code == 200
    assert c.get("/rehome/").json()["quarantined"] is False


@pytest.mark.asyncio
async def test_unmoved_project_boots_normally(tmp_path):
    state_dir = tmp_path / "state"
    root = tmp_path / "proj"
    state_dir.mkdir()
    root.mkdir()
    write_identity(state_dir, ProjectIdentity(project_uuid="u", indexed_root=str(root)))

    app = _mk_app()
    app.state.vector_store = None
    app.state.bm25_manager = None

    result = await _drive_seam(app, state_dir, root)

    # identity.indexed_root == current_root -> no move -> no rehome, not quarantined.
    assert result is None
    assert app.state.rehome_quarantine.active is False

    c = TestClient(app)
    assert c.get("/query/ping").status_code == 200


@pytest.mark.asyncio
async def test_resume_endpoint_clears_quarantine(tmp_path, monkeypatch):
    s = await _seed_moved(tmp_path)
    app = _mk_app()
    app.state.vector_store = s.vector
    app.state.bm25_manager = None

    # Force the in-boot rehome to FAIL once: leave a status=failed rehome.json and
    # return it without running any phase. The resume (2nd call) delegates to the
    # real run_rehome, which completes the swap from the failed checkpoint.
    original = orch.run_rehome
    calls = {"n": 0}

    async def flaky(state_dir, current_root, *, stores, embedder_guard=None):
        calls["n"] += 1
        if calls["n"] == 1:
            st = load_rehome_state(state_dir) or new_rehome_state(
                "u", str(s.old_root), str(s.new_root)
            )
            st.status = "failed"
            st.error = "simulated boot failure"
            write_rehome_state(state_dir, st)
            return st
        return await original(
            state_dir, current_root, stores=stores, embedder_guard=embedder_guard
        )

    monkeypatch.setattr(orch, "run_rehome", flaky)

    result = await _drive_seam(app, s.state_dir, s.new_root)
    assert result is not None and result.status == "failed"
    assert app.state.rehome_quarantine.active is True

    c = TestClient(app)
    # Quarantined: non-allowlisted route 503s, allowlist stays reachable.
    blocked = c.get("/query/ping")
    assert blocked.status_code == 503
    assert "rehome" in blocked.json()["detail"].lower()
    assert c.get("/rehome/").json()["quarantined"] is True

    # Resume drives the real run to done and clears the quarantine flag.
    r = c.post("/rehome/resume")
    assert r.status_code == 200
    body = r.json()
    assert body["quarantined"] is False
    assert body["status"] == "done"

    assert c.get("/rehome/").json()["quarantined"] is False
    assert c.get("/query/ping").status_code == 200

    # The resume actually performed the swap (folder + vector now cite new root).
    fm = FolderManager(s.state_dir)
    await fm.initialize(prune=False)
    paths = {rec.folder_path for rec in await fm.list_folders()}
    assert str(s.new_root / "pkg") in paths
    for i in range(3):
        row = await s.vector.get_by_id(f"c{i}")
        assert row["metadata"]["source"] == f"{s.new_root}/f{i}.py"
    assert await s.vector.get_count() == 3
