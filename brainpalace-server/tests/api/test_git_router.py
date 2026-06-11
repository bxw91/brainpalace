"""Tests for POST /git/reindex endpoint (Issue #15).

Verifies:
- 503 when git indexing is disabled (git_index_service is None).
- 503 when job_service is unavailable.
- Returns a job_id (enqueues, not inline) when git is enabled.
- dedupe_hit=True on repeated call while job is still PENDING.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.git import router
from brainpalace_server.models.job import JobEnqueueResponse, JobStatus


def _build_app(
    *,
    git_svc_enabled: bool = True,
    job_svc_available: bool = True,
    dedupe_hit: bool = False,
    project_root: str = "/repo/project",
) -> FastAPI:
    """Build a minimal FastAPI app with the git router mounted."""
    app = FastAPI()
    app.include_router(router, prefix="/git")

    fake_resp = JobEnqueueResponse(
        job_id="job_git_abc123",
        status=JobStatus.PENDING.value,
        queue_position=0,
        queue_length=1,
        message="Git history job enqueued",
        dedupe_hit=dedupe_hit,
    )
    mock_job_svc = MagicMock()
    mock_job_svc.enqueue_git_history_job = AsyncMock(return_value=fake_resp)

    app.state.git_index_service = MagicMock() if git_svc_enabled else None
    app.state.git_indexing_config = MagicMock()
    app.state.project_root = project_root
    app.state.job_service = mock_job_svc if job_svc_available else None

    return app


class TestGitReindexEndpoint:
    """POST /git/reindex behaviour."""

    def test_503_when_git_disabled(self) -> None:
        """Returns 503 when git_index_service is None."""
        client = TestClient(_build_app(git_svc_enabled=False))
        r = client.post("/git/reindex")
        assert r.status_code == 503
        assert "disabled" in r.json()["detail"].lower()

    def test_503_when_job_service_unavailable(self) -> None:
        """Returns 503 when job_service is None."""
        client = TestClient(_build_app(git_svc_enabled=True, job_svc_available=False))
        r = client.post("/git/reindex")
        assert r.status_code == 503

    def test_enqueues_and_returns_job_id(self) -> None:
        """Returns job_id when git is enabled (enqueued, not inline)."""
        client = TestClient(_build_app())
        r = client.post("/git/reindex")
        assert r.status_code == 200
        body = r.json()
        assert "job_id" in body
        assert body["job_id"] == "job_git_abc123"

    def test_dedupe_hit_propagated(self) -> None:
        """dedupe_hit is forwarded from the enqueue response."""
        client = TestClient(_build_app(dedupe_hit=True))
        r = client.post("/git/reindex")
        assert r.status_code == 200
        assert r.json()["dedupe_hit"] is True

    def test_response_contains_status(self) -> None:
        """Response includes status field."""
        client = TestClient(_build_app())
        r = client.post("/git/reindex")
        assert r.status_code == 200
        assert "status" in r.json()

    def test_503_when_project_root_empty(self) -> None:
        """Returns 503 when project_root is empty (no project root configured)."""
        client = TestClient(_build_app(project_root=""))
        r = client.post("/git/reindex")
        assert r.status_code == 503
        assert "project root" in r.json()["detail"].lower()
