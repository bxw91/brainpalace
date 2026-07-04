"""Loud blocked-jobs panel in brainpalace status."""

from brainpalace_cli.commands.status import render_blocked_jobs_row


def test_render_blocked_none_when_absent_or_zero() -> None:
    assert render_blocked_jobs_row({}) is None
    assert render_blocked_jobs_row({"count": 0, "latest": None}) is None


def test_render_blocked_row_text() -> None:
    text = render_blocked_jobs_row(
        {
            "count": 1,
            "latest": {
                "job_id": "job_1",
                "folder_path": "/tmp/p",
                "estimated_tokens": 412000,
                "limit": 100000,
                "blocked_since": "2026-07-04T12:00:00+00:00",
            },
        }
    )
    assert text is not None
    assert "paused" in text.lower()
    assert "412,000" in text
    assert "brainpalace jobs job_1 --approve" in text
