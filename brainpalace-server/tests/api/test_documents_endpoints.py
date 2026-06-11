"""Document/chunk explorer endpoints (dashboard plan 03)."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import index as index_router_mod
from brainpalace_server.services.manifest_tracker import FileRecord, FolderManifest


class FakeTracker:
    def __init__(self, manifest: FolderManifest | None) -> None:
        self._manifest = manifest

    async def load(self, folder_path: str) -> FolderManifest | None:
        self.loaded = folder_path
        return self._manifest


class FakeBackend:
    is_initialized = True

    def __init__(self, chunks: dict[str, dict] | None = None) -> None:
        self._chunks = chunks or {}

    async def get_by_id(self, chunk_id: str):
        return self._chunks.get(chunk_id)


def _manifest() -> FolderManifest:
    return FolderManifest(
        folder_path="/proj",
        files={
            "/proj/a.py": FileRecord(
                checksum="x", mtime=1.0, chunk_ids=["c1", "c2"], size_bytes=10
            ),
            "/proj/b.md": FileRecord(
                checksum="y", mtime=2.0, chunk_ids=["c3"], size_bytes=20
            ),
        },
    )


def _app(manifest: FolderManifest | None, backend: FakeBackend | None = None):
    sub = FastAPI()
    sub.include_router(index_router_mod.router, prefix="/index")
    sub.state.indexing_service = SimpleNamespace(manifest_tracker=FakeTracker(manifest))
    sub.state.storage_backend = backend or FakeBackend()
    return sub


def test_documents_lists_files_with_chunk_counts():
    c = TestClient(_app(_manifest()))
    r = c.get("/index/documents", params={"folder": "/proj"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    by_path = {f["path"]: f for f in body["files"]}
    assert by_path["/proj/a.py"]["chunk_count"] == 2
    assert by_path["/proj/b.md"]["size_bytes"] == 20


def test_documents_size_bytes_lazy_filled_when_zero(tmp_path):
    """A manifest record with size_bytes=0 (pre-Phase-L / never re-embedded)
    is back-filled from the live file on disk for display."""
    real = tmp_path / "real.py"
    real.write_text("x" * 123)
    manifest = FolderManifest(
        folder_path=str(tmp_path),
        files={
            str(real): FileRecord(
                checksum="x", mtime=1.0, chunk_ids=["c1"], size_bytes=0
            ),
            # A record whose file is gone stays 0 (nothing to stat).
            str(tmp_path / "missing.py"): FileRecord(
                checksum="y", mtime=1.0, chunk_ids=["c2"], size_bytes=0
            ),
        },
    )
    c = TestClient(_app(manifest))
    r = c.get("/index/documents", params={"folder": str(tmp_path)})
    assert r.status_code == 200
    by_path = {f["path"]: f for f in r.json()["files"]}
    assert by_path[str(real)]["size_bytes"] == 123
    assert by_path[str(tmp_path / "missing.py")]["size_bytes"] == 0


def test_documents_contains_filter_and_paging():
    c = TestClient(_app(_manifest()))
    r = c.get("/index/documents", params={"folder": "/proj", "contains": ".py"})
    assert [f["path"] for f in r.json()["files"]] == ["/proj/a.py"]
    r = c.get("/index/documents", params={"folder": "/proj", "limit": 1, "offset": 1})
    assert r.json()["total"] == 2
    assert len(r.json()["files"]) == 1


def test_documents_unknown_folder_404():
    c = TestClient(_app(None))
    r = c.get("/index/documents", params={"folder": "/nope"})
    assert r.status_code == 404


def test_documents_no_tracker_503():
    sub = FastAPI()
    sub.include_router(index_router_mod.router, prefix="/index")
    sub.state.indexing_service = SimpleNamespace(manifest_tracker=None)
    c = TestClient(sub)
    r = c.get("/index/documents", params={"folder": "/proj"})
    assert r.status_code == 503


def test_documents_rejects_invalid_paging():
    c = TestClient(_app(_manifest()))
    assert (
        c.get("/index/documents", params={"folder": "/proj", "offset": -1}).status_code
        == 422
    )
    assert (
        c.get("/index/documents", params={"folder": "/proj", "limit": 0}).status_code
        == 422
    )


def test_document_chunks_rejects_invalid_limit():
    c = TestClient(_app(_manifest()))
    r = c.get(
        "/index/documents/chunks",
        params={"folder": "/proj", "path": "/proj/a.py", "limit": -1},
    )
    assert r.status_code == 422


def test_document_chunks_returns_text_and_metadata():
    backend = FakeBackend(
        {
            "c1": {"text": "def a(): ...", "metadata": {"language": "python"}},
            "c2": {"text": "def b(): ...", "metadata": {"language": "python"}},
        }
    )
    c = TestClient(_app(_manifest(), backend))
    r = c.get(
        "/index/documents/chunks",
        params={"folder": "/proj", "path": "/proj/a.py"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_chunks"] == 2
    assert body["chunks"][0]["chunk_id"] == "c1"
    assert body["chunks"][0]["text"].startswith("def a")
    assert body["chunks"][0]["metadata"]["language"] == "python"


def test_document_chunks_unknown_file_404():
    c = TestClient(_app(_manifest()))
    r = c.get(
        "/index/documents/chunks",
        params={"folder": "/proj", "path": "/proj/zzz.py"},
    )
    assert r.status_code == 404
