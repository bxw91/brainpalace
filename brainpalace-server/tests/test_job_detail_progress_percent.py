"""Tests for JobDetailResponse.progress_percent (Phase F item 6)."""

from __future__ import annotations

from brainpalace_server.models.job import (
    JobDetailResponse,
    JobProgress,
    JobRecord,
    JobStatus,
    JobSummary,
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
        # percent is the explicit phase-weighted value, decoupled from the real
        # file counts (files_processed/files_total).
        progress = JobProgress(files_processed=25, files_total=57, percent=42.0)
        record = _make_record(progress)
        resp = JobDetailResponse.from_record(record)
        assert resp.progress is not None
        assert resp.progress_percent == record.progress.percent_complete  # type: ignore[union-attr]
        assert resp.progress_percent == 42.0

    def test_progress_percent_is_zero_when_progress_missing(self) -> None:
        record = _make_record(progress=None)
        resp = JobDetailResponse.from_record(record)
        assert resp.progress is None
        assert resp.progress_percent == 0.0

    def test_progress_percent_defaults_zero_without_explicit_percent(self) -> None:
        # Real file counts no longer drive the percent.
        progress = JobProgress(files_processed=25, files_total=57)
        record = _make_record(progress)
        resp = JobDetailResponse.from_record(record)
        assert resp.progress_percent == 0.0


class TestChunkDeltaPropagation:
    """Per-job chunk add/remove deltas flow into both response shapes."""

    def test_summary_carries_chunk_deltas(self) -> None:
        record = _make_record(progress=None)
        record.chunks_added = 120
        record.chunks_removed = 30
        summary = JobSummary.from_record(record)
        assert summary.chunks_added == 120
        assert summary.chunks_removed == 30

    def test_detail_carries_chunk_deltas(self) -> None:
        record = _make_record(progress=None)
        record.chunks_added = 120
        record.chunks_removed = 30
        record.total_chunks = 980  # index-wide total stays distinct
        detail = JobDetailResponse.from_record(record)
        assert detail.chunks_added == 120
        assert detail.chunks_removed == 30
        assert detail.total_chunks == 980
