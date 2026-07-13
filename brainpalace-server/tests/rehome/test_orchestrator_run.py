from contextlib import contextmanager

import pytest

from brainpalace_server.rehome import orchestrator as orch
from brainpalace_server.rehome.detect import MoveInfo
from brainpalace_server.rehome.identity import ProjectIdentity, write_identity
from brainpalace_server.services.folder_manager import FolderManager
from brainpalace_server.storage.vector_store import VectorStoreManager


@contextmanager
def _busy_lock(path):
    yield False


@pytest.mark.asyncio
async def test_run_rehome_refuses_nested(monkeypatch, tmp_path):
    write_identity(tmp_path, ProjectIdentity(project_uuid="u", indexed_root="/a/b"))
    monkeypatch.setattr(
        orch,
        "detect_move",
        lambda ident, root: MoveInfo(old_root="/a/b", new_root="/a/b/c", nested=True),
    )
    stores = orch.RehomeStores()  # all None
    with pytest.raises(orch.RehomeRefused):
        await orch.run_rehome(tmp_path, tmp_path / "c", stores=stores)
    st = orch.load_rehome_state(tmp_path)
    assert st is not None and st.status == "failed"


@pytest.mark.asyncio
async def test_run_rehome_busy_lock_raises(monkeypatch, tmp_path):
    write_identity(tmp_path, ProjectIdentity(project_uuid="u", indexed_root="/a/b"))
    monkeypatch.setattr(
        orch,
        "detect_move",
        lambda ident, root: MoveInfo(old_root="/a/b", new_root="/x/y", nested=False),
    )
    monkeypatch.setattr(orch, "try_file_lock", _busy_lock)  # yields False
    with pytest.raises(orch.RehomeLockBusy):
        await orch.run_rehome(tmp_path, tmp_path, stores=orch.RehomeStores())


@pytest.mark.asyncio
async def test_run_rehome_happy_path_remaps_registry(monkeypatch, tmp_path):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    # old_root is intentionally NOT created — a genuine move leaves it gone, so
    # A15 de-registers it (a COPY, where old_root still exists, is covered in
    # test_orchestrator_copy_registry.py).
    new_root.mkdir()

    write_identity(
        tmp_path, ProjectIdentity(project_uuid="u", indexed_root=str(old_root))
    )
    monkeypatch.setattr(
        orch,
        "detect_move",
        lambda ident, root: MoveInfo(
            old_root=str(old_root), new_root=str(new_root), nested=False
        ),
    )

    mgr = VectorStoreManager(
        persist_dir=str(tmp_path / "chroma"), collection_name="tcol"
    )
    await mgr.initialize()
    await mgr.upsert_documents(
        ids=["c1"],
        embeddings=[[0.1, 0.2]],
        documents=["a"],
        metadatas=[{"source": f"{old_root}/f.py"}],
    )
    fm = FolderManager(tmp_path)
    await fm.add_folder(str(old_root) + "/pkg", chunk_count=1, chunk_ids=["a_0"])

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        orch.registry, "remove_entry", lambda root: calls.append(("remove", root))
    )
    monkeypatch.setattr(
        orch.registry,
        "upsert_entry",
        lambda root, state_dir: calls.append(("upsert", root)),
    )

    stores = orch.RehomeStores(vector=mgr, folders=fm)
    result = await orch.run_rehome(tmp_path, new_root, stores=stores)

    assert result.status == "done"
    row = await mgr.get_by_id("c1")
    assert row["metadata"]["source"] == f"{new_root}/f.py"
    assert calls[0] == ("remove", old_root)
    assert calls[1][0] == "upsert" and calls[1][1] == new_root
