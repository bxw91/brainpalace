"""Query request and response models."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class QueryMode(str, Enum):
    """Retrieval modes."""

    VECTOR = "vector"
    BM25 = "bm25"
    HYBRID = "hybrid"
    GRAPH = "graph"  # Graph-only retrieval (Feature 113)
    MULTI = "multi"  # Multi-retrieval: vector + BM25 + graph with RRF (Feature 113)
    COMPUTE = "compute"  # Set-level aggregation over typed numeric Records (Phase 1)
    SCAN = "scan"  # Deterministic map-reduce over the session archive (Phase 2)
    ABSENCE = "absence"  # Anti-join over the records store (Phase 3)
    TIMELINE = "timeline"  # Edge-validity/supersession history walk (Phase 4)


class QueryRequest(BaseModel):
    """Request model for document queries."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="The search query text",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of results to return",
    )
    similarity_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score (0-1)",
    )
    mode: QueryMode = Field(
        default=QueryMode.HYBRID,
        description="Retrieval mode (vector, bm25, hybrid, graph, multi, "
        "compute, scan, absence, timeline)",
    )
    alpha: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Weight for hybrid search (1.0 = pure vector, 0.0 = pure bm25)",
    )
    use_memory: bool = Field(
        default=True,
        description=(
            "Boost relevant curated memories into the results (Phase 030). "
            "Applies to vector/hybrid/multi modes; ignored for pure bm25."
        ),
    )
    time_decay: bool = Field(
        default=True,
        description=(
            "Rank newer chunks higher via an exponential age factor (Phase 110). "
            "Tunable via BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS (0 disables "
            "globally). Set false to disable for this query."
        ),
    )
    rerank: bool | None = Field(
        default=None,
        description=(
            "Per-request reranking override: true forces two-stage reranking, "
            "false disables it, null (default) follows ENABLE_RERANKING."
        ),
    )

    # Content filtering
    source_types: list[str] | None = Field(
        default=None,
        description="Filter by source types: 'doc', 'code', 'test'",
        examples=[["doc"], ["code"], ["doc", "code"]],
    )
    languages: list[str] | None = Field(
        default=None,
        description="Filter by programming languages for code files",
        examples=[["python"], ["typescript", "javascript"], ["java", "kotlin"]],
    )
    file_paths: list[str] | None = Field(
        default=None,
        description="Filter by specific file paths (supports wildcards)",
        examples=[["docs/*.md"], ["src/**/*.py"]],
    )

    # BM25 query language override
    language: str | None = Field(
        None,
        description=(
            "BM25 query language override (ISO 639-1). "
            "Defaults to the project bm25.language setting."
        ),
    )

    # Graph entity type filtering (Feature 122 - Schema GraphRAG)
    entity_types: list[str] | None = Field(
        default=None,
        description=(
            "Filter graph results by entity types "
            "(e.g., ['Class', 'Function']). "
            "Only applies to graph and multi query modes."
        ),
        examples=[["Class", "Function"], ["Package", "Module"]],
    )
    relationship_types: list[str] | None = Field(
        default=None,
        description=(
            "Filter graph results by relationship types "
            "(e.g., ['calls', 'extends']). "
            "Only applies to graph and multi query modes."
        ),
        examples=[["calls", "extends"], ["imports", "contains"]],
    )

    @field_validator("languages")
    @classmethod
    def validate_languages(cls, v: list[str] | None) -> list[str] | None:
        """Validate that provided languages are supported."""
        if v is None:
            return v

        from ..indexing.document_loader import LanguageDetector

        detector = LanguageDetector()
        supported_languages = detector.get_supported_languages()

        invalid_languages = [lang for lang in v if lang not in supported_languages]
        if invalid_languages:
            raise ValueError(
                f"Unsupported languages: {invalid_languages}. "
                f"Supported languages: {supported_languages}"
            )

        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "How do I configure authentication?",
                    "top_k": 5,
                    "similarity_threshold": 0.3,
                    "mode": "hybrid",
                    "alpha": 0.5,
                },
                {
                    "query": "implement user authentication",
                    "top_k": 10,
                    "source_types": ["code"],
                    "languages": ["python", "typescript"],
                },
                {
                    "query": "API endpoints",
                    "top_k": 5,
                    "source_types": ["doc", "code"],
                    "file_paths": ["docs/api/*.md", "src/**/*.py"],
                },
            ]
        }
    }


class ComputeResult(BaseModel):
    """One set-level aggregation row (compute mode). Not a document."""

    # dict form — matches query.py's existing style (no ConfigDict import there)
    model_config = {"frozen": True}
    label: str  # human row label, e.g. "2026-W03" or "sales sum"
    value: float
    metric: str
    op: str  # sum|count|avg|max|min
    group: str | None = None  # group key (week/month/source/...) or None if ungrouped
    unit: str | None = None
    score: float = 0.0  # value normalised to 0..1 (display ordering only)


class ScanResult(BaseModel):
    """One scan-mode row: term occurrences per bucket. Not a document."""

    model_config = {"frozen": True}
    label: str  # human row label, e.g. "2026-W03" or "foobar count"
    value: float  # occurrence count (float for shape parity with compute)
    term: str  # the counted term/phrase
    group: str | None = None  # bucket key (week/month/day/source) or None
    score: float = 0.0  # value normalised to 0..1 (display ordering only)


class AbsenceResult(BaseModel):
    """One absence-mode row: a subject present under one partition value but
    absent under another. Not a document."""

    model_config = {"frozen": True}
    label: str  # the missing subject (row label)
    present_in: str  # partition value the subject IS under (A)
    absent_from: str  # partition value it is MISSING from (B)
    partition: str  # partition column used: "metric" | "source" | "domain"
    score: float = 0.0  # reserved for ordering parity; always 0.0 in v1


class TimelineResult(BaseModel):
    """One timeline-mode row: an entity's edge at a point in its history, with
    validity. Maps 1:1 from a graph `timeline_named` row. Not a document."""

    model_config = {"frozen": True}
    subject: str
    predicate: str
    object: str
    valid_from: str | None = None
    valid_until: str | None = None  # None = still valid
    valid: bool = True  # convenience mirror of (valid_until is None)
    score: float = 0.0  # ordering parity; timeline is ordered by valid_from


class QueryResult(BaseModel):
    """Single query result with source and score."""

    text: str = Field(..., description="The chunk text content")
    source: str = Field(..., description="Source file path")
    score: float = Field(..., description="Primary score (rank or similarity)")
    vector_score: float | None = Field(
        default=None, description="Score from vector search"
    )
    bm25_score: float | None = Field(default=None, description="Score from BM25 search")
    chunk_id: str = Field(..., description="Unique chunk identifier")

    # Content type information
    source_type: str = Field(
        default="doc", description="Type of content: 'doc', 'code', or 'test'"
    )
    language: str | None = Field(
        default=None, description="Programming language for code files"
    )

    # GraphRAG fields (Feature 113)
    graph_score: float | None = Field(
        default=None, description="Score from graph-based retrieval"
    )
    related_entities: list[str] | None = Field(
        default=None, description="Related entities from knowledge graph"
    )
    relationship_path: list[str] | None = Field(
        default=None, description="Relationship paths in the graph"
    )

    # Reranking fields (Feature 123)
    rerank_score: float | None = Field(
        default=None, description="Score from reranking stage (if enabled)"
    )
    original_rank: int | None = Field(
        default=None, description="Position before reranking (1-indexed)"
    )

    # Additional metadata
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class BlockedJobInfo(BaseModel):
    """Summary of a budget-blocked indexing job, attached to query responses."""

    job_id: str = Field(..., description="Blocked job identifier")
    folder_path: str = Field(..., description="Folder whose indexing is paused")
    estimated_tokens: int | None = Field(
        default=None, description="Estimated embedding tokens the job needs"
    )
    limit: int | None = Field(
        default=None, description="Configured max_embed_tokens_per_job cap"
    )
    blocked_since: str | None = Field(
        default=None, description="ISO timestamp the job was blocked"
    )


class QueryResponse(BaseModel):
    """Response model for document queries."""

    results: list[QueryResult] = Field(
        default_factory=list,
        description="List of matching document chunks",
    )
    query_time_ms: float = Field(
        ...,
        ge=0,
        description="Query execution time in milliseconds",
    )
    total_results: int = Field(
        default=0,
        ge=0,
        description="Total number of results found",
    )
    compute: list[ComputeResult] | None = Field(
        default=None,
        description="Set-level aggregation rows (compute mode); null for "
        "document retrieval. When set, `results` is empty.",
    )
    scan: list[ScanResult] | None = Field(
        default=None,
        description="Scan rows — term counts over the session archive (scan "
        "mode); null for document retrieval. When set, `results` is empty.",
    )
    absence: list[AbsenceResult] | None = Field(
        default=None,
        description="Absence rows — subjects present under one partition value "
        "but absent under another (absence mode); null for document retrieval. "
        "When set, `results` is empty.",
    )
    timeline: list[TimelineResult] | None = Field(
        default=None,
        description="Timeline rows — an entity's ordered edge-validity/"
        "supersession history (timeline mode); null for document retrieval. "
        "When set, `results` is empty.",
    )
    index_blocked: BlockedJobInfo | None = Field(
        default=None,
        description=(
            "Present when an indexing job is paused over the embedding-token "
            "budget — the index may be STALE. Approve via "
            "POST /index/jobs/{job_id}/approve."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "results": [
                        {
                            "text": "Authentication is configured via...",
                            "source": "docs/auth.md",
                            "score": 0.92,
                            "vector_score": 0.92,
                            "bm25_score": 0.85,
                            "chunk_id": "chunk_abc123",
                            "source_type": "doc",
                            "language": "markdown",
                            "metadata": {"chunk_index": 0},
                        },
                        {
                            "text": "def authenticate_user(username, password):",
                            "source": "src/auth.py",
                            "score": 0.88,
                            "vector_score": 0.88,
                            "bm25_score": 0.82,
                            "chunk_id": "chunk_def456",
                            "source_type": "code",
                            "language": "python",
                            "metadata": {"symbol_name": "authenticate_user"},
                        },
                    ],
                    "query_time_ms": 125.5,
                    "total_results": 2,
                }
            ]
        }
    }
