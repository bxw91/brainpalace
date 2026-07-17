"""Pydantic input schemas for BrainPalace MCP tools.

Each tool's input is described by a model here; the model is also the
source of truth for the JSON schema MCP clients see during ``list_tools``.
Descriptions are intentionally terse — every byte ships in the client's
context (see the "tool description context cost" risk in the Phase Q plan).
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from brainpalace_server.models.query import QueryMode as _ServerQueryMode
from pydantic import BaseModel, Field

# Optional list filters default to ``[]`` (not ``None``) so the generated JSON
# schema is a plain array — no ``anyOf: [array, null]`` union, which some LLM /
# MCP clients mishandle (the "null parameter during query" problem). The client
# treats an empty list as "no filter" (see api_client.query), so ``[]`` == omit.

# Explicit so mypy (strict) keeps a real static type for the `mode` field, and
# guarded so it can never SHIP narrower/wider than the server enum: the import
# fails the MCP process on drift, and the contract_parity gate fails CI. Keep the
# values in server-enum order.
QueryMode = Literal[
    "vector",
    "bm25",
    "hybrid",
    "graph",
    "multi",
    "compute",
    "scan",
    "absence",
    "timeline",
]
if set(get_args(QueryMode)) != {m.value for m in _ServerQueryMode}:
    raise RuntimeError(
        "MCP QueryMode Literal drifted from server QueryMode enum: "
        f"literal={sorted(get_args(QueryMode))} "
        f"enum={sorted(m.value for m in _ServerQueryMode)}"
    )

# Shared: override CWD-based server discovery. See the CWD-coupling risk
# in the Phase Q plan — the long-lived stdio MCP process is pinned to its
# spawn-time CWD, so callers may pass ``path`` to target a different project.
_PATH_DESC = "Resolve the server owning this path instead of the MCP process CWD"


class QueryInput(BaseModel):
    query: str = Field(..., description="Search query text")
    mode: QueryMode = Field(default="hybrid", description="Search mode")
    # le=50 (A6): the server rejects top_k>50 with a 422; the schema previously
    # said le=100, so a value the schema accepted the server still rejected.
    top_k: int = Field(default=8, ge=1, le=50)
    languages: list[str] = Field(
        default_factory=list,
        description="Filter by programming languages (empty = all)",
    )
    source_types: list[str] = Field(
        default_factory=list,
        description="Filter by source types (empty = all)",
    )
    file_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Filter by file path, wildcards supported e.g. '*.py' or "
            "'src/**' (empty = all)"
        ),
    )
    alpha: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Hybrid search weighting: 1.0=pure vector, 0.0=pure bm25. "
            "hybrid mode only (hybrid is the default mode)."
        ),
    )
    similarity_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score (0-1)",
    )
    entity_types: list[str] = Field(
        default_factory=list,
        description=(
            "Filter graph results by entity types, e.g. ['Class', 'Function']. "
            "graph/multi modes only (empty = all)."
        ),
    )
    relationship_types: list[str] = Field(
        default_factory=list,
        description=(
            "Filter graph results by relationship types, e.g. ['calls', "
            "'extends']. graph/multi modes only (empty = all)."
        ),
    )
    language: str | None = Field(
        default=None,
        description=(
            "BM25 query language override; defaults to project bm25.language. "
            "ISO 639-1 code (e.g. 'en', 'de', 'hr'). Only affects BM25 tokenization."
        ),
    )
    path: str | None = Field(default=None, description=_PATH_DESC)


class WhoamiInput(BaseModel):
    file_path: str | None = None


class StatusInput(BaseModel):
    path: str | None = Field(default=None, description=_PATH_DESC)


class FoldersListInput(BaseModel):
    path: str | None = Field(default=None, description=_PATH_DESC)


class JobsListInput(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)
    path: str | None = Field(default=None, description=_PATH_DESC)


class JobsApproveInput(BaseModel):
    """Input for the jobs_approve tool."""

    job_id: str = Field(..., description="Blocked job id to approve")
    path: str | None = Field(
        default=None, description="Project path (default: spawn-time CWD)"
    )


class MemorizeInput(BaseModel):
    text: str = Field(..., description="The durable fact to remember")
    section: str = Field(default="Notes", description="Markdown section")
    tags: list[str] | None = None
    path: str | None = Field(default=None, description=_PATH_DESC)


class RecallInput(BaseModel):
    query: str = Field(..., description="Recall query (memory namespace only)")
    top_k: int = Field(default=5, ge=1, le=50)
    path: str | None = Field(default=None, description=_PATH_DESC)


class SessionContextInput(BaseModel):
    path: str | None = Field(default=None, description=_PATH_DESC)


class AiGuideInput(BaseModel):
    tier: Literal["nudge", "core", "full"] = Field(
        default="full",
        description=(
            "full = complete usage guide (default); core = decision contract; "
            "nudge = one-line reminder. CORE is already in the server instructions."
        ),
    )


class ExtractionFetchInput(BaseModel):
    chunk_id: str = Field(..., description="Pending chunk id to fetch text for")
    path: str | None = Field(default=None, description=_PATH_DESC)


class ExtractionSubmitInput(BaseModel):
    payload: dict[str, Any] = Field(..., description="Extraction payload to submit")
    path: str | None = Field(default=None, description=_PATH_DESC)
