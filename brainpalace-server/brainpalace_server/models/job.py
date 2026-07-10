"""Job queue models for indexing job management."""

import hashlib
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, computed_field


class JobStatus(str, Enum):
    """Status of an indexing job."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class JobProgress(BaseModel):
    """Progress tracking for an indexing job."""

    files_processed: int = Field(default=0, ge=0, description="Files processed so far")
    files_total: int = Field(default=0, ge=0, description="Total files to process")
    chunks_created: int = Field(default=0, ge=0, description="Chunks created so far")
    current_file: str = Field(default="", description="Currently processing file")
    # Explicit phase-weighted percent (0-100) reported by the indexing pipeline.
    # Kept SEPARATE from files_processed/files_total: the pipeline's progress is
    # phase-weighted (load/chunk/embed/store), not a flat file ratio, while
    # files_* now carry real document counts for display. (Older persisted jobs
    # predating this field default to 0 — cosmetic only, for historical rows.)
    percent: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Phase-weighted completion percent"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last progress update timestamp",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def percent_complete(self) -> float:
        """Completion percentage (the explicit phase-weighted percent)."""
        return round(self.percent, 1)


class JobRecord(BaseModel):
    """Persistent job record for the queue."""

    id: str = Field(..., description="Unique job identifier (job_<uuid12>)")
    dedupe_key: str = Field(..., description="SHA256 hash for deduplication")

    # Request parameters (normalized)
    folder_path: str = Field(..., description="Resolved, normalized folder path")
    include_code: bool = Field(default=False, description="Whether to index code files")
    operation: str = Field(
        default="index", description="Operation type: 'index' or 'add'"
    )

    # Optional request parameters
    chunk_size: int = Field(default=512, description="Chunk size in tokens")
    chunk_overlap: int = Field(default=50, description="Chunk overlap in tokens")
    recursive: bool = Field(default=True, description="Recursive folder scan")
    supported_languages: list[str] | None = Field(
        default=None, description="Languages to index"
    )
    include_patterns: list[str] | None = Field(
        default=None, description="File patterns to include"
    )
    include_types: list[str] | None = Field(
        default=None, description="File type preset names to include"
    )
    exclude_patterns: list[str] | None = Field(
        default=None, description="File patterns to exclude"
    )
    injector_script: str | None = Field(
        default=None, description="Path to injector Python script"
    )
    folder_metadata_file: str | None = Field(
        default=None, description="Path to folder metadata JSON file"
    )
    force: bool = Field(
        default=False, description="Bypass manifest comparison for full reindex"
    )
    force_budget: bool = Field(
        default=False,
        description="Bypass the per-job embedding-token budget guard.",
    )
    budget_info: dict[str, int] | None = Field(
        default=None,
        description=(
            "Set when the job was BLOCKED by the embedding-token budget: "
            "{'estimated_tokens': ..., 'limit': ...}."
        ),
    )
    eviction_summary: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Eviction summary from manifest diff " "(added/changed/deleted counts)"
        ),
    )
    # Discriminator: "documents" (default, all legacy rows) or "git_history".
    # Old persisted rows lacking this field deserialize to "documents" via the
    # Field default — no migration required.
    job_type: str = Field(
        default="documents",
        description=(
            "Job type discriminator: 'documents' (default doc-indexing pipeline) "
            "or 'git_history' (git commit ingest)."
        ),
    )

    source: str = Field(
        default="manual",
        description=(
            "Job source: 'manual' (user-triggered), 'auto' (re-queue/retry), "
            "'watch' (file-watcher-triggered), 'folders_add', 'reconcile', or 'init'."
        ),
    )
    watch_mode: str | None = Field(
        default=None,
        description=(
            "Watch mode to apply after job completion: 'auto' or 'off'. "
            "None means don't change the current watch setting."
        ),
    )
    watch_debounce_seconds: int | None = Field(
        default=None,
        description="Per-folder debounce in seconds (None = use global default)",
    )

    # Provenance/authority (Phase 6.5): resolved at enqueue time by
    # JobQueueService.enqueue_job — always a concrete value ('authoritative'
    # or 'reference') for document jobs by the time the job is persisted.
    domain: str | None = Field(
        default=None,
        description="Folder domain label to stamp on the FolderRecord (6.5).",
    )
    authority: str | None = Field(
        default=None,
        description="Resolved folder authority: 'authoritative' or "
        "'reference' (6.5). None for legacy/non-index jobs.",
    )

    # Job state
    status: JobStatus = Field(
        default=JobStatus.PENDING, description="Current job status"
    )
    cancel_requested: bool = Field(
        default=False, description="Flag for graceful cancellation"
    )

    # Timestamps
    enqueued_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the job was enqueued",
    )
    started_at: datetime | None = Field(
        default=None, description="When the job started running"
    )
    finished_at: datetime | None = Field(
        default=None, description="When the job finished (done, failed, or cancelled)"
    )

    # Results and metadata
    error: str | None = Field(default=None, description="Error message if failed")
    retry_count: int = Field(default=0, ge=0, description="Number of retry attempts")
    progress: JobProgress | None = Field(default=None, description="Progress tracking")
    total_chunks: int = Field(
        default=0, ge=0, description="Index-wide chunk count after this job"
    )
    total_documents: int = Field(default=0, ge=0, description="Total documents indexed")
    chunks_added: int = Field(
        default=0, ge=0, description="Chunks inserted by THIS job (delta)"
    )
    chunks_removed: int = Field(
        default=0, ge=0, description="Chunks evicted by THIS job (delta)"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def execution_time_ms(self) -> int | None:
        """Calculate execution time in milliseconds."""
        if self.started_at is None:
            return None
        end_time = self.finished_at or datetime.now(timezone.utc)
        delta = end_time - self.started_at
        return int(delta.total_seconds() * 1000)

    @staticmethod
    def compute_dedupe_key(
        folder_path: str,
        include_code: bool,
        operation: str,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> str:
        """Compute deduplication key from job parameters.

        Args:
            folder_path: Normalized, resolved folder path.
            include_code: Whether to include code files.
            operation: Operation type (index or add).
            include_patterns: Optional include patterns.
            exclude_patterns: Optional exclude patterns.

        Returns:
            SHA256 hash of normalized parameters.
        """
        # Normalize path (resolve and lowercase on case-insensitive systems)
        resolved = str(Path(folder_path).resolve())

        # Build dedupe string
        parts = [
            resolved,
            str(include_code),
            operation,
            ",".join(sorted(include_patterns or [])),
            ",".join(sorted(exclude_patterns or [])),
        ]
        dedupe_string = "|".join(parts)

        return hashlib.sha256(dedupe_string.encode()).hexdigest()

    @staticmethod
    def compute_git_dedupe_key(repo_root: str) -> str:
        """Compute a deduplication key for a git-history indexing job.

        Uses a distinct namespace ("git_history|") so a git job and a doc job
        for the same path never collide on the dedupe key.

        Args:
            repo_root: Path to the repository root (will be resolved).

        Returns:
            SHA256 hex digest of the namespaced, resolved path.
        """
        resolved = str(Path(repo_root).resolve())
        return hashlib.sha256(f"git_history|{resolved}".encode()).hexdigest()


class JobEnqueueResponse(BaseModel):
    """Response when enqueueing a job."""

    job_id: str = Field(..., description="Unique job identifier")
    status: str = Field(default="pending", description="Job status")
    queue_position: int = Field(
        default=0, ge=0, description="Position in the queue (0 = first)"
    )
    queue_length: int = Field(default=0, ge=0, description="Total jobs in queue")
    message: str = Field(..., description="Human-readable status message")
    dedupe_hit: bool = Field(
        default=False, description="True if this was a duplicate request"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "job_abc123def456",
                    "status": "pending",
                    "queue_position": 2,
                    "queue_length": 5,
                    "message": "Job queued for /path/to/docs",
                    "dedupe_hit": False,
                }
            ]
        }
    }


class JobListResponse(BaseModel):
    """Response for listing jobs."""

    jobs: list["JobSummary"] = Field(default_factory=list, description="List of jobs")
    total: int = Field(default=0, ge=0, description="Total number of jobs")
    pending: int = Field(default=0, ge=0, description="Number of pending jobs")
    running: int = Field(default=0, ge=0, description="Number of running jobs")
    completed: int = Field(default=0, ge=0, description="Number of completed jobs")
    failed: int = Field(default=0, ge=0, description="Number of failed jobs")
    blocked: int = Field(default=0, ge=0, description="Number of budget-blocked jobs")


class JobSummary(BaseModel):
    """Summary view of a job for list responses."""

    id: str = Field(..., description="Job identifier")
    status: JobStatus = Field(..., description="Current status")
    folder_path: str = Field(..., description="Folder being indexed")
    operation: str = Field(..., description="Operation type")
    include_code: bool = Field(..., description="Whether indexing code")
    source: str = Field(default="manual", description="Job source: manual or auto")
    enqueued_at: datetime = Field(..., description="When queued")
    started_at: datetime | None = Field(default=None, description="When started")
    finished_at: datetime | None = Field(default=None, description="When finished")
    progress_percent: float = Field(default=0.0, description="Completion percentage")
    chunks_added: int = Field(default=0, description="Chunks inserted by this job")
    chunks_removed: int = Field(default=0, description="Chunks evicted by this job")
    error: str | None = Field(default=None, description="Error message if failed")
    budget_info: dict[str, int] | None = Field(
        default=None, description="Budget numbers when status is blocked"
    )

    @classmethod
    def from_record(cls, record: JobRecord) -> "JobSummary":
        """Create a summary from a full job record."""
        return cls(
            id=record.id,
            status=record.status,
            folder_path=record.folder_path,
            operation=record.operation,
            include_code=record.include_code,
            source=record.source,
            enqueued_at=record.enqueued_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            progress_percent=(
                record.progress.percent_complete if record.progress else 0.0
            ),
            chunks_added=record.chunks_added,
            chunks_removed=record.chunks_removed,
            error=record.error,
            budget_info=record.budget_info,
        )


class JobDetailResponse(BaseModel):
    """Detailed response for a single job."""

    id: str = Field(..., description="Job identifier")
    status: JobStatus = Field(..., description="Current status")
    folder_path: str = Field(..., description="Folder being indexed")
    operation: str = Field(..., description="Operation type")
    include_code: bool = Field(..., description="Whether indexing code")
    source: str = Field(default="manual", description="Job source: manual or auto")

    # Timestamps
    enqueued_at: datetime = Field(..., description="When queued")
    started_at: datetime | None = Field(default=None, description="When started")
    finished_at: datetime | None = Field(default=None, description="When finished")
    execution_time_ms: int | None = Field(
        default=None, description="Execution time in ms"
    )

    # Progress
    progress: JobProgress | None = Field(default=None, description="Progress details")
    progress_percent: float = Field(
        default=0.0,
        description=(
            "Flat progress percent (0-100). Mirrors progress.percent_complete "
            "for parity with JobSummary."
        ),
    )

    # Results
    total_documents: int = Field(default=0, description="Documents indexed")
    total_chunks: int = Field(
        default=0, description="Index-wide chunk count after this job"
    )
    chunks_added: int = Field(default=0, description="Chunks inserted by this job")
    chunks_removed: int = Field(default=0, description="Chunks evicted by this job")
    error: str | None = Field(default=None, description="Error message if failed")
    retry_count: int = Field(default=0, description="Retry attempts")
    cancel_requested: bool = Field(
        default=False, description="Whether cancellation requested"
    )
    eviction_summary: dict[str, Any] | None = Field(
        default=None,
        description="Eviction summary if manifest tracking was used",
    )
    budget_info: dict[str, int] | None = Field(
        default=None, description="Budget numbers when status is blocked"
    )

    @classmethod
    def from_record(cls, record: JobRecord) -> "JobDetailResponse":
        """Create a detail response from a full job record."""
        return cls(
            id=record.id,
            status=record.status,
            folder_path=record.folder_path,
            operation=record.operation,
            include_code=record.include_code,
            source=record.source,
            enqueued_at=record.enqueued_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            execution_time_ms=record.execution_time_ms,
            progress=record.progress,
            progress_percent=(
                record.progress.percent_complete if record.progress else 0.0
            ),
            total_documents=record.total_documents,
            total_chunks=record.total_chunks,
            chunks_added=record.chunks_added,
            chunks_removed=record.chunks_removed,
            error=record.error,
            retry_count=record.retry_count,
            cancel_requested=record.cancel_requested,
            eviction_summary=record.eviction_summary,
            budget_info=record.budget_info,
        )


class QueueStats(BaseModel):
    """Statistics about the job queue."""

    pending: int = Field(default=0, ge=0, description="Pending jobs count")
    running: int = Field(default=0, ge=0, description="Running jobs count")
    completed: int = Field(default=0, ge=0, description="Completed jobs count")
    failed: int = Field(default=0, ge=0, description="Failed jobs count")
    blocked: int = Field(default=0, ge=0, description="Budget-blocked jobs count")
    cancelled: int = Field(default=0, ge=0, description="Cancelled jobs count")
    total: int = Field(default=0, ge=0, description="Total jobs count")
    current_job_id: str | None = Field(
        default=None, description="Currently running job ID"
    )
    current_job_running_time_ms: int | None = Field(
        default=None, description="Current job running time in ms"
    )
