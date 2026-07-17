"""Fix 3 (A4) — job_type is exposed on JobSummary/JobDetailResponse.

Before this fix, the authoritative discriminator JobRecord.job_type was not
carried into the list/detail payloads, so a dashboard "Type" column keyed on
include_code alone mislabelled a git_history job as "docs"
(job_type default "documents" is never git_history's actual value).
"""

from __future__ import annotations

from brainpalace_server.models.job import (
    JobDetailResponse,
    JobRecord,
    JobStatus,
    JobSummary,
)


def _make_record(job_type: str) -> JobRecord:
    return JobRecord(
        id="job_abc123",
        dedupe_key="deadbeef",
        folder_path="/tmp/x",
        include_code=False,
        status=JobStatus.DONE,
        job_type=job_type,
    )


def test_summary_carries_job_type_git_history() -> None:
    record = _make_record("git_history")
    summary = JobSummary.from_record(record)
    assert summary.job_type == "git_history"


def test_summary_carries_job_type_default_documents() -> None:
    record = _make_record("documents")
    summary = JobSummary.from_record(record)
    assert summary.job_type == "documents"


def test_detail_carries_job_type_git_history() -> None:
    record = _make_record("git_history")
    detail = JobDetailResponse.from_record(record)
    assert detail.job_type == "git_history"
