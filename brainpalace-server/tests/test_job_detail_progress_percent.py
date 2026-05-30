"""Tests for JobDetailResponse.progress_percent (Phase F item 6)."""

from __future__ import annotations

from brainpalace_server.models.job import (
    JobDetailResponse,
    JobProgress,
    JobRecord,
    JobStatus,
)


def _make_record(progress: JobProgress | None) -> JobRecord:
    return JobRecord(
        id="job_abc123",
        dedupe_key="deadbeef",
        folder_path="/tmp/x",
        include_code=False,
        status=JobStatus.RUNNING,
        progress=progress,
    )


class TestJobDetailProgressPercent:
    def test_progress_percent_mirrors_nested_progress(self) -> None:
        progress = JobProgress(files_processed=25, files_total=100)
        record = _make_record(progress)
        resp = JobDetailResponse.from_record(record)
        assert resp.progress is not None
        assert resp.progress_percent == record.progress.percent_complete  # type: ignore[union-attr]
        assert resp.progress_percent == 25.0

    def test_progress_percent_is_zero_when_progress_missing(self) -> None:
        record = _make_record(progress=None)
        resp = JobDetailResponse.from_record(record)
        assert resp.progress is None
        assert resp.progress_percent == 0.0

    def test_progress_percent_handles_zero_total(self) -> None:
        progress = JobProgress(files_processed=0, files_total=0)
        record = _make_record(progress)
        resp = JobDetailResponse.from_record(record)
        assert resp.progress_percent == 0.0
