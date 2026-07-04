"""Blocked-job visibility: /health/status features + session-start context."""

from brainpalace_server.models.context import SessionContext
from brainpalace_server.services.session_context_service import SessionContextService

_SUMMARY = {
    "job_id": "job_abc123def456",
    "folder_path": "/tmp/p",
    "estimated_tokens": 412_000,
    "limit": 100_000,
    "blocked_since": "2026-07-04T12:00:00+00:00",
}


def test_session_context_carries_blocked_job() -> None:
    svc = (
        SessionContextService()
    )  # ctor defaults: (memory_service=None, budget_tokens=None)
    ctx = svc.build(
        project_root="/tmp/p", branch="main", doc_count=10, blocked_job=_SUMMARY
    )
    assert isinstance(ctx, SessionContext)
    assert ctx.blocked_job == _SUMMARY
    assert "indexing paused" in ctx.text.lower()
    assert "job_abc123def456 --approve" in ctx.text


def test_session_context_no_blocked_line_by_default() -> None:
    ctx = SessionContextService().build(project_root="/tmp/p")
    assert ctx.blocked_job is None
    assert "indexing paused" not in ctx.text.lower()
