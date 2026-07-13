"""Phase 130 — GitHistoryIndexService: gate, dedup, incremental since-sha."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from brainpalace_server.config.git_config import GitIndexingConfig
from brainpalace_server.services.git_history_index_service import (
    GitHistoryIndexService,
    load_git_last_sha,
)


def _run(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(f"content {name}\n")
    _run(repo, "add", name)
    _run(repo, "commit", "-m", f"add {name}")


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.email", "dev@example.com")
    _run(repo, "config", "user.name", "Dev Person")
    _commit(repo, "a.txt")
    _commit(repo, "b.txt")
    return repo


class FakeStore:
    def __init__(self) -> None:
        self.ids: set[str] = set()
        self.upserts: list[list[str]] = []

    async def get_by_id(self, chunk_id: str):  # noqa: ANN201
        return {"id": chunk_id} if chunk_id in self.ids else None

    async def upsert_documents(
        self, ids, embeddings, documents, metadatas
    ):  # noqa: ANN001,ANN201
        self.upserts.append(list(ids))
        self.ids.update(ids)


class FakeEmbedder:
    def __init__(self) -> None:
        self.embedded = 0

    async def embed_chunks(self, chunks, progress=None):  # noqa: ANN001,ANN201
        self.embedded += len(chunks)
        return [[0.0, 0.1] for _ in chunks]


def _svc(state_dir: Path):
    store, emb = FakeStore(), FakeEmbedder()
    svc = GitHistoryIndexService(
        embedding_generator=emb, storage_backend=store, state_dir=state_dir
    )
    return svc, store, emb


@pytest.mark.asyncio
async def test_disabled_config_indexes_nothing(git_repo: Path, tmp_path: Path) -> None:
    svc, store, emb = _svc(tmp_path / "state")
    summary = await svc.index_repo(str(git_repo), GitIndexingConfig(enabled=False))
    assert summary["enabled"] is False
    assert summary["commits_new"] == 0
    assert emb.embedded == 0


@pytest.mark.asyncio
async def test_indexes_full_history_first_run(git_repo: Path, tmp_path: Path) -> None:
    svc, store, emb = _svc(tmp_path / "state")
    summary = await svc.index_repo(str(git_repo), GitIndexingConfig(enabled=True))
    assert summary["commits_new"] == 2
    assert emb.embedded == 2
    assert store.upserts


@pytest.mark.asyncio
async def test_incremental_adds_only_new_commit(git_repo: Path, tmp_path: Path) -> None:
    svc, store, emb = _svc(tmp_path / "state")
    cfg = GitIndexingConfig(enabled=True)
    await svc.index_repo(str(git_repo), cfg)
    first_embedded = emb.embedded

    _commit(git_repo, "c.txt")
    summary = await svc.index_repo(str(git_repo), cfg)

    assert summary["commits_new"] == 1
    assert emb.embedded == first_embedded + 1


@pytest.mark.asyncio
async def test_reindex_no_change_is_noop(git_repo: Path, tmp_path: Path) -> None:
    svc, store, emb = _svc(tmp_path / "state")
    cfg = GitIndexingConfig(enabled=True)
    await svc.index_repo(str(git_repo), cfg)
    first_embedded = emb.embedded

    summary = await svc.index_repo(str(git_repo), cfg)

    assert summary["commits_new"] == 0
    assert emb.embedded == first_embedded


@pytest.mark.asyncio
async def test_non_repo_no_ops(tmp_path: Path) -> None:
    svc, store, emb = _svc(tmp_path / "state")
    summary = await svc.index_repo(
        str(tmp_path / "nope"), GitIndexingConfig(enabled=True)
    )
    assert summary["commits_new"] == 0
    assert emb.embedded == 0


# ---------------------------------------------------------------------------
# Phase 1 — monorepo subdir scope
# ---------------------------------------------------------------------------


def _init_monorepo(root: Path) -> Path:
    """Create a two-commit monorepo and return the subproject dir."""
    _run(root, "init", "-q")
    _run(root, "config", "user.email", "t@t.t")
    _run(root, "config", "user.name", "t")
    (root / "rootfile.txt").write_text("root\n")
    _run(root, "add", "-A")
    _run(root, "commit", "-qm", "root commit")
    sub = root / "projects" / "sub"
    sub.mkdir(parents=True)
    (sub / "a.py").write_text("x = 1\n")
    _run(root, "add", "-A")
    _run(root, "commit", "-qm", "sub commit")
    return sub


# ---------------------------------------------------------------------------
# load_git_last_sha — shared state-read helper (service + self-heal)
# ---------------------------------------------------------------------------


def test_load_git_last_sha_none_when_never_indexed(tmp_path: Path) -> None:
    assert load_git_last_sha(tmp_path / "state", "/some/repo") is None


def test_load_git_last_sha_none_when_no_state_dir() -> None:
    assert load_git_last_sha(None, "/some/repo") is None


@pytest.mark.asyncio
async def test_load_git_last_sha_matches_what_the_service_persisted(
    git_repo: Path, tmp_path: Path
) -> None:
    """The helper must read the exact same state file/key the service writes
    under — the whole point is to avoid the two diverging."""
    state_dir = tmp_path / "state"
    svc, store, emb = _svc(state_dir)
    await svc.index_repo(str(git_repo), GitIndexingConfig(enabled=True))

    last_sha = load_git_last_sha(state_dir, str(git_repo))

    head = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert last_sha == head


@pytest.mark.asyncio
async def test_monorepo_subdir_only_indexes_subdir_commits(tmp_path: Path) -> None:
    sub = _init_monorepo(tmp_path)
    svc, store, emb = _svc(tmp_path / "state")
    summary = await svc.index_repo(str(sub), GitIndexingConfig(enabled=True))
    assert summary["commits_total"] == 1


@pytest.mark.asyncio
async def test_monorepo_subdir_graph_joins_onto_toplevel_root(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: ``index_repo`` must join ``git log --numstat`` paths (which
    are always relative to the git toplevel) onto the toplevel, not onto the
    indexed subdir — else file ids double the subdir segment and the
    existing-node gate silently drops every ``modifies`` edge."""
    import brainpalace_server.indexing.git_graph as gg
    from brainpalace_server.config import settings
    from brainpalace_server.storage.graph_store import GraphStoreManager

    sub = _init_monorepo(tmp_path)
    toplevel = tmp_path.resolve()

    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    mgr = GraphStoreManager(persist_dir=tmp_path / "graphdb", store_type="sqlite")
    mgr.initialize()
    monkeypatch.setattr(gg, "get_graph_store_manager", lambda: mgr)

    # Pre-existing canonical code File node, keyed by the TOPLEVEL-joined
    # abs path (as the code indexer creates it).
    file_id = f"{toplevel}/projects/sub/a.py"
    mgr.add_triplet(
        "a.py",
        "contains",
        "foo",
        subject_type="File",
        object_type="Function",
        subject_id=file_id,
        object_id=f"{file_id}:foo",
        source_file=file_id,
    )

    svc, store, emb = _svc(tmp_path / "state")
    summary = await svc.index_repo(str(sub), GitIndexingConfig(enabled=True))

    assert summary["graph_triplets"] > 0
    store_ = mgr._graph_store
    row = store_._conn.execute(
        "SELECT count(*) FROM edges WHERE target_id = ? AND valid_until IS NULL",
        (file_id,),
    ).fetchone()
    assert row[0] == 1  # the `modifies` edge landed on the correct File node
