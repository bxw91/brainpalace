"""Regression tests for jobs detail rendering with the API's progress dict."""

from __future__ import annotations

from brainpalace_cli.commands.jobs import _create_job_detail_panel


def _base_job(**overrides: object) -> dict[str, object]:
    job: dict[str, object] = {
        "id": "job_abc",
        "status": "running",
        "folder_path": "/tmp/x",
        "operation": "index",
        "source": "manual",
        "enqueued_at": "2026-05-20T12:00:00Z",
        "started_at": "2026-05-20T12:01:00Z",
    }
    job.update(overrides)
    return job


def test_progress_dict_does_not_raise_typeerror() -> None:
    """Bug surfaced during Phase D smoke: progress is a JobProgress dict.

    The walrus `(progress := job.get("progress_percent", job.get("progress")))`
    fell back to the dict and then tried `f"{progress:.1f}%"`, raising
    `TypeError: unsupported format string passed to dict.__format__`.
    """
    job = _base_job(
        progress={
            "files_processed": 0,
            "files_total": 0,
            "chunks_created": 0,
            "current_file": "",
            "updated_at": "2026-05-20T12:01:00Z",
            "percent_complete": 0.0,
        },
    )
    # Should not raise.
    panel = _create_job_detail_panel(job)
    assert panel is not None


def test_progress_dict_renders_percent_complete() -> None:
    job = _base_job(
        progress={
            "files_processed": 5,
            "files_total": 10,
            "chunks_created": 7,
            "current_file": "x.py",
            "updated_at": "2026-05-20T12:01:00Z",
            "percent_complete": 50.0,
        },
    )
    panel = _create_job_detail_panel(job)
    rendered = str(panel.renderable)
    assert "50.0%" in rendered


def test_flat_progress_percent_still_works() -> None:
    """Backwards-compat: jobs whose dict has a flat progress_percent."""
    job = _base_job(progress_percent=42.0)
    panel = _create_job_detail_panel(job)
    rendered = str(panel.renderable)
    assert "42.0%" in rendered


def test_missing_progress_does_not_render_line() -> None:
    job = _base_job()
    job.pop("progress_percent", None)
    panel = _create_job_detail_panel(job)
    assert "Progress:" not in str(panel.renderable)
