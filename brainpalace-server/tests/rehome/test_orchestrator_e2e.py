"""End-to-end integration: full run, resume-after-crash, double-run idempotency,
no-re-embed, and external-folder verbatim-passthrough (spec plan-of-record step 4).

Seeds real stores (chroma vector, sqlite graph, sqlite reference catalog,
FolderManager, BM25IndexManager) under an ``old_root``-style layout and drives
the public ``run_rehome`` entry point end to end.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from llama_index.core.graph_stores.types import EntityNode, Relation
from llama_index.core.schema import TextNode

from brainpalace_server.indexing.bm25_index import BM25IndexManager
from brainpalace_server.rehome import orchestrator as orch
from brainpalace_server.rehome.identity import ProjectIdentity, write_identity
from brainpalace_server.rehome.state import load_rehome_state
from brainpalace_server.services.folder_manager import FolderManager
from brainpalace_server.storage.reference_catalog_store import (
    ReferenceCatalogStore,
    ReferenceEntry,
    ref_id,
)
from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore
from brainpalace_server.storage.vector_store import VectorStoreManager


@dataclass
class _Seeded:
    state_dir: Path
    old_root: Path
    new_root: Path
    external_dir: Path
    vector: VectorStoreManager
    graph: SQLitePropertyGraphStore
    refcat: ReferenceCatalogStore
    folders: FolderManager
    bm25: BM25IndexManager
    old_refcat_id: str


def _seed_graph(graph: SQLitePropertyGraphStore, old_root: str) -> None:
    graph.upsert_nodes(
        [
            EntityNode(
                name="pkg", label="Folder", properties={"path": f"{old_root}/pkg"}
            ),
            EntityNode(
                name="mod.py",
                label="File",
                properties={"path": f"{old_root}/pkg/mod.py"},
            ),
        ]
    )
    graph._conn.execute(f"UPDATE nodes SET id='{old_root}/pkg' WHERE name='pkg'")
    graph._conn.execute(
        f"UPDATE nodes SET id='{old_root}/pkg/mod.py' WHERE name='mod.py'"
    )
    graph._conn.commit()
    graph.upsert_relations(
        [
            Relation(
                source_id=f"{old_root}/pkg",
                target_id=f"{old_root}/pkg/mod.py",
                label="contains",
                properties={"source_file": f"{old_root}/pkg/mod.py"},
            ),
        ]
    )


async def _seed(tmp_path: Path) -> _Seeded:
    state_dir = tmp_path / "state"
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    external_dir = tmp_path / "external"
    for d in (state_dir, old_root, new_root, external_dir):
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

    graph = SQLitePropertyGraphStore(str(state_dir / "graph.db"))
    _seed_graph(graph, str(old_root))

    refcat = ReferenceCatalogStore(state_dir / "ref.db")
    old_pointer = f"{old_root}/doc.md"
    old_id = ref_id(old_pointer, str(old_root))
    refcat.upsert(
        [
            ReferenceEntry(
                id=old_id,
                domain="d",
                source=str(old_root),
                source_id=str(old_root),
                pointer=old_pointer,
            )
        ]
    )

    folders = FolderManager(state_dir)
    await folders.add_folder(
        str(old_root / "pkg"), chunk_count=3, chunk_ids=["c0", "c1", "c2"]
    )
    await folders.add_folder(str(external_dir), chunk_count=1, chunk_ids=["ext_0"])

    bm25 = BM25IndexManager(persist_dir=str(state_dir / "bm25"))
    nodes = [
        TextNode(text="hello", id_="c0", metadata={"source": f"{old_root}/f0.py"}),
        TextNode(
            text="ext doc", id_="ext_0", metadata={"source": str(external_dir / "e.md")}
        ),
    ]
    bm25.build_index(nodes)
    bm25.persist()

    return _Seeded(
        state_dir=state_dir,
        old_root=old_root,
        new_root=new_root,
        external_dir=external_dir,
        vector=vector,
        graph=graph,
        refcat=refcat,
        folders=folders,
        bm25=bm25,
        old_refcat_id=old_id,
    )


def _stores(seeded: _Seeded) -> orch.RehomeStores:
    return orch.RehomeStores(
        vector=seeded.vector,
        bm25=seeded.bm25,
        graph=seeded.graph,
        refcat=seeded.refcat,
        folders=seeded.folders,
        jobs=None,
        manifests=None,
    )


@pytest.mark.asyncio
async def test_full_run_marks_done_and_swaps_everything(tmp_path):
    s = await _seed(tmp_path)
    result = await orch.run_rehome(s.state_dir, s.new_root, stores=_stores(s))

    assert result.status == "done"

    for i in range(3):
        row = await s.vector.get_by_id(f"c{i}")
        assert row["metadata"]["source"] == f"{s.new_root}/f{i}.py"
    assert await s.vector.get_count() == 3  # no duplication

    node_ids = {r["id"] for r in s.graph._conn.execute("SELECT id FROM nodes")}
    assert node_ids == {f"{s.new_root}/pkg", f"{s.new_root}/pkg/mod.py"}

    new_pointer = f"{s.new_root}/doc.md"
    expected_new_id = ref_id(new_pointer, str(s.new_root))
    refcat_ids = {e.id for e in s.refcat.list()}
    assert expected_new_id in refcat_ids
    assert s.old_refcat_id not in refcat_ids


@pytest.mark.asyncio
async def test_no_reembed(tmp_path):
    s = await _seed(tmp_path)
    pre = {
        cid: (await s.vector.get_by_id(cid))["embedding"] for cid in ("c0", "c1", "c2")
    }
    pre_count = await s.vector.get_count()

    class _EmbedderGuard:
        def __init__(self) -> None:
            self.calls = 0

        def embed(self, *_args: object, **_kwargs: object) -> None:
            self.calls += 1
            raise AssertionError("embedding provider must not be called during rehome")

    guard = _EmbedderGuard()
    result = await orch.run_rehome(
        s.state_dir, s.new_root, stores=_stores(s), embedder_guard=guard
    )

    assert result.status == "done"
    assert guard.calls == 0
    assert await s.vector.get_count() == pre_count
    for cid, emb in pre.items():
        post = (await s.vector.get_by_id(cid))["embedding"]
        assert list(post) == list(emb)


@pytest.mark.asyncio
async def test_resume_after_phase_crash_completes(tmp_path, monkeypatch):
    s = await _seed(tmp_path)
    original = orch._run_phase
    state = {"raised": False}

    async def flaky(phase: int, ctx: orch.RehomeContext) -> None:
        if phase == 5 and not state["raised"]:
            state["raised"] = True
            raise RuntimeError("simulated crash")
        await original(phase, ctx)

    monkeypatch.setattr(orch, "_run_phase", flaky)
    with pytest.raises(RuntimeError):
        await orch.run_rehome(s.state_dir, s.new_root, stores=_stores(s))

    failed = load_rehome_state(s.state_dir)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.phase == 5

    monkeypatch.setattr(orch, "_run_phase", original)
    result = await orch.run_rehome(s.state_dir, s.new_root, stores=_stores(s))

    assert result.status == "done"
    for i in range(3):
        row = await s.vector.get_by_id(f"c{i}")
        assert row["metadata"]["source"] == f"{s.new_root}/f{i}.py"
    assert await s.vector.get_count() == 3  # no double-swap / duplication


@pytest.mark.asyncio
async def test_double_run_idempotent(tmp_path):
    s = await _seed(tmp_path)
    first = await orch.run_rehome(s.state_dir, s.new_root, stores=_stores(s))
    assert first.status == "done"

    snapshot = [await s.vector.get_by_id(f"c{i}") for i in range(3)]

    second = await orch.run_rehome(s.state_dir, s.new_root, stores=_stores(s))
    assert second.status == "done"

    for i in range(3):
        row = await s.vector.get_by_id(f"c{i}")
        assert row["metadata"] == snapshot[i]["metadata"]
    assert await s.vector.get_count() == 3


@pytest.mark.asyncio
async def test_external_folder_left_verbatim(tmp_path):
    s = await _seed(tmp_path)
    await orch.run_rehome(s.state_dir, s.new_root, stores=_stores(s))

    paths = {r.folder_path for r in await s.folders.list_folders()}
    assert str(s.external_dir) in paths
