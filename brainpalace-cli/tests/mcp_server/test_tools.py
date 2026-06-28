"""Unit tests for ``brainpalace_cli.mcp.tools`` handlers.

Each handler is exercised in isolation: ``discover_server_url`` is
patched to control discovery, and ``DocServeClient`` is replaced with
an in-test fake so no real HTTP traffic occurs. Async handlers are
driven through ``asyncio.run`` to keep the suite free of
``pytest-asyncio``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from brainpalace_cli.client.api_client import (
    ConnectionError as ABConnectionError,
)
from brainpalace_cli.client.api_client import (
    FolderInfo,
    HealthStatus,
    IndexingStatus,
    QueryResponse,
    QueryResult,
    ServerError,
)
from brainpalace_cli.mcp_server import schemas, tools


class _FakeClient:
    """Drop-in replacement for ``DocServeClient`` used by handler tests.

    Each test installs an instance via ``monkeypatch.setattr`` so the
    handler under test sees the canned responses (or the configured
    exception) instead of touching the network.
    """

    def __init__(self, base_url: str = "", **_: Any) -> None:
        self.base_url = base_url
        # Per-method overrides — assign these in a test to control the response.
        self.query_response: QueryResponse | None = None
        self.health_response: HealthStatus | None = None
        self.status_response: IndexingStatus | None = None
        self.folders_response: list[FolderInfo] | None = None
        self.jobs_response: list[dict[str, Any]] | None = None
        self.get_extraction_text_response: dict[str, Any] | None = None
        self.submit_extraction_response: dict[str, Any] | None = None
        # Exception to raise from every method (simulates a failing client).
        self.raise_on_call: Exception | None = None
        # Spy state — what the most recent call_tool saw.
        self.last_query_args: dict[str, Any] | None = None
        self.last_jobs_limit: int | None = None
        self.last_submit_extraction_payload: dict[str, Any] | None = None

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def query(self, **kwargs: Any) -> QueryResponse:
        self.last_query_args = kwargs
        if self.raise_on_call is not None:
            raise self.raise_on_call
        assert self.query_response is not None, "test forgot to set query_response"
        return self.query_response

    def health(self) -> HealthStatus:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        assert self.health_response is not None, "test forgot to set health_response"
        return self.health_response

    def status(self) -> IndexingStatus:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        assert self.status_response is not None, "test forgot to set status_response"
        return self.status_response

    def list_folders(self) -> list[FolderInfo]:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        assert self.folders_response is not None, "test forgot to set folders_response"
        return self.folders_response

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        self.last_jobs_limit = limit
        if self.raise_on_call is not None:
            raise self.raise_on_call
        assert self.jobs_response is not None, "test forgot to set jobs_response"
        return self.jobs_response

    def get_extraction_text(self, chunk_id: str) -> dict[str, Any]:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        assert (
            self.get_extraction_text_response is not None
        ), "test forgot to set get_extraction_text_response"
        return self.get_extraction_text_response

    def submit_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.last_submit_extraction_payload = payload
        if self.raise_on_call is not None:
            raise self.raise_on_call
        assert (
            self.submit_extraction_response is not None
        ), "test forgot to set submit_extraction_response"
        return self.submit_extraction_response


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, fake: _FakeClient) -> None:
    """Make ``DocServeClient(...)`` return the given fake from ``tools.py``."""
    monkeypatch.setattr(tools, "DocServeClient", lambda **_: fake)


def _patch_discovery(
    monkeypatch: pytest.MonkeyPatch,
    *,
    url: str | None = "http://127.0.0.1:9000",
    project: Path | None = Path("/p/demo"),
) -> None:
    monkeypatch.setattr(tools, "discover_server_url", lambda start=None: url)
    monkeypatch.setattr(tools, "discover_project_dir", lambda start=None: project)


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


def test_query_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    fake.query_response = QueryResponse(
        results=[
            QueryResult(
                text="hit",
                source="docs/x.md",
                score=0.91,
                chunk_id="c1",
                metadata={"lang": "md"},
            )
        ],
        query_time_ms=12.5,
        total_results=1,
    )
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    out = asyncio.run(tools.query_tool(schemas.QueryInput(query="x", mode="bm25")))

    assert out["total_results"] == 1
    assert out["results"][0]["chunk_id"] == "c1"
    assert fake.last_query_args == {
        "query_text": "x",
        "top_k": 8,
        "mode": "bm25",
        # Optional list filters now default to [] (clean array schema, no
        # nullable union); the client treats [] as "no filter".
        "source_types": [],
        "languages": [],
        "language": None,
    }


def test_query_no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_discovery(monkeypatch, url=None)
    # DocServeClient must NOT be called when discovery fails.
    monkeypatch.setattr(
        tools,
        "DocServeClient",
        lambda **_: pytest.fail("client should not be instantiated"),
    )

    out = asyncio.run(tools.query_tool(schemas.QueryInput(query="x")))

    assert "error" in out
    assert "no brainpalace server running" in out["error"]


def test_query_connection_error_maps(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    fake.raise_on_call = ABConnectionError("conn refused")
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    out = asyncio.run(tools.query_tool(schemas.QueryInput(query="x")))

    assert out == {"error": "server unreachable: conn refused"}


def test_query_server_error_maps(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    fake.raise_on_call = ServerError("boom", status_code=500, detail="db down")
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    out = asyncio.run(tools.query_tool(schemas.QueryInput(query="x")))

    assert out == {"error": "server error 500: db down"}


def test_query_path_overrides_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``path`` arg must reach ``discover_server_url`` — CWD-coupling fix."""
    seen: dict[str, Any] = {}

    def fake_discover(start: Path | None = None) -> str | None:
        seen["start"] = start
        return "http://127.0.0.1:9000"

    monkeypatch.setattr(tools, "discover_server_url", fake_discover)
    fake = _FakeClient()
    fake.query_response = QueryResponse(results=[], query_time_ms=1.0, total_results=0)
    _install_fake_client(monkeypatch, fake)

    asyncio.run(
        tools.query_tool(schemas.QueryInput(query="x", path="/elsewhere/project"))
    )

    assert seen["start"] == Path("/elsewhere/project")


def test_query_language_in_schema() -> None:
    """``language`` field must be present in QueryInput's JSON schema."""
    schema = schemas.QueryInput.model_json_schema()
    assert (
        "language" in schema["properties"]
    ), "QueryInput JSON schema must include 'language' property for MCP clients"
    lang_prop = schema["properties"]["language"]
    # Field description should mention BM25 and ISO 639-1.
    desc = lang_prop.get("description", "") or ""
    assert "BM25" in desc, "language field description should mention BM25"
    assert (
        "ISO 639-1" in desc or "639-1" in desc
    ), "language field description should mention ISO 639-1"


def test_query_language_forwarded_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``language`` is set, handler must forward it to DocServeClient.query."""
    fake = _FakeClient()
    fake.query_response = QueryResponse(results=[], query_time_ms=1.0, total_results=0)
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    asyncio.run(
        tools.query_tool(schemas.QueryInput(query="Suche", mode="bm25", language="de"))
    )

    assert fake.last_query_args is not None
    assert fake.last_query_args["language"] == "de"


def test_query_language_none_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``language`` is omitted, handler must forward ``language=None``."""
    fake = _FakeClient()
    fake.query_response = QueryResponse(results=[], query_time_ms=1.0, total_results=0)
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    asyncio.run(tools.query_tool(schemas.QueryInput(query="search")))

    assert fake.last_query_args is not None
    assert fake.last_query_args["language"] is None


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    fake.health_response = HealthStatus(
        status="ok", message=None, version="9.7.0", timestamp="t"
    )
    fake.status_response = IndexingStatus(
        total_documents=10,
        total_chunks=42,
        indexing_in_progress=False,
        current_job_id=None,
        progress_percent=100.0,
        last_indexed_at="t",
        indexed_folders=["/p/demo"],
    )
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    out = asyncio.run(tools.status_tool(schemas.StatusInput()))

    assert out["health"]["version"] == "9.7.0"
    assert out["indexing"]["total_chunks"] == 42


def test_status_no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_discovery(monkeypatch, url=None)
    out = asyncio.run(tools.status_tool(schemas.StatusInput()))
    assert "error" in out


# ---------------------------------------------------------------------------
# whoami
# ---------------------------------------------------------------------------


def test_whoami_no_project(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_discovery(monkeypatch, url=None, project=None)
    out = asyncio.run(tools.whoami_tool(schemas.WhoamiInput()))
    assert out == {"project_root": None, "url": None, "server_status": "no_project"}


def test_whoami_project_no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_discovery(monkeypatch, url=None, project=Path("/p/demo"))
    out = asyncio.run(tools.whoami_tool(schemas.WhoamiInput()))
    assert out == {
        "project_root": "/p/demo",
        "url": None,
        "server_status": "not_running",
    }


def test_whoami_project_running(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_discovery(monkeypatch, url="http://127.0.0.1:9000", project=Path("/p/demo"))
    out = asyncio.run(
        tools.whoami_tool(schemas.WhoamiInput(file_path="/p/demo/subdir"))
    )
    assert out["server_status"] == "running"
    assert out["url"] == "http://127.0.0.1:9000"


# ---------------------------------------------------------------------------
# folders_list
# ---------------------------------------------------------------------------


def test_folders_list_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    fake.folders_response = [
        FolderInfo(folder_path="/p/demo/docs", chunk_count=100, last_indexed="t")
    ]
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    out = asyncio.run(tools.folders_list_tool(schemas.FoldersListInput()))

    assert out["folders"][0]["folder_path"] == "/p/demo/docs"
    assert out["folders"][0]["chunk_count"] == 100


def test_folders_list_no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_discovery(monkeypatch, url=None)
    out = asyncio.run(tools.folders_list_tool(schemas.FoldersListInput()))
    assert "error" in out


# ---------------------------------------------------------------------------
# jobs_list
# ---------------------------------------------------------------------------


def test_jobs_list_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    fake.jobs_response = [{"job_id": "j1", "status": "completed"}]
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    out = asyncio.run(tools.jobs_list_tool(schemas.JobsListInput(limit=5)))

    assert out["jobs"] == [{"job_id": "j1", "status": "completed"}]
    assert fake.last_jobs_limit == 5


def test_jobs_list_default_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    fake.jobs_response = []
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    asyncio.run(tools.jobs_list_tool(schemas.JobsListInput()))

    assert fake.last_jobs_limit == 20


# ---------------------------------------------------------------------------
# extraction_fetch (Task 5)
# ---------------------------------------------------------------------------


def test_extraction_fetch_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """extraction_fetch_tool returns the text dict from the server."""
    fake = _FakeClient()
    fake.get_extraction_text_response = {"chunk_id": "c1", "text": "hello world"}
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    out = asyncio.run(
        tools.extraction_fetch_tool(schemas.ExtractionFetchInput(chunk_id="c1"))
    )

    assert out == {"chunk_id": "c1", "text": "hello world"}


def test_extraction_fetch_404_returns_err_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """On a 404 ServerError, extraction_fetch_tool must return an error dict (no-op
    signal to the agent, design E4) — NOT raise an exception."""
    fake = _FakeClient()
    fake.raise_on_call = ServerError("not found", status_code=404, detail="not pending")
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    out = asyncio.run(
        tools.extraction_fetch_tool(schemas.ExtractionFetchInput(chunk_id="missing"))
    )

    assert "error" in out
    assert "404" in out["error"]


def test_extraction_fetch_no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_discovery(monkeypatch, url=None)
    out = asyncio.run(
        tools.extraction_fetch_tool(schemas.ExtractionFetchInput(chunk_id="c1"))
    )
    assert "error" in out
    assert "no brainpalace server running" in out["error"]


# ---------------------------------------------------------------------------
# extraction_submit (Task 6)
# ---------------------------------------------------------------------------


def test_extraction_submit_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """extraction_submit_tool delegates to submit_extraction and returns its result."""
    fake = _FakeClient()
    fake.submit_extraction_response = {"status": "ok", "chunk_id": "c1"}
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    payload = {"source": "doc", "chunk_id": "c1", "triplets": []}
    out = asyncio.run(
        tools.extraction_submit_tool(schemas.ExtractionSubmitInput(payload=payload))
    )

    assert out == {"status": "ok", "chunk_id": "c1"}
    assert fake.last_submit_extraction_payload == payload


def test_extraction_submit_no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_discovery(monkeypatch, url=None)
    out = asyncio.run(
        tools.extraction_submit_tool(
            schemas.ExtractionSubmitInput(
                payload={"source": "doc", "chunk_id": "c1", "triplets": []}
            )
        )
    )
    assert "error" in out
    assert "no brainpalace server running" in out["error"]


def test_extraction_submit_server_error_maps(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    fake.raise_on_call = ServerError("conflict", status_code=409, detail="duplicate")
    _patch_discovery(monkeypatch)
    _install_fake_client(monkeypatch, fake)

    out = asyncio.run(
        tools.extraction_submit_tool(
            schemas.ExtractionSubmitInput(
                payload={"source": "doc", "chunk_id": "c1", "triplets": []}
            )
        )
    )

    assert "error" in out
    assert "409" in out["error"]
